"""The live app's remaining pages (task 4): app_data JSON builders, the new read-only endpoints, the JSON answer of the
multipart POST, the task:<id>/rag/plan/subtasks topics and the client sources.

Every row written here is a synthetic fixture.
"""
from __future__ import annotations

import http.client
import inspect
import json
import re
import sqlite3
import unittest
from pathlib import Path

from helpers import FakeEnv  # noqa: F401  (imported so the shared path setup runs first)
from test_app_shell import AppServerCase
from test_ws_live import LiveCase

from wwii_build import app_data, live
from wwii_build.dashboard import APP_DIR, Dashboard

NOW = "2026-01-01T00:00:00+00:00"


def add_task(conn, task_id: str, state: str = "READY", kind: str = "task", extra: str | None = None, wave: int = 1) -> None:
    conn.execute("INSERT INTO tasks(task_id,packet,owner,mode,model_profile,definition_hash,created_at,updated_at,state,wave,kind,extra) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (task_id, task_id.split("/")[0], "o", "build", "IMPLEMENT", "h", NOW, NOW, state, wave, kind, extra or "{}"))


def add_deliver(conn, deliver_id: str, packet: str | None = None) -> None:
    conn.execute("INSERT INTO deliver_catalog(deliver_id,owner,domain,description,source_kind,source_ref,execution_kind,definition_hash,"
                 "enabled,availability,updated_at) VALUES(?,?,?,?,?,?,?,?,1,'available',?)",
                 (deliver_id, "o", "d", "תיאור", "system_manifest" if packet else "dashboard", "ref", "worker", "h", NOW))


class DataCase(AppServerCase):
    def setUp(self):
        super().setUp()
        self.other = sqlite3.connect(str(self.dash.db.path), timeout=10, isolation_level=None)

    def tearDown(self):
        self.other.close()
        super().tearDown()

    def get_json(self, path: str, headers: dict | None = None):
        status, _, body = self.request(path, headers=headers)
        return status, (json.loads(body) if status == 200 else body)


class ConsoleResult(unittest.TestCase):
    def test_error_table_answer_and_empty(self):
        self.assertEqual(app_data._console_result({"error": "נחסם"}, {}), {"kind": "error", "text": "נחסם"})
        table = app_data._console_result({"mode": "cypher"}, {"columns": ["n", "m"], "rows": [{"n": 1, "m": "x"}, {"n": None}]})
        self.assertEqual(table["kind"], "table")
        self.assertEqual(table["columns"], ["n", "m"])
        self.assertEqual(table["rows"], [["1", '"x"'], ["null", "null"]])
        self.assertEqual(table["total"], 2)
        inferred = app_data._console_result({"mode": "cypher"}, {"rows": [{"a": 1}]})
        self.assertEqual(inferred["columns"], ["a"])
        long_cell = app_data._console_result({"mode": "cypher"}, {"columns": ["a"], "rows": [{"a": "x" * 9000}]})
        self.assertLessEqual(len(long_cell["rows"][0][0]), app_data.CELL_MAX_CHARS)
        many = app_data._console_result({"mode": "cypher"}, {"columns": ["a"], "rows": [{"a": i} for i in range(500)]})
        self.assertEqual((len(many["rows"]), many["total"]), (app_data.RESULT_MAX_ROWS, 500))
        answer = app_data._console_result({"mode": "natural"}, {"summary": "42", "used_entity_names": ["x"], "evidence_source_ids": [3]})
        self.assertEqual(answer, {"kind": "answer", "text": "42", "entities": ["x"], "evidence_ids": ["3"]})
        self.assertEqual(app_data._console_result({"mode": "natural"}, {}), {"kind": "empty"})

    def test_valid_id(self):
        for good in ("A/1", "MANUAL/ws-4-all-pages", "weather.snow_research", "a:b@c"):
            self.assertTrue(app_data.valid_id(good), good)
        for bad in ("", "a b", "x;y", "a\nb", "a" * 201, "<script>"):
            self.assertFalse(app_data.valid_id(bad), bad)


class Builders(DataCase):
    def test_capability_counts_and_shelf_titles(self):
        add_deliver(self.other, "sys.a", packet="atlas")
        for group, name in (("g1", "f1"), ("g1", "f2"), ("g2", "f3")):
            self.other.execute("INSERT INTO deliver_capabilities(capability_id,deliver_id,group_name,name,kind,updated_at) VALUES(?,?,?,?,'files',?)",
                               (f"sys.a/{group}/{name}", "sys.a", group, name, NOW))
        self.other.execute("INSERT INTO deliver_capabilities(capability_id,deliver_id,group_name,name,kind,active,updated_at) "
                           "VALUES('sys.a/g3/old','sys.a','g3','old','files',0,?)", (NOW,))
        self.assertEqual(app_data.capability_counts(self.dash), {"sys.a": (2, 3)})            # inactive rows are not counted
        self.dash.db.set_flag("onboarding_title:atlas", "אטלס")
        delivers = [{"packet": "atlas", "source_kind": "system_manifest"}, {"packet": "other", "source_kind": "system_manifest"},
                    {"packet": "x", "source_kind": "dashboard"}]
        self.assertEqual(app_data.shelf_titles(self.dash, delivers), {"atlas": "אטלס", "other": "other"})

    def test_task_detail_unknown_and_known(self):
        self.assertEqual(app_data.task_detail(self.dash, "nope"), ([], {"exists": False, "task_id": "nope"}))
        add_task(self.other, "A/0", "PASSED", wave=0)
        add_task(self.other, "A/1")
        self.other.execute("INSERT INTO task_dependencies(task_id,depends_on) VALUES('A/1','A/0')")
        self.other.execute("INSERT INTO approvals(kind,subject,status,task_id,reason,created_at) VALUES('review','A/1','pending','A/1','סיבה',?)", (NOW,))
        self.other.execute("INSERT INTO approvals(kind,subject,status,task_id,reason,created_at) VALUES('review','A/1','approved','A/1','old',?)", (NOW,))
        attempts, meta = app_data.task_detail(self.dash, "A/1")
        self.assertEqual(attempts, [])
        self.assertTrue(meta["exists"])
        self.assertEqual((meta["task"]["state"], meta["task"]["write_scope"]), ("READY", []))
        self.assertEqual(meta["deps"], [{"task_id": "A/0", "state": "PASSED"}])
        self.assertEqual([t["task_id"] for t in meta["task_options"]], ["A/0"])            # the task itself is not a dependency option
        self.assertEqual([(a["kind"], a["reason"]) for a in meta["approvals"]], [("review", "סיבה")])   # pending only
        self.assertIsNone(meta["chain"])
        self.assertEqual(meta["lineage"], {"parents": [], "children": []})
        self.assertFalse(meta["is_deliver"])
        self.assertIsNone(meta["graph_access"])
        self.assertEqual((meta["artifacts"], meta["tests"], meta["context_pack"], meta["brief"]), ([], [], None, ""))
        self.assertEqual(sorted(meta["models"]), sorted(self.dash.cfg.data["models"]))
        json.dumps(meta, default=str)                                                       # JSON-able as sent over the socket

    def test_task_detail_attempts_artifacts_tests_and_repair_chain(self):
        add_task(self.other, "A/1", "FAILED")
        self.other.execute("UPDATE tasks SET repairs_count=1,failure_class='TEST_FAILED' WHERE task_id='A/1'")
        add_task(self.other, "REPAIR/A/1/1", "PASSED", kind="repair")
        self.other.execute("UPDATE tasks SET parent_task_id='A/1',repair_no=1,failure_class='TEST_FAILED',failure_summary='תוקן' WHERE task_id='REPAIR/A/1/1'")
        self.other.execute("INSERT INTO task_attempts(task_id,kind,attempt_no,provider,model_key,model,effort,status,started_at,input_tokens,reported_cost_usd) "
                           "VALUES('A/1','execute',1,'codex','codex','gpt-x','high','FAILED',?,5,NULL)", (NOW,))
        self.other.execute("INSERT INTO artifacts(task_id,kind,path,source_path,description,created_at) VALUES('A/1','screenshot','/tmp/x.png','x.png','צילום',?)", (NOW,))
        self.other.execute("INSERT INTO test_results(task_id,name,kind,passed,exit_code,output_tail,created_at) VALUES('A/1','unit','command',0,1,'boom',?)", (NOW,))
        attempts, meta = app_data.task_detail(self.dash, "A/1")
        self.assertEqual(len(attempts), 1)
        self.assertEqual((attempts[0]["input_tokens"], attempts[0]["cached_input_tokens"], attempts[0]["reported_cost_usd"]), (5, None, None))   # unknown stays null
        self.assertEqual([(a["media"], a["kind"]) for a in meta["artifacts"]], [("image", "screenshot")])
        self.assertEqual([(t["name"], t["passed"], t["output_tail"]) for t in meta["tests"]], [("unit", False, "boom")])
        chain = meta["chain"]
        self.assertEqual((chain["role"], chain["repairs_count"]), ("parent", 1))
        self.assertEqual([s["type"] for s in chain["steps"]], ["execute", "repair"])
        self.assertEqual(chain["steps"][1]["task_id"], "REPAIR/A/1/1")
        _, repair_meta = app_data.task_detail(self.dash, "REPAIR/A/1/1")
        self.assertEqual((repair_meta["chain"]["role"], repair_meta["chain"]["parent_task_id"], repair_meta["chain"]["parent_state"]), ("repair", "A/1", "FAILED"))

    def test_task_detail_deliver_and_system_task(self):
        add_task(self.other, "D/1", extra=json.dumps({"system_task": True, "context_request": " ידע ", "evidence": ["a.md"]}))
        add_deliver(self.other, "D/1")
        _, meta = app_data.task_detail(self.dash, "D/1")
        self.assertTrue(meta["is_deliver"])
        self.assertEqual(meta["graph_access"]["access_mode"], "none")
        self.assertEqual(meta["system"], {"status": None, "changed_count": 0})
        self.assertEqual((meta["context_request"], meta["planned_files"]), ("ידע", ["a.md"]))

    def test_task_diff_without_worktree_is_empty_and_unknown_task_says_so(self):
        add_task(self.other, "A/1")
        self.assertEqual(app_data.task_diff(self.dash, "A/1"), {"exists": True, "files": [], "diff": ""})
        self.assertEqual(app_data.task_diff(self.dash, "nope"), {"exists": False, "files": [], "diff": ""})

    def test_rag_items_and_meta(self):
        add_task(self.other, "PLAN/1", "RUNNING", kind="plan")
        self.other.execute("INSERT INTO graph_console_queries(created_at,updated_at,mode,query_text,model_key,status,result_json,elapsed_ms,input_tokens) "
                           "VALUES(?,?,'cypher','MATCH (n) RETURN n','local','READY',?,7,3)",
                           (NOW, NOW, json.dumps({"columns": ["n"], "rows": [{"n": 1}], "cypher": "MATCH (n) RETURN n"})))
        self.other.execute("INSERT INTO graph_console_queries(created_at,updated_at,mode,query_text,status,error) VALUES(?,?,'natural','שאלה','FAILED','נכשל')", (NOW, NOW))
        self.other.execute("INSERT INTO graph_console_queries(created_at,updated_at,mode,query_text,task_id,status) VALUES(?,?,'natural','ישן','PLAN/1','QUEUED')", (NOW, NOW))
        items = {i["query_text"]: i for i in app_data.rag_items(self.dash)}
        self.assertEqual(items["MATCH (n) RETURN n"]["result"]["kind"], "table")
        self.assertEqual(items["MATCH (n) RETURN n"]["tokens"], [3, 0, 0])
        self.assertEqual(items["MATCH (n) RETURN n"]["generated_cypher"], "MATCH (n) RETURN n")
        self.assertEqual(items["שאלה"]["result"], {"kind": "error", "text": "נכשל"})
        self.assertEqual(items["ישן"]["status"], "RUNNING")                                  # a queued query shows its task's state
        add_deliver(self.other, "weather.x")
        self.other.execute("INSERT INTO deliver_graph_access(deliver_id,access_mode,scope_text,max_chunks,max_chars,updated_at) VALUES('weather.x','limited','טנקים',9,9000,?)", (NOW,))
        meta = app_data.rag_meta(self.dash)
        self.assertEqual([(a["deliver_id"], a["access_mode"], a["max_chunks"]) for a in meta["access"]], [("weather.x", "limited", 9)])
        self.assertEqual(meta["graph_rag_url"], "")                                        # nothing configured by default
        self.assertIn("models", meta)

    def test_plan_items_with_proposal_and_attachment(self):
        add_task(self.other, "PLAN/1", "PASSED", kind="plan", extra=json.dumps({"prompt": "תכנן"}))
        proposal = {"summary": "הצעה", "questions": ["מה?"], "tasks": [{"key": "k", "title": "t", "instructions": "x" * 400, "write_scope": ["a/"], "read_only": True}]}
        self.other.execute("INSERT INTO plan_proposals(plan_task_id,created_at,status,request,proposal,validation) VALUES('PLAN/1',?,'pending','r',?,?)",
                           (NOW, json.dumps(proposal), json.dumps([{"level": "error", "key": "k", "message": "חסר"}])))
        pid = self.other.execute("SELECT id FROM plan_proposals").fetchone()[0]
        self.other.execute("INSERT INTO approvals(kind,subject,status,created_at) VALUES('plan_proposal',?,'pending',?)", (str(pid), NOW))
        self.other.execute("INSERT INTO planner_attachments(plan_task_id,original_name,stored_path,media_type,kind,size_bytes,sha256,created_at) "
                           "VALUES('PLAN/1','m.png','/x','image/png','image',2048,'s',?)", (NOW,))
        (plan,) = app_data.plan_items(self.dash)
        self.assertEqual((plan["task_id"], plan["prompt"]), ("PLAN/1", "תכנן"))
        self.assertEqual([(a["name"], a["selected"]) for a in plan["attachments"]], [("m.png", False)])
        (p,) = plan["proposals"]
        self.assertEqual((p["summary"], p["questions"], p["status"]), ("הצעה", ["מה?"], "pending"))
        self.assertIsNotNone(p["approval_id"])
        self.assertEqual(len(p["tasks"][0]["instructions"]), 300)                              # long instructions are cut for the list
        self.assertTrue(p["tasks"][0]["read_only"])
        self.assertEqual(p["validation"][0]["message"], "חסר")

    def test_subtask_items_and_meta(self):
        add_task(self.other, "P/1")
        h = "a" * 64
        self.other.execute("INSERT INTO subtask_patterns(pattern_hash,title,spec_json,reuse_count,promotion_status,first_seen_at,last_seen_at) "
                           "VALUES(?,?,?,3,'eligible',?,?)", (h, "בדיקת יחידה", json.dumps({"instructions": "הרץ"}), NOW, NOW))
        self.other.execute("INSERT INTO subtask_occurrences(pattern_hash,parent_task_id,child_task_id,source,created_at) VALUES(?,'P/1',NULL,'dashboard',?)", (h, NOW))
        (item,) = app_data.subtask_items(self.dash)
        self.assertEqual((item["pattern_hash"], item["promotion_status"], item["spec"]), (h, "eligible", {"instructions": "הרץ"}))
        self.assertTrue(item["suggestion"].startswith("reusable."))
        self.assertEqual(item["occurrences"][0]["parent_task_id"], "P/1")
        meta = app_data.subtask_meta(self.dash)
        self.assertEqual([p["task_id"] for p in meta["parents"]], ["P/1"])
        self.assertGreater(meta["default_threshold"], 0)

    def test_event_facets_and_new_task_options(self):
        base = app_data.event_facets(self.dash)
        for event, task, provider in (("ZZ_A", "T/1", "zz_codex"), ("ZZ_B", None, None), ("ZZ_A", "T/2", "zz_claude")):
            self.other.execute("INSERT INTO event_log(at,event,task_id,provider) VALUES(?,?,?,?)", (NOW, event, task, provider))
        facets = app_data.event_facets(self.dash)
        self.assertEqual(facets["total"], base["total"] + 3)
        self.assertEqual(facets["type_count"], base["type_count"] + 2)
        self.assertEqual(facets["task_count"], base["task_count"] + 2)
        self.assertEqual([t for t in facets["types"] if t.startswith("ZZ_")], ["ZZ_A", "ZZ_B"])
        self.assertEqual([p for p in facets["providers"] if p.startswith("zz_")], ["zz_claude", "zz_codex"])
        self.assertEqual(facets["latest"]["id"], self.other.execute("SELECT MAX(id) FROM event_log").fetchone()[0])
        options = app_data.new_task_options(self.dash)
        self.assertEqual(sorted(options), ["context_files", "mcp", "models", "owners", "planner_max_chars", "planner_max_chunks"])
        self.assertIsInstance(options["owners"], list)
        self.assertGreater(options["planner_max_chunks"], 0)


class Endpoints(DataCase):
    def test_json_endpoints(self):
        self.dash.graph_rag.health = lambda: {"status": "UNREACHABLE", "url": "http://127.0.0.1:1", "reachable": False, "model": None,
                                              "nodes": None, "relationships": None, "insights": None, "latency_ms": 0, "detail": "synthetic"}
        add_task(self.other, "A/1")
        status, options = self.get_json("/api/new-task-options")
        self.assertEqual(status, 200)
        self.assertIn("owners", options)
        status, facets = self.get_json("/api/events/facets")
        self.assertEqual((status, facets["total"]), (200, self.dash.db.event_count()))
        status, health = self.get_json("/api/rag/health")
        self.assertEqual((status, health["status"], health["nodes"]), (200, "UNREACHABLE", None))
        status, diff = self.get_json("/api/task/diff?id=A%2F1")
        self.assertEqual((status, diff), (200, {"exists": True, "files": [], "diff": ""}))
        self.assertEqual(self.get_json("/api/task/diff?id=missing")[1]["exists"], False)

    def test_task_diff_refuses_bad_ids(self):
        for path in ("/api/task/diff", "/api/task/diff?id=", "/api/task/diff?id=a%20b", "/api/task/diff?id=a%3Bb",
                     "/api/task/diff?id=" + "a" * 201):
            status, body = self.get_json(path)
            self.assertEqual(status, 400, path)
            self.assertIn(b"invalid task id", body)

    def test_new_endpoints_are_localhost_only(self):
        for path in ("/api/new-task-options", "/api/events/facets", "/api/rag/health", "/api/task/diff?id=A"):
            self.assertEqual(self.request(path, headers={"Host": "evil.example"})[0], 403, path)

    def test_every_page_module_is_served(self):
        for name in ("task", "events", "rag", "plan", "new", "subtasks", "delivers", "deliver"):
            status, headers, body = self.request(f"/app/pages/{name}.js")
            self.assertEqual(status, 200, name)
            self.assertTrue(headers["content-type"].startswith("text/javascript"), name)
            self.assertEqual(body, (APP_DIR / "pages" / f"{name}.js").read_bytes())
        self.assertEqual(self.request("/app/subtask_form.js")[0], 200)


class JsonAnswerOfPosts(DataCase):
    """The planner upload stays a multipart POST; with Accept: application/json it answers {ok, message} instead of a redirect."""

    def post(self, fields: dict, files: list[tuple[str, bytes]] = (), token: str | None = None, json_answer: bool = True, host: str | None = None):
        boundary = "----synthetic-boundary"
        parts = []
        for name, value in {"token": self.dash.token if token is None else token, **fields}.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for filename, data in files:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="planner_files"; filename="{filename}"\r\n'
                         f'Content-Type: text/plain\r\n\r\n'.encode() + data + b"\r\n")
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if json_answer:
            headers["Accept"] = "application/json"
        if host:
            headers["Host"] = host
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", "/action", body=body, headers=headers)
            res = conn.getresponse()
            return res.status, {k.lower(): v for k, v in res.getheaders()}, res.read()
        finally:
            conn.close()

    def test_action_answers_json_for_the_app(self):
        status, headers, body = self.post({"action": "state_chat_new"})
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("application/json"))
        answer = json.loads(body)
        self.assertEqual(answer["ok"], True)
        self.assertEqual(self.dash.db.get_flag("state_chat_new"), "1")

    def test_errors_are_ok_false_not_a_server_error(self):
        status, _, body = self.post({"action": "no_such_action"})
        self.assertEqual(status, 200)
        answer = json.loads(body)
        self.assertEqual(answer["ok"], False)
        self.assertIn("unknown action", answer["message"])

    def test_token_and_host_are_still_enforced(self):
        self.assertEqual(self.post({"action": "state_chat_new"}, token="wrong")[0], 403)
        self.assertEqual(self.post({"action": "state_chat_new"}, token="")[0], 403)
        self.assertEqual(self.post({"action": "state_chat_new"}, host="evil.example")[0], 403)
        self.assertIsNone(self.dash.db.get_flag("state_chat_new"))

    def test_without_accept_the_post_still_redirects_to_the_classic_page(self):
        status, headers, _ = self.post({"action": "state_chat_new", "back": "/plan"}, json_answer=False)
        self.assertEqual(status, 303)
        self.assertTrue(headers["location"].startswith("/classic/plan?msg="), headers["location"])

    def test_upload_limits_are_answered_as_errors(self):
        files = [(f"f{i}.txt", b"x") for i in range(9)]
        status, _, body = self.post({"action": "plan", "prompt": "p"}, files=files)
        self.assertEqual(status, 400)
        self.assertIn("8".encode(), body)


