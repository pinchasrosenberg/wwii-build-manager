from __future__ import annotations

import json
import os
from unittest import mock

from helpers import TmpTestCase

from wwii_build.config import DEFAULTS, Config, deep_merge
from wwii_build.credentials import (KEYCHAIN_ACCOUNT, KEYCHAIN_SERVICE,
                                    LEGACY_KEYCHAIN_ENTRIES, TypeSafeCredentialStore)
from wwii_build import control
from wwii_build.db import DB
from wwii_build.dashboard import Dashboard
from wwii_build.jev import ChoiceReply, JevClient, JevError, JevService
from wwii_build.graph_rag import GraphRagService
from wwii_build.listeners import (ListenerEngine, compile_snow_state, register_listener_manifest,
                                  scan_episode_context, selector_matches, validate_listener_manifest)
from wwii_build.models import iso, utcnow
from wwii_build.mcp_server import TOOLS, Server


def choice_first(body, timeout):
    criteria = body["questions"]["route"]["criteria"]
    selected = next(key for key in criteria if key != "__no_match__")
    return {"answers": {"route": {"type": "choice", "choice": selected,
                                    "probabilities": {key: float(key == selected) for key in criteria},
                                    "confidence": 0.99}},
            "usage": {"input_tokens": 12, "output_tokens": 2}, "model": "jev-1.13.0"}


