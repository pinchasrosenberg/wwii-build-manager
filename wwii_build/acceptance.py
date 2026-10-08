"""Deterministic acceptance. The manager runs these itself; no model is asked whether
the build passed.

Built-in checks: ownership (write scope), git diff --check, secret scan, non-empty
change for build tasks, handoff validity (advisory), dependency-manifest policy.
Commands: [acceptance].default_commands + the task's overlay commands + pytest files
the worker added inside its own write scope.
A receipt (JSON) bound to the task branch HEAD lets `resume` skip re-running.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Config
from .models import TaskRequest, iso, utcnow
from .sanitize import _PATTERNS, child_env

DEP_MANIFESTS = re.compile(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|setup\.(py|cfg)|package(-lock)?\.json|"
                           r"yarn\.lock|pnpm-lock\.yaml|Pipfile(\.lock)?|poetry\.lock|uv\.lock|Cargo\.(toml|lock))$")


@dataclass
class Check:
    name: str
    kind: str              # builtin | command
    passed: bool
    blocking: bool = True
    exit_code: int | None = None
    duration_s: float = 0.0
    output_tail: str = ""
    paths: list[str] = field(default_factory=list)     # e.g. ownership violations


@dataclass
class AcceptanceReport:
    task_id: str
    head_commit: str | None
    checks: list[Check] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    force_review: list[str] = field(default_factory=list)
    ran_task_commands: bool = False

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking)

    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.blocking and not c.passed]

    def receipt(self) -> dict:
        return {"task_id": self.task_id, "head_commit": self.head_commit, "passed": self.passed,
                "force_review": self.force_review, "ran_task_commands": self.ran_task_commands,
                "checks": [asdict(c) for c in self.checks], "at": iso(utcnow())}


def resolve_python(cfg: Config) -> str:
    p = cfg.section("acceptance").get("python")
    if p:
        return p
    readme = cfg.repo / "game" / "README.md"
    if readme.is_file():
        m = re.search(r"(/[^\s`]+/\.venv/bin/python\S*)", readme.read_text(errors="replace"))
        if m and os.path.exists(m.group(1)):
            return m.group(1)
    return sys.executable


def in_scope(path: str, scope: list[str]) -> bool:
    for s in scope:
        if s.endswith("/"):
            if path.startswith(s):
                return True
        elif path == s or path.startswith(s + "/"):
            return True
    return False


def _fmt(v: str, ctx: dict) -> str:
    for k, val in ctx.items():
        v = v.replace("{" + k + "}", val)
    return v


_RUNNING: set[subprocess.Popen] = set()
_RUNNING_LOCK = threading.Lock()


def kill_running_commands() -> int:
    """Stop/kill path: acceptance commands run in threads; kill their process groups."""
    n = 0
    with _RUNNING_LOCK:
        for p in list(_RUNNING):
            try:
                os.killpg(p.pid, signal.SIGKILL)
                n += 1
            except ProcessLookupError:
                pass
    return n


def run_command(argv: list[str], cwd: Path, env: dict, timeout: float) -> tuple[int | None, str, float]:
    t0 = time.time()
    try:
        p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             start_new_session=True)
    except (FileNotFoundError, PermissionError) as e:
        return 127, str(e), time.time() - t0
    with _RUNNING_LOCK:
        _RUNNING.add(p)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out.decode("utf-8", "replace"), time.time() - t0
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, _ = p.communicate()
        return None, out.decode("utf-8", "replace") + "\n[timeout]", time.time() - t0
    finally:
        with _RUNNING_LOCK:
            _RUNNING.discard(p)


def run_acceptance(cfg: Config, wt, task: TaskRequest, worktree: Path, base: str, handoff_status: str,
                   tail_bytes: int = 6000) -> AcceptanceReport:
    head = wt.head(worktree)
    rep = AcceptanceReport(task.task_id, head)
    changed = wt.changed_files(worktree, base)
    rep.changed_files = changed

    # ownership
    outside = [f for f in changed if not in_scope(f, task.write_scope)]
    rep.checks.append(Check("ownership", "builtin", not outside, paths=outside,
                            output_tail=("outside write scope:\n" + "\n".join(outside)) if outside else "ok"))
    # diff --check
    ok, out = wt.diff_check(worktree, base)
    rep.checks.append(Check("diff-check", "builtin", ok, output_tail=out or "ok"))
    # secrets
    from .generated import EXCLUDE_PATHSPECS
    diff = wt.git("diff", "-U0", f"{base}..HEAD", "--", ".", *EXCLUDE_PATHSPECS, cwd=worktree).out
    added = "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    hits = [p.pattern[:40] for p in _PATTERNS if p.search(added)]
    rep.checks.append(Check("no-secrets", "builtin", not hits, output_tail=("patterns: " + ", ".join(hits)) if hits else "ok"))
    # non-empty
    if not task.read_only:
        rep.checks.append(Check("nonempty-change", "builtin", bool(changed),
                                output_tail="no files changed" if not changed else f"{len(changed)} files"))
    # handoff (advisory)
    rep.checks.append(Check("handoff-valid", "builtin", handoff_status == "VALID", blocking=False,
                            output_tail=handoff_status))
    if handoff_status != "VALID":
        rep.force_review.append(f"handoff {handoff_status}")
    # dependency manifests
    deps = [f for f in changed if DEP_MANIFESTS.search(f)]
    policy = cfg.section("approvals").get("dependency_changes", "review")
    if deps:
        if task.extra.get("system_task"):
            rep.checks.append(Check("dependency-changes", "builtin", False,
                                    output_tail="Task Manager self-repair cannot activate dependency changes: "
                                                + ", ".join(deps)))
        elif policy == "block":
            rep.checks.append(Check("dependency-changes", "builtin", False, output_tail="blocked: " + ", ".join(deps)))
        else:
            rep.checks.append(Check("dependency-changes", "builtin", True, blocking=False,
                                    output_tail=f"{policy}: " + ", ".join(deps)))
            if policy == "review":
                rep.force_review.append("dependency manifests changed: " + ", ".join(deps))

    # commands
    py = resolve_python(cfg)
    ctx = {"python": py, "repo": str(cfg.repo), "worktree": str(worktree), "task_id": task.task_id}
    acfg = cfg.section("acceptance")
    default_timeout = float(acfg.get("command_timeout_seconds", 900))
    cmds = [dict(c, _task=False) for c in acfg.get("default_commands", [])] + \
           [dict(c, _task=True) for c in task.acceptance]
    if acfg.get("run_scope_pytests", True) and not task.read_only:
        tests = sorted({f for f in changed if re.search(r"(^|/)test_[^/]*\.py$", f) and in_scope(f, task.write_scope)
                        and (worktree / f).exists()})
        if tests:
            cmds.append({"name": "scope-pytests", "argv": ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                                          *tests],
                         "env": {"PYTHONPATH": "{worktree}:{repo}/.runtime-deps/driver-runtime"}, "_task": False})
    for c in cmds:
        when = c.get("when_exists")
        if when and not (worktree / when).exists():
            continue
        argv = [_fmt(a, ctx) for a in c["argv"]]
        extra = {k: _fmt(v, ctx) for k, v in (c.get("env") or {}).items()}
        extra.update({"WWII_PY": py, "WWII_REPO": str(cfg.repo), "WWII_WORKTREE": str(worktree),
                      "PYTHONDONTWRITEBYTECODE": "1"})   # acceptance must not create __pycache__ in the worktree
        env = child_env(extra, path_extra=[str(Path(py).parent)])
        rc, out, dur = run_command(argv, worktree, env, float(c.get("timeout_seconds", default_timeout)))
        rep.checks.append(Check(c["name"], "command", rc == 0, exit_code=rc, duration_s=round(dur, 2),
                                output_tail=out[-tail_bytes:]))
        if c["_task"]:
            rep.ran_task_commands = True
    return rep


def save_receipt(rep: AcceptanceReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep.receipt(), ensure_ascii=False, indent=1))
