from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import FakeEnv
from wwii_build.dashboard import Dashboard
from wwii_build.db import DB
from wwii_build.mcp_server import Server, TOOLS


class EventJournalTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="wwii-event-journal-")
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_event_survives_database_reopen_and_filters_from_one_reader(self):
        path = self.tmp / "events.sqlite3"
        db = DB(path)
        event_id = db.event("TASK_SAMPLE", task_id="A/1", provider="codex", source="test", value=7)
        db.close()

        reopened = DB(path)
        try:
            rows = reopened.events(task_id="A/1", provider="codex", search="value", limit=10)
            self.assertEqual([row["id"] for row in rows], [event_id])
            self.assertEqual(reopened.event_count(event="TASK_SAMPLE"), 1)
        finally:
            reopened.close()

    def test_dashboard_and_json_api_read_the_persisted_journal(self):
        env = FakeEnv(self.tmp)
        dashboard = Dashboard(env.cfg)
        try:
            event_id = dashboard.db.event("DASHBOARD_SAMPLE", task_id="A/1", source="test")
            payload = dashboard.events_json({"event": "DASHBOARD_SAMPLE", "limit": "20"})
            self.assertEqual(payload["source"], "sqlite:event_log")
            self.assertEqual(payload["events"][0]["id"], event_id)
            page = dashboard.page_events({"event": "DASHBOARD_SAMPLE"})
            self.assertIn("יומן אירועים", page)
            self.assertIn("מקור נתונים פעיל: SQLite", page)
            self.assertIn("DASHBOARD_SAMPLE", page)
        finally:
            dashboard.db.close()

    def test_mcp_exposes_read_only_event_journal_tools(self):
        names = {tool["name"] for tool in TOOLS}
        self.assertIn("event_log_list", names)
        self.assertIn("event_log_get", names)

        env = FakeEnv(self.tmp)
        dashboard = Dashboard(env.cfg)
        server = Server.__new__(Server)
        server.dashboard = dashboard
        try:
            event_id = dashboard.db.event("MCP_SAMPLE", source="test", answer=42)
            listed = server.call("event_log_list", {"event": "MCP_SAMPLE", "limit": 10})
            fetched = server.call("event_log_get", {"event_id": event_id})
            self.assertEqual(listed["events"][0]["id"], event_id)
            self.assertEqual(fetched["event"]["detail"]["answer"], 42)
        finally:
            dashboard.db.close()


if __name__ == "__main__":
    unittest.main()
