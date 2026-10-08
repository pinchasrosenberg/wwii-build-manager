"""Test fixtures: throwaway git repos, fake CLI providers, a cycle driver."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path

warnings.simplefilter("ignore", ResourceWarning)   # throwaway sqlite handles in tests

MANAGER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MANAGER))

from wwii_build.config import DEFAULTS, Config, deep_merge  # noqa: E402
from wwii_build.db import DB  # noqa: E402
from wwii_build.plan_importer import import_plan  # noqa: E402
from wwii_build.scheduler import Scheduler, Services  # noqa: E402
from wwii_build.worktrees import WorktreeManager  # noqa: E402

FAKE = MANAGER / "fakes" / "fake_cli.py"
REAL_REPO = MANAGER / "examples" / "ww2-game-plan"   # the real WWII game plan this manager was built for
REAL_REGISTRY = REAL_REPO / "docs/game/LEGO_OWNERSHIP_REGISTRY.json"
OK_CHECK = {"name": "no-broken", "argv": ["/bin/sh", "-c", "! grep -rq BROKEN --include=*.txt ."]}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("test repo\n")
    git(repo, "add", "README.md")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return repo


def copy_real_plan(repo: Path) -> None:
    """Real registry + context tree, left UNTRACKED (like the real repo)."""
    (repo / "docs/game").mkdir(parents=True)
    shutil.copy(REAL_REGISTRY, repo / "docs/game/LEGO_OWNERSHIP_REGISTRY.json")
    shutil.copytree(REAL_REPO / "context", repo / "context")
    shutil.copy(REAL_REPO / "AGENTS.md", repo / "AGENTS.md")


def mini_plan(repo: Path, tasks: list[dict]) -> None:
    """Synthetic registry with the same shape as the real one."""
    items, packets, roles = [], {}, {}
    for t in tasks:
        dom = t.get("domain", "d_" + t["owner"])
        t.setdefault("packet", t["task_id"].split("/")[0])
        t.setdefault("mode", "build")
        t.setdefault("depends_on", [])
        t.setdefault("model_profile", "IMPLEMENT")
        t["context_entry"] = f"context/game/domains/{dom}/roles/{t['owner']}.md"
        lid = "lego." + t["task_id"].replace("/", "_")
        t["lego_ids"] = [lid] if t.get("scope") else []
        if t.get("scope"):
            items.append({"lego_id": lid, "output_path": t.pop("scope"), "dependency_interfaces": ["StableIdentity"],
                          "acceptance_he": "accept", "domain": dom, "owner_agent": t["owner"]})
        else:
            t.pop("scope", None)
        roles[t["owner"]] = {"domain": dom}
        p = packets.setdefault(t["packet"], {"id": t["packet"], "title": f"packet {t['packet']}", "accept": ["works"],
                                             "brief_path": f"context/game/build_packets/{t['packet']}/BRIEF.md",
                                             "context_files": [], "read": []})
        base = repo / "context/game"
        for rel in (f"domains/{dom}/DOMAIN.md", f"domains/{dom}/roles/{t['owner']}.md",
                    f"build_packets/{t['packet']}/BRIEF.md"):
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_text(f"# {rel}\n")
        t.pop("domain", None)
    (repo / "context/game/global").mkdir(parents=True, exist_ok=True)
    (repo / "context/game/global/INVARIANTS.md").write_text("# invariants\n")
    (repo / "context/game/interfaces").mkdir(parents=True, exist_ok=True)
    (repo / "context/game/interfaces/README.md").write_text("# interfaces\n")
    reg = {"dispatch_tasks": tasks, "items": items, "build_packets": list(packets.values()), "owner_roles": roles}
    (repo / "docs/game").mkdir(parents=True, exist_ok=True)
    (repo / "docs/game/LEGO_OWNERSHIP_REGISTRY.json").write_text(json.dumps(reg, indent=1))


LEGACY_ROUTING = {
    "IMPLEMENT": ["sol", "sonnet"], "DESIGN": ["sonnet", "sol"], "RESEARCH": ["opus", "sonnet"],
    "DEEP": ["astra", "opus"], "VISUAL": ["sol", "sonnet"], "EXTRACT": ["luna", "haiku"], "REVIEW": ["opus", "sol"],
    "REPAIR_CODE": ["sol", "sonnet"], "REPAIR_TEXT": ["sonnet", "sol"], "REPAIR_EVIDENCE": ["sonnet", "sol"],
    "REPAIR_HANDOFF": ["sol", "sonnet"], "REPAIR_ESCALATED": ["sonnet", "sol", "opus"],
    "REPAIR_ARCHITECTURE": ["opus", "astra"], "MANUAL": ["sol", "sonnet"], "PLAN": ["sol", "sonnet"],
}


class FakeEnv:
    """A repo + scenario + config wired to the fake CLIs."""

    def __init__(self, root: Path, scenario: dict | None = None, overrides: dict | None = None,
                 overlay: str = "", baseline: bool = True):
        self.root = root
        self.repo = root / "repo" if (root / "repo").exists() else init_repo(root)
        self.scn_path = root / "scenario.json"
        self.log_path = root / "calls.jsonl"
        self.state_path = root / "fake_state.json"
        self.overlay_path = root / "overlay.toml"
        self.overlay_path.write_text(overlay)
        self.write_scenario(scenario or {})
        data = deep_merge(DEFAULTS, {
            # Scripted scenarios need a fixed order (codex first). Production routing is by fit (test_units.FitRouting).
            "routing": LEGACY_ROUTING,
            "providers": {"codex": {"command": [sys.executable, str(FAKE), "codex", "--scenario", str(self.scn_path)]},
                          "claude": {"command": [sys.executable, str(FAKE), "claude", "--scenario", str(self.scn_path)]}},
            "notifications": {"enabled": False},
            # Legacy scheduler tests exercise provider behavior, not the Jev
            # integration. Dedicated listener/context-gate tests enable it.
            "jev": {"enabled": False, "require_for_all_llm_context": False},
            "scheduler": {"control_poll_seconds": 0.05, "retry_backoff_seconds": [0, 0, 0], "task_timeout_minutes": 5},
            "stop": {"graceful_timeout_seconds": 3, "kill_after_term_seconds": 1},
            "acceptance": {"default_commands": [OK_CHECK], "run_scope_pytests": False},
            "plan": {"overlay": str(self.overlay_path)},
            "quota": {"reset_safety_margin_seconds": 1},
            "review": {"auto_pass_requires_task_commands": False},
            "dashboard": {"language": "en"},
            "mcp": {"claude_config_paths": ["{repo}/.mcp.json"]},
        })
        self.cfg = Config(repo=self.repo, data=deep_merge(data, overrides or {}), path=None)
        self.baseline = baseline

    def write_scenario(self, scn: dict) -> None:
        scn = dict(scn)
        scn.setdefault("log", str(self.log_path))
        scn.setdefault("state", str(self.state_path))
        self.scn_path.write_text(json.dumps(scn))

    def calls(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(ln) for ln in self.log_path.read_text().splitlines() if ln.strip()]

    def services(self) -> Services:
        wt = WorktreeManager(self.cfg)
        if self.baseline and not wt.baseline_exists():
            wt.ensure_excludes()
            wt.create_baseline(["AGENTS.md", "context", "docs"])
        svc = Services(self.cfg)
        import_plan(self.cfg, svc.db)
        return svc

    def scheduler(self, svc: Services | None = None, **kw) -> Scheduler:
        s = Scheduler(svc or self.services(), **kw)
        s.prepare()
        return s


async def drive(sched: Scheduler, until, timeout: float = 30.0, step: float = 0.05) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        sched.wake.clear()
        await sched.cycle()
        if until():
            return
        try:
            await asyncio.wait_for(sched.wake.wait(), step)
        except asyncio.TimeoutError:
            pass
    states = {r["task_id"]: (r["state"], r["state_reason"]) for r in sched.db.q("SELECT * FROM tasks")}
    raise AssertionError(f"timeout; states={json.dumps(states, indent=1)}")


def state(sched: Scheduler, tid: str) -> str | None:
    t = sched.db.task(tid)
    return t["state"] if t else None


async def settle(sched: Scheduler, timeout: float = 20) -> None:
    """Wait for all running attempts / finalizers."""
    end = time.monotonic() + timeout
    while (sched.running or sched.post) and time.monotonic() < end:
        await asyncio.sleep(0.05)


class TmpTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="wwii-build-test-")
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()
