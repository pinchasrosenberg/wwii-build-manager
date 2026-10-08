"""Live state over the dashboard socket (wwii_build.live): change detection, topics, snapshots, patches, actions.

All rows written here are synthetic fixtures, written through a second sqlite connection to imitate the scheduler
daemon / CLI writing from another process.
"""
from __future__ import annotations

import json
import socket
import sqlite3
import time
import unittest
import urllib.request

from helpers import FakeEnv, TmpTestCase, init_repo
from test_ws_transport import TinyClient

from wwii_build import live
from wwii_build.dashboard import Dashboard

NOW = "2026-01-01T00:00:00+00:00"


class LiveCase(TmpTestCase):
    def setUp(self):
        super().setUp()
        init_repo(self.tmp)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.dash = Dashboard(FakeEnv(self.tmp, overrides={"dashboard": {"port": self.port}}).cfg)
        self.dash.serve_in_thread()
        self.other = sqlite3.connect(str(self.dash.db.path), timeout=10, isolation_level=None)   # "another process"
        self.clients: list[TinyClient] = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.other.close()
        self.dash.shutdown()
        super().tearDown()

    def client(self, *topics: str, revs: dict | None = None, timeout: float = 3.0) -> TinyClient:
        c = TinyClient(self.port, token=self.dash.token)
        self.clients.append(c)
        c.sock.settimeout(timeout)
        self.assertEqual(c.recv_json()["type"], "welcome")
        if topics:
            c.send_json({"type": "subscribe", "topics": list(topics), "revs": revs or {}})
        return c

    def snapshots(self, c: TinyClient, count: int) -> dict:
        """Read `count` snapshots plus the subscribed ack; return {topic: snapshot} (+ "ack")."""
        got = {}
        for _ in range(count):
            msg = c.recv_json()
            self.assertEqual(msg["type"], "snapshot", msg)
            got[msg["topic"]] = msg
        got["ack"] = c.recv_json()
        self.assertEqual(got["ack"]["type"], "subscribed", got["ack"])
        return got

    def expect_silence(self, c: TinyClient, seconds: float = 0.8) -> None:
        c.sock.settimeout(seconds)
        with self.assertRaises(socket.timeout):
            c.recv_json()
        c.sock.settimeout(3.0)

    def wait_for(self, cond, timeout: float = 5.0) -> None:
        end = time.monotonic() + timeout
        while not cond():
            if time.monotonic() > end:
                self.fail("condition not reached")
            time.sleep(0.02)

    def add_approval(self) -> int:
        cur = self.other.execute("INSERT INTO approvals(kind,subject,status,created_at) VALUES('model','sol','pending',?)",
                                 (NOW,))
        return cur.lastrowid

    def add_event(self, name: str) -> int:
        return self.other.execute("INSERT INTO event_log(at,event) VALUES(?,?)", (NOW, name)).lastrowid


