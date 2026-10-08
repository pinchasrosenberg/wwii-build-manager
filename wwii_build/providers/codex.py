"""CodexCliProvider (verified against codex-cli 0.148.0).

Run:   codex exec --json -m <model> -c model_reasoning_effort="<e>" -s <sandbox> -C <worktree>
             --ephemeral --output-schema <schema> -o <last.json> [--ignore-user-config] -
       (prompt on stdin; JSONL events: thread.started, turn.started, item.*, turn.completed{usage},
        turn.failed{error}, error)
Quota: codex app-server (stdio JSON-RPC) -> account/rateLimits/read. No inference.
       Hard allowlist of methods: the reset-credit consume / add-credits calls can never be sent.
Model and effort are ALWAYS passed explicitly: the user's ~/.codex/config.toml default
(currently gpt-6-astra / ultra) must never be used implicitly.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from ..models import AttemptStatus, ExecutionRun, ProviderStatus, RunSpec, utcnow
from ..sanitize import child_env
from .base import ModelInfo, RunCollector, StatusReport, WorkerProvider, run_cmd, which
from .limits import codex_limit_from_text, is_auth_error, is_model_error

REQUIRED_EXEC_FLAGS = ["--json", "--output-schema", "--output-last-message", "--ephemeral", "--cd", "--sandbox",
                       "--model"]
APP_SERVER_ALLOWED_METHODS = frozenset({"initialize", "initialized", "account/rateLimits/read", "account/read"})


class CodexCliProvider(WorkerProvider):
    name = "codex"
    _exec_help: str | None = None         # `codex exec --help` text from the last status check

    def resolve_binary(self) -> list[str] | None:
        cmd = list(self.cfg.get("command") or ["codex"])
        if not cmd:
            return None
        head = cmd[0]
        if os.path.isabs(head) or os.sep in head:
            return cmd if os.path.exists(head) else None
        found = which(head)
        return [found, *cmd[1:]] if found else None

    def env(self) -> dict:
        extra = {k: os.environ[k] for k in ("CODEX_HOME",) if k in os.environ}
        api = {}
        if self.allow_api_billing:
            api = {k: os.environ[k] for k in ("OPENAI_API_KEY", "CODEX_API_KEY") if k in os.environ}
        return child_env(extra, allow_api_env=api)

    async def check_status(self, *, with_quota: bool = True) -> StatusReport:
        b = self.resolve_binary()
        if not b:
            return StatusReport(self.name, False, status=ProviderStatus.MISSING, notes=["codex binary not found"])
        rep = StatusReport(self.name, True, binary=b)
        rc, out, err = await run_cmd([*b, "--version"], self.env(), 20)
        rep.version = (out or err).strip() or None
        rc, out, err = await run_cmd([*b, "exec", "--help"], self.env(), 20)
        self._exec_help = out
        if "--search" not in out:
            rep.notes.append("codex exec lacks --search: allow_web tasks run without web access")
        rep.missing_flags = [f for f in REQUIRED_EXEC_FLAGS if f not in out]
        rep.flags_ok = not rep.missing_flags
        rc, out, err = await run_cmd([*b, "login", "status"], self.env(), 20)
        text = (out + "\n" + err).strip()
        low = text.lower()
        if "chatgpt" in low and "logged in" in low:
            rep.auth_mode, rep.billing_ok = "subscription", True
        elif "api key" in low and "logged in" in low:
            rep.auth_mode = "api"
            rep.billing_ok = self.allow_api_billing
        elif "not logged in" in low or rc not in (0, None):
            rep.auth_mode = "none"
        else:
            rep.auth_mode = "unknown"
        rep.auth_detail = text.splitlines()[0][:120] if text else ""
        if rep.auth_mode == "none":
            rep.status = ProviderStatus.AUTH_ERROR
        elif not rep.billing_ok:
            rep.status = ProviderStatus.BILLING_BLOCKED
            rep.notes.append("Codex is not in ChatGPT-subscription mode; blocked (billing.allow_api_billing=false)")
        elif not rep.flags_ok:
            rep.status = ProviderStatus.MISSING
            rep.notes.append(f"codex exec lacks required flags: {rep.missing_flags}")
        else:
            rep.status = ProviderStatus.UNKNOWN
        if with_quota and rep.auth_mode == "subscription" and self.cfg.get("quota_source") == "app-server":
            try:
                rep.quota = await self.read_rate_limits(b)
            except Exception as e:  # quota read failing must not block anything by itself
                rep.notes.append(f"rate limit read failed: {e}")
        return rep

    async def read_rate_limits(self, b: list[str] | None = None, timeout: float = 25) -> dict | None:
        b = b or self.resolve_binary()
        if not b:
            return None
        p = await asyncio.create_subprocess_exec(*b, "app-server", env=self.env(), stdin=asyncio.subprocess.PIPE,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                 start_new_session=True, limit=8 * 1024 * 1024)

        async def send(obj: dict) -> None:
            if obj["method"] not in APP_SERVER_ALLOWED_METHODS:     # hard safety allowlist
                raise PermissionError(f"app-server method not allowed: {obj['method']}")
            p.stdin.write((json.dumps(obj) + "\n").encode())
            await p.stdin.drain()

        async def recv(want: int):
            while True:
                line = await p.stdout.readline()
                if not line:
                    return None
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m.get("id") == want:
                    return m

        try:
            async def dialog():
                await send({"id": 1, "method": "initialize",
                            "params": {"clientInfo": {"name": "wwii_build_manager", "version": "0.1.0"}}})
                init = await recv(1)
                if not init or "error" in init:
                    raise RuntimeError(f"initialize failed: {init and init.get('error')}")
                await send({"method": "initialized"})
                await send({"id": 2, "method": "account/rateLimits/read"})
                r = await recv(2)
                if not r or "error" in r:
                    raise RuntimeError(f"rateLimits/read failed: {r and r.get('error')}")
                return r["result"]
            return await asyncio.wait_for(dialog(), timeout)
        finally:
            if p.returncode is None:
                p.terminate()
                try:
                    await asyncio.wait_for(p.wait(), 5)
                except asyncio.TimeoutError:
                    p.kill()
                    await p.wait()

    async def inspect_models(self) -> list[ModelInfo]:
        b = self.resolve_binary()
        if not b:
            return []
        rc, out, err = await run_cmd([*b, "debug", "models"], self.env(), 60)
        try:
            data = json.loads(out)
        except ValueError:
            return []
        return [ModelInfo(m.get("slug"), m.get("visibility") == "list", m.get("visibility", ""))
                for m in data.get("models", []) if m.get("slug")]

    def web_enabled(self, spec: RunSpec) -> bool:
        # `--search` ("Enable live web search") is passed only for an opted-in research run, and only when the
        # installed CLI documents it; otherwise the run stays web-closed rather than failing on an unknown flag.
        supported = self._exec_help is None or "--search" in self._exec_help
        return bool(spec.allow_web) and spec.kind not in ("review", "plan") and supported

    def build_command(self, spec: RunSpec) -> list[str]:
        b = self.resolve_binary() or ["codex"]
        m = spec.model
        sandbox = self.cfg.get("read_only_sandbox", "read-only") if (spec.task.read_only or spec.kind == "review") \
            else self.cfg.get("sandbox", "workspace-write")
        argv = [*b, "exec", "--json", "-m", m.model]
        if m.effort:
            argv += ["-c", f'model_reasoning_effort="{m.effort}"']
        argv += ["-s", sandbox, "-C", spec.worktree, "--ephemeral",
                 "--output-schema", spec.result_schema_path,
                 "-o", str(Path(spec.run_dir) / "last_message.json")]
        if spec.image_paths:
            argv += ["--image", *spec.image_paths]
        if self.web_enabled(spec):
            argv.append("--search")
        if spec.mcp_selected:
            # MCP definitions live in the user config: load it, but enable only the chosen servers.
            for n in spec.mcp_all:
                argv += ["-c", f"mcp_servers.{n}.enabled={'true' if n in spec.mcp_selected else 'false'}"]
        elif self.cfg.get("ignore_user_config", True):
            argv.append("--ignore-user-config")
        argv += list(self.cfg.get("extra_args", []))
        argv.append("-")
        return argv

    def on_line(self, line: str, col: RunCollector, spec: RunSpec) -> None:
        s = line.strip()
        if not s:
            return
        try:
            ev = json.loads(s)
        except ValueError:
            sig = codex_limit_from_text(s, utcnow())
            if sig:
                col.signals.append(sig)
            return
        col.events += 1
        t = ev.get("type", "")
        if t == "thread.started":
            col.session_id = ev.get("thread_id")
        elif t in ("item.completed", "item.updated"):
            item = ev.get("item") or {}
            it = item.get("type") or item.get("item_type")
            if it in ("agent_message", "assistant_message") and item.get("text"):
                col.final_text = item["text"]
            elif it == "error" and item.get("message"):
                self._error(item["message"], col)
        elif t == "turn.completed":
            u = ev.get("usage") or {}
            for k in ("input_tokens", "cached_input_tokens", "output_tokens"):
                if isinstance(u.get(k), int):
                    col.usage[k] = col.usage.get(k, 0) + u[k]
        elif t == "turn.failed":
            err = ev.get("error") or {}
            self._error(err.get("message") if isinstance(err, dict) else str(err), col)
        elif t == "error":
            self._error(ev.get("message") or json.dumps(ev), col)

    @staticmethod
    def _error(msg: str | None, col: RunCollector) -> None:
        if not msg:
            return
        col.errors.append(msg)
        sig = codex_limit_from_text(msg, utcnow())
        if sig:
            col.signals.append(sig)

    def classify(self, rc, col: RunCollector, stderr_text: str, spec: RunSpec, interrupted: bool) -> ExecutionRun:
        last = Path(spec.run_dir) / "last_message.json"
        if last.exists():
            txt = last.read_text(errors="replace")
            col.final_text = txt or col.final_text
            try:
                col.structured = json.loads(txt)
            except ValueError:
                pass
        if not col.signals:
            sig = codex_limit_from_text(stderr_text[-4000:], utcnow())
            if sig:
                col.signals.append(sig)
        errors = "\n".join(col.errors) + "\n" + stderr_text[-4000:]
        run = ExecutionRun(status=AttemptStatus.SUCCEEDED, exit_code=rc, final_text=col.final_text,
                           structured=col.structured, session_id=col.session_id,
                           input_tokens=col.usage.get("input_tokens"),
                           cached_input_tokens=col.usage.get("cached_input_tokens"),
                           output_tokens=col.usage.get("output_tokens"),
                           quota_signals=list(col.signals), last_message_path=str(last) if last.exists() else None)
        if any(s.kind == "LIMIT_HIT" for s in col.signals):
            run.status, run.failure_class = AttemptStatus.QUOTA_LIMITED, "quota"
        elif rc not in (0, None) and is_auth_error(errors):
            run.status, run.failure_class = AttemptStatus.AUTH_ERROR, "auth"
        elif rc not in (0, None) and is_model_error(errors):
            run.status, run.failure_class = AttemptStatus.MODEL_UNAVAILABLE, "model_unavailable"
        elif interrupted:
            run.status, run.failure_class = AttemptStatus.INTERRUPTED, "interrupted"
        elif rc == 0:
            run.status = AttemptStatus.SUCCEEDED
        elif rc in (126, 127):
            run.status, run.failure_class = AttemptStatus.CRASHED, "provider_missing"
        else:
            run.status, run.failure_class = AttemptStatus.CRASHED, "cli_error"
        run.error = errors.strip()[-1500:] or None
        return run
