"""Progress streaming of long operations over the dashboard socket (unstick, onboarding, state chat, graph console).

All rows, manifests and provider answers here are synthetic fixtures.
"""
from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from helpers import init_repo
from test_ws_live import LiveCase

from wwii_build import live
from wwii_build import onboarding as ob
from wwii_build import unstick as us
from wwii_build.dashboard import ALREADY_RUNNING, Dashboard
from wwii_build.models import AttemptStatus

MANIFEST = '''
[system]
id = "demo"
title = "Demo system"
context_dir = "context/systems/demo"
description = "synthetic"

[[components]]
deliver_id = "demo.core"
title = "Core"
owner = "core_owner"
domain = "core"
execution_kind = "deterministic"
root = "src"
description = "Core library."
docs = ["README.md"]
'''


class StubProvider:
    """A model that answers after ``gate`` is released (synthetic)."""

    def __init__(self, gate: threading.Event | None = None):
        self.gate = gate
        self.entered = threading.Event()

    async def run_task(self, spec, supervisor, timeout=None):
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(10)
        return SimpleNamespace(status=AttemptStatus.SUCCEEDED, structured={"answer": "synthetic answer",
                                                                           "suggested_actions": ["step"]},
                               final_text="", input_tokens=1, output_tokens=2, cached_input_tokens=0,
                               reported_cost_usd=0.0, quota_signals=[], error=None, failure_class=None)


class StreamCase(LiveCase):
    def start(self, c, aid, name, args=None) -> None:
        c.send_json({"type": "action", "id": aid, "name": name, "args": args or {}})

    def until_result(self, c, aid, bag: list | None = None) -> dict:
        """Read until the action.result of ``aid``; everything read before it lands in ``bag``."""
        bag = [] if bag is None else bag
        while True:
            msg = c.recv_json()
            if msg["type"] == "action.result" and msg["id"] == aid:
                return msg
            bag.append(msg)

    def lines(self, bag: list, aid) -> list[str]:
        return [m["line"] for m in bag if m["type"] == "progress" and m["id"] == aid]


class UnstickProgress(unittest.TestCase):
    def test_callback_gets_findings_and_actions_without_changing_the_return_value(self):
        from helpers import FakeEnv
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            init_repo(Path(tmp))
            env = FakeEnv(Path(tmp))
            db = Dashboard(env.cfg).db
            db.set_flag("paused", "1")
            heard: list[str] = []
            with mock.patch.object(us, "_start_daemon"):
                streamed = us.unstick(env.cfg, db, "test", progress=heard.append)
                db.set_flag("paused", "1")
                plain = us.unstick(env.cfg, db, "test")
        for key in ("findings", "actions", "needs_you", "counts", "source"):
            self.assertEqual(streamed[key], plain[key], key)
        for key in ("findings", "actions", "needs_you"):
            self.assertIs(type(streamed[key]), list, key)           # the report stays plain JSON data
        self.assertEqual(len(heard), len(streamed["findings"]) + len(streamed["actions"]) + len(streamed["needs_you"]))
        for finding in streamed["findings"]:
            self.assertIn(f"ממצא: {finding}", heard)
        for action in streamed["actions"]:
            self.assertIn(f"פעולה: {action}", heard)
        self.assertLess(heard.index(f"ממצא: {streamed['findings'][0]}"), heard.index(f"פעולה: {streamed['actions'][0]}"))

    def test_a_failing_listener_does_not_stop_the_pass(self):
        from helpers import FakeEnv
        import tempfile
        from pathlib import Path

        def broken(line):
            raise OSError("socket closed")
        with tempfile.TemporaryDirectory() as tmp:
            init_repo(Path(tmp))
            env = FakeEnv(Path(tmp))
            db = Dashboard(env.cfg).db
            with mock.patch.object(us, "_start_daemon"):
                report = us.unstick(env.cfg, db, "test", progress=broken)
        self.assertTrue(report["findings"])