class Snapshots(LiveCase):
    def test_subscribe_returns_snapshot_per_topic_with_ack(self):
        c = self.client("overview", "approvals", "quota", "events", "unstick", "tasks.active", "workers", "delivers",
                        timeout=5.0)
        got = self.snapshots(c, 8)
        self.assertEqual(got["ack"]["current"], [])
        self.assertEqual(got["ack"]["rejected"], [])
        self.assertEqual(got["approvals"]["data"], {"key": "id", "items": [], "meta": {}})
        overview = got["overview"]["data"]
        self.assertIsNone(overview["key"])
        self.assertEqual(overview["meta"]["status"], "DAEMON NOT RUNNING")
        self.assertEqual(overview["meta"]["counts"], {})
        self.assertEqual(got["unstick"]["data"]["meta"], {"report": None})
        self.assertIn("edges", got["delivers"]["data"]["meta"])
        self.assertTrue(all(isinstance(got[t]["rev"], int) for t in ("overview", "approvals")))

    def test_old_or_missing_rev_gets_snapshot_current_rev_does_not(self):
        c = self.client("approvals")
        rev = self.snapshots(c, 1)["approvals"]["rev"]
        stale = self.client("approvals", revs={"approvals": 1})
        self.assertEqual(self.snapshots(stale, 1)["approvals"]["rev"], rev)       # same state, same rev
        fresh = self.client("approvals", revs={"approvals": rev})
        ack = fresh.recv_json()
        self.assertEqual(ack["type"], "subscribed")                                # no snapshot: client is current
        self.assertEqual(ack["current"], ["approvals"])
        later = self.client("approvals", revs={"approvals": rev - 1})
        self.assertEqual(self.snapshots(later, 1)["approvals"]["rev"], rev)

    def test_resubscribe_after_change_returns_new_snapshot(self):
        c = self.client("approvals")
        rev = self.snapshots(c, 1)["approvals"]["rev"]
        approval_id = self.add_approval()
        patch = c.recv_json()
        self.assertEqual((patch["type"], patch["rev"]), ("patch", rev + 1))
        c.send_json({"type": "subscribe", "topics": ["approvals"], "revs": {"approvals": rev}})   # missed nothing, old rev
        snap = c.recv_json()
        self.assertEqual((snap["type"], snap["rev"]), ("snapshot", rev + 1))
        self.assertEqual([i["id"] for i in snap["data"]["items"]], [approval_id])

    def test_invalid_topics_are_rejected(self):
        c = self.client("nope", "deliver:bad id!", "chat:abc", "deliver:", "approvals")
        got = self.snapshots(c, 1)
        self.assertEqual(got["ack"]["topics"], ["approvals"])
        self.assertEqual(set(got["ack"]["rejected"]), {"nope", "deliver:bad id!", "chat:abc", "deliver:"})
        c.send_json({"type": "subscribe", "topics": "approvals"})
        self.assertEqual(c.recv_json()["error"], "bad_topics")

    def test_topic_limit_per_connection(self):
        c = self.client(timeout=5.0)
        c.send_json({"type": "subscribe", "topics": [f"chat:{i}" for i in range(live.MAX_TOPICS_PER_CONNECTION + 3)]})
        for _ in range(live.MAX_TOPICS_PER_CONNECTION):
            self.assertEqual(c.recv_json()["type"], "snapshot")
        ack = c.recv_json()
        self.assertEqual(len(ack["topics"]), live.MAX_TOPICS_PER_CONNECTION)
        self.assertEqual(len(ack["rejected"]), 3)


class Patches(LiveCase):
    def test_write_from_second_connection_produces_patch_within_a_second(self):
        c = self.client("approvals", "workers")
        rev = self.snapshots(c, 2)["approvals"]["rev"]
        c.sock.settimeout(1.0)
        started = time.monotonic()
        approval_id = self.add_approval()
        patch = c.recv_json()
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual((patch["type"], patch["topic"], patch["rev"]), ("patch", "approvals", rev + 1))
        self.assertEqual([i["id"] for i in patch["upsert"]], [approval_id])
        self.assertEqual(patch["upsert"][0]["subject"], "sol")
        self.assertEqual(patch["remove"], [])
        self.assertNotIn("meta", patch)
        self.other.execute("UPDATE approvals SET status='approved' WHERE id=?", (approval_id,))
        patch = c.recv_json()
        self.assertEqual((patch["rev"], patch["upsert"], patch["remove"]), (rev + 2, [], [approval_id]))

    def test_only_subscribers_of_the_changed_topic_get_the_patch(self):
        watcher, bystander = self.client("approvals"), self.client("quota")
        self.snapshots(watcher, 1), self.snapshots(bystander, 1)
        self.add_approval()
        self.assertEqual(watcher.recv_json()["topic"], "approvals")
        self.expect_silence(bystander)

    def test_unchanged_topics_send_nothing_on_unrelated_commit(self):
        c = self.client("approvals")
        self.snapshots(c, 1)
        self.other.execute("INSERT INTO scheduler_state(key,value) VALUES('unrelated','1')")
        self.expect_silence(c)

    def test_overview_follows_flags_and_task_counts(self):
        c = self.client("overview", "tasks.active")
        got = self.snapshots(c, 2)
        self.other.execute("INSERT INTO scheduler_state(key,value) VALUES('paused','1')")
        patch = c.recv_json()
        self.assertEqual((patch["topic"], patch["rev"]), ("overview", got["overview"]["rev"] + 1))
        self.assertTrue(patch["meta"]["paused"])
        self.assertEqual(patch["meta"]["status"], "PAUSED")
        self.other.execute("INSERT INTO tasks(task_id,packet,owner,mode,model_profile,definition_hash,created_at,"
                           "updated_at,state,wave) VALUES('T/1','T','o','build','IMPLEMENT','h',?,?,'READY',2)",
                           (NOW, NOW))
        seen = {}
        while len(seen) < 2:
            msg = c.recv_json()
            seen[msg["topic"]] = msg
        self.assertEqual([t["task_id"] for t in seen["tasks.active"]["upsert"]], ["T/1"])
        self.assertIn("description_he", seen["tasks.active"]["upsert"][0])
        self.assertEqual(seen["overview"]["meta"]["counts"], {"READY": 1})
        self.assertEqual(seen["overview"]["meta"]["wave"], 2)
        self.other.execute("UPDATE tasks SET state='PASSED' WHERE task_id='T/1'")
        seen = {}
        while len(seen) < 2:
            msg = c.recv_json()
            seen[msg["topic"]] = msg
        self.assertEqual(seen["tasks.active"]["upsert"], [])
        self.assertEqual(seen["tasks.active"]["remove"], ["T/1"])
        self.assertEqual(seen["overview"]["meta"]["wave"], "done")

    def test_unstick_topic_follows_the_report_flag(self):
        c = self.client("unstick")
        self.snapshots(c, 1)
        report = {"at": NOW, "findings": ["x"], "actions": [], "needs_you": []}
        self.other.execute("INSERT INTO scheduler_state(key,value) VALUES('unstick_last_report',?)",
                           (json.dumps(report),))
        patch = c.recv_json()
        self.assertEqual(patch["meta"], {"report": report})
        self.assertEqual((patch["upsert"], patch["remove"]), ([], []))

    def test_unsubscribe_stops_patches_and_unwatched_topics_are_dropped(self):
        c = self.client("approvals")
        self.snapshots(c, 1)
        self.assertIn("approvals", self.dash.live._states)
        c.send_json({"type": "unsubscribe", "topics": ["approvals"]})
        self.wait_for(lambda: not self.dash.hub.subscriptions(self.dash.hub.connections()[0]))
        self.add_approval()
        self.expect_silence(c)
        self.wait_for(lambda: "approvals" not in self.dash.live._states)

    def test_disconnect_drops_topic_state(self):
        c = self.client("approvals")
        self.snapshots(c, 1)
        c.close()
        self.wait_for(lambda: not self.dash.live._states)

    def test_detector_survives_a_failing_topic(self):
        c = self.client("approvals")
        self.snapshots(c, 1)
        original = self.dash.pending_approval_rows
        self.dash.pending_approval_rows = lambda: 1 / 0
        self.add_approval()
        self.wait_for(lambda: self.dash.live.last_error and "approvals" in self.dash.live.last_error)
        self.dash.pending_approval_rows = original
        self.add_approval()
        self.assertEqual(len(c.recv_json()["upsert"]), 2)


