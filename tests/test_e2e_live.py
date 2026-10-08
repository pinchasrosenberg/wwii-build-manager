"""End to end: a real dashboard, a real socket, a DB write from another connection and an action from the client.

All rows written here are synthetic fixtures; the second sqlite connection imitates the scheduler daemon / CLI / MCP
server, which write the same database from other processes.
"""
from __future__ import annotations

import unittest

from test_ws_live import LiveCase


class DashboardEndToEnd(LiveCase):
    def read_until(self, c, wanted) -> list[dict]:
        """Read messages until every predicate in `wanted` matched one (order does not matter); return all read."""
        seen, missing = [], list(wanted)
        while missing:
            msg = c.recv_json()                 # a stalled stream raises socket.timeout after the client timeout
            seen.append(msg)
            missing = [w for w in missing if not w(msg)]
        return seen

    def test_external_write_and_action_both_reach_a_subscribed_socket(self):
        c = self.client("overview", "events", timeout=5.0)
        got = self.snapshots(c, 2)
        self.assertEqual(got["overview"]["data"]["meta"]["status"], "DAEMON NOT RUNNING")
        self.assertFalse(got["overview"]["data"]["meta"]["review_auto_approve_all"])

        # 1. another process writes the state: the overview patch arrives without the client asking
        self.other.execute("INSERT INTO scheduler_state(key,value) VALUES('paused','1')")
        patch = c.recv_json()
        self.assertEqual((patch["type"], patch["topic"]), ("patch", "overview"))
        self.assertEqual(patch["rev"], got["overview"]["rev"] + 1)
        self.assertTrue(patch["meta"]["paused"])
        self.assertEqual(patch["meta"]["status"], "PAUSED")

        # 2. the client runs an action: its result arrives, and so do the changes it caused (overview + events)
        c.send_json({"type": "action", "id": "e2e-1", "name": "set_auto_approve_all", "args": {"enabled": True}})
        seen = self.read_until(c, [
            lambda m: m["type"] == "action.result" and m["id"] == "e2e-1" and m["ok"] is True,
            lambda m: m["type"] == "patch" and m["topic"] == "overview" and m["meta"]["review_auto_approve_all"] is True,
            lambda m: m["type"] == "patch" and m["topic"] == "events"
            and any(e["event"] == "AUTO_APPROVAL_MODE_CHANGED" for e in m["upsert"]),
        ])
        self.assertEqual(sum(1 for m in seen if m["type"] == "action.result"), 1)
        row = self.other.execute("SELECT value FROM scheduler_state WHERE key='review_auto_approve_all'").fetchone()
        self.assertEqual(row[0], "1")

        # 3. the socket stays alive and quiet afterwards (no polling traffic, no duplicate patches)
        c.send_json({"type": "ping"})
        self.assertEqual(c.recv_json(), {"type": "pong"})


if __name__ == "__main__":
    unittest.main()
