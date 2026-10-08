"""Child guard: runs one worker CLI and makes sure it cannot outlive the daemon.

Usage: python -I childguard.py --parent <pid> -- <argv...>

* Runs in its own session/process group (created by the supervisor); the CLI
  inherits that group, so the supervisor can signal the whole group.
* Forwards SIGINT/SIGTERM to the CLI.
* If the daemon disappears (crash, SIGKILL, laptop lid + OOM ...), sends SIGINT to
  the CLI, then SIGTERM, then SIGKILL. No orphaned Claude/Codex processes.
Stdlib only, no imports from the package (runs with -I).
"""
import os
import signal
import subprocess
import sys
import time


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 4 or args[0] != "--parent" or args[2] != "--":
        print("usage: childguard.py --parent PID -- argv...", file=sys.stderr)
        return 2
    parent = int(args[1])
    argv = args[3:]
    # A signal arriving while the CLI is being spawned must not kill the guard
    # (KeyboardInterrupt) and orphan the CLI holding our pipes; replay it instead.
    pending = []
    signal.signal(signal.SIGINT, lambda sig, _frame: pending.append(sig))
    signal.signal(signal.SIGTERM, lambda sig, _frame: pending.append(sig))
    try:
        child = subprocess.Popen(argv)
    except FileNotFoundError as e:
        print(f"childguard: executable not found: {e}", file=sys.stderr)
        return 127
    except PermissionError as e:
        print(f"childguard: permission denied: {e}", file=sys.stderr)
        return 126

    def forward(sig, _frame):
        try:
            child.send_signal(sig)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGINT, forward)
    signal.signal(signal.SIGTERM, forward)
    for sig in pending:
        forward(sig, None)

    def parent_alive() -> bool:
        if os.getppid() != parent:
            return False
        try:
            os.kill(parent, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    while True:
        try:
            rc = child.wait(timeout=1.0)
            return rc if rc >= 0 else 128 - rc
        except subprocess.TimeoutExpired:
            pass
        if not parent_alive():
            for sig, grace in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 2)):
                try:
                    child.send_signal(sig)
                except ProcessLookupError:
                    break
                deadline = time.time() + grace
                while time.time() < deadline and child.poll() is None:
                    time.sleep(0.2)
                if child.poll() is not None:
                    break
            return 130


if __name__ == "__main__":
    sys.exit(main())
