"""ClaudeCliProvider (verified against Claude Code 2.1.280).

Run:   claude -p --output-format stream-json --verbose --model <m> [--effort <e>]
              --no-session-persistence --json-schema <schema> --permission-mode <mode>
              --permission-prompts none --allowedTools ... --disallowedTools ...
              --strict-mcp-config [--safe-mode]          (prompt on stdin, cwd = worktree)
Quota: no non-inference quota read exists in this CLI; state is learned from
       stream-json ``rate_limit_event`` (five_hour / seven_day / seven_day_opus /
       seven_day_sonnet, resetsAt, isUsingOverage) and limit text. Otherwise UNKNOWN.
Billing guard: ``claude auth status --json`` must show a subscription login; API keys
are never forwarded; an ``isUsingOverage`` event aborts the run (paid extra usage).
Never uses --bare (it would switch auth to ANTHROPIC_API_KEY only).
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from ..models import AttemptStatus, ExecutionRun, ProviderStatus, RunSpec, utcnow
from ..prompts import RESULT_SCHEMA, REVIEW_SCHEMA
from ..sanitize import child_env
from .base import ModelInfo, RunCollector, StatusReport, WorkerProvider, run_cmd, which
from .limits import claude_limit_from_text, claude_rate_limit_event, is_auth_error, is_model_error

REQUIRED_FLAGS = ["--print", "--output-format", "--json-schema", "--no-session-persistence", "--model",
                  "--permission-mode"]
OPTIONAL_FLAGS = ["--effort", "--safe-mode", "--permission-prompts", "--strict-mcp-config"]
WEB_TOOLS = ("WebFetch", "WebSearch")     # disallowed by default; allowed only for allow_web research runs
DESKTOP_GLOB = "~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude"


def _version_key(p: str):
    v = Path(p).parts[-5] if len(Path(p).parts) >= 5 else "0"
    return tuple(int(x) if x.isdigit() else 0 for x in v.split("."))


def discover_claude() -> str | None:
    found = which("claude")
    if found:
        return found
    local = os.path.expanduser("~/.claude/local/claude")
    if os.path.exists(local):
        return local
    cands = sorted(glob.glob(os.path.expanduser(DESKTOP_GLOB)), key=_version_key)
    return cands[-1] if cands else None


class ClaudeCliProvider(WorkerProvider):
    name = "claude"

    def __init__(self, cfg: dict, allow_api_billing: bool = False, allow_overage: bool = False):
        super().__init__(cfg, allow_api_billing)
        self.allow_overage = allow_overage
        self._help: str | None = None

    def resolve_binary(self) -> list[str] | None:
        cmd = list(self.cfg.get("command") or [])
        if cmd:
            head = cmd[0]
            if os.path.isabs(head) or os.sep in head:
                return cmd if os.path.exists(head) else None
            found = which(head)
            return [found, *cmd[1:]] if found else None
        found = discover_claude()
        return [found] if found else None

    def env(self) -> dict:
        extra = {k: os.environ[k] for k in ("CLAUDE_CONFIG_DIR",) if k in os.environ}
        api = {}
        if self.allow_api_billing:
            api = {k: os.environ[k] for k in ("ANTHROPIC_API_KEY",) if k in os.environ}
        return child_env(extra, allow_api_env=api)

    async def check_status(self, *, with_quota: bool = True) -> StatusReport:
        b = self.resolve_binary()
        if not b:
            return StatusReport(self.name, False, status=ProviderStatus.MISSING,
                                notes=["claude binary not found on PATH, ~/.claude/local, or the desktop app bundle"])
        rep = StatusReport(self.name, True, binary=b)
        rc, out, err = await run_cmd([*b, "--version"], self.env(), 30)
        rep.version = (out or err).strip() or None
        rc, out, err = await run_cmd([*b, "--help"], self.env(), 30)
        self._help = out
        rep.missing_flags = [f for f in REQUIRED_FLAGS if f not in out]
        rep.flags_ok = not rep.missing_flags
        missing_opt = [f for f in OPTIONAL_FLAGS if f not in out]
        if missing_opt:
            rep.notes.append(f"optional flags not supported (skipped): {missing_opt}")
        rc, out, err = await run_cmd([*b, "auth", "status", "--json"], self.env(), 30)
        try:
            st = json.loads(out)
        except ValueError:
            st = {}
        method = str(st.get("authMethod") or "unknown")
        provider = str(st.get("apiProvider") or "firstParty")
        rep.auth_detail = f"loggedIn={st.get('loggedIn')} authMethod={method} apiProvider={provider}"
        subs = [s.lower() for s in self.cfg.get("subscription_auth_methods", [])]
        if not st.get("loggedIn") or method == "none":
            rep.auth_mode, rep.status = "none", ProviderStatus.AUTH_ERROR
            rep.notes.append("Claude CLI not logged in. Run `claude auth login` (subscription) in a terminal.")
        elif provider != "firstParty":
            rep.auth_mode = "api"
        elif method.lower() in subs:
            rep.auth_mode = "subscription"
        elif "key" in method.lower() or "api" in method.lower() or "console" in method.lower():
            rep.auth_mode = "api"
        else:
            rep.auth_mode = "unknown"
            rep.notes.append(f"authMethod {method!r} not in providers.claude.subscription_auth_methods; "
                             "blocked until confirmed as a subscription login")
        rep.billing_ok = rep.auth_mode == "subscription" or (rep.auth_mode == "api" and self.allow_api_billing)
        if rep.status != ProviderStatus.AUTH_ERROR:
            if not rep.billing_ok:
                rep.status = ProviderStatus.BILLING_BLOCKED
            elif not rep.flags_ok:
                rep.status = ProviderStatus.MISSING
                rep.notes.append(f"claude lacks required flags: {rep.missing_flags}")
            else:
                rep.status = ProviderStatus.UNKNOWN
        rep.notes.append("quota: no non-inference read in this CLI; learned from rate_limit_event during runs")
        return rep

    async def inspect_models(self) -> list[ModelInfo]:
        # The CLI has no model listing command; configured ids are validated on first use.
        return []

    def _supports(self, flag: str) -> bool:
        return self._help is None or flag in self._help

    def web_enabled(self, spec: RunSpec) -> bool:
        return bool(spec.allow_web) and spec.kind not in ("review", "plan")

    def build_command(self, spec: RunSpec) -> list[str]:
        b = self.resolve_binary() or ["claude"]
        web = self.web_enabled(spec)
        m = spec.model
        schema = spec.schema or (REVIEW_SCHEMA if spec.kind == "review" else RESULT_SCHEMA)
        argv = [*b, "-p", "--output-format", "stream-json", "--verbose", "--model", m.model]
        if m.effort and self._supports("--effort"):
            argv += ["--effort", m.effort]
        argv += ["--no-session-persistence", "--json-schema", json.dumps(schema)]
        attachment_dirs = list(dict.fromkeys(str(Path(path).parent) for path in spec.attachment_paths))
        if attachment_dirs and self._supports("--add-dir"):
            # Every upload is kept in its own digest directory, so Claude can read
            # selected files without gaining access to uploads Jev did not select.
            argv += ["--add-dir", *attachment_dirs]
        requested_tools = [str(x) for x in (spec.task.extra.get("allowed_tools") or []) if str(x)]
        if spec.task.read_only or spec.kind == "review":
            tools = list(self.cfg.get("read_only_tools", ["Read", "Glob", "Grep"]))
            if requested_tools:
                tools = [tool for tool in tools if tool in requested_tools]
            if web:
                tools += [tool for tool in WEB_TOOLS if tool not in tools]
            argv += ["--permission-mode", "dontAsk", "--tools", ",".join(tools)]
            if tools:
                argv += ["--allowedTools", *tools]
        else:
            tools = list(self.cfg.get("allowed_tools", []))
            if requested_tools:
                tools = [tool for tool in tools if tool in requested_tools]
            if web:
                tools += [tool for tool in WEB_TOOLS if tool not in tools]
            argv += ["--permission-mode", self.cfg.get("permission_mode", "acceptEdits")]
            if tools:
                argv += ["--allowedTools", *tools]
        # The web tools leave the deny list only for an opted-in research run; every other deny stays.
        disallowed = [tool for tool in self.cfg.get("disallowed_tools") or [] if not (web and tool in WEB_TOOLS)]
        if disallowed:
            argv += ["--disallowedTools", *disallowed]
        if self._supports("--permission-prompts"):
            argv += ["--permission-prompts", "none"]
        if spec.mcp_selected and spec.mcp_config_path:
            # Only the servers this task opted into; safe-mode would disable MCP, so user settings are
            # excluded via --setting-sources instead.
            argv += ["--mcp-config", spec.mcp_config_path, "--strict-mcp-config", "--setting-sources", "project,local"]
            argv += ["--allowedTools", *[f"mcp__{n}" for n in spec.mcp_selected]]
        else:
            if self._supports("--strict-mcp-config"):
                argv += ["--strict-mcp-config"]
            if self.cfg.get("safe_mode", True) and self._supports("--safe-mode"):
                argv += ["--safe-mode"]
        argv += list(self.cfg.get("extra_args", []))
        return argv

    def on_line(self, line: str, col: RunCollector, spec: RunSpec) -> None:
        s = line.strip()
        if not s:
            return
        try:
            ev = json.loads(s)
        except ValueError:
            sig = claude_limit_from_text(s, utcnow(), spec.model.family)
            if sig:
                col.signals.append(sig)
            return
        col.events += 1
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            col.session_id = ev.get("session_id")
            col.model_seen = ev.get("model")
        elif t == "rate_limit_event":
            info = ev.get("rate_limit_info") or {}
            sig = claude_rate_limit_event(info)
            if sig:
                col.signals.append(sig)
                if sig.kind == "OVERAGE" and not self.allow_overage:
                    col.overage = True
                    col.abort_reason = "claude overage (paid extra usage) refused: billing.allow_claude_overage=false"
        elif t == "assistant":
            for c in (ev.get("message") or {}).get("content") or []:
                if c.get("type") == "text" and c.get("text"):
                    col.final_text = c["text"]
        elif t == "result":
            col.session_id = ev.get("session_id") or col.session_id
            if isinstance(ev.get("result"), str):
                col.final_text = ev["result"]
            if ev.get("structured_output") is not None:
                col.structured = ev["structured_output"]
            if isinstance(ev.get("total_cost_usd"), (int, float)):
                col.cost = float(ev["total_cost_usd"])
            u = ev.get("usage") or {}
            if isinstance(u.get("input_tokens"), int):
                col.usage["input_tokens"] = u["input_tokens"] + int(u.get("cache_creation_input_tokens") or 0)
            if isinstance(u.get("cache_read_input_tokens"), int):
                col.usage["cached_input_tokens"] = u["cache_read_input_tokens"]
            if isinstance(u.get("output_tokens"), int):
                col.usage["output_tokens"] = u["output_tokens"]
            if ev.get("is_error"):
                msg = ev.get("result") if isinstance(ev.get("result"), str) else json.dumps(ev.get("errors") or ev)
                col.errors.append(msg)
                sig = claude_limit_from_text(msg, utcnow(), spec.model.family)
                if sig and not any(x.kind == "LIMIT_HIT" for x in col.signals):
                    col.signals.append(sig)

    def classify(self, rc, col: RunCollector, stderr_text: str, spec: RunSpec, interrupted: bool) -> ExecutionRun:
        if not any(s.kind == "LIMIT_HIT" for s in col.signals):
            sig = claude_limit_from_text(stderr_text[-4000:], utcnow(), spec.model.family)
            if sig:
                col.signals.append(sig)
        errors = "\n".join(col.errors) + "\n" + stderr_text[-4000:]
        run = ExecutionRun(status=AttemptStatus.SUCCEEDED, exit_code=rc, final_text=col.final_text,
                           structured=col.structured, session_id=col.session_id,
                           input_tokens=col.usage.get("input_tokens"),
                           cached_input_tokens=col.usage.get("cached_input_tokens"),
                           output_tokens=col.usage.get("output_tokens"), reported_cost_usd=col.cost,
                           quota_signals=list(col.signals))
        if col.overage:
            run.status, run.failure_class = AttemptStatus.BILLING_BLOCKED, "overage"
        elif any(s.kind == "LIMIT_HIT" for s in col.signals):
            run.status, run.failure_class = AttemptStatus.QUOTA_LIMITED, "quota"
        elif (rc not in (0, None) or col.errors) and is_auth_error(errors):
            run.status, run.failure_class = AttemptStatus.AUTH_ERROR, "auth"
        elif (rc not in (0, None) or col.errors) and is_model_error(errors):
            run.status, run.failure_class = AttemptStatus.MODEL_UNAVAILABLE, "model_unavailable"
        elif interrupted:
            run.status, run.failure_class = AttemptStatus.INTERRUPTED, "interrupted"
        elif rc == 0 and not col.errors:
            run.status = AttemptStatus.SUCCEEDED
        elif rc in (126, 127):
            run.status, run.failure_class = AttemptStatus.CRASHED, "provider_missing"
        else:
            run.status, run.failure_class = AttemptStatus.CRASHED, "cli_error"
        run.error = errors.strip()[-1500:] or None
        return run
