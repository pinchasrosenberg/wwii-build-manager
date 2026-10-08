"""Repair Tasks + generated-artifact policy + user-reported usage reset (fake CLIs only)."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from pathlib import Path

from helpers import FakeEnv, TmpTestCase, drive, git, init_repo, mini_plan, state

from wwii_build import control
from wwii_build.generated import is_generated
from wwii_build.models import QuotaSignal, utcnow
from wwii_build.worktrees import WorktreeManager

R1 = "REPAIR/A/1/1"


def one_task(repo, **kw):
    t = {"task_id": "A/1", "owner": "a", "scope": "mod_a/"}
    t.update(kw)
    mini_plan(repo, [t])


def calls_for(env, tid):
    return [c for c in env.calls() if c.get("task_id") == tid]


def tree(repo, ref):
    return git(repo, "ls-tree", "-r", "--name-only", ref)


def events(s, name=None):
    q = "SELECT event, task_id, detail FROM event_log ORDER BY id"
    rows = s.db.q(q)
    return [r for r in rows if name is None or r["event"] == name]


async def until_before_cycle(s, pred, timeout=20):
    """Drive cycles but stop BEFORE the next cycle once pred holds (so nothing new is dispatched)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        s.wake.clear()
        await s.cycle()
        try:
            await asyncio.wait_for(s.wake.wait(), 0.05)
        except asyncio.TimeoutError:
            pass
    raise AssertionError("timeout")