class DashboardHelpers(StreamCase):
    def test_progress_is_a_noop_without_a_stream_and_scoped_to_the_thread(self):
        self.dash.progress("nobody listens")                       # no error
        heard = []
        with self.dash.progress_to(heard.append):
            self.dash.progress("a")
            other = []
            t = threading.Thread(target=lambda: (self.dash.progress("other thread"), other.append(1)))
            t.start()
            t.join()
            self.assertEqual(other, [1])
        self.dash.progress("after")
        self.assertEqual(heard, ["a"])

    def test_run_exclusive_rejects_a_second_run_of_the_same_key_only(self):
        inside, release = threading.Event(), threading.Event()
        first = []
        t = threading.Thread(target=lambda: first.append(
            self.dash.run_exclusive("k", lambda: (inside.set(), release.wait(5), "first done")[2])))
        t.start()
        self.assertTrue(inside.wait(3))
        self.assertEqual(self.dash.run_exclusive("k", lambda: "never"), ALREADY_RUNNING)
        self.assertEqual(self.dash.run_exclusive("other", lambda: "fine"), "fine")
        release.set()
        t.join()
        self.assertEqual(first, ["first done"])
        self.assertEqual(self.dash.run_exclusive("k", lambda: "again"), "again")     # released afterwards

    def test_exclusive_key_is_released_when_the_operation_raises(self):
        with self.assertRaises(RuntimeError):
            self.dash.run_exclusive("k", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(self.dash.run_exclusive("k", lambda: "ok"), "ok")

    def test_busy_answer_is_not_ok_in_run_form(self):
        with mock.patch.object(Dashboard, "run_exclusive", return_value=ALREADY_RUNNING):
            ok, message = self.dash.run_form({"action": "unstick"}, {})
        self.assertEqual((ok, message), (False, "כבר רץ"))


class UnstickOverSocket(StreamCase):
    def test_progress_arrives_before_the_result(self):
        self.dash.db.set_flag("paused", "1")
        c = self.client()
        with mock.patch.object(us, "_start_daemon"):
            self.start(c, "u1", "unstick")
            bag: list = []
            result = self.until_result(c, "u1", bag)
        progress = self.lines(bag, "u1")
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(len(progress), 2)
        self.assertTrue(any(line.startswith("ממצא: ") for line in progress))
        self.assertTrue(any(line.startswith("פעולה: ") for line in progress))
        self.assertTrue(all(m["type"] in ("progress", "patch", "snapshot") for m in bag), bag)

    def test_second_unstick_while_one_runs_is_rejected(self):
        inside, release = threading.Event(), threading.Event()

        def slow(cfg, db, source="dashboard", progress=None):
            progress("ממצא: בדיקה")
            inside.set()
            release.wait(5)
            return {"findings": [], "actions": [], "needs_you": []}
        c = self.client()
        with mock.patch.object(us, "unstick", slow):
            self.start(c, "first", "unstick")
            self.assertTrue(inside.wait(3))
            self.start(c, "second", "unstick")
            bag: list = []
            second = self.until_result(c, "second", bag)
            self.assertEqual((second["ok"], second["message"]), (False, "כבר רץ"))
            self.assertEqual(self.lines(bag, "first"), ["ממצא: בדיקה"])       # the first one's stream is unaffected
            release.set()
            first = self.until_result(c, "first")
            self.assertTrue(first["ok"], first)
            self.start(c, "third", "unstick")                                   # free again afterwards
            self.assertTrue(self.until_result(c, "third")["ok"])

    def test_second_client_is_rejected_too_and_gets_no_foreign_progress(self):
        inside, release = threading.Event(), threading.Event()

        def slow(cfg, db, source="dashboard", progress=None):
            progress("ממצא: א")
            inside.set()
            release.wait(5)
            return {"findings": [], "actions": [], "needs_you": []}
        a, b = self.client(), self.client()
        with mock.patch.object(us, "unstick", slow):
            self.start(a, "a1", "unstick")
            self.assertTrue(inside.wait(3))
            self.start(b, "b1", "unstick")
            bag: list = []
            self.assertEqual(self.until_result(b, "b1", bag)["message"], "כבר רץ")
            self.assertEqual(self.lines(bag, "b1"), [])
            release.set()
            self.until_result(a, "a1")

    def test_progress_lines_are_capped_per_action(self):
        def chatty(cfg, db, source="dashboard", progress=None):
            for i in range(10):
                progress(f"שורה {i}")
            return {"findings": [], "actions": [], "needs_you": []}
        c = self.client()
        with mock.patch.object(us, "unstick", chatty), mock.patch.object(live, "MAX_PROGRESS_LINES", 3):
            self.start(c, "x", "unstick")
            bag: list = []
            self.assertTrue(self.until_result(c, "x", bag)["ok"])
        self.assertEqual(self.lines(bag, "x"), ["שורה 0", "שורה 1", "שורה 2"])

    def test_form_post_path_has_no_stream_and_still_works(self):
        with mock.patch.object(us, "_start_daemon"):
            message = self.dash.action({"action": "unstick"})
        self.assertIn("בוצעו", message)


class OnboardOverSocket(StreamCase):
    def setUp(self):
        super().setUp()
        repo = self.dash.cfg.repo
        (repo / "src").mkdir()
        (repo / "src" / "README.md").write_text("# Core\n\nsynthetic\n")
        (repo / "demo.toml").write_text(MANIFEST)

    def test_onboard_streams_progress_then_result(self):
        def fake_graph(cfg, db, m, graph_service=None, force=False, progress=None, batch=40):
            progress("graph entities 1/1")
            return {"enabled": True}
        c = self.client()
        with mock.patch.object(ob, "push_structured_graph", fake_graph):
            self.start(c, "o1", "system_onboard", {"manifest": "demo.toml", "graph": True})
            bag: list = []
            result = self.until_result(c, "o1", bag)
        progress = self.lines(bag, "o1")
        self.assertTrue(result["ok"], result)
        self.assertIn("demo", result["message"])
        self.assertTrue(progress[0].startswith("טוען את המניפסט"), progress)
        self.assertIn("graph entities 1/1", progress)
        self.assertTrue(progress[-1].startswith("נשמרו"), progress)
        self.assertEqual(self.dash.db.one("SELECT COUNT(*) n FROM system_onboarding")["n"], 2)   # index + component

    def test_graph_flag_false_skips_the_graph(self):
        c = self.client()
        with mock.patch.object(ob, "push_structured_graph", side_effect=AssertionError("graph must be skipped")):
            self.start(c, "o2", "system_onboard", {"manifest": "demo.toml", "graph": False})
            self.assertTrue(self.until_result(c, "o2")["ok"])

    def test_second_onboard_while_one_runs_is_rejected(self):
        inside, release = threading.Event(), threading.Event()

        def slow(cfg, db, manifest_path, graph=None, dry_run=False, graph_service=None, progress=None):
            progress("מתחיל")
            inside.set()
            release.wait(5)
            return {"system": "demo", "components": [], "capabilities": {}}
        c = self.client()
        with mock.patch.object(ob, "onboard", slow):
            self.start(c, "first", "system_onboard", {"manifest": "demo.toml"})
            self.assertTrue(inside.wait(3))
            self.start(c, "second", "system_onboard", {"manifest": "demo.toml"})
            second = self.until_result(c, "second")
            self.assertEqual((second["ok"], second["message"]), (False, "כבר רץ"))
            # unstick is a different operation: it is not blocked by the running onboard
            with mock.patch.object(us, "_start_daemon"):
                self.start(c, "u", "unstick")
                self.assertTrue(self.until_result(c, "u")["ok"])
            release.set()
            self.assertTrue(self.until_result(c, "first")["ok"])

    def test_manifest_argument_is_validated(self):
        c = self.client()
        for i, manifest in enumerate(("", "../../etc/passwd", "/etc/hosts", "src/README.md", "missing", "nope.toml")):
            self.start(c, f"m{i}", "system_onboard", {"manifest": manifest})
            result = self.until_result(c, f"m{i}")
            self.assertFalse(result["ok"], manifest)
        outside = self.tmp / "outside.toml"
        outside.write_text(MANIFEST)
        self.start(c, "out", "system_onboard", {"manifest": str(outside)})
        self.assertFalse(self.until_result(c, "out")["ok"])
        self.assertEqual(self.dash.db.one("SELECT COUNT(*) n FROM system_onboarding")["n"], 0)

    def test_a_known_manifest_name_resolves_inside_the_systems_directory(self):
        self.assertEqual(self.dash._manifest_path("ww2_atlas"), ob.SYSTEMS_DIR / "ww2_atlas.toml")
        self.assertEqual(self.dash._manifest_path("ww2_atlas.toml"), ob.SYSTEMS_DIR / "ww2_atlas.toml")

    def test_onboard_error_is_a_failed_result_and_releases_the_lock(self):
        c = self.client()
        (self.dash.cfg.repo / "bad.toml").write_text("[system]\nid='x'\n")
        self.start(c, "bad", "system_onboard", {"manifest": "bad.toml", "graph": False})
        result = self.until_result(c, "bad")
        self.assertFalse(result["ok"])
        self.start(c, "good", "system_onboard", {"manifest": "demo.toml", "graph": False})
        self.assertTrue(self.until_result(c, "good")["ok"])


class StateChatOverSocket(StreamCase):
    def test_thinking_comes_first_and_every_client_sees_the_chat_topic_update(self):
        gate = threading.Event()
        provider = StubProvider(gate)
        self.dash.providers = {"codex": provider, "claude": provider}
        asker = self.client()
        watcher = self.client("overview")
        self.snapshots(watcher, 1)
        self.start(asker, "chat1", "state_chat", {"message": "synthetic question", "model_key": "sol",
                                                  "conversation_id": ""})
        self.assertTrue(provider.entered.wait(5))
        # while the model is thinking the user's message is already committed and pushed to the other client
        seen = []
        while not any(m.get("topic") == "overview" and m.get("meta", {}).get("chat_conversation_id") == 1 for m in seen):
            seen.append(watcher.recv_json())
        watcher.send_json({"type": "subscribe", "topics": ["chat:1"], "revs": {}})
        snap = None
        while snap is None:
            msg = watcher.recv_json()
            snap = msg if msg.get("type") == "snapshot" and msg["topic"] == "chat:1" else None
        self.assertEqual([m["role"] for m in snap["data"]["items"]], ["user"])
        self.assertEqual(snap["data"]["items"][0]["content"], "synthetic question")
        gate.set()
        bag: list = []
        result = self.until_result(asker, "chat1", bag)
        progress = self.lines(bag, "chat1")
        self.assertTrue(result["ok"], result)
        self.assertEqual(progress[0], "thinking")
        self.assertGreaterEqual(len(progress), 3)
        self.assertIn("התשובה נשמרה בשיחה", progress)
        patch = None                                                    # the answer reaches the watcher as a patch
        while patch is None:
            msg = watcher.recv_json()
            patch = msg if msg.get("type") == "patch" and msg["topic"] == "chat:1" else None
        self.assertEqual([m["role"] for m in patch["upsert"]], ["assistant"])
        self.assertIn("synthetic answer", patch["upsert"][0]["content"])

    def test_chat_failure_still_streams_thinking_and_reports_the_error(self):
        self.dash.providers = {}
        c = self.client()
        self.start(c, "chat2", "state_chat", {"message": "synthetic", "model_key": "sol"})
        bag: list = []
        result = self.until_result(c, "chat2", bag)
        self.assertFalse(result["ok"])
        self.assertEqual(self.lines(bag, "chat2"), ["thinking"])


class GraphConsoleOverSocket(StreamCase):
    def test_cypher_query_streams_before_the_result(self):
        self.dash.graph_rag.query_cypher = lambda query, params, max_rows: {"count": 3, "rows": []}
        c = self.client()
        self.start(c, "g1", "graph_console_query", {"query_mode": "cypher", "query": "MATCH (n) RETURN n"})
        bag: list = []
        result = self.until_result(c, "g1", bag)
        self.assertTrue(result["ok"], result)
        progress = self.lines(bag, "g1")
        self.assertEqual(progress[0], "שאילתה #1 נשמרה")
        self.assertIn("מריץ Cypher לקריאה בלבד", progress)

    def test_natural_llm_query_streams_selection_and_answer_stages(self):
        gate = threading.Event()
        provider = StubProvider(gate)
        provider_payload = {"summary": "synthetic", "questions": [], "tasks": []}

        async def run_task(spec, supervisor, timeout=None):
            provider.entered.set()
            gate.wait(10)
            return SimpleNamespace(status=AttemptStatus.SUCCEEDED, structured=provider_payload, final_text="",
                                   input_tokens=1, cached_input_tokens=0, output_tokens=2, reported_cost_usd=0.0,
                                   error=None, failure_class=None)
        provider.run_task = run_task
        self.dash.providers = {"codex": provider, "claude": provider}
        self.dash.graph_rag.selected_query = lambda *a, **k: {"candidate_count": 0, "selected": []}
        c = self.client()
        self.start(c, "g2", "graph_console_query", {"query_mode": "natural", "query": "synthetic?", "model_key": "sol"})
        self.assertTrue(provider.entered.wait(5))
        gate.set()
        bag: list = []
        result = self.until_result(c, "g2", bag)
        self.assertTrue(result["ok"], result)
        progress = self.lines(bag, "g2")
        self.assertEqual(progress[0], "שאילתה #1 נשמרה")
        self.assertIn("Jev בוחר מקורות מהגרף", progress)
        self.assertTrue(any("ממתין לתשובה מ־sol" in line for line in progress), progress)
        self.assertEqual(progress[-1], "התשובה התקבלה ונשמרת")


class PokeLatency(StreamCase):
    def test_poke_wakes_the_detector_before_the_next_poll(self):
        self.dash.live.stop()
        live_state = live.LiveState(self.dash, poll_seconds=30)       # a poll that would never fire in this test
        wakes = []
        original = live_state.tick
        live_state.tick = lambda changed, now=None: (wakes.append(changed), original(changed, now))[1]
        live_state.start()
        try:
            self.wait_for(lambda: len(wakes) >= 1)
            before = len(wakes)
            self.other.execute("INSERT INTO event_log(at,event) VALUES('2026-01-01T00:00:00+00:00','X')")
            live_state.poke()
            self.wait_for(lambda: len(wakes) > before, timeout=3)
            self.assertTrue(wakes[-1])
        finally:
            live_state.stop()


if __name__ == "__main__":
    unittest.main()
