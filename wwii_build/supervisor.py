"""Process supervisor: every task runs as a separate child in its own process group,
wrapped by childguard. Captures stdout/stderr to files, streams stdout lines to a
callback, supports graceful interrupt -> terminate -> kill."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

GUARD = str(Path(__file__).resolve().parent / "childguard.py")


def process_start_time(pid: int) -> str | None:
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        s = out.stdout.strip()
        return s or None
    except Exception:
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def is_same_process(pid: int | None, started: str | None) -> bool:
    """PID reuse guard: alive AND same start time as recorded."""
    if not pid_alive(pid):
        return False
    return started is not None and process_start_time(pid) == started


def signal_pid(pid: int | None, sig: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def signal_group(pgid: int | None, sig: int) -> bool:
    if not pgid:
        return False
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


@dataclass
class Handle:
    proc: asyncio.subprocess.Process
    pid: int
    pgid: int
    started: str | None
    stdout_path: str
    stderr_path: str
    started_at: float = field(default_factory=time.time)
    interrupted: bool = False
    killed: bool = False
    _tasks: list = field(default_factory=list)

    @property
    def returncode(self) -> int | None:
        return self.proc.returncode


class Supervisor:
    def __init__(self):
        self.handles: dict[int, Handle] = {}   # attempt_id -> handle

    async def spawn(self, key: int, argv: list[str], *, cwd: str, env: dict, stdin_path: str | None,
                    stdout_path: str, stderr_path: str,
                    on_stdout_line: Callable[[str], None] | None = None) -> Handle:
        Path(stdout_path).parent.mkdir(parents=True, exist_ok=True)
        stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", GUARD, "--parent", str(os.getpid()), "--", *argv,
                cwd=cwd, env=env, stdin=stdin, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True, limit=16 * 1024 * 1024)
        finally:
            if stdin_path:
                stdin.close()
        h = Handle(proc=proc, pid=proc.pid, pgid=proc.pid, started=process_start_time(proc.pid),
                   stdout_path=stdout_path, stderr_path=stderr_path)
        h._tasks = [asyncio.create_task(self._pump(proc.stdout, stdout_path, on_stdout_line)),
                    asyncio.create_task(self._pump(proc.stderr, stderr_path, None))]
        self.handles[key] = h
        return h

    @staticmethod
    async def _pump(stream, path: str, cb) -> None:
        with open(path, "ab") as f:
            while True:
                line = await stream.readline()
                if not line:
                    break
                f.write(line)
                f.flush()
                if cb:
                    try:
                        cb(line.decode("utf-8", "replace"))
                    except Exception as e:  # parsing must never kill the pump
                        f.write(f"\n[wwii-build parser error: {e!r}]\n".encode())

    async def wait(self, key: int, timeout: float | None = None) -> int | None:
        h = self.handles[key]
        try:
            await asyncio.wait_for(h.proc.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        await asyncio.gather(*h._tasks, return_exceptions=True)
        return h.proc.returncode

    def interrupt(self, key: int) -> None:
        h = self.handles.get(key)
        if h and h.returncode is None:
            h.interrupted = True
            signal_pid(h.pid, signal.SIGINT)   # guard forwards once; group-wide would double-deliver

    def kill(self, key: int) -> None:
        h = self.handles.get(key)
        if h and h.returncode is None:
            h.killed = True
            signal_group(h.pgid, signal.SIGKILL)

    async def shutdown(self, key: int, graceful: float, term_grace: float = 5.0) -> int | None:
        """SIGINT -> wait -> SIGTERM -> wait -> SIGKILL."""
        h = self.handles.get(key)
        if not h:
            return None
        if h.returncode is None:
            self.interrupt(key)
            rc = await self.wait(key, graceful)
            if rc is None:
                signal_pid(h.pid, signal.SIGTERM)
                rc = await self.wait(key, term_grace)
            if rc is None:
                self.kill(key)
                rc = await self.wait(key, 5)
        return h.returncode

    def forget(self, key: int) -> None:
        self.handles.pop(key, None)

    def running_keys(self) -> list[int]:
        return [k for k, h in self.handles.items() if h.returncode is None]