class EventsTopic(LiveCase):
    def test_events_stream_new_rows_exactly_once(self):
        old = self.add_event("OLD")
        c = self.client("events")
        snap = self.snapshots(c, 1)["events"]
        self.assertEqual([e["id"] for e in snap["data"]["items"]], [old])
        self.other.execute("BEGIN")                  # one commit, so one detector tick sees both rows
        first, second = self.add_event("A"), self.add_event("B")
        self.other.execute("COMMIT")
        patch = c.recv_json()
        self.assertEqual((patch["type"], patch["topic"], patch["rev"]), ("patch", "events", snap["rev"] + 1))
        self.assertEqual([e["id"] for e in patch["upsert"]], [first, second])
        self.assertEqual(patch["remove"], [])
        third = self.add_event("C")
        patch = c.recv_json()
        self.assertEqual([e["id"] for e in patch["upsert"]], [third])
        self.assertEqual(patch["rev"], snap["rev"] + 2)
        self.other.execute("INSERT INTO scheduler_state(key,value) VALUES('unrelated','1')")
        self.expect_silence(c)

    def test_event_detail_is_decoded_like_the_api(self):
        c = self.client("events")
        self.snapshots(c, 1)
        self.dash.db.event("DECODED", source="test", n=3)
        patch = c.recv_json()
        self.assertEqual(patch["upsert"][0]["detail"], {"source": "test", "n": 3})

    def test_snapshot_is_capped_and_ascending(self):
        ids = [self.add_event(f"E{i}") for i in range(live.SNAPSHOT_EVENTS + 5)]
        c = self.client("events")
        got = [e["id"] for e in self.snapshots(c, 1)["events"]["data"]["items"]]
        self.assertEqual(got, ids[-live.SNAPSHOT_EVENTS:])

    def test_a_burst_is_resynced_with_a_snapshot(self):
        c = self.client("events")
        self.snapshots(c, 1)
        self.other.execute("BEGIN")
        for i in range(live.EVENT_PATCH_MAX + 20):
            self.add_event(f"B{i}")
        self.other.execute("COMMIT")
        msg = c.recv_json()
        self.assertEqual(msg["type"], "snapshot")
        self.assertEqual(len(msg["data"]["items"]), live.SNAPSHOT_EVENTS)


