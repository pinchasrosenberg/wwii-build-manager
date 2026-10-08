"""WorkerProvider: the only thing the scheduler knows about an execution backend.

Codex CLI and Claude Code CLI implement it today; a future DeliverRuntimeProvider
implements the same interface (quote -> run -> result) without touching the scheduler.
"""
from __future__ import annotations

import abc
import asyncio
import datetime as dt
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..models import (AttemptStatus, ExecutionQuote, ExecutionRun, ModelProfile, ProviderStatus,
                      QuotaSignal, RunSpec, utcnow)
from ..supervisor import Supervisor


@dataclass
class StatusReport:
    provider: str
    installed: bool
    binary: list[str] | None = None
    version: str | None = None
    auth_mode: str | None = None          # subscription | api | none | unknown
    auth_detail: str = ""
    billing_ok: bool = False              # False blocks dispatch
    status: ProviderStatus = ProviderStatus.UNKNOWN
    flags_ok: bool = True
    missing_flags: list[str] = field(default_factory=list)
    quota: dict | None = None             # raw machine-readable quota, when available
    notes: list[str] = field(default_factory=list)


@dataclass
class ModelInfo:
    id: str
    listed: bool
    detail: str = ""


class RunCollector:
    """Accumulates parsed stream state for one run (fed line by line)."""

    def __init__(self):
        self.final_text: str | None = None
        self.structured = None
        self.session_id: str | None = None
        self.usage: dict = {}
        self.cost: float | None = None
        self.errors: list[str] = []
        self.signals: list[QuotaSignal] = []
        self.overage = False
        self.abort_reason: str | None = None   # provider asks the runner to stop this run now
        self.model_seen: str | None = None
        self.events = 0


async def run_cmd(argv: list[str], env: dict, timeout: float = 30, stdin: bytes | None = None,
                  cwd: str | None = None) -> tuple[int | None, str, str]:
    try:
        p = await asyncio.create_subprocess_exec(*argv, env=env, cwd=cwd, stdin=asyncio.subprocess.PIPE,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                 start_new_session=True)
    except (FileNotFoundError, PermissionError) as e:
        return None, "", str(e)
    try:
        out, err = await asyncio.wait_for(p.communicate(stdin), timeout)
    except asyncio.TimeoutError:
        p.kill()
        await p.wait()
        return None, "", "timeout"
    return p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


class WorkerProvider(abc.ABC):
    name: str = "abstract"

    def __init__(self, cfg: dict, allow_api_billing: bool = False):
        self.cfg = cfg
        self.allow_api_billing = allow_api_billing
        self._status_cache: tuple[float, StatusReport] | None = None

    # --- interface -------------------------------------------------------
    @abc.abstractmethod
    def resolve_binary(self) -> list[str] | None: ...

    @abc.abstractmethod
    async def check_status(self, *, with_quota: bool = True) -> StatusReport: ...

    @abc.abstractmethod
    async def inspect_models(self) -> list[ModelInfo]: ...

    @abc.abstractmethod
    def build_command(self, spec: RunSpec) -> list[str]: ...

    @abc.abstractmethod
    def env(self) -> dict: ...

    @abc.abstractmethod
    def on_line(self, line: str, col: RunCollector, spec: RunSpec) -> None: ...

    @abc.abstractmethod
    def classify(self, rc: int | None, col: RunCollector, stderr_text: str, spec: RunSpec,
                 interrupted: bool) -> ExecutionRun: ...

    def web_enabled(self, spec: RunSpec) -> bool:
        """Whether this run gets web tools. Closed unless the task opted in (spec.allow_web) and the
        provider can honor it; reviews and planner runs never get web access."""
        return False

    def quote(self, model: ModelProfile) -> ExecutionQuote:
        return ExecutionQuote(provider=self.name, model_key=model.key, quota_family=model.family,
                              billing_mode="subscription" if not self.allow_api_billing else "unknown")

    async def cached_status(self, max_age: float = 600) -> StatusReport:
        now = asyncio.get_running_loop().time()
        if self._status_cache and now - self._status_cache[0] < max_age:
            return self._status_cache[1]
        st = await self.check_status(with_quota=False)
        self._status_cache = (now, st)
        return st

    def invalidate(self) -> None:
        self._status_cache = None

    # --- shared run loop ---------------------------------------------------
    async def run_task(self, spec: RunSpec, sup: Supervisor, *, timeout: float,
                       on_started=None, on_event=None) -> ExecutionRun:
        argv = self.build_command(spec)
        run_dir = Path(spec.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "command.json").write_text(json.dumps(argv, ensure_ascii=False))
        col = RunCollector()

        def on_line(line: str) -> None:
            before = len(col.signals), col.overage
            self.on_line(line, col, spec)
            if col.abort_reason and not aborted:
                aborted.append(col.abort_reason)
                sup.interrupt(spec.attempt_id)
            if on_event and (len(col.signals), col.overage) != before:
                on_event(col)

        aborted: list[str] = []

        h = await sup.spawn(spec.attempt_id, argv, cwd=spec.worktree, env=self.env(), stdin_path=spec.prompt_path,
                            stdout_path=str(run_dir / "stdout.jsonl"), stderr_path=str(run_dir / "stderr.log"),
                            on_stdout_line=on_line)
        if on_started:
            on_started(h)
        rc = await sup.wait(spec.attempt_id, timeout)
        timed_out = rc is None
        if timed_out:
            rc = await sup.shutdown(spec.attempt_id, graceful=20)
        stderr_text = Path(h.stderr_path).read_text(errors="replace") if Path(h.stderr_path).exists() else ""
        run = self.classify(rc, col, stderr_text, spec, interrupted=h.interrupted or h.killed)
        if timed_out and run.status in (AttemptStatus.CRASHED, AttemptStatus.INTERRUPTED):
            run.status, run.failure_class = AttemptStatus.TIMED_OUT, "timeout"
        run.stdout_path, run.stderr_path = h.stdout_path, h.stderr_path
        run.exit_code = rc
        sup.forget(spec.attempt_id)
        return run


def which(cmd: str) -> str | None:
    return shutil.which(cmd, path=os.pathsep.join([os.environ.get("PATH", ""), os.path.expanduser("~/.local/bin"),
                                                   "/opt/homebrew/bin", "/usr/local/bin"]))


def epoch(ts) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def now() -> dt.datetime:
    return utcnow()