class JevListenerTests(TmpTestCase):
    def cfg(self, enabled=True):
        repo = self.tmp / "repo"
        repo.mkdir(exist_ok=True)
        return Config(repo=repo, data=deep_merge(DEFAULTS, {"notifications": {"enabled": False},
                       "jev": {"enabled": enabled, "local_budget": 1000}}), path=None)

    def seed(self, db):
        now = iso(utcnow())
        for did, kind in (("episode.context_scan", "deterministic"), ("weather.snow_research", "llm_research")):
            db.x("INSERT INTO deliver_catalog(deliver_id,description,source_kind,execution_kind,availability,enabled,updated_at) VALUES(?,?,?,?,?,1,?)",
                 (did, did, "test", kind, "prototype", now))
        db.x("INSERT INTO deliver_listener_edges(listener_id,source_deliver_id,target_deliver_id,event_type,context_selector,source_kind,edge_type,jev_gate,enabled,proposal_reason,updated_at) VALUES(?,?,?,?,?,'test','listener',1,1,?,?)",
             ("snow.signal_to_research", "episode.context_scan", "weather.snow_research", "CONTEXT_SCANNED",
              json.dumps({"episode_any_truthy": ["possible_snow"]}), "snow signal", now))

    def test_listener_requires_explicit_jev_choice(self):
        cfg = self.cfg(True); db = DB(":memory:"); self.seed(db)
        service = JevService(cfg, db, client=JevClient(transport=choice_first))
        routed = ListenerEngine(cfg, db, service).emit(
            episode_id="e1", source_deliver_id="episode.context_scan", event_type="CONTEXT_SCANNED",
            episode_patch={"possible_snow": True}, context_refs=["graph:weather:1"])
        self.assertEqual(routed.status, "SELECTED")
        activation = db.one("SELECT * FROM listener_activations")
        self.assertEqual(activation["target_deliver_id"], "weather.snow_research")
        self.assertEqual(db.one("SELECT status FROM jev_route_decisions")["status"], "SUCCESS")

    def test_disabled_jev_activates_nothing(self):
        cfg = self.cfg(False); db = DB(":memory:"); self.seed(db)
        routed = ListenerEngine(cfg, db).emit(
            episode_id="e1", source_deliver_id="episode.context_scan", event_type="CONTEXT_SCANNED",
            episode_patch={"possible_snow": True})
        self.assertEqual(routed.status, "NO_ACTIVATION")
        self.assertEqual(db.one("SELECT COUNT(*) n FROM listener_activations")["n"], 0)
        self.assertEqual(db.one("SELECT status FROM jev_route_decisions")["status"],
                         "JEV_DISABLED_NO_ACTIVATION")

    def test_all_llm_context_is_fail_closed(self):
        cfg = self.cfg(False); db = DB(":memory:")
        selected = JevService(cfg, db).select_context_bundles("task", [{
            "id": "context:core", "description": "task envelope", "execution_kind": "context_bundle",
            "required_for_execution": True}], "build task")
        self.assertEqual(selected, [])
        self.assertIsNone(db.one("SELECT selected_id FROM jev_route_decisions")["selected_id"])

    def test_snow_functions_preserve_unknowns(self):
        self.assertTrue(scan_episode_context({"tags": ["winter"]})["possible_snow"])
        snow = compile_snow_state({"present": True, "evidence_refs": ["claim:1"]})
        self.assertIn("depth_cm", snow["unknown_fields"])
        self.assertTrue(selector_matches({"episode_field_equals": {"snow.present": True}},
                                         {"snow": {"present": True}}, {}))

    def test_every_lego_has_listener_decision_and_unknown_target_is_inert(self):
        cfg = self.cfg(True); db = DB(":memory:")
        now = iso(utcnow())
        db.x("INSERT INTO deliver_catalog(deliver_id,description,source_kind,execution_kind,availability,enabled,updated_at) VALUES('build.tank','tank','test','worker','available',1,?)", (now,))
        manifest = [{"lego_id": "tank.powertrain", "no_listener_reason": "", "proposed_listeners": [{
            "listener_id": "tank.powertrain::terrain", "event_type": "POWERTRAIN_READY",
            "target_deliver_id": "terrain.mobility", "reason": "terrain may change traction",
            "episode_truthy_any": [], "tags_any": [], "battle_any": ["vehicle_movement"],
            "episode_equals": [], "build_status": []}]}]
        self.assertEqual(validate_listener_manifest(manifest, ["tank.powertrain"]), [])
        result = register_listener_manifest(db, "build.tank", manifest, source_ref="attempt:1")
        self.assertEqual(result["placeholders"], 1)
        self.assertEqual(db.one("SELECT enabled FROM deliver_catalog WHERE deliver_id='terrain.mobility'")["enabled"], 0)
        edge = db.one("SELECT source_lego_id,jev_gate FROM deliver_listener_edges WHERE listener_id=?",
                      ("tank.powertrain::terrain",))
        self.assertEqual(edge["source_lego_id"], "tank.powertrain")
        self.assertEqual(edge["jev_gate"], 1)

    def test_health_check_uses_existing_deliver_ids_and_records_usage(self):
        cfg = self.cfg(True); db = DB(":memory:"); self.seed(db)

        class Credentials:
            def present(self): return True
            def source(self): return "test"

        class Client:
            def list_models(self, model):
                return [{"name": "jev-latest", "description": "test", "release_date": "2026-01-01"}]
            def choice(self, *, state, criteria, model, instructions):
                selected = next(iter(criteria))
                return ChoiceReply(selected, {k: float(k == selected) for k in criteria}, .99,
                                   "jev-1.13.0", {"input_tokens": 9, "output_tokens": 2}, "req-health")

        result = JevService(cfg, db, client=Client(), credential_store=Credentials()).health_check()
        self.assertEqual(result["status"], "READY")
        self.assertIn(result["selected_deliver_id"], result["candidate_deliver_ids"])
        self.assertEqual(db.one("SELECT input_tokens FROM jev_health_checks")["input_tokens"], 9)
        self.assertEqual(db.one("SELECT input_tokens FROM jev_usage_requests")["input_tokens"], 9)

    def test_keychain_contract_uses_stable_service_and_current_macos_user(self):
        self.assertEqual(KEYCHAIN_SERVICE, "typesafe-delivers")
        self.assertTrue(KEYCHAIN_ACCOUNT)
        self.assertIn(("wwii-build.typesafe.api-key", "typesafe-api"), LEGACY_KEYCHAIN_ENTRIES)

    def test_keychain_read_prefers_stable_entry_then_legacy(self):
        store = TypeSafeCredentialStore(env={})
        with mock.patch.object(store, "_frameworks", return_value=(mock.Mock(), object())), \
             mock.patch("wwii_build.credentials.platform.system", return_value="Darwin"), \
             mock.patch.object(store, "_keychain_get_entry", side_effect=[None, "legacy-secret"]) as lookup:
            self.assertEqual(store.get(), "legacy-secret")
        self.assertEqual(lookup.call_args_list[0].args[2:], (KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT))
        self.assertEqual(lookup.call_args_list[1].args[2:], LEGACY_KEYCHAIN_ENTRIES[0])

    def test_keychain_lookup_never_prompts_and_restores_interaction(self):
        """A locked keychain without a screen (CI, SSH) must read as missing, not block on an unlock dialog."""
        store = TypeSafeCredentialStore(env={})
        security = mock.Mock()
        seen = []

        def lookup(sec, core, service, account):
            seen.append(sec.SecKeychainSetUserInteractionAllowed.call_args.args[0])
            return None

        with mock.patch.object(store, "_frameworks", return_value=(security, object())), \
             mock.patch("wwii_build.credentials.platform.system", return_value="Darwin"), \
             mock.patch.object(store, "_keychain_get_entry", side_effect=lookup):
            self.assertIsNone(store.get())
        self.assertTrue(seen and all(v == 0 for v in seen))            # interaction off during every lookup
        last = security.SecKeychainSetUserInteractionAllowed.call_args.args[0]
        self.assertEqual(security.SecKeychainSetUserInteractionAllowed.call_count, 2)   # off, then restored

    def test_locked_keychain_reads_as_missing(self):
        from wwii_build.credentials import ERR_INTERACTION_NOT_ALLOWED
        security = mock.Mock()
        security.SecKeychainFindGenericPassword.return_value = ERR_INTERACTION_NOT_ALLOWED
        self.assertIsNone(TypeSafeCredentialStore._keychain_get_entry(security, mock.Mock(), "svc", "acct"))

    def test_rejected_dashboard_key_does_not_replace_saved_credential(self):
        dash = Dashboard(self.cfg())
        with mock.patch.object(JevClient, "list_models", side_effect=JevError("authentication", 403)), \
             mock.patch.object(dash.jev.credentials, "set") as save:
            result = dash.action({"action": "save_typesafe_key", "typesafe_key": "rejected-example"})
        self.assertIn("המפתח הקודם נשאר שמור", result)
        save.assert_not_called()

    def test_ready_health_releases_only_jev_context_backoff(self):
        db = DB(":memory:")
        now = iso(utcnow())
        for tid, reason in (("jev-task", "Jev did not approve required LLM context; retry is delayed"),
                            ("jev-countdown", "retry backoff until 2026-10-01T07:31:00+00:00"),
                            ("other-task", "technical retry")):
            db.x("INSERT INTO tasks(task_id,packet,owner,mode,model_profile,definition_hash,state,state_reason,not_before,created_at,updated_at) "
                 "VALUES(?,'P','owner','build','IMPLEMENT','hash','PENDING',?,?,?,?)",
                (tid, reason, now, now, now))
        db.event("JEV_CONTEXT_GATE_BLOCKED", task_id="jev-countdown", reason="required context not selected")
        self.assertEqual(control.release_jev_backoff(db), 2)
        self.assertIsNone(db.task("jev-task")["not_before"])
        self.assertIsNone(db.task("jev-countdown")["not_before"])
        self.assertIsNotNone(db.task("other-task")["not_before"])
        self.assertEqual(db.one("SELECT event FROM event_log WHERE event='JEV_BACKOFF_RELEASED'")["event"],
                         "JEV_BACKOFF_RELEASED")

    def test_dashboard_never_renders_typesafe_key(self):
        cfg = self.cfg(True)
        old = os.environ.get("TYPESAFE_API_KEY")
        os.environ["TYPESAFE_API_KEY"] = "test-secret-that-must-not-render"
        try:
            page = Dashboard(cfg).page_delivers(None)
        finally:
            if old is None:
                os.environ.pop("TYPESAFE_API_KEY", None)
            else:
                os.environ["TYPESAFE_API_KEY"] = old
        self.assertIn("type='password'", page)
        self.assertIn("שמור ב־environment", page)
        self.assertIn("id='arcsMode'", page)
        self.assertIn("id='catalogMode'", page)
        self.assertIn(".deliver-tile{", page)
        self.assertIn("מרכז השליטה של ה־Delivers", page)
        self.assertNotIn("test-secret-that-must-not-render", page)

    def test_task_manager_context_grants_and_dependencies_are_real(self):
        cfg = self.cfg(True); db = DB(":memory:"); now = iso(utcnow())
        for tid in ("build.a", "build.b"):
            db.x("INSERT INTO tasks(task_id,packet,owner,mode,model_profile,definition_hash,state,created_at,updated_at) "
                 "VALUES(?, 'P', 'owner', 'build', 'IMPLEMENT', 'hash', 'PENDING', ?, ?)", (tid, now, now))
        db.x("INSERT INTO context_sources(source_key,origin_kind,origin_ref,title,excerpt,content_sha256,tags_json,active,created_at,updated_at) "
             "VALUES('graph.weather','graph','node:weather','מזג אוויר','winter evidence','hash','[]',1,?,?)", (now, now))
        dash = Dashboard(cfg); dash.db = db
        self.assertIn("נוספה", dash.action({"action": "bind_task_context", "task_id": "build.a",
                                              "source_key": "graph.weather"}))
        self.assertEqual(db.one("SELECT active FROM task_context_bindings WHERE task_id='build.a'")["active"], 1)
        self.assertIn("נוספה", dash.action({"action": "add_task_dependency", "task_id": "build.a",
                                              "depends_on": "build.b"}))
        self.assertEqual(db.deps("build.a"), ["build.b"])
        page = dash.page_task("build.a", None)
        self.assertIn("גישה לקונטקסט דרך Jev", page)
        self.assertIn("בקש מהמודל לשנות את המשימה", page)
        self.assertIn("graph.weather", page)

    def test_mcp_exposes_every_new_task_control(self):
        names = {tool["name"] for tool in TOOLS}
        self.assertTrue({"task_dependency_add", "task_model_set", "task_context_access",
                         "deliver_model_set", "deliver_graph_access_set", "rag_graph_query",
                         "graph_query_console",
                         "rag_graph_status", "rag_graph_configure", "scoped_change_request",
                         "context_planned_task_create", "system_repair_task_create",
                         "subtask_create", "subtask_patterns", "subtask_promote",
                         "deterministic_run_record", "listener_activation_update",
                         "auto_approval_mode"}.issubset(names))
        cfg = self.cfg(True); db = DB(":memory:"); now = iso(utcnow())
        for tid in ("build.a", "build.b"):
            db.x("INSERT INTO tasks(task_id,packet,owner,mode,model_profile,definition_hash,state,created_at,updated_at) "
                 "VALUES(?, 'P', 'owner', 'build', 'IMPLEMENT', 'hash', 'PENDING', ?, ?)", (tid, now, now))
        db.x("INSERT INTO context_sources(source_key,origin_kind,origin_ref,title,excerpt,content_sha256,tags_json,active,created_at,updated_at) "
             "VALUES('graph.weather','graph','node:weather','weather','winter evidence','hash','[]',1,?,?)", (now, now))
        dash = Dashboard(cfg); dash.db = db
        server = Server.__new__(Server); server.dashboard = dash
        result = server.call("task_context_access", {"task_id": "build.a", "source_key": "graph.weather", "active": True})
        self.assertIn("Jev", result["result"])
        server.call("task_dependency_add", {"task_id": "build.a", "depends_on": "build.b"})
        self.assertEqual(db.deps("build.a"), ["build.b"])
        server.call("auto_approval_mode", {"enabled": True})
        self.assertEqual(db.get_flag("review_auto_approve_all"), "1")
        context_plan = server.call("context_planned_task_create", {
            "title": "plan weather context", "instructions": "inspect evidence",
            "context_request": "historical snow and terrain", "worker_model_key": "sol",
            "write_scope": [], "read_only": True})
        self.assertEqual(context_plan["status"], "context_planning")
        self.assertTrue(context_plan["worker_contract_locked"])
        self.assertEqual(json.loads(db.task(context_plan["task_id"])["extra"])["context_request"],
                         "historical snow and terrain")
        sub = server.call("subtask_create", {"parent_task_id": "build.a", "title": "inspect snow",
                                               "instructions": "inspect only the selected snow evidence",
                                               "model_key": "sol", "write_scope": [], "read_only": True,
                                               "context_files": [], "reference_files": [], "mcp_servers": [],
                                               "tool_names": ["Read"], "acceptance_commands": []})
        self.assertFalse(sub["deliver_created"])
        self.assertEqual(json.loads(db.task(sub["task_id"])["extra"])["allowed_tools"], ["Read"])
        self.assertEqual(server.call("subtask_patterns", {})["patterns"][0]["reuse_count"], 1)
        db.x("INSERT INTO deliver_catalog(deliver_id,description,source_kind,execution_kind,availability,enabled,updated_at) "
             "VALUES('catalog.research','research','test','llm_research','available',1,?)", (now,))
        dash.graph_rag = GraphRagService(cfg, db, transport=lambda *_: {"ok": True})
        server.call("deliver_model_set", {"deliver_id": "catalog.research", "model_key": "sonnet"})
        self.assertEqual(db.one("SELECT preferred_model_key FROM deliver_catalog WHERE deliver_id='catalog.research'")["preferred_model_key"],
                         "sonnet")
        self.assertIn("מודל קבוע ל־Deliver", dash.page_deliver("catalog.research", None))
        server.call("deliver_graph_access_set", {"deliver_id": "catalog.research", "access_mode": "limited",
                                                  "scope_text": "snow", "max_chunks": 3, "max_chars": 2000})
        self.assertEqual(db.one("SELECT access_mode FROM deliver_graph_access WHERE deliver_id='catalog.research'")["access_mode"],
                         "limited")

    def test_runtime_observability_persists_deterministic_runs_context_and_listener_state(self):
        cfg = self.cfg(True); db = DB(":memory:"); self.seed(db); now = iso(utcnow())
        db.x("INSERT INTO context_sources(source_key,deliver_id,origin_kind,origin_ref,title,excerpt,content_sha256,tags_json,active,created_at,updated_at) "
             "VALUES('det.ctx','episode.context_scan','test','node:1','context','1234567890','hash','[]',1,?,?)",
             (now, now))
        dash = Dashboard(cfg); dash.db = db
        server = Server.__new__(Server); server.dashboard = dash
        recorded = server.call("deterministic_run_record", {
            "deliver_id": "episode.context_scan", "status": "RUNNING", "input_bytes": 12,
            "output_bytes": 4, "detail": {"step": "scan"}})
        self.assertTrue(recorded["persisted"])
        self.assertEqual(recorded["cost_usd"], 0)
        page = dash.page_delivers(None)
        self.assertIn("שכבת קונטקסט רשומה", page)
        self.assertIn("Delivers דטרמיניסטיים", page)
        self.assertIn("10 B", page)
        light = dash.page_deliver("episode.context_scan", None)
        self.assertIn("חוזה קל ושמור", light)
        self.assertIn("עלות מודל $0", light)
        self.assertNotIn("מודל קבוע ל־Deliver", light)

        service = JevService(cfg, db, client=JevClient(transport=choice_first))
        ListenerEngine(cfg, db, service).emit(
            episode_id="e1", source_deliver_id="episode.context_scan", event_type="CONTEXT_SCANNED",
            episode_patch={"possible_snow": True})
        activation = db.one("SELECT activation_id FROM listener_activations")
        changed = server.call("listener_activation_update", {
            "activation_id": activation["activation_id"], "status": "RUNNING"})
        self.assertEqual(changed["status"], "RUNNING")
        self.assertEqual(db.one("SELECT status FROM listener_activations")["status"], "RUNNING")
        self.assertIn("Listeners שנבחרו או רצים בפועל", dash.page_delivers(None))

    def test_graph_rag_access_is_bounded_and_jev_gated(self):
        cfg = self.cfg(True); db = DB(":memory:"); self.seed(db)
        requests = []

        def transport(method, path, payload, timeout):
            requests.append((method, path, payload))
            if path == "/health":
                return {"ok": True, "model": "nomic-embed-text", "neo4j": "local"}
            if path == "/entities/stats":
                return {"ok": True, "nodeCount": 1337, "relCount": 1541, "insightCount": 50}
            return {"ok": True, "context": "snow depth and frozen roads\n\nunrelated tank factory",
                    "used_entity_names": ["snow", "roads"]}

        rag = GraphRagService(cfg, db, transport=transport)
        rag.save_access("weather.snow_research", "limited", "snow", 2, 2000)
        candidates = rag.retrieve_candidates("weather.snow_research", "what happened")
        self.assertEqual(len(candidates), 1)
        self.assertIn("snow depth", candidates[0]["excerpt"])
        self.assertFalse(requests[-1][2]["use_cypher"])

        class Jev:
            def select_context_bundles(self, task_id, items, objective):
                return [items[0]["id"]]

        selected = rag.selected_query(Jev(), "weather.snow_research", "snow conditions")
        self.assertEqual(selected["gate"], "jev")
        self.assertEqual(len(selected["selected"]), 1)
        self.assertEqual(rag.health()["nodes"], 1337)

    def test_graph_console_runs_bounded_read_only_cypher_and_natural_query(self):
        cfg = self.cfg(True); db = DB(":memory:"); self.seed(db)
        cypher_calls = []

        def rag_transport(method, path, payload, timeout):
            if path == "/pipeline/query":
                return {"ok": True, "context": "winter evidence", "cypher": "MATCH (n) RETURN n LIMIT 1",
                        "elapsed_ms": 3, "used_entity_names": ["winter"]}
            if path == "/health":
                return {"ok": True, "model": "local-test", "neo4j": "local"}
            return {"ok": True, "nodeCount": 1, "relCount": 2}

        def cypher_transport(method, path, payload, timeout):
            cypher_calls.append(payload)
            return {"ok": True, "columns": ["count"], "rows": [{"count": 7}], "count": 1,
                    "truncated": False}

        dash = Dashboard(cfg); dash.db = db
        dash.graph_rag = GraphRagService(cfg, db, transport=rag_transport, cypher_transport=cypher_transport)
        direct = dash.run_graph_console_query("cypher", "MATCH (n) RETURN count(n) AS count", max_rows=25)
        self.assertEqual(direct["status"], "READY")
        self.assertEqual(cypher_calls[0]["max_rows"], 25)
        with self.assertRaises(ValueError):
            dash.run_graph_console_query("cypher", "MATCH (n) DELETE n RETURN count(n)")
        natural = dash.run_graph_console_query("natural", "מה ידוע על החורף?", "local")
        self.assertEqual(natural["status"], "READY")
        page = dash.page_graph_rag(None)
        self.assertIn("winter evidence", page)
        self.assertIn("MATCH (n) RETURN n LIMIT 1", page)