class NewTopics(LiveCase):
    def test_parse_topic_accepts_task_ids_and_the_new_static_topics(self):
        self.assertEqual(live.parse_topic("task:MANUAL/ws-4"), ("task", "MANUAL/ws-4"))
        for name in ("rag", "plan", "subtasks"):
            self.assertEqual(live.parse_topic(name), (name, ""))
        for bad in ("task:", "task:bad id", "task:" + "a" * 201, "tasks:x", "rag:x", "plan:1"):
            self.assertIsNone(live.parse_topic(bad), bad)

    def test_snapshots_of_rag_plan_and_subtasks(self):
        c = self.client("rag", "plan", "subtasks", timeout=5.0)
        got = self.snapshots(c, 3)
        self.assertEqual([got[t]["data"]["key"] for t in ("rag", "plan", "subtasks")], ["id", "task_id", "pattern_hash"])
        self.assertEqual(got["rag"]["data"]["items"], [])
        self.assertIn("access", got["rag"]["data"]["meta"])
        self.assertIn("models", got["plan"]["data"]["meta"])
        self.assertGreater(got["subtasks"]["data"]["meta"]["default_threshold"], 0)

    def test_task_topic_snapshot_and_patch(self):
        add_task(self.other, "A/1", "READY")
        c = self.client("task:A/1", "task:missing", timeout=5.0)
        got = self.snapshots(c, 2)
        self.assertTrue(got["task:A/1"]["data"]["meta"]["exists"])
        self.assertEqual(got["task:A/1"]["data"]["key"], "id")
        self.assertEqual(got["task:missing"]["data"]["meta"], {"exists": False, "task_id": "missing"})
        self.other.execute("UPDATE tasks SET state='FAILED' WHERE task_id='A/1'")
        patch = c.recv_json()
        self.assertEqual((patch["type"], patch["topic"]), ("patch", "task:A/1"))
        self.assertEqual(patch["meta"]["task"]["state"], "FAILED")
        self.other.execute("INSERT INTO task_attempts(task_id,kind,attempt_no,provider,model_key,model,effort,status,started_at) "
                           "VALUES('A/1','execute',1,'codex','codex','gpt-x','high','RUNNING',?)", (NOW,))
        patch = c.recv_json()
        self.assertEqual([a["status"] for a in patch["upsert"]], ["RUNNING"])

    def test_rag_topic_follows_a_new_console_query(self):
        c = self.client("rag", timeout=5.0)
        self.snapshots(c, 1)
        self.other.execute("INSERT INTO graph_console_queries(created_at,updated_at,mode,query_text,status,result_json) "
                           "VALUES(?,?,'cypher','MATCH (n) RETURN n','READY',?)", (NOW, NOW, json.dumps({"columns": ["n"], "rows": [{"n": 1}]})))
        patch = c.recv_json()
        self.assertEqual(patch["topic"], "rag")
        self.assertEqual([(i["query_text"], i["result"]["kind"]) for i in patch["upsert"]], [("MATCH (n) RETURN n", "table")])

    def test_forms_of_the_new_pages_run_through_the_same_actions_over_the_socket(self):
        c = self.client(timeout=5.0)
        c.send_json({"type": "action", "id": "a1", "name": "create_subtask", "args": {"parent_task_id": "nope", "title": "t", "instructions": "i"}})
        result = c.recv_json()
        self.assertEqual((result["type"], result["id"], result["ok"]), ("action.result", "a1", False))
        c.send_json({"type": "action", "id": "a2", "name": "graph_console_query", "args": {"query_mode": "cypher", "query": "MATCH (n) DELETE n", "max_rows": "5"}})
        result = c.recv_json()
        while result.get("type") == "progress":                                                # progress lines come before the result
            result = c.recv_json()
        self.assertEqual((result["id"], result["ok"]), ("a2", False))                          # a write query is blocked before running


