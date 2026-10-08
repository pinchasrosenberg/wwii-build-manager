"""Scheduler integration tests against fake Codex/Claude executables (no quota spent)."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

from helpers import FakeEnv, TmpTestCase, drive, git, init_repo, mini_plan, settle, state

from wwii_build import control
from wwii_build.activation import activation_id, record_activation
from wwii_build.models import ProviderStatus, TaskState
from wwii_build.scheduler import Decision, Scheduler
from wwii_build.supervisor import pid_alive


def two_chain(repo):
    mini_plan(repo, [{"task_id": "A/root", "owner": "a", "scope": "mod_a/"},
                     {"task_id": "B/child", "owner": "b", "scope": "mod_b/", "depends_on": ["A/root"]}])


class ActivationRestart(TmpTestCase):
    def _scheduler(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "synthetic/done", "owner": "synthetic", "scope": "synthetic/"}])
        scheduler = FakeEnv(self.tmp).scheduler()
        self.addCleanup(scheduler.db.close)
        scheduler.db.x("UPDATE tasks SET state='PASSED' WHERE task_id='synthetic/done'")
        return scheduler

    async def test_idle_scheduler_requests_restart_when_activation_marker_changes(self):
        scheduler = self._scheduler()
        record_activation(scheduler.db)
        self.assertEqual((await scheduler.cycle())["stopping"], "restart")

    async def test_scheduler_waits_for_running_workers_before_restart(self):
        scheduler = self._scheduler()
        scheduler.running[1] = mock.Mock(task_id="synthetic/running")
        record_activation(scheduler.db)
        summary = await scheduler.cycle()
        self.assertIsNone(scheduler.stopping)
        self.assertEqual(summary["running"], ["synthetic/running"])
        scheduler.running.clear()
        self.assertEqual((await scheduler.cycle())["stopping"], "restart")

    async def test_successful_system_activation_records_marker(self):
        scheduler = self._scheduler()
        candidate = self.tmp / "synthetic-candidate"
        candidate.mkdir()
        scheduler.db.x("UPDATE tasks SET state='CODE_READY',worktree=? WHERE task_id='synthetic/done'",
                       (str(candidate),))
        scheduler.wt.head = mock.Mock(return_value="synthetic-candidate-commit")
        scheduler.wt.merge_to_integration = mock.Mock(return_value=(True, "", "synthetic-integration-commit"))
        staged = mock.Mock(path=self.tmp / "synthetic-stage",
                           changed_files=["tools/build_manager/wwii_build/synthetic.py"])
        with mock.patch("wwii_build.scheduler.stage_release", return_value=staged), \
                mock.patch("wwii_build.scheduler.activate_release"):
            await scheduler._activate_system_repair(
                "synthetic/done", scheduler.db.task("synthetic/done"),
                {"system_base_commit": "synthetic-base", "system_source_manifest": {}})
        self.assertEqual(activation_id(scheduler.db), 1)
        self.assertEqual(scheduler.db.task("synthetic/done")["state_reason"],
                         "system repair activated; graceful restart requested")


class Dependencies(TmpTestCase):
    async def test_dependency_scheduling_and_unlock(self):
        two_chain(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        await s.cycle()
        self.assertEqual(state(s, "B/child"), "WAITING_DEPENDENCY")
        self.assertIn(state(s, "A/root"), ("RUNNING",))
        await drive(s, lambda: state(s, "B/child") == "PASSED")
        self.assertEqual(state(s, "A/root"), "PASSED")
        # dependent was forked from integration after A merged: it sees A's file
        wt = Path(s.db.task("B/child")["worktree"])
        self.assertTrue((wt / "mod_a/fake_codex.txt").exists())
        # dependency handoff was supplied as context, producer implementation was not
        cp = s.db.one("SELECT manifest FROM context_packs WHERE task_id='B/child' ORDER BY id DESC")
        paths = [i["path"] for i in json.loads(cp["manifest"])["items"]]
        self.assertIn("handoff:A/root", paths)
        self.assertFalse(any(p.startswith("mod_a/") for p in paths))
        ev = [r["event"] for r in s.db.q("SELECT event FROM event_log")]
        for e in ("TASK_READY", "TASK_STARTED", "TASK_COMPLETED", "TESTS_PASSED", "TASK_PASSED"):
            self.assertIn(e, ev)
        # usage accounting: tokens recorded when reported
        a = s.db.one("SELECT * FROM task_attempts WHERE task_id='A/root'")
        self.assertEqual((a["input_tokens"], a["output_tokens"]), (1200, 300))
        self.assertIsNone(a["reported_cost_usd"])      # codex reports no cost: stays null
        self.assertIsNotNone(a["quota_before"])

    async def test_parked_parents_of_one_owner_do_not_deadlock_their_repairs(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"},
                         {"task_id": "A/2", "owner": "a", "scope": "y/"}])
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        for tid in ("A/1", "A/2"):           # both parents wait for a repair (parked: no worker)
            s.db.x("UPDATE tasks SET state='WAITING_REPAIR' WHERE task_id=?", (tid,))
        rep = lambda tid: Decision(tid, TaskState.READY, "", wave=0)
        s.db.x("INSERT INTO tasks(task_id, packet, owner, mode, model_profile, lego_ids, write_scope, acceptance, "
               "extra, definition_hash, wave, state, created_at, updated_at, kind, parent_task_id) "
               "SELECT 'REPAIR/A/1/1', packet, owner, mode, 'REPAIR_CODE', lego_ids, write_scope, acceptance, extra, "
               "'r', wave, 'READY', created_at, updated_at, 'repair', 'A/1' FROM tasks WHERE task_id='A/1'")
        picked = [d.task_id for d, _ in s.pick_dispatch([rep("REPAIR/A/1/1")], running=[])]
        self.assertEqual(picked, ["REPAIR/A/1/1"])      # A/2 (same owner, parked) no longer blocks it

    async def test_one_writer_rule(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "shared/"},
                         {"task_id": "B/1", "owner": "b", "scope": "shared/sub/"},
                         {"task_id": "C/1", "owner": "a", "scope": "other/"},
                         {"task_id": "D/1", "owner": "d", "scope": "free/"}])
        env = FakeEnv(self.tmp, {"codex": {"default": "long_running:30"}})
        s = env.scheduler()
        await s.cycle()
        running = {r.task_id for r in s.running.values()}
        self.assertEqual(running, {"A/1", "D/1"})   # B overlaps A's scope; C has A's owner
        self.assertEqual(state(s, "B/1"), "READY")
        await s.shutdown_workers("stop")


class QuotaFallback(TmpTestCase):
    async def test_codex_limit_falls_back_to_claude_and_blocks_codex(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["rate_limit:3600"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        att = s.db.q("SELECT provider, status FROM task_attempts WHERE task_id='A/1' ORDER BY id")
        self.assertEqual([(a["provider"], a["status"]) for a in att],
                         [("codex", "QUOTA_LIMITED"), ("claude", "SUCCEEDED")])
        self.assertEqual(s.db.task("A/1")["failed_attempts"], 0)     # quota is not a failure
        q = s.quota.row("codex")
        self.assertEqual(q["status"], "BLOCKED_UNKNOWN")               # "Try again at <time>" -> blocked
        self.assertIsNotNone(q["blocked_until"])
        ev = [r["event"] for r in s.db.q("SELECT event FROM event_log")]
        self.assertIn("PROVIDER_LIMIT", ev)
        self.assertIn("FALLBACK_SELECTED", ev)
        claude_run = s.db.one("SELECT * FROM task_attempts WHERE provider='claude'")
        self.assertAlmostEqual(claude_run["reported_cost_usd"], 0.0123)   # reported by CLI, not invented

    async def test_waiting_quota_then_reset_wakeup(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["rate_limit_iso:3", "success"]}}},
                      overrides={"providers": {"claude": {"enabled": False}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "WAITING_QUOTA")
        nw = s.db.get_flag("next_wakeup_at")
        self.assertIsNotNone(nw)                      # wakeup scheduled at reset, not busy polling
        self.assertEqual(s.db.get_flag("next_wakeup_reason"), "quota reset")
        await drive(s, lambda: state(s, "A/1") == "PASSED", timeout=90)

    async def test_model_unavailable_blocks_only_that_model(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/", "model_profile": "DESIGN"}])
        env = FakeEnv(self.tmp, {"claude": {"tasks": {"A/1": ["model_unavailable"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(s.quota.row("claude", "model:claude-sonnet-5-5")["status"], "MODEL_UNAVAILABLE")
        self.assertEqual(s.quota.row("claude")["status"], "UNKNOWN")       # provider itself not blocked
        self.assertEqual(s.db.one("SELECT provider FROM task_attempts WHERE status='SUCCEEDED'")["provider"], "codex")


class Approvals(TmpTestCase):
    async def test_deep_task_waits_for_approval_then_runs_astra(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/deep", "owner": "a", "scope": "x/", "model_profile": "DEEP"}])
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        await s.cycle()
        self.assertEqual(state(s, "A/deep"), "WAITING_APPROVAL")
        await s.cycle()
        self.assertEqual(len(env.calls()), 0 if not env.calls() else len([c for c in env.calls() if c.get("task_id")]))
        ap = s.db.one("SELECT * FROM approvals WHERE task_id='A/deep' AND status='pending'")
        self.assertEqual(ap["subject"], "astra")
        self.assertEqual(s.db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"], 1)  # no dupes
        control.decide(s.db, env.cfg, ap["id"], approve=False)
        await s.cycle()
        ap2 = s.db.one("SELECT * FROM approvals WHERE task_id='A/deep' AND status='pending'")
        self.assertEqual(ap2["subject"], "opus")           # rejection moves along the chain, still asks
        control.decide(s.db, env.cfg, ap2["id"], approve=True)
        await drive(s, lambda: state(s, "A/deep") == "PASSED")
        self.assertEqual(s.db.one("SELECT model FROM task_attempts")["model"], "claude-opus-5-5")

    async def test_review_required_without_task_tests(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, overrides={"review": {"auto_pass_requires_task_commands": True}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "REVIEW_REQUIRED")
        control.decide(s.db, env.cfg, control.pending_approval_for_task(s.db, "A/1"), True)
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(len([c for c in env.calls() if c.get("task_id") == "A/1"]), 1)   # worker not re-run


class Failures(TmpTestCase):
    async def test_failed_tests_retry_with_context_then_escalate(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["test_fail"]}}},
                      overrides={"repair": {"enabled": False}})   # legacy full-retry path
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "BLOCKED")
        t = s.db.task("A/1")
        self.assertIn("ESCALATION_REQUIRED", t["state_reason"])
        self.assertEqual(t["failed_attempts"], 3)
        att = s.db.q("SELECT provider, status, failure_class FROM task_attempts WHERE task_id='A/1' ORDER BY id")
        self.assertTrue(all(a["provider"] == "codex" for a in att))     # retry same model, no premium burn
        self.assertTrue(all(a["failure_class"] == "test_failure" for a in att))
        retry_prompt = Path(s.db.q("SELECT prompt_path FROM context_packs ORDER BY id")[1]["prompt_path"]).read_text()
        self.assertIn("retry:attempt-2", retry_prompt)
        self.assertIn("no-broken", retry_prompt)                          # failing test named in retry context
        self.assertIn("Previous diff", retry_prompt)
        esc = s.db.one("SELECT * FROM approvals WHERE kind='escalation' AND status='pending'")
        self.assertIsNotNone(esc)
        # approving the escalation with another model re-queues it on that model
        control.decide(s.db, env.cfg, esc["id"], True, model_key="sonnet")
        self.assertEqual(s.db.task("A/1")["preferred_model_key"], "sonnet")

    async def test_provider_crash_is_retried(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["crash", "success"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        att = s.db.q("SELECT provider, status FROM task_attempts ORDER BY id")
        self.assertEqual([(a["provider"], a["status"]) for a in att], [("codex", "CRASHED"), ("codex", "SUCCEEDED")])

    async def test_malformed_output_keeps_raw_and_requires_review(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["malformed"]}}},
                      overrides={"repair": {"repair_malformed_handoff": False}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "REVIEW_REQUIRED")
        a = s.db.one("SELECT * FROM task_attempts")
        self.assertEqual(a["handoff_status"], "MALFORMED")
        self.assertIn("prose instead of JSON", Path(a["stdout_path"]).read_text())
        self.assertIn("handoff MALFORMED", s.db.task("A/1")["state_reason"])

    async def test_provider_missing_falls_back(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, overrides={"providers": {"codex": {"command": ["/nonexistent/codex"]}}})
        s = env.scheduler()
        await s.refresh_all()
        self.assertEqual(s.quota.row("codex")["status"], "MISSING")
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(s.db.one("SELECT provider FROM task_attempts")["provider"], "claude")

    async def test_auth_error_blocks_provider(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/", "model_profile": "DESIGN"}])
        env = FakeEnv(self.tmp, {"claude": {"auth": "none"}})
        s = env.scheduler()
        await s.refresh_all()
        self.assertEqual(s.quota.row("claude")["status"], "AUTH_ERROR")
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(s.db.one("SELECT provider FROM task_attempts")["provider"], "codex")
        self.assertFalse(any(c.get("flavor") == "claude" and c.get("task_id") for c in env.calls()))

    async def test_auth_error_during_run(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["auth_error"]}}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "PASSED")
        self.assertEqual(s.quota.row("codex")["status"], "AUTH_ERROR")
        self.assertEqual(s.db.task("A/1")["failed_attempts"], 0)

    async def test_scope_violation_fails_acceptance(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["out_of_scope"]}}},
                      overrides={"repair": {"enabled": False}})   # legacy path; repair path in test_repair.py
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "BLOCKED")
        own = s.db.q("SELECT passed FROM test_results WHERE name='ownership' ORDER BY id")
        self.assertEqual({r["passed"] for r in own}, {0})
        first = s.db.one("SELECT failure_class FROM task_attempts ORDER BY id")
        self.assertEqual(first["failure_class"], "scope_violation")
        retry_prompt = Path(s.db.q("SELECT prompt_path FROM context_packs ORDER BY id")[1]["prompt_path"]).read_text()
        self.assertIn("outside_scope/fake.txt", retry_prompt)        # the worker is told exactly what to revert
        self.assertEqual(state(s, "A/1"), "BLOCKED")                  # never integrated


class BillingGuard(TmpTestCase):
    async def test_api_key_mode_is_blocked(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp, {"codex": {"auth": "api"}, "claude": {"auth": "api_key"}})
        s = env.scheduler()
        await s.refresh_all()
        await s.cycle()
        self.assertEqual(s.quota.row("codex")["status"], "BILLING_BLOCKED")
        self.assertEqual(s.quota.row("claude")["status"], "BILLING_BLOCKED")
        self.assertEqual(state(s, "A/1"), "WAITING_PROVIDER")
        self.assertFalse([c for c in env.calls() if c.get("task_id")])

    async def test_claude_overage_is_aborted(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/", "model_profile": "DESIGN"}])
        env = FakeEnv(self.tmp, {"claude": {"tasks": {"A/1": ["overage"]}}})
        s = env.scheduler()
        t0 = time.monotonic()
        await drive(s, lambda: s.db.one("SELECT 1 FROM task_attempts WHERE status='BILLING_BLOCKED'") is not None)
        self.assertLess(time.monotonic() - t0, 20)          # not the fake's 60s: interrupted immediately
        self.assertEqual(s.quota.row("claude")["status"], "BLOCKED_SESSION")
        self.assertIn("overage", s.quota.row("claude")["source"])

    async def test_workers_never_receive_api_keys(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-leak-123456789012345678901",  # gitleaks:allow (fake key: proves env scrubbing)
                                          "ANTHROPIC_API_KEY": "sk-ant-leak-12345678901234",
                                          "CLAUDE_CODE_MESSAGING_TOKEN": "x"}):
            s = env.scheduler()
            await drive(s, lambda: state(s, "A/1") == "PASSED")
        keys = next(c for c in env.calls() if c.get("task_id") == "A/1")["env_keys"]
        self.assertFalse([k for k in keys if k.startswith(("OPENAI", "ANTHROPIC", "CLAUDE_CODE"))])

    async def test_app_server_method_allowlist(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/"}])
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        await s.refresh_provider("codex")
        methods = {c["app_server_method"] for c in env.calls() if "app_server_method" in c}
        self.assertEqual(methods, {"initialize", "initialized", "account/rateLimits/read"})
        self.assertEqual(s.quota.row("codex")["used_percent"], 10)
        from wwii_build.providers.codex import APP_SERVER_ALLOWED_METHODS
        self.assertNotIn("account/rateLimitResetCredit/consume", APP_SERVER_ALLOWED_METHODS)
        self.assertNotIn("account/sendAddCreditsNudgeEmail", APP_SERVER_ALLOWED_METHODS)


class ProcessControl(TmpTestCase):
    def _env(self, behavior="long_running:60", n=2):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": f"T{i}/w", "owner": f"o{i}", "scope": f"m{i}/"} for i in range(n)])
        return FakeEnv(self.tmp, {"codex": {"default": behavior}})

    def _pids(self, s):
        return [h.pid for h in s.svc.sup.handles.values()]

    async def _spawned(self, s, n=2, timeout=10):
        end = time.monotonic() + timeout
        while len(s.svc.sup.handles) < n and time.monotonic() < end:
            await asyncio.sleep(0.02)
        self.assertEqual(len(s.svc.sup.handles), n)

    async def test_pause_stops_new_tasks(self):
        env = self._env("success", 2)
        s = env.scheduler()
        control.pause(s.db, env.cfg)
        await s.cycle()
        self.assertFalse(s.running)
        self.assertEqual(state(s, "T0/w"), "READY")
        control.resume(s.db, env.cfg)
        await drive(s, lambda: state(s, "T0/w") == "PASSED" and state(s, "T1/w") == "PASSED")

    async def test_pause_interrupt_running(self):
        env = self._env()
        s = env.scheduler()
        await s.cycle()
        self.assertEqual(len(s.running), 2)
        await self._spawned(s)
        control.pause(s.db, env.cfg, interrupt_running=True)
        await drive(s, lambda: state(s, "T0/w") == "PAUSED" and state(s, "T1/w") == "PAUSED")
        self.assertFalse(s.running)
        # partial work was committed on the task branch, not lost
        log = git(env.repo, "log", "--oneline", "wwii-build/task/T0__w")
        self.assertIn("INTERRUPTED", log)
        control.resume(s.db, env.cfg)
        await s.cycle()
        self.assertEqual(len(s.running), 2)
        await s.shutdown_workers("stop")

    async def test_stop_graceful_no_orphans(self):
        env = self._env()
        s = env.scheduler()
        await s.cycle()
        await self._spawned(s)
        end = time.monotonic() + 10
        while len([c for c in env.calls() if c.get("behavior", "").startswith("long_running")]) < 2 \
                and time.monotonic() < end:
            await asyncio.sleep(0.05)
        pids = self._pids(s)
        control.enqueue(s.db, env.cfg, "stop")
        await s.cycle()
        self.assertEqual(s.stopping, "stop")
        await s.shutdown_workers("stop")
        for p in pids:
            self.assertFalse(pid_alive(p))
        sigints = [c for c in env.calls() if c.get("event") == "SIGINT"]
        self.assertEqual(len(sigints), 2)                        # graceful: CLI saw exactly one SIGINT
        for tid in ("T0/w", "T1/w"):
            self.assertEqual(state(s, tid), "PENDING")
        self.assertFalse(s.db.q("SELECT * FROM workers"))
        self.assertTrue(all(a["status"] == "INTERRUPTED" for a in s.db.q("SELECT status FROM task_attempts")))

    async def test_kill_immediately(self):
        env = self._env()
        s = env.scheduler()
        await s.cycle()
        await self._spawned(s)
        pids = self._pids(s)
        t0 = time.monotonic()
        control.enqueue(s.db, env.cfg, "kill")
        await s.cycle()
        s.db.set_flag("emergency_stop", "now")
        await s.shutdown_workers("kill")
        self.assertLess(time.monotonic() - t0, 5)
        for p in pids:
            self.assertFalse(pid_alive(p))
        await s.cycle()
        self.assertFalse(s.running)                              # scheduler disabled
        with self.assertRaises(control.ControlError):
            control.resume(s.db, env.cfg)                        # needs --clear-emergency
        control.resume(s.db, env.cfg, clear_emergency=True)

    async def test_daemon_crash_leaves_no_orphan(self):
        """SIGKILL the daemon process: the child guard must stop the CLI on its own."""
        env = self._env()
        repo = env.repo
        script = f"""