class DeliverAndChatTopics(LiveCase):
    def add_deliver(self, deliver_id: str = "D/one") -> None:
        self.other.execute("INSERT INTO deliver_catalog(deliver_id,owner,domain,description,updated_at) "
                           "VALUES(?,?,?,?,?)", (deliver_id, "owner", "dom", "synthetic deliver", NOW))

    def add_capability(self, name: str, deliver_id: str = "D/one") -> None:
        self.other.execute("INSERT INTO deliver_capabilities(capability_id,deliver_id,group_name,name,kind,updated_at) "
                           "VALUES(?,?,?,?,?,?)", (f"{deliver_id}/g/{name}", deliver_id, "g", name, "declared", NOW))

    def test_deliver_topic_has_capabilities_and_follows_changes(self):
        self.add_deliver()
        self.add_capability("first")
        c = self.client("deliver:D/one", "deliver:D/missing", "delivers", timeout=5.0)
        got = self.snapshots(c, 3)
        data = got["deliver:D/one"]["data"]
        self.assertEqual(data["key"], "capability_id")
        self.assertEqual([i["name"] for i in data["items"]], ["first"])
        self.assertTrue(data["meta"]["exists"])
        self.assertEqual(data["meta"]["deliver"]["deliver_id"], "D/one")
        self.assertFalse(got["deliver:D/missing"]["data"]["meta"]["exists"])
        self.assertEqual([d["deliver_id"] for d in got["delivers"]["data"]["items"]], ["D/one"])
        self.add_capability("second")
        seen = {}
        while "deliver:D/one" not in seen:           # heavy topics are throttled to about one rebuild per second
            msg = c.recv_json()
            seen[msg["topic"]] = msg
        self.assertEqual([i["name"] for i in seen["deliver:D/one"]["upsert"]], ["second"])

    def test_chat_topic_streams_appended_messages(self):
        def say(conv: int, role: str, text: str) -> int:
            return self.other.execute("INSERT INTO state_chat_messages(conversation_id,role,content,created_at) "
                                      "VALUES(?,?,?,?)", (conv, role, text, NOW)).lastrowid
        first = say(7, "user", "שלום")
        say(8, "user", "another conversation")
        c = self.client("chat:7")
        data = self.snapshots(c, 1)["chat:7"]["data"]
        self.assertEqual([m["id"] for m in data["items"]], [first])
        self.assertEqual(data["meta"], {"conversation_id": 7})
        say(8, "assistant", "not for chat:7")
        self.expect_silence(c)
        second = say(7, "assistant", "תשובה")
        patch = c.recv_json()
        self.assertEqual([m["id"] for m in patch["upsert"]], [second])


