"""Acceptance simulation on the REAL dispatch graph with fake CLIs (no LLM, no quota).

Scenario (spec step 59):
  B00/contracts, B03/evidence_sources, B07/inventory are the ready roots.
  - B03 finishes (Claude/opus).
  - B07 gets a simulated Codex usage limit -> the scheduler moves it to the Claude fallback.
  - B00 (DEEP) requires approval.
  Pause stops new tasks; resume continues; stop closes every process and saves state;
  a restart restores it without re-running finished work.
Then the rest of the graph runs to completion (approving premium runs as they appear).
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from helpers import (REAL_REGISTRY, FakeEnv, TmpTestCase, copy_real_plan, drive, git, init_repo, mini_plan,
                     state)

from wwii_build import control
from wwii_build.config import Config, deep_merge
from wwii_build.dashboard import Dashboard
from wwii_build.dryrun import dry_run, render
from wwii_build.supervisor import pid_alive
from wwii_build.worktrees import WorktreeManager

OVERLAY = '''
[tasks."B07/inventory"]
write_scope = ["docs/game/reports/B07_inventory/"]
'''
ROOTS = ("B00/contracts", "B03/evidence_sources", "B07/inventory")
DEBUG_STATE = []


async def wait_for(pred, timeout=30.0, step=0.05, what=""):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        await asyncio.sleep(step)
    raise AssertionError(f"timeout waiting for {what}; {DEBUG_STATE[0]() if DEBUG_STATE else ''}")


@unittest.skipUnless(REAL_REGISTRY.is_file(), "real registry not present")
class FullSimulation(TmpTestCase):
    async def test_step59_scenario_and_whole_graph(self):
        repo = init_repo(self.tmp)
        copy_real_plan(repo)
        scenario = {
            "codex": {"tasks": {"B07/inventory": ["rate_limit_iso:3600"]}},
            "claude": {"tasks": {"B03/evidence_sources": ["long_running:1"],
                                 "B00/contracts": ["long_running:60", "success"],
                                 "B03/evidence_claims": ["long_running:60", "success"]}},
        }
        env = FakeEnv(self.tmp, scenario, overlay=OVERLAY)
        svc = env.services()
        s = env.scheduler(svc)
        db = s.db
        DEBUG_STATE[:] = [lambda: json.dumps({r["task_id"]: [r["state"], r["state_reason"]] for r in db.q(
            "SELECT * FROM tasks WHERE state NOT IN ('WAITING_DEPENDENCY')")} | {"approvals": [dict(a) for a in db.q(
            "SELECT id, task_id, subject, status FROM approvals")]}, indent=1)]
        run1 = asyncio.create_task(s.run())

        # --- roots: one finishes, one hits Codex quota -> Claude, one needs approval --------------
        await wait_for(lambda: state(s, "B03/evidence_sources") == "PASSED" and state(s, "B07/inventory") == "PASSED",
                       90, what="B03 + B07 passed")
        self.assertEqual(state(s, "B00/contracts"), "WAITING_APPROVAL")
        ap = db.one("SELECT * FROM approvals WHERE task_id='B00/contracts' AND status='pending'")
        self.assertEqual(ap["subject"], "astra")
        b07 = db.q("SELECT provider, model, status FROM task_attempts WHERE task_id='B07/inventory' ORDER BY id")
        self.assertEqual([(a["provider"], a["status"]) for a in b07], [("codex", "QUOTA_LIMITED"), ("claude", "SUCCEEDED")])
        self.assertEqual(b07[1]["model"], "claude-sonnet-5-5")               # VISUAL chain: sol -> sonnet
        self.assertEqual(db.one("SELECT model FROM task_attempts WHERE task_id='B03/evidence_sources'")["model"],
                         "claude-opus-5-5")                                 # RESEARCH -> opus (automatic)
        self.assertIn(db.one("SELECT status FROM provider_state WHERE provider='codex' AND family='*'")["status"],
                      ("BLOCKED_UNKNOWN", "BLOCKED_SESSION", "BLOCKED_WEEKLY"))
        # read-only inventory: report filed by the manager and shown as an artifact
        self.assertTrue(db.one("SELECT 1 FROM artifacts WHERE task_id='B07/inventory' AND kind='report'"))
        self.assertIn("docs/game/reports/B07_inventory/REPORT.md",
                      git(repo, "ls-tree", "-r", "--name-only", "wwii-build/integration"))

        # --- pause stops new tasks ------------------------------------------------------------------
        control.pause(db, env.cfg)
        # astra approved, but Codex is blocked -> DEEP falls to opus, which also needs a human (manual Astra or Opus)
        control.decide(db, env.cfg, ap["id"], True)
        await wait_for(lambda: db.one("SELECT 1 FROM approvals WHERE task_id='B00/contracts' AND subject='opus' "
                                      "AND status='pending'") is not None, 30, what="opus approval")
        ap2 = db.one("SELECT id FROM approvals WHERE task_id='B00/contracts' AND subject='opus' AND status='pending'")
        control.decide(db, env.cfg, ap2["id"], True)
        await wait_for(lambda: state(s, "B00/contracts") == "READY", 30, what="B00 READY while paused")
        # B03/evidence_claims unlocked when B03/evidence_sources passed and may have started before the pause;
        # pause lets running work finish but must start nothing new.
        running_at_pause = {r.task_id for r in s.running.values()}
        await asyncio.sleep(0.8)
        self.assertLessEqual({r.task_id for r in s.running.values()}, running_at_pause | {"B03/evidence_claims"})
        self.assertIsNone(db.one("SELECT 1 FROM task_attempts WHERE task_id='B00/contracts'"))   # paused: not started
        self.assertEqual(state(s, "B00/contracts"), "READY")

        # --- resume continues -----------------------------------------------------------------------
        control.resume(db, env.cfg)
        await wait_for(lambda: len(s.svc.sup.handles) == 2, 40, what="two workers running")
        pids = [h.pid for h in s.svc.sup.handles.values()]
        await wait_for(lambda: len([c for c in env.calls() if c.get("behavior") == "long_running:60"]) == 2, 10,
                       what="fakes started")

        # --- stop: close every process, save state ---------------------------------------------------
        control.enqueue(db, env.cfg, "stop")
        self.assertEqual(await asyncio.wait_for(run1, 30), "stopped")
        for p in pids:
            self.assertFalse(pid_alive(p))
        self.assertEqual(state(s, "B00/contracts"), "PENDING")
        self.assertEqual(state(s, "B03/evidence_claims"), "PENDING")
        self.assertFalse(db.q("SELECT * FROM workers"))
        calls_before = {c["task_id"]: 0 for c in env.calls() if c.get("task_id")}
        for c in env.calls():
            if c.get("task_id"):
                calls_before[c["task_id"]] += 1

        # --- restart restores it -------------------------------------------------------------------------
        svc2 = env.services()                   # fresh process state, same SQLite
        s2 = env.scheduler(svc2)
        notes = await s2.reconcile()
        self.assertEqual(state(s2, "B03/evidence_sources"), "PASSED")        # not re-run
        run2 = asyncio.create_task(s2.run())
        await wait_for(lambda: state(s2, "B00/contracts") == "PASSED", 90, what="B00 passed after restart")
        # B00 unlocks wave 1; Codex is still blocked, so IMPLEMENT work goes to Claude sonnet
        await wait_for(lambda: s2.db.one("SELECT 1 FROM task_attempts WHERE task_id='B01/ground_powertrain'"), 20,
                       what="B01 started")
        self.assertEqual(s2.db.one("SELECT provider FROM task_attempts WHERE task_id='B01/ground_powertrain'")["provider"],
                         "claude")

        # --- drive the whole graph: approve premium runs as a human would ------------------------------
        async def approve_all():
            while True:
                for a in s2.db.q("SELECT id FROM approvals WHERE status='pending'"):
                    control.decide(s2.db, env.cfg, a["id"], True)
                await asyncio.sleep(0.1)
        approver = asyncio.create_task(approve_all())
        try:
            await wait_for(lambda: s2.db.one("SELECT COUNT(*) n FROM tasks WHERE state!='PASSED'")["n"] == 0, 180,
                           step=0.2, what="all tasks passed")
        finally:
            approver.cancel()
        control.enqueue(s2.db, env.cfg, "stop")
        await asyncio.wait_for(run2, 30)

        total = s2.db.one("SELECT COUNT(*) n FROM tasks")["n"]
        self.assertEqual(total, 28)
        # no finished task was ever executed again
        for c in env.calls():
            pass
        after = {}
        for c in env.calls():
            if c.get("task_id"):
                after[c["task_id"]] = after.get(c["task_id"], 0) + 1
        self.assertEqual(after["B03/evidence_sources"], calls_before["B03/evidence_sources"])
        self.assertEqual(after["B07/inventory"], calls_before["B07/inventory"])
        # final integration saw everything, integration branch holds every task's output
        tree = git(repo, "ls-tree", "-r", "--name-only", "wwii-build/integration")
        self.assertIn("capabilities/ground_vehicles/assemblies/ground_vehicle/fake_claude.txt", tree)
        merges = git(repo, "log", "--oneline", "--merges", "wwii-build/integration").splitlines()
        self.assertEqual(len(merges), 28)
        ev = {r["event"] for r in s2.db.q("SELECT DISTINCT event FROM event_log")}
        for e in ("TASK_READY", "TASK_STARTED", "PROVIDER_LIMIT", "FALLBACK_SELECTED", "TASK_COMPLETED",
                  "TASK_PASSED", "PAUSE_REQUESTED", "STOP_REQUESTED", "APPROVAL_REQUIRED", "RECONCILED", "MILESTONE"):
            self.assertIn(e, ev)
        # the user's own branch/index/working tree were never touched
        self.assertEqual(git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip(), "main")
        self.assertEqual(git(repo, "log", "--oneline", "main").count("\n"), 1)


@unittest.skipUnless(REAL_REGISTRY.is_file(), "real registry not present")
class DryRun(TmpTestCase):
    async def test_dry_run_sends_no_llm_request(self):
        repo = init_repo(self.tmp)
        copy_real_plan(repo)
        env = FakeEnv(self.tmp, overlay=OVERLAY, baseline=False)
        rep = await dry_run(env.cfg, check_providers=True)
        would = {w["task_id"]: w for w in rep["would_run"]}
        self.assertEqual(set(would), {"B03/evidence_sources", "B07/inventory"})
        self.assertEqual((would["B07/inventory"]["provider"], would["B07/inventory"]["model"]), ("codex", "gpt-5.6-sol"))
        self.assertEqual((would["B03/evidence_sources"]["provider"], would["B03/evidence_sources"]["model"]),
                         ("claude", "claude-opus-5-5"))
        b00 = next(o for o in rep["not_starting"] if o["task_id"] == "B00/contracts")
        self.assertEqual(b00["state"], "WAITING_APPROVAL")
        self.assertIn("gpt-6-astra", b00["would_use_after_approval"])
        self.assertTrue(Path(would["B07/inventory"]["prompt_path"]).is_file())
        self.assertFalse([c for c in env.calls() if c.get("task_id")])       # zero exec / -p invocations
        self.assertFalse(env.cfg.db_path.exists())                            # nothing persisted
        self.assertFalse(WorktreeManager(env.cfg).baseline_exists())
        text = render(rep)
        self.assertIn("WOULD START NOW (2)", text)
        self.assertIn("B00/contracts", text)


class Dashboard_(TmpTestCase):
    async def test_dashboard_pages_and_csrf(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        env = FakeEnv(self.tmp, overrides={"dashboard": {"port": port}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        d = Dashboard(env.cfg)
        d.serve_in_thread()
        try:
            base = f"http://127.0.0.1:{port}"
            html = await asyncio.to_thread(lambda: urllib.request.urlopen(base + "/classic/").read().decode())
            for needle in ("השהה", "עצור", "עצירת חירום מיידית", "מכסות", "A/1", "לא ידוע"):
                self.assertIn(needle, html)
            page = await asyncio.to_thread(lambda: urllib.request.urlopen(base + "/task?id=A/1").read().decode())
            for needle in ("ניסיונות ביצוע", "הקונטקסט שנשלח", "קבצים שהשתנו", "בדיקות", "תוצרים", "x/fake_codex.txt"):
                self.assertIn(needle, page)
            st = json.loads(await asyncio.to_thread(lambda: urllib.request.urlopen(base + "/api/state").read()))
            self.assertEqual(st["tasks"][0]["state"], "PASSED")

            def post(data: bytes, host=None):
                req = urllib.request.Request(base + "/action", data=data, method="POST")
                if host:
                    req.add_header("Host", host)
                try:
                    return urllib.request.urlopen(req).status
                except urllib.error.HTTPError as e:
                    return e.code
            self.assertEqual(await asyncio.to_thread(post, b"action=pause&token=wrong"), 403)
            self.assertIsNone(s.db.get_flag("paused"))
            self.assertEqual(await asyncio.to_thread(post, f"action=pause&token={d.token}".encode(), "evil.example"), 403)
            self.assertEqual(await asyncio.to_thread(post, f"action=pause&token={d.token}".encode()), 200)
            self.assertEqual(s.db.get_flag("paused"), "1")
        finally:
            d.shutdown()


class Baseline(TmpTestCase):
    async def test_baseline_snapshots_untracked_plan_without_touching_user_tree(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        (repo / "README.md").write_text("locally modified, not staged\n")
        (repo / "scratch.txt").write_text("user's untracked file\n")
        git(repo, "add", "scratch.txt")                 # user has something staged too
        env = FakeEnv(self.tmp, baseline=False)
        wt = WorktreeManager(env.cfg)
        before = (git(repo, "status", "--porcelain"), git(repo, "diff", "--cached"), git(repo, "rev-parse", "HEAD"))
        r = wt.create_baseline(["AGENTS.md", "context", "docs"])
        after = (git(repo, "status", "--porcelain"), git(repo, "diff", "--cached"), git(repo, "rev-parse", "HEAD"))
        self.assertEqual(before, after)
        self.assertTrue(r["created"])
        tree = git(repo, "ls-tree", "-r", "--name-only", "wwii-build/integration")
        self.assertIn("docs/game/LEGO_OWNERSHIP_REGISTRY.json", tree)
        self.assertIn("context/game/global/INVARIANTS.md", tree)
        self.assertNotIn("scratch.txt", tree)
        self.assertEqual(git(repo, "show", "wwii-build/integration:README.md"), "test repo\n")   # HEAD version
        self.assertFalse(wt.create_baseline()["created"])                   # create-only, never overwrites


if __name__ == "__main__":
    unittest.main()
