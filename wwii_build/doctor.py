"""`wwii-build doctor`: installation/auth/flags/config checks. No inference.

The only network call is Codex app-server `account/rateLimits/read` (an account read,
not a model call); pass --no-quota to skip it.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import socket
import sqlite3
import subprocess
import sys

from .config import Config
from .control import daemon_pid
from .plan_importer import PlanError, build_requests, compute_waves
from .providers import build_providers
from .worktrees import WorktreeManager

OK, WARN, FAIL = "ok", "warn", "FAIL"


def _line(status: str, name: str, detail: str) -> dict:
    return {"status": status, "check": name, "detail": detail}


async def doctor(cfg: Config, with_quota: bool = True) -> list[dict]:
    out: list[dict] = []
    out.append(_line(OK if sys.version_info >= (3, 11) else FAIL, "python",
                     f"{platform.python_version()} ({sys.executable})"))
    out.append(_line(OK, "platform", f"{platform.system()} {platform.mac_ver()[0] or platform.release()}"))
    out.append(_line(OK, "sqlite", sqlite3.sqlite_version))
    # git / repo
    try:
        v = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
        out.append(_line(OK, "git", v))
    except FileNotFoundError:
        out.append(_line(FAIL, "git", "git not found"))
    wt = WorktreeManager(cfg)
    r = wt.git("rev-parse", "--abbrev-ref", "HEAD", check=False)
    dirty = wt.git("status", "--porcelain", check=False).out.splitlines()
    out.append(_line(OK, "repo", f"{cfg.repo} on branch {r.out.strip()} ({len(dirty)} dirty/untracked entries; "
                                 "the manager never touches them)"))
    if wt.baseline_exists():
        out.append(_line(OK, "integration branch", f"{wt.branch} @ {wt.rev('refs/heads/' + wt.branch)[:12]}"))
    else:
        untracked_plan = wt.git("ls-files", "--others", "--exclude-standard", "--", "context", "docs/game", "game",
                                check=False).out.splitlines()
        out.append(_line(WARN, "integration branch",
                         f"{wt.branch} missing. {len(untracked_plan)} plan files are untracked in git; run "
                         "`wwii-build baseline` to snapshot them (temporary index; your branch/index untouched)"))
    # plan
    try:
        reqs = build_requests(cfg)
        waves = compute_waves(reqs)
        roots = sorted(t.task_id for t in reqs if not t.depends_on)
        out.append(_line(OK, "plan", f"{len(reqs)} dispatch tasks, {max(waves.values()) + 1} waves, roots: {', '.join(roots)}"))
    except (PlanError, OSError, KeyError) as e:
        out.append(_line(FAIL, "plan", str(e)))
    out.append(_line(OK if cfg.overlay_path.exists() else WARN, "plan overlay", str(cfg.overlay_path)))
    out.append(_line(OK if cfg.path else WARN, "config",
                     str(cfg.path) if cfg.path else f"no config file; defaults in use (create {cfg.state_dir / 'config.toml'})"))
    billing = cfg.section("billing")
    out.append(_line(OK if not billing.get("allow_api_billing") else WARN, "billing",
                     f"allow_api_billing={billing.get('allow_api_billing')} allow_claude_overage={billing.get('allow_claude_overage')}"))
    leaked = [k for k in os.environ if k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CODEX_API_KEY")]
    if leaked:
        out.append(_line(WARN, "api keys in environment",
                         f"{', '.join(leaked)} set in your shell; workers never receive them (env allowlist)"))
    # providers
    providers = build_providers(cfg)
    for name, p in providers.items():
        pc = cfg.provider(name)
        if not pc.get("enabled", True):
            out.append(_line(WARN, f"{name}", "disabled in config"))
            continue
        rep = await p.check_status(with_quota=with_quota)
        if not rep.installed:
            out.append(_line(FAIL, f"{name} installed", "; ".join(rep.notes)))
            continue
        out.append(_line(OK, f"{name} installed", f"{rep.version} at {' '.join(rep.binary)}"))
        out.append(_line(OK if rep.flags_ok else FAIL, f"{name} flags",
                         "all required non-interactive/structured flags present" if rep.flags_ok
                         else f"missing {rep.missing_flags}"))
        st = OK if rep.auth_mode == "subscription" and rep.billing_ok else FAIL
        out.append(_line(st, f"{name} auth", f"mode={rep.auth_mode}; {rep.auth_detail}"))
        for n in rep.notes:
            out.append(_line(WARN if "not" in n.lower() or "fail" in n.lower() else OK, f"{name} note", n))
        if rep.quota:
            snap = (rep.quota.get("rateLimitsByLimitId") or {}).get("codex") or rep.quota.get("rateLimits") or {}
            for wname in ("primary", "secondary"):
                w = snap.get(wname)
                if w:
                    import datetime as dt
                    reset = dt.datetime.fromtimestamp(w["resetsAt"]).astimezone().isoformat(timespec="minutes") \
                        if w.get("resetsAt") else "unknown"
                    out.append(_line(WARN if w.get("usedPercent", 0) >= 90 else OK, f"{name} quota {wname}",
                                     f"{w.get('usedPercent')}% used of {w.get('windowDurationMins')}-min window; "
                                     f"resets {reset}; plan {snap.get('planType')}"))
            rc = rep.quota.get("rateLimitResetCredits") or {}
            if rc.get("availableCount"):
                out.append(_line(OK, f"{name} banked resets",
                                 f"{rc['availableCount']} available — never consumed automatically"))
        models = await p.inspect_models()
        listed = {m.id for m in models}
        for key, m in cfg.models().items():
            if m.provider != name:
                continue
            if not models:
                out.append(_line(OK, f"model {key}", f"{m.model} (CLI has no model listing; validated on first use)"))
            elif m.model in listed:
                out.append(_line(OK, f"model {key}", f"{m.model} listed in local catalog"))
            else:
                out.append(_line(WARN, f"model {key}", f"{m.model} not in `codex debug models` catalog; may be gated. "
                                                       "Status stays UNKNOWN until a real run confirms"))
    # dashboard port
    host, port = cfg.section("dashboard").get("host", "127.0.0.1"), int(cfg.section("dashboard").get("port", 8765))
    pid = daemon_pid(cfg)
    s = socket.socket()
    try:
        s.bind((host, port))
        out.append(_line(OK, "dashboard port", f"{host}:{port} free"))
    except OSError:
        out.append(_line(OK if pid else WARN, "dashboard port",
                         f"{host}:{port} in use" + (f" (daemon pid {pid})" if pid else "")))
    finally:
        s.close()
    out.append(_line(OK, "daemon", f"running (pid {pid})" if pid else "not running"))
    return out


def render(lines: list[dict]) -> str:
    w = max(len(x["check"]) for x in lines)
    return "\n".join(f"[{x['status']:4}] {x['check']:<{w}}  {x['detail']}" for x in lines)