class GeneratedArtifacts(TmpTestCase):
    def test_policy_is_narrow(self):
        for p in ("game/__pycache__/x.cpython-314.pyc", "a/b.pyc", ".pytest_cache/v/x", "x/.mypy_cache/y",
                  ".ruff_cache/z", ".coverage", "a/.DS_Store", "__pycache__/m.pyc"):
            self.assertTrue(is_generated(p), p)
        for p in ("a/b.py", "a/pycache.txt", "cache/x.json", "a/coverage.md", "tests/test_x.py"):
            self.assertFalse(is_generated(p), p)

    async def test_1_pycache_does_not_cause_ownership_failure(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["pycache"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        own = s.db.q("SELECT passed, output_tail FROM test_results WHERE name='ownership'")
        self.assertTrue(all(r["passed"] for r in own))
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE kind='repair'"))       # no LLM repair needed
        self.assertEqual(len(calls_for(env, "A/1")), 1)

    async def test_2_pyc_never_committed_and_precommitted_pyc_is_cleaned(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["pycache"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        for ref in ("wwii-build/task/A__1", "wwii-build/integration"):
            t = tree(env.repo, ref)
            self.assertNotIn(".pyc", t)
            self.assertNotIn(".pytest_cache", t)
            self.assertNotIn(".DS_Store", t)
            self.assertIn("mod_a/fake_codex.txt", t)
        # B03 regression: generated files already committed on a task branch are untracked by the manager (no LLM)
        repo2 = self.tmp / "b03"
        repo2.mkdir()
        r = init_repo(repo2)
        one_task(r)
        env2 = FakeEnv(repo2)
        s2 = env2.scheduler()
        await drive(s2, lambda: state(s2, "A/1") == "PASSED")
        wt = Path(s2.db.task("A/1")["worktree"])
        (wt / "game/__pycache__").mkdir(parents=True)
        (wt / "game/__pycache__/contracts.cpython-314.pyc").write_bytes(b"\x00bytecode")
        git(wt, "add", "-f", "game/__pycache__/contracts.cpython-314.pyc")
        git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "old manager committed bytecode")
        s2.db.set_task_state("A/1", "CODE_READY", "simulate recheck of a branch with committed .pyc")
        n_calls = len(calls_for(env2, "A/1"))
        await drive(s2, lambda: state(s2, "A/1") == "PASSED")
        self.assertTrue(events(s2, "GENERATED_ARTIFACTS_CLEANED"))
        self.assertNotIn(".pyc", tree(r, "wwii-build/task/A__1"))
        self.assertEqual(len(calls_for(env2, "A/1")), n_calls)                    # no LLM

    async def test_3_real_out_of_scope_py_still_fails_ownership_then_repairs(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["out_of_scope_py"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        first = s.db.one("SELECT passed, output_tail FROM test_results WHERE name='ownership' ORDER BY id")
        self.assertEqual(first["passed"], 0)
        self.assertIn("outside_scope/mod.py", first["output_tail"])
        rep = s.db.task(R1)
        self.assertEqual(rep["failure_class"], "SCOPE_ERROR")
        self.assertNotIn("outside_scope/mod.py", tree(env.repo, "wwii-build/integration"))


class RepairFlow(TmpTestCase):
    async def test_4_to_10_failed_test_creates_minimal_repair_and_parent_passes(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"], R1: ["slow_fix:1"]}}})
        s = env.scheduler()
        # 4 + 6: failure creates a Repair Task and the parent waits for it
        await drive(s, lambda: state(s, "A/1") == "WAITING_REPAIR" and state(s, R1) == "RUNNING")
        r = s.db.task(R1)
        self.assertEqual((r["kind"], r["parent_task_id"], r["repair_no"], r["failure_class"]),
                         ("repair", "A/1", 1, "REPAIRABLE_CODE"))
        self.assertIsNotNone(r["failed_attempt_id"])
        self.assertIn("no-broken", r["failure_summary"])
        self.assertEqual(s.db.task("A/1")["active_repair_id"], R1)
        self.assertEqual(r["worktree"], s.db.task("A/1")["worktree"])               # same worktree
        # 5: minimal context
        cps = s.db.q("SELECT task_id, prompt_path, manifest, total_bytes FROM context_packs ORDER BY id")
        parent_cp, repair_cp = cps[0], cps[1]
        self.assertEqual(repair_cp["task_id"], R1)
        prompt = Path(repair_cp["prompt_path"]).read_text()
        for needle in ("TASK_ID: REPAIR/A/1/1", "Failure class: REPAIRABLE_CODE", "failed check: `no-broken`",
                       "repair:current-diff", "handoff:parent", "mod_a/", "REPAIR_RESULT"):
            self.assertIn(needle, prompt)
        self.assertNotIn("<<<BEGIN context/game/build_packets", prompt)             # no BRIEF
        self.assertNotIn("<<<BEGIN context/game/domains/d_a/DOMAIN.md", prompt)     # no domain doc
        self.assertNotIn("<<<BEGIN registry:", prompt)
        items = {i["path"]: i["mode"] for i in json.loads(repair_cp["manifest"])["items"]}
        self.assertEqual(items["context/game/build_packets/A/BRIEF.md"], "excluded")
        # 9 + 10: repair -> manager re-runs acceptance -> parent passes, dependents would unlock
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(state(s, R1), "PASSED")
        self.assertTrue(s.db.one("SELECT 1 FROM test_results WHERE via_task_id=? AND name='no-broken' AND passed=1", (R1,)))
        self.assertEqual(len(calls_for(env, "A/1")), 1)                             # original never re-sent
        ra = s.db.one("SELECT model, effort FROM task_attempts WHERE task_id=?", (R1,))
        self.assertEqual((ra["model"], ra["effort"]), ("gpt-5.6-sol", "medium"))      # cheaper than the original
        self.assertEqual(s.db.one("SELECT effort FROM task_attempts WHERE task_id='A/1'")["effort"], "high")
        ev = [e["event"] for e in events(s)]
        for e in ("FAILURE_CLASSIFIED", "REPAIR_CREATED", "REPAIR_STARTED", "REPAIR_COMPLETED", "REPAIR_SUCCEEDED",
                  "TASK_PASSED"):
            self.assertIn(e, ev)
        self.assertIn("OK A/1", (Path(s.db.task("A/1")["worktree"]) / "mod_a/fake_codex.txt").read_text())

    async def test_7_8_unrelated_continue_dependents_blocked(self):
        mini_plan(init_repo(self.tmp), [
            {"task_id": "A/1", "owner": "a", "scope": "mod_a/"},
            {"task_id": "B/1", "owner": "b", "scope": "mod_b/", "depends_on": ["A/1"]},
            {"task_id": "C/1", "owner": "c", "scope": "mod_c/"}])
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"], R1: ["slow_fix:4"],
                                                     "C/1": ["long_running:2"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "C/1") == "PASSED")
        self.assertEqual(state(s, "A/1"), "WAITING_REPAIR")          # C finished while A was being repaired
        self.assertEqual(state(s, "B/1"), "WAITING_DEPENDENCY")
        self.assertIsNone(s.db.get_flag("paused"))                    # no global pause for a task error
        await drive(s, lambda: state(s, "B/1") == "PASSED")
        self.assertEqual(state(s, "A/1"), "PASSED")

    async def test_11_failed_repair_creates_second_repair_with_history(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"], R1: ["noop"], "REPAIR/A/1/2": ["success"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(state(s, R1), "FAILED")
        self.assertEqual(state(s, "REPAIR/A/1/2"), "PASSED")
        p2 = Path(s.db.one("SELECT prompt_path FROM context_packs WHERE task_id='REPAIR/A/1/2'")["prompt_path"]).read_text()
        self.assertIn("repair:history", p2)
        self.assertIn(R1, p2)
        self.assertEqual(s.db.task("A/1")["repairs_count"], 2)

    async def test_12_repair_limit_blocks_and_asks(self):
        one_task(init_repo(self.tmp))
        noop = {f"REPAIR/A/1/{i}": ["noop"] for i in range(1, 5)}
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"], **noop, "REPAIR/A/1/4": ["success"]}},
                                 "claude": {"tasks": noop}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "BLOCKED")
        t = s.db.task("A/1")
        self.assertIn("REPAIR_LIMIT_REACHED", t["state_reason"])
        self.assertEqual(t["repairs_count"], 3)
        self.assertEqual(len(s.db.q("SELECT * FROM tasks WHERE kind='repair'")), 3)
        self.assertEqual(s.db.task("REPAIR/A/1/3")["model_profile"], "REPAIR_ESCALATED")
        self.assertNotEqual(s.db.one("SELECT model FROM task_attempts WHERE task_id='REPAIR/A/1/3'")["model"],
                            "claude-opus-5-5")                          # premium never automatic in repairs
        ap = s.db.one("SELECT * FROM approvals WHERE task_id='A/1' AND kind='repair_limit' AND status='pending'")
        self.assertIsNotNone(ap)
        await asyncio.sleep(0.3)
        n = len([c for c in env.calls() if str(c.get("task_id", "")).startswith("REPAIR/")])
        await s.cycle()
        self.assertEqual(n, 3)                                          # stopped spending
        control.decide(s.db, env.cfg, ap["id"], True, model_key="sol")  # one more, on sol
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(state(s, "REPAIR/A/1/4"), "PASSED")

    async def test_16_architecture_conflict_requests_manual_review(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["edit_shared"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "ARCHITECTURE_REVIEW_REQUIRED")
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE kind='repair'"))       # no automatic repair
        ap = s.db.one("SELECT * FROM approvals WHERE kind='architecture_review' AND status='pending'")
        self.assertIn("game/contracts.py", ap["subject"])
        control.decide(s.db, env.cfg, ap["id"], True, model_key="sonnet")
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(s.db.task(R1)["model_profile"], "REPAIR_ARCHITECTURE")
        self.assertNotIn("game/contracts.py", tree(env.repo, "wwii-build/integration"))

    async def test_20_repair_cannot_violate_parent_scope(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"], R1: ["escape"],
                                                     "REPAIR/A/1/2": ["success"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(state(s, R1), "FAILED")
        self.assertEqual(s.db.task("REPAIR/A/1/2")["failure_class"], "SCOPE_ERROR")
        self.assertNotIn("outside_scope/fake.txt", tree(env.repo, "wwii-build/integration"))

    async def test_malformed_handoff_gets_readonly_handoff_repair(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["malformed"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        r = s.db.task(R1)
        self.assertEqual((r["failure_class"], r["mode"], r["model_profile"]),
                         ("REPAIRABLE_HANDOFF", "read_only_handoff", "REPAIR_HANDOFF"))
        cmd = next(c for c in env.calls() if c.get("task_id") == R1)["args"]
        self.assertEqual(cmd[cmd.index("-s") + 1], "read-only")
        self.assertEqual(s.db.one("SELECT handoff_status FROM task_attempts WHERE task_id='A/1'")["handoff_status"],
                         "VALID")

    async def test_evidence_repair_is_cheap_sonnet_not_opus(self):
        one_task(init_repo(self.tmp), model_profile="RESEARCH")
        env = FakeEnv(self.tmp, {"claude": {"tasks": {"A/1": ["trailing_blank"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(s.db.one("SELECT model FROM task_attempts WHERE task_id='A/1'")["model"], "claude-opus-5-5")
        self.assertEqual(s.db.task(R1)["model_profile"], "REPAIR_EVIDENCE")
        self.assertEqual(s.db.one("SELECT model FROM task_attempts WHERE task_id=?", (R1,))["model"], "claude-sonnet-5-5")
        self.assertIn("diff-check", s.db.task(R1)["failure_summary"])


class NotRepairs(TmpTestCase):
    async def test_13_quota_does_not_create_repair(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"], R1: ["rate_limit_iso:3600"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(s.db.task("A/1")["repairs_count"], 1)                    # quota on the repair: same repair
        att = s.db.q("SELECT provider, status FROM task_attempts WHERE task_id=? ORDER BY id", (R1,))
        self.assertEqual([(a["provider"], a["status"]) for a in att], [("codex", "QUOTA_LIMITED"), ("claude", "SUCCEEDED")])
        # quota on the original: no repair at all
        repo2 = self.tmp / "q2"
        repo2.mkdir()
        one_task(init_repo(repo2))
        env2 = FakeEnv(repo2, {"codex": {"tasks": {"A/1": ["rate_limit_iso:3600"]}}})
        s2 = env2.scheduler()
        await drive(s2, lambda: state(s2, "A/1") == "PASSED")
        self.assertFalse(s2.db.q("SELECT * FROM tasks WHERE kind='repair'"))

    async def test_14_auth_failure_does_not_create_repair(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["auth_error"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE kind='repair'"))
        self.assertEqual(s.quota.row("codex")["status"], "AUTH_ERROR")

    async def test_15_missing_dependency_is_not_invented(self):
        mini_plan(init_repo(self.tmp), [
            {"task_id": "A/1", "owner": "a", "scope": "mod_a/"},
            {"task_id": "Z/1", "owner": "z", "scope": "game/runtime/other/", "depends_on": ["A/1"]}])
        overlay = ('[tasks."A/1"]\nacceptance = [{ name = "imports", argv = ["/bin/sh", "-c", '
                   '"printf \\"ModuleNotFoundError: No module named \'%s\'\\\\n\\" game.runtime.other.mod; exit 1"] }]\n')
        env = FakeEnv(self.tmp, overlay=overlay)
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "BLOCKED")
        self.assertIn("DEPENDENCY_MISSING", s.db.task("A/1")["state_reason"])
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE kind='repair'"))
        self.assertTrue(s.db.one("SELECT 1 FROM approvals WHERE kind='dependency_missing' AND subject='Z/1'"))
        self.assertTrue(s.db.one("SELECT 1 FROM capability_gaps WHERE task_id='A/1' AND kind='cross_domain_request'"))
        self.assertEqual(len(calls_for(env, "A/1")), 1)


class RepairLifecycle(TmpTestCase):
    def _env(self, repair_behavior):
        one_task(init_repo(self.tmp))
        return FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"], R1: [repair_behavior]}}})

    async def test_17_pause_resume_with_repair(self):
        env = self._env("success")
        s = env.scheduler()
        await until_before_cycle(s, lambda: s.db.task(R1) is not None)
        control.pause(s.db, env.cfg)
        for _ in range(5):
            await s.cycle()
            await asyncio.sleep(0.05)
        self.assertEqual(state(s, R1), "READY")
        self.assertFalse(s.running)
        control.resume(s.db, env.cfg)
        await drive(s, lambda: state(s, "A/1") == "PASSED")

    async def test_18_restart_recovers_active_repair(self):
        env = self._env("success")
        s = env.scheduler()
        await until_before_cycle(s, lambda: s.db.task(R1) is not None)
        # a crashed daemon left the repair RUNNING with a dead worker
        aid = s.db.x("INSERT INTO task_attempts(task_id, kind, attempt_no, provider, model_key, model, status, started_at, "
                     "cwd, base_commit) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (R1, "execute", 1, "codex", "sol", "gpt-5.6-sol", "RUNNING", "2026-09-28T00:00:00+00:00",
                      s.db.task("A/1")["worktree"], None))
        s.db.x("INSERT INTO workers(attempt_id, task_id, provider, model, pid, pgid, process_started, started_at) "
               "VALUES(?,?,?,?,?,?,?,?)", (aid, R1, "codex", "gpt-5.6-sol", 999999, 999999, "never", "x"))
        s.db.set_task_state(R1, "RUNNING", "crashed")
        s2 = env.scheduler()
        await s2.reconcile()
        self.assertEqual(state(s2, R1), "PENDING")
        self.assertEqual(state(s2, "A/1"), "WAITING_REPAIR")
        self.assertEqual(s2.db.one("SELECT status FROM task_attempts WHERE id=?", (aid,))["status"], "ORPHANED")
        await drive(s2, lambda: state(s2, "A/1") == "PASSED")

    async def test_19_stop_preserves_parent_and_repair_state(self):
        env = self._env("slow_fix:30")
        s = env.scheduler()
        await drive(s, lambda: state(s, R1) == "RUNNING")
        end = time.monotonic() + 10
        while not calls_for(env, R1) and time.monotonic() < end:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)
        wt = Path(s.db.task("A/1")["worktree"])
        head_before = git(wt, "rev-parse", "HEAD").strip()
        s.stopping = "stop"
        await s.shutdown_workers("stop")
        self.assertEqual(state(s, R1), "PENDING")
        p = s.db.task("A/1")
        self.assertEqual((p["state"], p["active_repair_id"]), ("WAITING_REPAIR", R1))
        self.assertEqual(s.db.one("SELECT status FROM task_attempts WHERE task_id=?", (R1,))["status"], "INTERRUPTED")
        self.assertTrue(wt.is_dir())
        self.assertTrue(git(wt, "merge-base", "--is-ancestor", head_before, "HEAD") == "")
        # restart continues the same repair chain
        env.write_scenario({"codex": {"tasks": {R1: ["success"]}}})
        s2 = env.scheduler()
        await s2.reconcile()
        await drive(s2, lambda: state(s2, "A/1") == "PASSED")
        self.assertEqual(s2.db.task("A/1")["repairs_count"], 1)


class ResetButton(TmpTestCase):
    async def test_user_reported_reset_unblocks_waiting_tasks(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, overrides={"providers": {"claude": {"enabled": False}}})
        s = env.scheduler()
        s.quota.record_signal(QuotaSignal("codex", "*", "LIMIT_HIT", "weekly", utcnow() + dt.timedelta(days=3)))
        await s.cycle()
        self.assertEqual(state(s, "A/1"), "WAITING_QUOTA")
        msg = control.provider_reset_done(s.db, env.cfg, "codex", "test")
        self.assertIn("reset recorded", msg)
        self.assertEqual(s.quota.row("codex")["status"], "UNKNOWN")
        self.assertIsNone(s.quota.row("codex")["blocked_until"])
        self.assertEqual(s.quota.row("codex")["source"], "user reported reset (in app)")
        self.assertTrue(s.db.one("SELECT 1 FROM quota_events WHERE kind='USER_RESET'"))
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        # the daemon re-read the real Codex limits after the report (never a consume call)
        methods = {c["app_server_method"] for c in env.calls() if "app_server_method" in c}
        self.assertNotIn("account/rateLimitResetCredit/consume", methods)
        self.assertIn("account/rateLimits/read", methods)

    async def test_claude_family_reset(self):
        one_task(init_repo(self.tmp), model_profile="RESEARCH")
        env = FakeEnv(self.tmp, overrides={"providers": {"codex": {"enabled": False}}})
        s = env.scheduler()
        s.quota.record_signal(QuotaSignal("claude", "opus", "LIMIT_HIT", "weekly", None))
        s.quota.record_signal(QuotaSignal("claude", "sonnet", "LIMIT_HIT", "weekly", None))
        await s.cycle()
        self.assertEqual(state(s, "A/1"), "WAITING_QUOTA")
        control.provider_reset_done(s.db, env.cfg, "claude", "test")
        self.assertTrue(s.quota.availability("claude", "opus").usable)
        await drive(s, lambda: state(s, "A/1") == "PASSED")


class RepairDashboard(TmpTestCase):
    async def test_dashboard_shows_repair_chain_and_reset_buttons(self):
        from wwii_build.dashboard import Dashboard
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"], R1: ["noop"], "REPAIR/A/1/2": ["success"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        d = Dashboard(env.cfg)
        page = d.page_task("A/1", None)
        for needle in ("שרשרת תיקונים", "ביצוע מקורי #1", "תיקון #1", "תיקון #2", "תיקונים 2 מתוך 3",
                       "REPAIRABLE_CODE", "קבלה אחרי התיקון"):
            self.assertIn(needle, page)
        rpage = d.page_task(R1, None)
        self.assertIn("תיקון של", rpage)
        over = d.page_overview(None)
        self.assertIn("└─", over)
        self.assertIn("ביצעתי reset למכסת Codex באפליקציה", over)
        self.assertIn("ביצעתי reset למכסת Claude באפליקציה", over)
        msg = d.action({"action": "reset_done", "provider": "claude"})
        self.assertIn("reset recorded", msg)


class FreshQuota(TmpTestCase):
    async def test_claude_usage_is_recorded_during_the_run(self):
        one_task(init_repo(self.tmp), model_profile="DESIGN")
        env = FakeEnv(self.tmp, {"claude": {"tasks": {"A/1": ["events_then_wait:3"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "RUNNING")
        end = time.monotonic() + 10
        while s.quota.row("claude")["session_used_percent"] is None and time.monotonic() < end:
            await asyncio.sleep(0.1)
        r = s.quota.row("claude")
        self.assertEqual(state(s, "A/1"), "RUNNING")                  # still running: live, not end-of-run
        self.assertAlmostEqual(r["session_used_percent"], 37)
        self.assertAlmostEqual(r["weekly_used_percent"], 55)
        self.assertIsNotNone(r["session_reset_at"])
        self.assertIsNotNone(r["data_at"])
        self.assertEqual(r["status"], "AVAILABLE")
        await drive(s, lambda: state(s, "A/1") == "PASSED")

    async def test_codex_limits_polled_in_background(self):
        one_task(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"quota": {"used": 33, "reset_in_s": 5 * 86400, "window_mins": 10080}}},
                      overrides={"providers": {"codex": {"quota_poll_seconds": 0.3}}})
        s = env.scheduler()
        s.db.set_flag("paused", "1")                                  # polling does not depend on running tasks
        end = time.monotonic() + 5
        while time.monotonic() < end:
            await s.cycle()
            await asyncio.sleep(0.1)
        n = s.db.one("SELECT COUNT(*) n FROM quota_events WHERE provider='codex' AND kind='SNAPSHOT'")["n"]
        self.assertGreaterEqual(n, 3)
        r = s.quota.row("codex")
        self.assertEqual((r["weekly_used_percent"], r["session_used_percent"]), (33, None))
        self.assertFalse([c for c in env.calls() if c.get("task_id")])      # no inference while polling

    def test_allowed_event_is_a_snapshot_and_never_blocks(self):
        from wwii_build.providers.limits import claude_rate_limit_event
        from wwii_build.db import DB
        from wwii_build.quota import QuotaManager
        sig = claude_rate_limit_event({"status": "allowed", "resetsAt": 1791047417, "rateLimitType": "seven_day",
                                       "utilization": 0.93})
        self.assertEqual((sig.kind, sig.window, round(sig.used_percent)), ("SNAPSHOT", "weekly", 93))
        q = QuotaManager(DB(":memory:"), {"near_limit_percent": 90})
        q.record_signal(sig)
        r = q.row("claude")
        self.assertEqual((r["status"], r["weekly_used_percent"]), ("NEAR_LIMIT", 93))
        self.assertTrue(q.availability("claude").usable)
