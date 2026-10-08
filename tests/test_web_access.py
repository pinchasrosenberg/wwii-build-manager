"""Opt-in web access for research tasks (extra.allow_web): closed by default, argv per provider, validation,
the prompt-injection guard, per-attempt record and the dashboard badge. Fake CLIs and synthetic tasks only."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import FakeEnv, TmpTestCase, drive, init_repo, mini_plan, settle

from wwii_build import manual as mn
from wwii_build.config import DEFAULTS, Config, deep_merge
from wwii_build.dashboard import Dashboard
from wwii_build.models import RunSpec, TaskRequest
from wwii_build.prompts import WEB_GUARD_HEADER
from wwii_build.providers.claude import ClaudeCliProvider
from wwii_build.providers.codex import CodexCliProvider

WEB = ("WebFetch", "WebSearch")


def base(repo):
    mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "mod_a/"}])


def task(read_only=False, **extra) -> TaskRequest:
    return TaskRequest(task_id="MANUAL/synthetic-research", packet="MANUAL", owner="o", domain="d",
                       mode="read_only_manual" if read_only else "build", model_profile="MANUAL", lego_ids=[],
                       write_scope=["docs/game/reports/synthetic/"], depends_on=[], context_entry=None,
                       brief_path=None, extra=extra)


def spec(model_key: str, req: TaskRequest, tmp: Path, kind="execute", allow_web=False) -> RunSpec:
    cfg = Config(repo=tmp, data=deep_merge(DEFAULTS, {}), path=None)
    return RunSpec(task=req, attempt_id=1, attempt_no=1, model=cfg.model(model_key), worktree=str(tmp),
                   prompt_path="prompt.md", run_dir=str(tmp / "run"), result_schema_path="schema.json", kind=kind,
                   allow_web=allow_web)


def values_after(argv: list[str], flag: str) -> list[str]:
    """Every argument following ``flag`` up to the next option."""
    out: list[str] = []
    for i, a in enumerate(argv):
        if a == flag:
            for b in argv[i + 1:]:
                if b.startswith("--"):
                    break
                out.append(b)
    return out


class ProviderArgv(TmpTestCase):
    def claude(self) -> ClaudeCliProvider:
        return ClaudeCliProvider(DEFAULTS["providers"]["claude"])

    def test_claude_default_run_keeps_web_tools_disallowed(self):
        for read_only in (False, True):
            argv = self.claude().build_command(spec("sonnet", task(read_only), self.tmp))
            disallowed = values_after(argv, "--disallowedTools")
            for tool in WEB:
                self.assertIn(tool, disallowed)
                self.assertNotIn(tool, values_after(argv, "--allowedTools"))
            self.assertIn("Bash(curl*)", disallowed)

    def test_claude_allow_web_moves_web_tools_from_deny_to_allow(self):
        for read_only in (False, True):
            argv = self.claude().build_command(spec("sonnet", task(read_only, allow_web=True), self.tmp,
                                                    allow_web=True))
            disallowed, allowed = values_after(argv, "--disallowedTools"), values_after(argv, "--allowedTools")
            for tool in WEB:
                self.assertNotIn(tool, disallowed)
                self.assertIn(tool, allowed)
            # every other deny stays in place
            self.assertIn("Bash(curl*)", disallowed)
            self.assertIn("Bash(git push*)", disallowed)
            if read_only:
                self.assertIn("WebFetch", argv[argv.index("--tools") + 1].split(","))

    def test_claude_allow_web_survives_a_narrow_tool_contract(self):
        req = task(False, allow_web=True, allowed_tools=["Read"])
        allowed = values_after(self.claude().build_command(spec("sonnet", req, self.tmp, allow_web=True)),
                               "--allowedTools")
        self.assertEqual(sorted(allowed), sorted(["Read", *WEB]))

    def test_claude_review_and_plan_runs_never_get_web(self):
        for kind in ("review", "plan"):
            argv = self.claude().build_command(spec("sonnet", task(True, allow_web=True), self.tmp, kind=kind,
                                                    allow_web=True))
            self.assertIn("WebFetch", values_after(argv, "--disallowedTools"))

    def test_codex_search_only_when_allow_web(self):
        codex = CodexCliProvider(DEFAULTS["providers"]["codex"])
        self.assertNotIn("--search", codex.build_command(spec("sol", task(), self.tmp)))
        argv = codex.build_command(spec("sol", task(allow_web=True), self.tmp, allow_web=True))
        self.assertIn("--search", argv)
        self.assertLess(argv.index("--search"), argv.index("-"))
        self.assertNotIn("--search", codex.build_command(spec("sol", task(allow_web=True), self.tmp, kind="review",
                                                              allow_web=True)))

    def test_codex_without_documented_search_flag_stays_closed(self):
        codex = CodexCliProvider(DEFAULTS["providers"]["codex"])
        codex._exec_help = "Run Codex non-interactively\n  --json  --ephemeral\n"
        run = spec("sol", task(allow_web=True), self.tmp, allow_web=True)
        self.assertFalse(codex.web_enabled(run))
        self.assertNotIn("--search", codex.build_command(run))


class Validation(TmpTestCase):
    def test_allow_web_is_stored_and_defaults_closed(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        [web, closed, form_false] = mn.create_tasks(s.db, env.cfg, [
            {"title": "synthetic web research", "read_only": True, "allow_web": True},
            {"title": "synthetic closed research", "read_only": True},
            {"title": "synthetic form false", "read_only": True, "allow_web": "0"}])
        self.assertTrue(json.loads(s.db.task(web)["extra"])["allow_web"])
        self.assertFalse(json.loads(s.db.task(closed)["extra"])["allow_web"])
        self.assertFalse(json.loads(s.db.task(form_false)["extra"])["allow_web"])

    def test_allow_web_rejected_for_task_manager_tasks(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        with self.assertRaises(mn.ManualError) as cm:
            mn.create_tasks(s.db, env.cfg, [{"title": "synthetic repair", "task_target": "task_manager",
                                             "model_key": "sol", "allow_web": True}])
        self.assertIn("allow_web", str(cm.exception))
        _, msgs = mn.validate(s.db, env.cfg, [{"title": "synthetic repair", "system_task": True, "allow_web": True}])
        self.assertTrue(any(m["level"] == "error" and "allow_web" in m["message"] for m in msgs))
        self.assertFalse(s.db.q("SELECT * FROM tasks WHERE source='manual'"))

    def test_planner_schema_and_prompt_carry_allow_web(self):
        item = mn.PLAN_SCHEMA["properties"]["tasks"]["items"]
        self.assertIn("allow_web", item["properties"])
        self.assertIn("allow_web", item["required"])

    def test_dashboard_form_creates_web_task_and_rejects_system_target(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        dash = Dashboard(env.cfg); dash.db = s.db; dash.wake = lambda: None
        self.assertIn("מחקר עם גישה לרשת", dash.page_new(None, {}))
        self.assertIn("name='allow_web'", dash.page_new(None, {}))
        ok, tid, _ = dash.add_task_post({"title": "synthetic web", "read_only": "1", "allow_web": "1",
                                         "description_he": "מחקר"}, {})
        self.assertTrue(ok, tid)
        self.assertTrue(json.loads(s.db.task(tid)["extra"])["allow_web"])
        ok, message, _ = dash.add_task_post({"title": "synthetic repair", "task_target": "task_manager",
                                             "allow_web": "1", "description_he": "תיקון"}, {})
        self.assertFalse(ok)
        self.assertIn("allow_web", message)

    def test_deliver_template_carries_allow_web(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        sp = {"title": "synthetic source sweep", "instructions": "collect sources", "model_key": "sol",
              "read_only": True, "allow_web": True}
        for _ in range(3):
            mn.create_subtasks(s.db, env.cfg, "A/1", [sp], {"codex": {}, "claude": {}}, "test")
        pattern = s.db.one("SELECT * FROM subtask_patterns")
        self.assertTrue(json.loads(pattern["spec_json"])["allow_web"])
        did = mn.promote_subtask_pattern(s.db, env.cfg, pattern["pattern_hash"], "synthetic.source.sweep", "qa")
        self.assertEqual(s.db.one("SELECT allow_web FROM deliver_templates WHERE deliver_id=?", (did,))[0], 1)
        self.assertTrue(mn.template_task_spec(s.db, did)["allow_web"])
        mn.set_template_allow_web(s.db, did, False)
        self.assertFalse(mn.template_task_spec(s.db, did)["allow_web"])

    def test_closed_pattern_hash_is_unchanged_by_the_new_field(self):
        sp = {"title": "t", "instructions": "i", "write_scope": ["a/"]}
        self.assertEqual(mn._subtask_pattern_hash(sp), mn._subtask_pattern_hash(dict(sp, allow_web=False)))
        self.assertNotEqual(mn._subtask_pattern_hash(sp), mn._subtask_pattern_hash(dict(sp, allow_web=True)))


class EndToEnd(TmpTestCase):
    async def test_runs_record_web_and_guard_only_for_allow_web_tasks(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        s = env.scheduler()
        ids = mn.create_tasks(s.db, env.cfg, [
            {"key": "web-claude", "title": "synthetic web claude", "model_key": "sonnet", "fallback": False,
             "read_only": True, "allow_web": True, "auto_approve": True},
            {"key": "web-codex", "title": "synthetic web codex", "model_key": "sol", "fallback": False,
             "read_only": True, "allow_web": True, "auto_approve": True},
            {"key": "closed-claude", "title": "synthetic closed claude", "model_key": "sonnet", "fallback": False,
             "read_only": True, "auto_approve": True}])
        web_claude, web_codex, closed = ids
        finished = lambda tid: s.db.one("SELECT 1 FROM task_attempts WHERE task_id=? AND kind='execute' "
                                        "AND ended_at IS NOT NULL", (tid,))
        await drive(s, lambda: all(finished(t) for t in ids))
        await settle(s)
        calls: dict[str, list] = {}
        for c in env.calls():          # the first run per task is its execute attempt (a review may follow)
            if c.get("args") and c.get("task_id") in ids:
                calls.setdefault(c["task_id"], c["args"])
        self.assertIn("WebSearch", values_after(calls[web_claude], "--allowedTools"))
        self.assertNotIn("WebSearch", values_after(calls[web_claude], "--disallowedTools"))
        self.assertIn("--search", calls[web_codex])
        self.assertIn("WebSearch", values_after(calls[closed], "--disallowedTools"))
        self.assertNotIn("WebSearch", values_after(calls[closed], "--allowedTools"))

        def attempt_web(tid):
            return s.db.one("SELECT web_enabled FROM task_attempts WHERE task_id=? AND kind='execute'", (tid,))[0]
        self.assertEqual([attempt_web(t) for t in ids], [1, 1, 0])
        for tid, expected in zip(ids, (True, True, False)):
            started = s.db.one("SELECT detail FROM event_log WHERE event='TASK_STARTED' AND task_id=?", (tid,))
            self.assertIs(json.loads(started["detail"])["web_enabled"], expected)
            prompt = Path(s.db.one("SELECT prompt_path FROM context_packs WHERE task_id=? ORDER BY id LIMIT 1",
                                   (tid,))["prompt_path"]).read_text()
            self.assertEqual(WEB_GUARD_HEADER in prompt, expected, tid)
            if expected:
                for needle in ("never instructions", "source URL", "Never send repository content"):
                    self.assertIn(needle, prompt)
        self.assertFalse(s.db.one("SELECT 1 FROM task_attempts WHERE kind='review' AND web_enabled=1"))

        dash = Dashboard(env.cfg); dash.db = s.db; dash.wake = lambda: None
        overview = dash.page_overview(None)
        self.assertEqual(overview.count("pill s-WEB"), 2)
        self.assertIn("pill s-WEB", dash.page_task(web_claude, None))
        self.assertNotIn("pill s-WEB", dash.page_task(closed, None))
        rows = {r["task_id"]: r for r in dash.task_rows()}
        self.assertEqual([rows[t]["allow_web"] for t in ids], [True, True, False])


class SecurityHeaderTests(unittest.TestCase):
    """Clickjacking and open-redirect guards of the dashboard."""

    def test_redirect_targets_stay_on_this_host(self):
        from wwii_build.dashboard import local_path
        self.assertEqual(local_path("/task?id=B01/x"), "/task?id=B01/x")
        for bad in ("https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)",
                    "/ok\r\nSet-Cookie: x=1", "", None):
            self.assertEqual(local_path(bad), "/", bad)