class ClientSources(unittest.TestCase):
    JS = sorted(APP_DIR.rglob("*.js"))

    def test_router_pages_exist_and_nav_points_at_pages(self):
        router = (APP_DIR / "router.js").read_text(encoding="utf-8")
        pages = dict(re.findall(r"(\w+): \(\) => import\('\./pages/(\w+)\.js'\)", router))
        self.assertEqual(set(pages), {"overview", "tasks", "delivers", "deliver", "task", "events", "rag", "plan", "new", "battle", "subtasks"})
        for route, module in pages.items():
            self.assertTrue((APP_DIR / "pages" / f"{module}.js").is_file(), route)
        nav = re.findall(r"^\s*\['(\w+)', '[^']+', \[[^\]]*\]\],?$", router, flags=re.M)
        self.assertEqual(nav, ["overview", "tasks", "delivers", "subtasks", "rag", "new", "battle", "plan", "events"])
        self.assertTrue(set(nav) <= set(pages))

    def test_only_the_pages_without_an_app_version_link_to_classic(self):
        # the review page and the classic overview extras (artifacts, capability gaps, model watch) are not in this task's page list
        for js in self.JS:
            for url in re.findall(r"/classic/[^'\"`)\s]*", js.read_text(encoding="utf-8")):
                self.assertTrue(url == "/classic/" or url.startswith("/classic/review?id="), f"{js.name}: {url}")
        nav_js = (APP_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("/classic/", nav_js)

    def test_every_action_the_app_sends_exists_in_dashboard_action(self):
        source = inspect.getsource(Dashboard.action) + inspect.getsource(Dashboard.run_form)
        names = set()
        for js in self.JS:
            text = js.read_text(encoding="utf-8")
            names |= set(re.findall(r"new Form\(ctx, '(\w+)'", text))
            names |= set(re.findall(r"actionButton\(ctx, [^,]+, [^,]+, '(\w+)'", text))
            names |= set(re.findall(r"\bact\('(\w+)'", text))
            names |= set(re.findall(r"ctx\.(?:act|upload)\('(\w+)'", text))
        self.assertTrue({"add_task", "plan", "scoped_plan", "retry", "skip", "recheck", "set_provider", "expedite", "create_subtask",
                         "promote_subtask", "graph_console_query", "save_graph_rag_config", "graph_rag_health", "approve", "reject",
                         "add_task_dependency", "bind_task_context", "toggle_task_context", "add_context", "save_deliver_graph_access"} <= names, sorted(names))
        for name in sorted(names):
            self.assertTrue(f'"{name}"' in source, f"the app sends '{name}' but Dashboard.action does not handle it")

    def test_form_field_names_match_what_the_handlers_read(self):
        """The fields of the forms the handlers parse by name (a typo here silently drops an input)."""
        new_page = (APP_DIR / "pages" / "new.js").read_text(encoding="utf-8")
        for field in ("task_target", "title", "description_he", "name", "instructions", "model_key", "fallback", "owner", "deps", "write_scope",
                      "read_only", "ctx", "context_request", "context_planner_model_key", "ctx_extra", "refs", "mcp", "tool_names", "checks", "auto_approve"):
            self.assertRegex(new_page, rf"form\.(?:text|area|select|check|group)\('{field}'", field)
        sub = (APP_DIR / "subtask_form.js").read_text(encoding="utf-8")
        for field in ("title", "instructions", "model_key", "owner", "fallback", "write_scope", "read_only", "context_files", "reference_files",
                      "mcp_servers", "tool_names", "acceptance_commands"):
            self.assertRegex(sub, rf"form\.(?:text|area|select|check)\('{field}'", field)


if __name__ == "__main__":
    unittest.main()
