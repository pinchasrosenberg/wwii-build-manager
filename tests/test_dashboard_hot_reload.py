"""Focused acceptance coverage for dashboard hot reload behavior."""
from __future__ import annotations

import threading

from helpers import TmpTestCase
from wwii_build import ws
from wwii_build.activation import activation_id, record_activation, restart_decision
from wwii_build.dashboard import app_version
from wwii_build.db import DB


class DashboardHotReload(TmpTestCase):
    def test_activation_marker_requests_restart_only_after_activation(self):
        db = DB(self.tmp / "state.sqlite3")
        self.addCleanup(db.close)

        seen = activation_id(db)
        self.assertEqual(restart_decision(seen, activation_id(db)), "unchanged")
        current = record_activation(db)
        self.assertEqual(restart_decision(seen, current, busy=True), "wait")
        self.assertEqual(restart_decision(seen, current), "restart")

    def test_app_version_changes_with_served_asset_content(self):
        app = self.tmp / "app"
        app.mkdir()
        asset = app / "app.js"
        asset.write_text("first", encoding="utf-8")
        first = app_version(app)

        asset.write_text("second", encoding="utf-8")
        self.assertNotEqual(app_version(app), first)

    def test_service_restart_uses_websocket_1012(self):
        class Connection:
            def __init__(self):
                self.closed = None
                self.done = threading.Event()

            def close(self, code, reason):
                self.closed = (code, reason)
                self.done.set()

            def abort(self):
                raise AssertionError("graceful close must not abort")

        hub = ws.Hub("token")
        connection = Connection()
        hub._subs[connection] = set()
        hub.close_all(code=ws.CLOSE_SERVICE_RESTART, reason="service restart")

        self.assertEqual(connection.closed, (1012, "service restart"))