class Actions(LiveCase):
    def setUp(self):
        super().setUp()
        self.skipped: list[dict] = []

    def act(self, c: TinyClient, aid, name: str, args: dict | None = None) -> dict:
        c.send_json({"type": "action", "id": aid, "name": name, "args": args or {}})
        while True:
            msg = c.recv_json()
            if msg["type"] == "action.result":
                return msg
            self.skipped.append(msg)              # a patch may overtake the result

    def flag(self, key: str):
        row = self.other.execute("SELECT value FROM scheduler_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def test_action_round_trip_changes_db_and_returns_result(self):
        c = self.client("overview")
        self.snapshots(c, 1)
        result = self.act(c, "req-1", "set_auto_approve_all", {"enabled": True})
        self.assertEqual((result["id"], result["ok"]), ("req-1", True))
        self.assertIn("הופעל", result["message"])
        self.assertEqual(self.flag("review_auto_approve_all"), "1")
        self.assertEqual(self.other.execute("SELECT COUNT(*) FROM event_log WHERE event='AUTO_APPROVAL_MODE_CHANGED'")
                         .fetchone()[0], 1)
        # the change also reaches the subscribed overview as a patch
        patch = self.skipped.pop(0) if self.skipped else c.recv_json()
        self.assertEqual((patch["topic"], patch["meta"]["review_auto_approve_all"]), ("overview", True))
        off =self.act(c, 2, "set_auto_approve_all", {"enabled": False})
        self.assertEqual((off["id"], off["ok"]), (2, True))
        self.assertEqual(self.flag("review_auto_approve_all"), "0")

    def test_action_uses_the_same_code_path_as_the_form(self):
        c = self.client()
        calls = []
        original = self.dash.action
        self.dash.action = lambda form, uploads=None: calls.append(dict(form)) or original(form, uploads)
        self.act(c, "a", "set_auto_approve_all", {"enabled": 1, "back": "/x"})
        self.assertEqual(calls, [{"enabled": "1", "back": "/x", "action": "set_auto_approve_all"}])

    def test_failures_report_ok_false(self):
        c = self.client()
        self.assertFalse(self.act(c, "u", "no_such_action")["ok"])
        self.assertIn("unknown action", self.act(c, "u2", "no_such_action")["message"])
        bad = self.act(c, "v", "approve", {"approval_id": 999})
        self.assertFalse(bad["ok"])
        self.assertTrue(bad["message"].startswith("error:"))
        self.assertFalse(self.act(c, "w", "approve", {})["ok"])                      # missing argument -> KeyError
        self.assertFalse(self.act(c, "x", "set_auto_approve_all", {"enabled": {"a": 1}})["ok"])
        self.assertFalse(self.act(c, "y", "Bad-Name!")["ok"])
        c.send_json({"type": "action", "name": "pause"})                              # no id
        self.assertEqual(c.recv_json()["error"], "bad_action")
        c.send_json({"type": "action", "id": "z", "name": "pause", "args": [1]})
        self.assertFalse(c.recv_json()["ok"])

    def test_actions_run_off_the_reader_thread(self):
        import threading
        started, release = threading.Event(), threading.Event()
        original = self.dash.action

        def slow(form, uploads=None):
            started.set()
            release.wait(5)
            return original(form, uploads)
        self.dash.action = slow
        c = self.client()
        c.send_json({"type": "action", "id": "slow", "name": "set_auto_approve_all", "args": {"enabled": "0"}})
        self.assertTrue(started.wait(3))
        c.send_json({"type": "ping"})
        self.assertEqual(c.recv_json(), {"type": "pong"})                             # reader is not blocked
        release.set()
        self.assertEqual(c.recv_json()["id"], "slow")

    def test_pending_action_cap(self):
        import threading
        release = threading.Event()
        self.dash.action = lambda form, uploads=None: release.wait(5) and "ok"
        c = self.client()
        for i in range(live.MAX_PENDING_ACTIONS):
            c.send_json({"type": "action", "id": i, "name": "pause"})
        c.send_json({"type": "action", "id": "extra", "name": "pause"})
        msg = c.recv_json()
        self.assertEqual((msg["id"], msg["ok"]), ("extra", False))
        release.set()


class FormArgs(unittest.TestCase):
    def test_conversion_rules(self):
        form, multi = live.form_from_args({
            "enabled": True, "off": False, "n": 3, "none": None, "text": "t", "token": "ignored", "action": "ignored",
            "write_scope": ["a/", "b/"], "mcp_servers": ["x", "y"], "deps": ["T/1", "T/2"]})
        self.assertEqual(form, {"enabled": "1", "off": "0", "n": "3", "none": "", "text": "t",
                                "write_scope": "a/\nb/", "mcp_servers": "x,y", "deps": "T/1\nT/2"})
        self.assertEqual(multi["deps"], ["T/1", "T/2"])
        self.assertEqual(multi["text"], ["t"])
        for bad in ({"a": {"b": 1}}, {"a": [{"b": 1}]}, {"a": [True]}):
            with self.assertRaises(ValueError):
                live.form_from_args(bad)

    def test_topic_names(self):
        for name in live.STATIC_TOPICS + ("deliver:D/one", "deliver:a:b", "chat:12"):
            self.assertIsNotNone(live.parse_topic(name), name)
        for name in ("", "deliver", "deliver:", "chat:", "chat:-1", "chat:x", "deliver:a b", "Tasks", None, 5,
                     "chat:" + "1" * 13):
            self.assertIsNone(live.parse_topic(name), name)


class I18nEndpoint(LiveCase):
    def test_api_i18n_returns_hebrew_and_english_strings(self):
        raw = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/i18n").read()
        data = json.loads(raw.decode("utf-8"))
        self.assertEqual(data["default"], "he")
        self.assertEqual(data["dir"]["he"], "rtl")
        self.assertEqual(data["strings"]["he"]["Tasks"], "משימות")
        self.assertEqual(data["strings"]["en"]["Tasks"], "Tasks")
        self.assertEqual(data["states"]["he"]["PASSED"], "עבר")
        self.assertEqual(set(data["strings"]["he"]), set(data["strings"]["en"]))

    def test_existing_json_endpoints_still_work(self):
        for path in ("/api/state", "/api/delivers", "/api/events"):
            with self.subTest(path=path):
                self.assertEqual(urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}").status, 200)
        state = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/state").read())
        self.assertTrue(set(state) >= {"tasks", "workers", "quota", "approvals", "jev"})


if __name__ == "__main__":
    unittest.main()