import asyncio, sys
sys.path.insert(0, {str(Path(__file__).parents[1])!r}); sys.path.insert(0, {str(Path(__file__).parent)!r})
from helpers import FakeEnv
from pathlib import Path
env = FakeEnv(Path({str(self.tmp)!r}), {{"codex": {{"default": "long_running:120"}}}})
async def main():
    s = env.scheduler()
    await s.cycle()
    while len(s.svc.sup.handles) < 2:
        await asyncio.sleep(0.02)
    print("PIDS", *[h.pid for h in s.svc.sup.handles.values()], flush=True)
    await asyncio.sleep(120)
asyncio.run(main())
"""
        p = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        line = ""
        for _ in range(200):
            line = p.stdout.readline()
            if line.startswith("PIDS"):
                break
        guard_pids = [int(x) for x in line.split()[1:]]
        self.assertEqual(len(guard_pids), 2)
        time.sleep(0.5)
        p.kill()                                                  # daemon dies hard
        p.wait()
        deadline = time.time() + 20
        while time.time() < deadline and any(pid_alive(x) for x in guard_pids):
            time.sleep(0.2)
        self.assertFalse(any(pid_alive(x) for x in guard_pids))
        time.sleep(0.5)
        fake_alive = subprocess.run(["pgrep", "-f", str(env.scn_path)], capture_output=True, text=True).stdout.split()
        self.assertEqual(fake_alive, [])
        # restart: reconcile the RUNNING rows the dead daemon left behind
        s2 = env.scheduler()
        notes = await s2.reconcile()
        self.assertTrue(any("orphaned" in n for n in notes))
        for tid in ("T0/w", "T1/w"):
            self.assertEqual(state(s2, tid), "PENDING")
        self.assertFalse(s2.db.q("SELECT * FROM workers"))

    async def test_restart_never_reruns_passed_and_rechecks_code_ready(self):
        env = self._env("success", 2)
        s = env.scheduler()
        await drive(s, lambda: state(s, "T0/w") == "PASSED" and state(s, "T1/w") == "PASSED")
        n_calls = len([c for c in env.calls() if c.get("task_id")])
        # simulate a crash between worker exit and acceptance for T1
        s.db.set_task_state("T1/w", "CODE_READY", "simulated crash before acceptance")
        s2 = env.scheduler()
        await s2.reconcile()
        await drive(s2, lambda: state(s2, "T1/w") == "PASSED")
        self.assertEqual(len([c for c in env.calls() if c.get("task_id")]), n_calls)   # no LLM re-run
        self.assertEqual(state(s2, "T0/w"), "PASSED")
