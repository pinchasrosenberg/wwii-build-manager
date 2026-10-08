"""ONE real end-to-end smoke run against an installed CLI, in a throwaway repo.

Spends a small amount of *subscription* quota (never API billing). Not collected by
`unittest discover` (file name does not start with test_). Opt-in only:

    python3 tools/build_manager/tests/smoke_real.py --provider codex --yes-spend-quota
    python3 tools/build_manager/tests/smoke_real.py --provider claude --yes-spend-quota

The task is trivial (write one file) and runs at low effort. It never touches the game plan.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeEnv, drive, init_repo, mini_plan, state  # noqa: E402

BRIEF = """# SMOKE — build manager smoke test

Create exactly one file: `smoke/hello.txt` containing the single line `hello from the build farm`.
Do not create or modify anything else. Then return the JSON handoff.
"""


async def main(provider: str) -> int:
    with tempfile.TemporaryDirectory(prefix="wwii-build-smoke-") as td:
        root = Path(td)
        repo = init_repo(root)
        profile = "IMPLEMENT" if provider == "codex" else "DESIGN"
        mini_plan(repo, [{"task_id": "SMOKE/hello", "owner": "smoke", "scope": "smoke/", "model_profile": profile}])
        (repo / "context/game/build_packets/SMOKE/BRIEF.md").write_text(BRIEF)
        other = "claude" if provider == "codex" else "codex"
        env = FakeEnv(root, overrides={
            "providers": {"codex": {"command": ["codex"]}, "claude": {"command": []}, other: {"enabled": False}},
            "models": {"sol": {"effort": "low"}, "sonnet": {"effort": "low"}},
            "acceptance": {"default_commands": [{"name": "hello-file",
                                                 "argv": ["/bin/sh", "-c", "grep -q 'hello from the build farm' smoke/hello.txt"]}]},
            "scheduler": {"task_timeout_minutes": 10},
        })
        s = env.scheduler()
        await s.refresh_all()
        print("provider status:", [dict(r) for r in s.db.q("SELECT provider, family, status, used_percent, source "
                                                           "FROM provider_state")])
        try:
            await drive(s, lambda: state(s, "SMOKE/hello") in ("PASSED", "REVIEW_REQUIRED", "BLOCKED",
                                                                "WAITING_PROVIDER", "WAITING_QUOTA"), timeout=660)
        finally:
            await s.shutdown_workers("stop")
        t = s.db.task("SMOKE/hello")
        print("final state:", t["state"], "-", t["state_reason"])
        for a in s.db.q("SELECT * FROM task_attempts"):
            row = {k: a[k] for k in ("provider", "model", "effort", "status", "failure_class", "exit_code",
                                     "input_tokens", "cached_input_tokens", "output_tokens", "reported_cost_usd",
                                     "handoff_status", "session_id", "started_at", "ended_at")}
            print("attempt:", json.dumps(row, indent=1))
            print("quota before:", a["quota_before"])
            print("quota after: ", a["quota_after"])
            print("command:", a["command"][:600] if a["command"] else None)
            out = Path(a["stdout_path"]).read_text(errors="replace") if a["stdout_path"] else ""
            print("event types:", sorted({json.loads(l).get("type") for l in out.splitlines() if l.startswith("{")}))
        for r in s.db.q("SELECT name, passed FROM test_results"):
            print("check:", r["name"], "pass" if r["passed"] else "FAIL")
        return 0 if t["state"] == "PASSED" else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["codex", "claude"], required=True)
    ap.add_argument("--yes-spend-quota", action="store_true")
    a = ap.parse_args()
    if not a.yes_spend_quota:
        sys.exit("refusing: pass --yes-spend-quota to run one real (subscription) request")
    sys.exit(asyncio.run(main(a.provider)))
