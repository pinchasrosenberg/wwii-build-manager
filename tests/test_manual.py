"""Manual tasks, MCP selection, prompt planner, Hebrew dashboard (fake CLIs only)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from helpers import FakeEnv, TmpTestCase, drive, git, init_repo, mini_plan, state

from wwii_build import control
from wwii_build import manual as mn
from wwii_build.dashboard import Dashboard


def base(repo):
    mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "mod_a/"}])


def args_for(env, tid):
    return next(c["args"] for c in env.calls() if c.get("task_id") == tid)


class ManualTasks(TmpTestCase):
    async def test_manual_task_with_model_context_deps_and_check(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        (env.repo / "notes").mkdir()
        (env.repo / "notes/design.md").write_text("MANUAL-CONTEXT-MARKER\n")
        s = env.scheduler()
        [tid] = mn.create_tasks(s.db, env.cfg, [{
            "key": "Tank HUD", "title": "Tank HUD", "instructions": "Build the HUD INSTRUCTION-MARKER",
            "model_key": "sonnet", "fallback": False, "depends_on": ["A/1"], "write_scope": ["hud/"],
            "context_files": ["notes/design.md"], "tool_names": ["Read", "Grep"],
            "acceptance_commands": ["! grep -rq BROKEN hud"]}])
        self.assertEqual(tid, "MANUAL/tank-hud")
        await s.cycle()
        self.assertEqual(state(s, tid), "WAITING_DEPENDENCY")
        await drive(s, lambda: state(s, tid) == "PASSED")
        a = s.db.one("SELECT provider, model FROM task_attempts WHERE task_id=?", (tid,))
        self.assertEqual((a["provider"], a["model"]), ("claude", "claude-sonnet-5-5"))
        prompt = Path(s.db.one("SELECT prompt_path FROM context_packs WHERE task_id=?", (tid,))["prompt_path"]).read_text()
        for needle in ("## INSTRUCTIONS", "INSTRUCTION-MARKER", "MANUAL-CONTEXT-MARKER", "handoff:A/1", "- `hud/`",
                       "## TASK TOOL CONTRACT", "Read, Grep"):
            self.assertIn(needle, prompt)
        self.assertTrue(s.db.one("SELECT 1 FROM test_results WHERE task_id=? AND name='check-1' AND passed=1", (tid,)))
        self.assertEqual(s.db.task(tid)["source"], "manual")

    async def test_no_fallback_pins_the_model(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp, overrides={"providers": {"claude": {"auth": "x"}}}, scenario={"claude": {"auth": "none"}})
        s = env.scheduler()
        [tid] = mn.create_tasks(s.db, env.cfg, [{"title": "pinned", "model_key": "sonnet", "fallback": False,
                                                 "write_scope": ["p/"]}])
        await s.refresh_all()
        await s.cycle()
        self.assertEqual(state(s, tid), "WAITING_PROVIDER")        # does not silently move to codex
        [t2] = mn.create_tasks(s.db, env.cfg, [{"title": "flex", "model_key": "sonnet", "fallback": True,
                                                "write_scope": ["q/"]}])
        await drive(s, lambda: state(s, t2) == "PASSED")
        self.assertEqual(s.db.one("SELECT provider FROM task_attempts WHERE task_id=?", (t2,))["provider"], "codex")

    async def test_task_and_global_auto_approval_skip_only_the_human_review_gate(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp, overrides={"review": {"auto_pass_requires_task_commands": True}})
        s = env.scheduler()
        [per_task] = mn.create_tasks(s.db, env.cfg, [{"title": "auto task", "model_key": "sol",
                                                       "write_scope": ["auto-task/"], "auto_approve": True}])
        self.assertTrue(json.loads(s.db.task(per_task)["extra"])["auto_approve"])
        await drive(s, lambda: state(s, per_task) == "PASSED")
        event = s.db.one("SELECT detail FROM event_log WHERE event='REVIEW_AUTO_APPROVED' AND task_id=?", (per_task,))
        self.assertEqual(json.loads(event["detail"])["scope"], "task")

        [global_task] = mn.create_tasks(s.db, env.cfg, [{"title": "global auto", "model_key": "sol",
                                                         "write_scope": ["global-auto/"]}])
        dash = Dashboard(env.cfg); dash.db = s.db; dash.wake = lambda: None
        self.assertIn("הופעל", dash.action({"action": "set_auto_approve_all", "enabled": "1"}))
        await drive(s, lambda: state(s, global_task) == "PASSED")
        self.assertEqual(s.db.get_flag("review_auto_approve_all"), "1")
        event = s.db.one("SELECT detail FROM event_log WHERE event='REVIEW_AUTO_APPROVED' AND task_id=?", (global_task,))
        self.assertEqual(json.loads(event["detail"])["scope"], "global")

    def test_validation_rejects_bad_specs(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        bad = [({"title": "x", "write_scope": ["a/"], "depends_on": ["NOPE/1"]}, "dependency"),
               ({"title": "x"}, "write scope"),
               ({"title": "x", "write_scope": ["a/"], "model_key": "gpt-9"}, "unknown model"),
               ({"title": "x", "write_scope": ["/etc/"]}, "relative"),
               ({"title": "x", "write_scope": ["../up/"]}, "relative"),
               ({"title": "x", "write_scope": ["a/"], "mcp_servers": ["ghost"]}, "MCP")]
        for spec, needle in bad:
            with self.assertRaises(mn.ManualError) as cm:
                mn.create_tasks(s.db, env.cfg, [spec], mcp_available={"codex": {}, "claude": {}})
            self.assertIn(needle, str(cm.exception))
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE source='manual'"))

    def test_task_manager_repair_has_fixed_scope_and_mandatory_checks(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        [tid] = mn.create_tasks(s.db, env.cfg, [{
            "title": "repair dashboard", "instructions": "fix the dashboard safely",
            "task_target": "task_manager", "model_key": "sol", "write_scope": [],
        }])
        row = s.db.task(tid)
        extra = json.loads(row["extra"])
        self.assertEqual(row["packet"], "SYSTEM")
        self.assertEqual(row["mode"], "system_repair")
        self.assertEqual(json.loads(row["write_scope"]), ["tools/build_manager/"])
        self.assertTrue(extra["system_task"])
        self.assertTrue(extra["full_checkout"])
        self.assertEqual(row["owner"], "task_manager_maintenance")
        checks = {item["name"] for item in json.loads(row["acceptance"])}
        self.assertTrue({"system-compile", "system-manager-tests", "system-cli-smoke"}.issubset(checks))
        with self.assertRaises(mn.ManualError):
            mn.create_tasks(s.db, env.cfg, [{"title": "escape", "task_target": "task_manager",
                                             "model_key": "sol", "write_scope": ["game/"]}])

    def test_refused_while_old_daemon_runs(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        with mock.patch("wwii_build.control.daemon_pid", return_value=12345):
            with self.assertRaises(mn.ManualError):
                mn.create_tasks(s.db, env.cfg, [{"title": "x", "write_scope": ["a/"]}])
            s.db.set_flag("daemon_code_version", str(mn.CODE_VERSION))
            mn.create_tasks(s.db, env.cfg, [{"title": "x", "write_scope": ["a/"]}])

    def test_ready_task_can_be_expedited_for_the_next_dispatch(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        [tid] = mn.create_tasks(s.db, env.cfg, [{"title": "urgent", "model_key": "sol",
                                                 "write_scope": ["urgent/"]}])
        self.assertGreater(s.db.task(tid)["dispatch_priority"], 0)
        decisions = s.evaluate()
        self.assertEqual(state(s, tid), "READY")
        self.assertIn("expedited", control.expedite(s.db, tid, "test"))
        s.max_parallel = 1
        picked = s.pick_dispatch(decisions, running=[])
        self.assertEqual(picked[0][0].task_id, tid)
        self.assertGreater(s.db.task(tid)["dispatch_priority"], 0)
        dash = Dashboard(env.cfg); dash.db = s.db
        self.assertIn("דחוף שוב", dash.page_overview(None))

        [dependent] = mn.create_tasks(s.db, env.cfg, [{"title": "waits", "model_key": "sol",
                                                        "depends_on": [tid], "write_scope": ["waits/"]}])
        self.assertEqual(s.db.task(dependent)["dispatch_priority"], 0)
        plan_id = mn.create_plan(s.db, env.cfg, "plan this now")
        self.assertGreater(s.db.task(plan_id)["dispatch_priority"], s.db.task(tid)["dispatch_priority"])


class McpSelection(TmpTestCase):
    async def test_codex_enables_only_selected_servers(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"mcp": ["alpha", "beta"]}})
        s = env.scheduler()
        [tid] = mn.create_tasks(s.db, env.cfg, [{"title": "uses alpha", "model_key": "sol", "write_scope": ["m/"],
                                                 "mcp_servers": ["alpha"]}], mcp_available={"codex": {"alpha": {}, "beta": {}}})
        await drive(s, lambda: state(s, tid) == "PASSED" and state(s, "A/1") == "PASSED")
        a = args_for(env, tid)
        self.assertIn("mcp_servers.alpha.enabled=true", a)
        self.assertIn("mcp_servers.beta.enabled=false", a)
        self.assertNotIn("--ignore-user-config", a)
        self.assertIn("--ignore-user-config", args_for(env, "A/1"))           # others unchanged: no MCP at all

    async def test_claude_gets_only_selected_servers_file(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        (env.repo / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "ctx7": {"command": "/bin/echo", "args": ["x"]}, "other": {"command": "/bin/echo"}}}))
        s = env.scheduler()
        [tid] = mn.create_tasks(s.db, env.cfg, [{"title": "uses ctx7", "model_key": "sonnet", "fallback": False,
                                                 "write_scope": ["c/"], "mcp_servers": ["ctx7"]}],
                                mcp_available={"claude": {"ctx7": {}, "other": {}}})
        await drive(s, lambda: state(s, tid) == "PASSED")
        a = args_for(env, tid)
        self.assertIn("--strict-mcp-config", a)
        self.assertNotIn("--safe-mode", a)
        self.assertIn("mcp__ctx7", a)
        cfg_path = Path(a[a.index("--mcp-config") + 1])
        self.assertFalse(cfg_path.exists())                                  # copied definitions deleted after run
        self.assertIn("--safe-mode", next(c["args"] for c in env.calls() if c.get("task_id") == "A/1"
                                          and c.get("flavor") == "claude") if any(
            c.get("task_id") == "A/1" and c.get("flavor") == "claude" for c in env.calls()) else ["--safe-mode"])


class PersistedSubtasks(TmpTestCase):
    def test_reuse_becomes_eligible_but_only_explicit_promotion_creates_deliver(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        spec = {"title": "Rebuild tank track", "instructions": "Implement the reusable track contract",
                "model_key": "sol", "fallback": True, "write_scope": ["mod_a/tracks/"],
                "context_files": ["context/game/INVARIANTS.md"], "reference_files": [],
                "mcp_servers": [], "tool_names": ["Read", "Grep"], "acceptance_commands": ["true"]}
        children = []
        for _ in range(3):
            children += mn.create_subtasks(s.db, env.cfg, "A/1", [spec], {"codex": {}, "claude": {}}, "test")
        pattern = s.db.one("SELECT * FROM subtask_patterns")
        self.assertEqual((pattern["reuse_count"], pattern["promotion_status"]), (3, "eligible"))
        self.assertFalse(s.db.one("SELECT 1 FROM deliver_catalog WHERE source_kind='subtask_promotion'"))
        self.assertTrue(set(children).issubset(set(s.db.deps("A/1"))))
        child_extra = json.loads(s.db.task(children[0])["extra"])
        self.assertEqual(child_extra["allowed_tools"], ["Read", "Grep"])
        self.assertEqual(child_extra["subtask_of"], "A/1")
        did = mn.promote_subtask_pattern(s.db, env.cfg, pattern["pattern_hash"], "tank.track.rebuild",
                                         "tank-owner", "vehicles")
        self.assertEqual(did, "tank.track.rebuild")
        self.assertEqual(s.db.one("SELECT source_kind FROM deliver_catalog WHERE deliver_id=?", (did,))["source_kind"],
                         "subtask_promotion")
        template = s.db.one("SELECT * FROM deliver_templates WHERE deliver_id=?", (did,))
        self.assertEqual(json.loads(template["tool_names_json"]), ["Grep", "Read"])
        self.assertEqual(s.db.one("SELECT promotion_status FROM subtask_patterns")["promotion_status"], "promoted")

    def test_subtask_page_explains_boundary_and_exposes_controls(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        dash = Dashboard(env.cfg); dash.db = s.db
        page = dash.page_subtasks(None)
        for needle in ("תתי־משימות ודפוסי שימוש חוזר", "אינה הופכת ל־Deliver", "name='tool_names'",
                       "name='context_files'", "סף ברירת מחדל"):
            self.assertIn(needle, page)
        task_page = dash.page_task("A/1", None)
        self.assertIn("פירוק לתת־משימות", task_page)


PROMPT = """Build a small radio feature.
- radio-core: scope=radio/core/; model=sol; cmd=test -d radio/core
- radio-ui: scope=radio/ui/; deps=radio-core,A/1; model=sonnet
- radio-notes: ro
"""


class Planner(TmpTestCase):
    def test_plan_schema_is_valid_for_codex_strict_outputs(self):
        item = mn.PLAN_SCHEMA["properties"]["tasks"]["items"]
        self.assertEqual(set(item["properties"]), set(item["required"]))

    async def test_prompt_to_proposal_to_tasks(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        integ_before = git(env.repo, "rev-parse", "wwii-build/integration").strip()
        pid = mn.create_plan(s.db, env.cfg, PROMPT)
        await drive(s, lambda: state(s, pid) == "PASSED")
        att = s.db.one("SELECT model FROM task_attempts WHERE task_id=?", (pid,))
        self.assertEqual(att["model"], "gpt-5.6-sol")
        self.assertIsNone(s.db.task(pid)["preferred_model_key"])      # automatic: routed by fit
        self.assertIn("-s", args_for(env, pid))
        self.assertEqual(args_for(env, pid)[args_for(env, pid).index("-s") + 1], "read-only")
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE kind='task' AND source='planner'"))  # nothing before approval
        prop = s.db.one("SELECT * FROM plan_proposals")
        self.assertEqual(prop["status"], "pending")
        ap = s.db.one("SELECT * FROM approvals WHERE kind='plan_proposal' AND status='pending'")
        msg = control.decide(s.db, env.cfg, ap["id"], True)
        self.assertIn("created 3 tasks", msg)
        ids = json.loads(s.db.one("SELECT created_task_ids FROM plan_proposals")["created_task_ids"])
        self.assertEqual(ids, ["MANUAL/plan1-radio-core", "MANUAL/plan1-radio-ui", "MANUAL/plan1-radio-notes"])
        self.assertEqual(set(s.db.deps("MANUAL/plan1-radio-ui")), {"MANUAL/plan1-radio-core", "A/1"})
        self.assertEqual(s.db.task("MANUAL/plan1-radio-notes")["mode"], "read_only_manual")
        await drive(s, lambda: all(state(s, i) in ("PASSED", "REVIEW_REQUIRED") for i in ids), timeout=40)
        self.assertEqual(state(s, "MANUAL/plan1-radio-ui"), "PASSED")
        # the planner itself never wrote to the integration branch
        log = git(env.repo, "log", "--format=%s", f"{integ_before}..wwii-build/integration")
        self.assertNotIn("PLAN/", log)

    async def test_global_auto_approval_creates_valid_planner_tasks(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        s.db.set_flag("review_auto_approve_all", "1")
        plan_id = mn.create_plan(s.db, env.cfg, PROMPT)
        await drive(s, lambda: state(s, plan_id) == "PASSED")
        proposal = s.db.one("SELECT * FROM plan_proposals WHERE plan_task_id=?", (plan_id,))
        self.assertEqual(proposal["status"], "approved")
        created = json.loads(proposal["created_task_ids"])
        self.assertEqual(len(created), 3)
        self.assertFalse(s.db.q("SELECT * FROM approvals WHERE task_id=? AND kind='plan_proposal' AND status='pending'",
                                (plan_id,)))
        event = s.db.one("SELECT detail FROM event_log WHERE event='PLAN_PROPOSAL_AUTO_APPROVED' AND task_id=?",
                         (plan_id,))
        self.assertEqual(json.loads(event["detail"])["source"], "global auto approval")
        await drive(s, lambda: all(state(s, task_id) == "PASSED" for task_id in created), timeout=40)

    async def test_dashboard_toggle_is_the_only_planner_auto_approval_source(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp, overrides={"planner": {"auto_create": True}})
        s = env.scheduler()
        plan_id = mn.create_plan(s.db, env.cfg, PROMPT)
        await drive(s, lambda: state(s, plan_id) == "PASSED")
        proposal = s.db.one("SELECT * FROM plan_proposals WHERE plan_task_id=?", (plan_id,))
        self.assertEqual(proposal["status"], "pending")
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE kind='task' AND source='planner'"))
        self.assertTrue(s.db.q(
            "SELECT * FROM approvals WHERE task_id=? AND kind='plan_proposal' AND status='pending'",
            (plan_id,)))

    async def test_graph_console_selected_model_returns_answer_immediately_without_creating_tasks(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        dash = Dashboard(env.cfg); dash.db = s.db
        # Keep this unit test independent from any real Graph RAG service that
        # may happen to be running on the developer machine's default port.
        dash.graph_rag.retrieve_candidates = lambda *args, **kwargs: []
        result = dash.run_graph_console_query("natural", "מה ידוע בגרף?", "sol")
        self.assertEqual(result["status"], "READY")
        record = s.db.one("SELECT * FROM graph_console_queries WHERE id=?", (result["id"],))
        self.assertEqual(record["status"], "READY")
        self.assertIsNone(record["task_id"])
        self.assertEqual((record["provider"], record["input_tokens"], record["output_tokens"]),
                         ("codex", 1200, 300))
        self.assertEqual(json.loads(record["result_json"])["tasks"], [])
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE kind='plan'"))
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE kind='task' AND source='planner'"))

    async def test_invalid_proposal_is_not_offered(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        pid = mn.create_plan(s.db, env.cfg, "- broken: scope=b/; deps=does-not-exist")
        await drive(s, lambda: state(s, pid) == "FAILED")
        self.assertEqual(s.db.one("SELECT status FROM plan_proposals")["status"], "invalid")
        self.assertFalse(s.db.q("SELECT * FROM approvals WHERE kind='plan_proposal'"))
        self.assertIn("does-not-exist", s.db.task(pid)["state_reason"])

    def test_context_plan_locks_task_and_hydrates_jev_selected_sources(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        md = env.repo / "docs/game/weather.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text("שלג כבד וקרקע קפואה באזור הקרב")
        s = env.scheduler()
        spec = {"title": "בנה מזג אוויר", "instructions": "בנה את הסצנה", "model_key": "sol",
                "fallback": True, "owner": "", "depends_on": ["A/1"], "write_scope": ["weather/"],
                "read_only": False, "context_files": [], "reference_files": [], "mcp_servers": [],
                "tool_names": [], "acceptance_commands": ["true"], "auto_approve": True}
        pid = mn.create_context_plan(s.db, env.cfg, spec, "מצא מידע על שלג וקרקע קפואה")
        plan = s.db.task(pid)
        extra = json.loads(plan["extra"])
        self.assertEqual(extra["context_target_spec"]["model_key"], "sol")
        self.assertTrue(mn.planner_markdown_candidates(env.cfg, "שלג קרקע"))
        chosen = {"id": "rag-context:test", "source_key": "rag:test", "title": "שלג בקרב",
                  "description": "selected snow", "origin_kind": "graph_rag", "origin_ref": "neo4j:test",
                  "graph_entity_id": "Weather:1", "excerpt": "snow evidence", "content_sha256": "abc"}
        extra["jev_selected_context"] = [chosen]
        s.db.x("UPDATE tasks SET extra=? WHERE task_id=?", (json.dumps(extra, ensure_ascii=False), pid))
        plan = s.db.task(pid)
        proposal = {"summary": "context selected", "questions": [], "tasks": [{
            **spec, "key": "malicious-change", "title": "changed", "model_key": "astra",
            "write_scope": ["wrong/"], "context_files": ["docs/game/weather.md"],
            "context_source_ids": ["rag-context:test"], "context_request": "changed"}]}
        prop_id, msgs = mn.store_proposal(s.db, env.cfg, plan, proposal, None, {"codex": {}, "claude": {}})
        self.assertFalse([m for m in msgs if m["level"] == "error"])
        stored = json.loads(s.db.one("SELECT proposal FROM plan_proposals WHERE id=?", (prop_id,))["proposal"])["tasks"][0]
        self.assertEqual(stored["title"], "בנה מזג אוויר")
        self.assertEqual(stored["model_key"], "sol")
        self.assertEqual(stored["write_scope"], ["weather/"])
        self.assertEqual(stored["context_request"], "מצא מידע על שלג וקרקע קפואה")
        [tid] = mn.apply_proposal(s.db, env.cfg, prop_id, {"codex": {}, "claude": {}})
        task_extra = json.loads(s.db.task(tid)["extra"])
        self.assertEqual(task_extra["evidence"], ["docs/game/weather.md"])
        self.assertEqual(task_extra["context_source_ids"], ["rag-context:test"])
        self.assertEqual(s.db.one("SELECT source_key FROM task_context_bindings WHERE task_id=?", (tid,))["source_key"],
                         "rag:test")


class DashboardPages(TmpTestCase):
    async def test_new_task_form_plan_page_and_hebrew(self):
        from wwii_build import dashboard as dmod
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp, {"codex": {"mcp": ["alpha"]}})
        s = env.scheduler()
        d = Dashboard(env.cfg)
        page = d.page_new(None)
        for needle in ("משימה חדשה", "name='deps' value='A/1'", "name='ctx'", "alpha", "צור משימה",
                       "הפעל אישור אוטומטי להכול", "name='auto_approve'", "name='context_request'",
                       "Neo4j Graph RAG", "name='context_planner_model_key'", "מתכנן המערכת",
                       "מתכנן הקונטקסט", "הוראות ביצוע לעובד", "יותר גישה מגדילה",
                       "name='task_target'", "תיקון מערכת ניהול המשימות", "restart חינני"):
            self.assertIn(needle, page)
        rag_page = d.page_graph_rag(None)
        self.assertIn("חופש חיפוש, לא חופש ביצוע", rag_page)
        self.assertIn("אינה נותנת למתכנן גישה לסודות", rag_page)
        self.assertIn("שאילתת Neo4j בשפת Cypher", rag_page)
        self.assertIn("שאלה חופשית דרך LLM", rag_page)
        overview = d.page_overview(None)
        self.assertIn("planner-main-prompt", overview)
        self.assertIn("המתכנן יבחר פירוק, מודלים, קונטקסט, כלים ותלויות", overview)
        ok, msg, err_page = d.add_task_post({"title": "keep me", "instructions": "TYPED-TEXT", "model_key": "sol",
                                             "fallback": "1"}, {"deps": ["A/1"]})
        self.assertFalse(ok)
        self.assertIn("write scope", msg)
        self.assertIn("TYPED-TEXT", err_page)                                   # nothing the user typed is lost
        ok, tid, _ = d.add_task_post({"title": "HUD", "model_key": "sol", "fallback": "1", "write_scope": "hud/\n",
                                      "checks": "true"}, {"deps": ["A/1"], "mcp": ["codex:alpha", "claude:zzz"]})
        self.assertTrue(ok)
        self.assertEqual(json.loads(s.db.task(tid)["extra"])["mcp"], ["alpha"])
        self.assertIn("A/1", s.db.deps(tid))
        ok, context_plan, _ = d.add_task_post({"title": "Snow", "instructions": "build snow",
                                               "model_key": "sol", "fallback": "1", "write_scope": "snow/\n",
                                               "context_request": "מצא שלג היסטורי מתאים"}, {})
        self.assertTrue(ok)
        self.assertTrue(context_plan.startswith("PLAN/"))
        self.assertEqual(json.loads(s.db.task(context_plan)["extra"])["context_request"],
                         "מצא שלג היסטורי מתאים")
        msg = d.action({"action": "plan", "prompt": "- x: scope=x/"})
        self.assertIn("PLAN/", msg)
        self.assertIn("בקשות תכנון", d.page_plan(None))
        dmod._LANG.v = "he"
        try:
            over = d.page_overview(None)
            self.assertIn("dir='rtl'", over)
            for needle in ("סקירה", "משימות", "השהה", "עצור", "+ משימה חדשה", "אישור אוטומטי לכל המשימות"):
                self.assertIn(needle, over)
            self.assertIn("משימה חדשה", d.page_new(None))
            self.assertIn("פרומפט ← משימות", d.page_plan(None))
        finally:
            dmod._LANG.v = "he"


class ReviewPage(TmpTestCase):
    async def test_view_what_was_created_before_approve(self):
        import socket
        import urllib.error
        import urllib.request
        from wwii_build import dashboard as dmod
        base(init_repo(self.tmp))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        env = FakeEnv(self.tmp, {"codex": {"tasks": {"A/1": ["visual"]}}},
                      overrides={"dashboard": {"port": port}, "review": {"auto_pass_requires_task_commands": True}})
        s = env.scheduler()
        await drive(s, lambda: state(s, "A/1") == "REVIEW_REQUIRED")
        d = Dashboard(env.cfg)
        d.serve_in_thread()
        base_url = f"http://127.0.0.1:{port}"

        def get(path):
            try:
                r = urllib.request.urlopen(base_url + path)
                return r.status, dict(r.headers), r.read()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read()
        try:
            st, _, over = get("/classic/?lang=en")
            self.assertIn(b"/review?id=A/1", over)                        # button next to the approval
            st, _, page = get("/review?id=A/1")
            page = page.decode()
            self.assertEqual(st, 200)
            for needle in ("צפה במה שנוצר", "mod_a/preview.png", "<img src='",
                           "<iframe sandbox", "mod_a/tank.py", "class='add'", "ARMOR_MM",
                           "אשר", "סיכום", "ויזואלי", "פתיחת הדוח המקורי"):
                self.assertIn(needle, page)
            visual = page.split("<h2 id='visual'>", 1)[1].split("<h2 id='code'>", 1)[0]
            self.assertNotIn("README.md", visual)
            self.assertNotIn("/game-preview", visual)  # a task's image must not be replaced by the demo tank
            model_path = self.tmp / "task-model.glb"
            model_path.write_bytes(b"glTF")
            d.db.x("INSERT INTO artifacts(task_id,kind,path,source_path,created_at) VALUES(?,?,?,?,?)",
                   ("A/1", "preview_3d", str(model_path), "mod_a/task-model.glb", "2026-01-01T00:00:00Z"))
            model_id = d.db.one("SELECT id FROM artifacts WHERE task_id='A/1' AND kind='preview_3d'")["id"]
            _, _, model_page = get("/review?id=A/1")
            self.assertIn(f"src='/game-preview?artifact={model_id}'".encode(), model_page)
            self.assertEqual(get(f"/artifact/{model_id}")[2], b"glTF")
            st, _, preview = get("/game-preview")
            self.assertEqual(st, 200)
            self.assertIn("תצוגת רכיבי המשחק".encode(), preview)
            st, _, script = get("/game-static/main.js")
            self.assertEqual(st, 200)
            self.assertIn(b"WebGLRenderer", script)
            st, hdrs, img = get("/wtfile?task=A/1&path=mod_a/preview.png&raw=1")
            self.assertEqual((st, hdrs.get("Content-Type")), (200, "image/png"))
            self.assertEqual(hdrs.get("Content-Security-Policy"), "sandbox")   # model output can't drive the dashboard
            self.assertTrue(img.startswith(b"\x89PNG"))
            st, hdrs, _ = get("/wtfile?task=A/1&path=mod_a/report.html&raw=1")
            self.assertEqual(hdrs.get("Content-Security-Policy"), "sandbox")
            st, _, code = get("/wtfile?task=A/1&path=mod_a/tank.py")
            self.assertIn(b"ARMOR_MM = 80", code)
            self.assertEqual(get("/wtfile?task=A/1&path=README.md&raw=1")[0], 404)          # not part of the change
            self.assertEqual(get("/wtfile?task=A/1&path=../../../etc/passwd&raw=1")[0], 404)
            st, _, he = get("/review?id=A/1&lang=he")
            self.assertIn("צפה במה שנוצר".encode(), he)
        finally:
            d.shutdown()
            dmod._LANG.v = "he"
