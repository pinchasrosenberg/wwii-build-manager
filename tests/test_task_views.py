"""Focused synthetic fixtures for the bounded dashboard task views."""
from __future__ import annotations

import datetime as dt
import json

from helpers import TmpTestCase

from wwii_build.db import DB
from wwii_build.task_views import (active_tasks, history_search, problem_reason, problem_tasks,
                                   task_dependency_detail)
from wwii_build.live import LiveState, _Sweep

NOW = dt.datetime(2026, 1, 8, tzinfo=dt.timezone.utc)
NOW_S = NOW.isoformat()


class TaskViews(TmpTestCase):
    def setUp(self):
        super().setUp()
        self.db = DB(self.tmp / "synthetic.sqlite")

    def tearDown(self):
        self.db.conn.close()
        super().tearDown()

    def task(self, task_id, state="PENDING", **values):
        base = {"task_id": task_id, "packet": "synthetic", "owner": "owner", "mode": "build",
                "model_profile": "IMPLEMENT", "definition_hash": "synthetic", "state": state,
                "created_at": NOW_S, "updated_at": NOW_S}
        base.update(values)
        keys = list(base)
        self.db.x(f"INSERT INTO tasks({','.join(keys)}) VALUES({','.join('?' for _ in keys)})", tuple(base.values()))

    def dep(self, task_id, depends_on):
        self.db.x("INSERT INTO task_dependencies(task_id,depends_on) VALUES(?,?)", (task_id, depends_on))

    def test_state_partition_and_repair_nesting(self):
        self.task("run", "RUNNING")
        self.task("ready", "READY")
        self.task("wait", "WAITING_REPAIR", active_repair_id="wait/r1", repairs_count=1)
        self.task("wait/r1", "RUNNING", kind="repair", parent_task_id="wait", repair_no=1,
                  last_model_key="sol")
        self.task("failed", "FAILED", updated_at=dt.datetime.now(dt.timezone.utc).isoformat())
        self.task("passed", "PASSED")
        active = active_tasks(self.db)
        self.assertEqual([t["task_id"] for t in active], ["run", "ready", "wait"])
        nested = next(t for t in active if t["task_id"] == "wait")["repairs"]
        self.assertEqual([(r["repair_no"], r["model"]) for r in nested], [(1, "sol")])
        self.assertNotIn("wait/r1", [t["task_id"] for t in active])
        self.assertEqual([t["task_id"] for t in problem_tasks(self.db, now=NOW)], ["failed"])

    def test_default_problems_hide_old_and_superseded_failed_repairs(self):
        old = (NOW - dt.timedelta(days=8)).isoformat()
        self.task("parent", "PASSED")
        self.task("parent/r1", "FAILED", kind="repair", parent_task_id="parent", repair_no=1)
        self.task("old", "BLOCKED", updated_at=old)
        self.task("current", "REVIEW_REQUIRED")
        self.assertEqual([t["task_id"] for t in problem_tasks(self.db, now=NOW)], ["current"])
        self.assertEqual({t["task_id"] for t in problem_tasks(self.db, include_all=True, now=NOW)},
                         {"parent/r1", "old", "current"})

    def test_reason_assembly_uses_checks_attempt_repair_approval_and_unstick_events(self):
        self.task("bad", "BLOCKED", state_reason="merge conflict", failure_class="REPAIRABLE_CODE")
        stderr = self.tmp / "synthetic-stderr.log"
        stderr.write_text("synthetic stderr tail")
        attempt = self.db.x("INSERT INTO task_attempts(task_id,attempt_no,provider,model_key,model,status,"
                            "failure_class,diagnosis,started_at,ended_at,exit_code,stderr_path) "
                            "VALUES('bad',1,'codex','sol','gpt','FAILED_ATTEMPT','TEST','synthetic diagnosis',?,?,?,?)",
                            (NOW_S, NOW_S, 2, str(stderr)))
        self.db.x("INSERT INTO test_results(task_id,attempt_id,name,kind,passed,exit_code,output_tail,created_at) "
                  "VALUES('bad',?,'check-1','command',0,2,'synthetic output',?)", (attempt, NOW_S))
        self.task("bad/r1", "FAILED", kind="repair", parent_task_id="bad", repair_no=1,
                  last_model_key="sonnet", failure_summary="synthetic repair failure")
        self.db.x("INSERT INTO approvals(task_id,kind,status,reason,note,created_at,decided_at) "
                  "VALUES('bad','repair_limit','rejected','synthetic reason','synthetic rejection',?,?)", (NOW_S, NOW_S))
        self.db.x("INSERT INTO event_log(at,event,task_id,detail) VALUES(?,'UNSTICK_RETRY','bad',?)",
                  (NOW_S, json.dumps({"result": "synthetic tried retry"})))
        reason = problem_reason(self.db, "bad")
        self.assertEqual(reason["failed_checks"][0]["name"], "check-1")
        self.assertIn("synthetic stderr", reason["last_attempt"]["stderr_tail"])
        self.assertEqual(reason["repairs"][0]["model"], "sonnet")
        self.assertEqual(reason["approvals"][0]["note"], "synthetic rejection")
        self.assertEqual(reason["events"][0]["event"], "UNSTICK_RETRY")

    def test_history_search_is_paged_and_filters_all_states(self):
        for i in range(55):
            self.task(f"history/{i:02}", "PASSED" if i % 2 else "CANCELLED",
                      owner="alice" if i < 52 else "bob", last_model_key="sol" if i % 3 else "sonnet",
                      title=f"synthetic needle {i}")
        attempt = self.db.x("INSERT INTO task_attempts(task_id,attempt_no,provider,model_key,model,status,started_at) "
                            "VALUES('history/01',1,'codex','sol','gpt','SUCCEEDED',?)", (NOW_S,))
        failed_attempt = self.db.x("INSERT INTO task_attempts(task_id,attempt_no,provider,model_key,model,status,started_at) "
                                   "VALUES('history/03',1,'claude','sonnet','claude','FAILED_ATTEMPT',?)", (NOW_S,))
        self.db.x("INSERT INTO test_results(task_id,attempt_id,name,kind,passed,created_at) "
                  "VALUES('history/03',?,'synthetic-failed','command',0,?)", (failed_attempt, NOW_S))
        first = history_search(self.db, "synthetic needle", {}, 1)
        second = history_search(self.db, "synthetic needle", {}, 2)
        self.assertEqual((len(first["items"]), len(second["items"]), first["total"]), (50, 5, 55))
        filtered = history_search(self.db, "", {"state": "PASSED", "owner": "alice", "model": "sol"}, 1)
        self.assertTrue(filtered["items"])
        self.assertTrue(all(t["state"] == "PASSED" and t["owner"] == "alice" and t["model"] == "sol"
                            for t in filtered["items"]))
        self.assertEqual([t["task_id"] for t in history_search(self.db, "", {"provider": "codex"}, 1)["items"]],
                         ["history/01"])
        self.assertIn("history/03", {t["task_id"] for t in history_search(self.db, "", {"has_failed": True}, 1)["items"]})

    def test_dependency_detail_transitive_cycle_missing_blocker_and_dependents(self):
        self.task("root", "WAITING_DEPENDENCY")
        self.task("middle", "WAITING_DEPENDENCY")
        self.task("failed-leaf", "FAILED", state_reason="synthetic failed prerequisite")
        self.task("consumer", "PENDING")
        self.task("downstream", "PENDING")
        self.dep("root", "middle")
        self.dep("middle", "failed-leaf")
        self.dep("failed-leaf", "root")  # cycle-safe traversal
        self.dep("consumer", "root")
        self.dep("downstream", "consumer")
        detail = task_dependency_detail(self.db, "root")
        self.assertEqual(detail["prerequisites"][0]["task_id"], "middle")
        self.assertEqual(detail["prerequisites"][0]["children"][0]["task_id"], "failed-leaf")
        self.assertTrue(detail["prerequisites"][0]["children"][0]["children"][0]["cycle"])
        self.assertIn("failed-leaf", detail["blocking_roots"])
        self.assertEqual([d["task_id"] for d in detail["dependents"]], ["consumer", "failed-leaf"])
        self.assertEqual(detail["downstream_more"], 2)

        self.db.conn.execute("PRAGMA foreign_keys=OFF")
        self.db.x("INSERT INTO task_dependencies(task_id,depends_on) VALUES('root','missing-synthetic')")
        missing = task_dependency_detail(self.db, "root")
        self.assertTrue(next(n for n in missing["prerequisites"] if n["task_id"] == "missing-synthetic")["missing"])
        self.assertIn("missing-synthetic", missing["blocking_roots"])

    def test_live_topics_never_include_passed_and_requests_are_correlated(self):
        self.task("active", "READY")
        self.task("passed", "PASSED")
        self.task("failed", "FAILED", updated_at=dt.datetime.now(dt.timezone.utc).isoformat())

        class Hub:
            def __init__(self): self.handlers = {}
            def on(self, name, fn): self.handlers[name] = fn

        class Dash:
            db = self.db
            hub = Hub()
            cfg = object()
            def models_info(self): return {}
            def task_rows(self): return [dict(r) for r in self.db.q("SELECT * FROM tasks")]

        dash = Dash()
        live = LiveState(dash)
        active, _ = live._build("tasks.active", "", _Sweep(dash))
        problems, _ = live._build("tasks.problems", "", _Sweep(dash))
        self.assertEqual([t["task_id"] for t in active], ["active"])
        self.assertEqual([t["task_id"] for t in problems], ["failed"])
        self.assertNotIn("passed", {t["task_id"] for t in active + problems})

        class Conn:
            def __init__(self): self.sent = []
            def send_json(self, obj): self.sent.append(obj)

        conn = Conn()
        live.handle_search(conn, {"type": "search", "id": "synthetic-q", "topic": "tasks.history", "page": 1})
        self.assertEqual((conn.sent[-1]["type"], conn.sent[-1]["id"], conn.sent[-1]["ok"]),
                         ("search.result", "synthetic-q", True))
        self.assertIn("passed", {t["task_id"] for t in conn.sent[-1]["items"]})
        live.handle_task_detail(conn, {"type": "task.detail", "id": "synthetic-d", "task_id": "active"})
        self.assertEqual((conn.sent[-1]["type"], conn.sent[-1]["id"], conn.sent[-1]["detail"]["exists"]),
                         ("task.detail.result", "synthetic-d", True))
