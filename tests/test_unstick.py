"""The "why is it stuck? continue" button: deterministic diagnosis and bounded resume actions."""
from __future__ import annotations

import json
from unittest import mock

from helpers import FakeEnv, TmpTestCase, init_repo, mini_plan
from wwii_build import unstick as us
from wwii_build.db import DB
from wwii_build.models import iso, utcnow


class UnstickTests(TmpTestCase):
    async def test_resume_approvals_backoff_and_failed_root_retry_bounded(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "a/"},
                         {"task_id": "B/1", "owner": "b", "scope": "b/", "depends_on": ["A/1"]},
                         {"task_id": "C/1", "owner": "c", "scope": "c/"}])
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        db = s.db
        db.set_flag("paused", "1")
        db.x("UPDATE tasks SET state='FAILED', state_reason='repair_limit rejected by user', last_model_key='sol' "
             "WHERE task_id='A/1'")
        db.x("UPDATE tasks SET state='WAITING_DEPENDENCY' WHERE task_id='B/1'")
        db.x("UPDATE tasks SET state='PENDING', not_before=? WHERE task_id='C/1'", ("2999-01-01T00:00:00+00:00",))
        db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
             ("C/1", "model", "opus", "pending", "premium", iso(utcnow())))
        with mock.patch.object(us, "_start_daemon") as start:
            rep = us.unstick(env.cfg, db, "test")
        start.assert_called_once()                                   # no daemon running in the test
        self.assertFalse(db.get_flag("paused"))
        self.assertEqual(db.one("SELECT status FROM approvals WHERE task_id='C/1'")["status"], "approved")
        self.assertIsNone(db.task("C/1")["not_before"])
        self.assertEqual(db.task("A/1")["state"], "PENDING")         # the root blocker is retried ...
        self.assertEqual(db.task("A/1")["preferred_model_key"], "sonnet")   # ... on another best-fit model
        self.assertTrue(any("A/1" in f and "מעכב 1" in f for f in rep["findings"]))
        self.assertEqual(json.loads(db.get_flag("unstick_last_report"))["source"], "test")
        # bounded: after MAX_UNSTICK_RETRIES the task is handed to the user instead of looping
        for _ in range(us.MAX_UNSTICK_RETRIES):
            db.x("UPDATE tasks SET state='FAILED' WHERE task_id='A/1'")
            with mock.patch.object(us, "_start_daemon"):
                rep = us.unstick(env.cfg, db, "test")
        self.assertEqual(db.task("A/1")["state"], "FAILED")
        self.assertTrue(any(x.startswith("A/1") for x in rep["needs_you"]))
