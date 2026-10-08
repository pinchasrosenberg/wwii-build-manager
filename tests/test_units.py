"""Pure-logic tests: plan import, routing/fallback, quota, parsing, context isolation, env scrubbing."""
from __future__ import annotations

import datetime as dt
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from helpers import REAL_REGISTRY, FakeEnv, TmpTestCase, copy_real_plan, init_repo, mini_plan

from wwii_build.config import DEFAULTS, Config, deep_merge
from wwii_build.context_builder import ContextBuilder
from wwii_build.db import DB
from wwii_build.models import ProviderStatus, QuotaSignal, TaskRequest, utcnow
from wwii_build.plan_importer import PlanError, build_requests, compute_waves, import_plan, load_registry
from wwii_build.providers.limits import (claude_limit_from_text, claude_rate_limit_event, codex_limit_from_text,
                                         parse_time_phrase)
from wwii_build.quota import QuotaManager
from wwii_build.result_parser import MALFORMED, MISSING, VALID, parse_result
from wwii_build.routing import RUN, WAIT_APPROVAL, WAIT_PROVIDER, WAIT_QUOTA, select_route
from wwii_build.sanitize import child_env, redact
from wwii_build.scheduler import scopes_overlap

HAVE_REAL = REAL_REGISTRY.is_file()


def cfg_for(repo: Path, **over) -> Config:
    return Config(repo=repo, data=deep_merge(DEFAULTS, over), path=None)


def req(tid="T/x", profile="IMPLEMENT", **kw) -> TaskRequest:
    base = dict(task_id=tid, packet="T", owner="o", domain="d", mode="build", model_profile=profile, lego_ids=[],
                write_scope=["a/"], depends_on=[], context_entry=None, brief_path=None)
    base.update(kw)
    return TaskRequest(**base)


@unittest.skipUnless(HAVE_REAL, "real registry not present")
class RealPlanImport(TmpTestCase):
    def test_imports_existing_dispatch_graph(self):
        repo = init_repo(self.tmp)
        copy_real_plan(repo)
        cfg = cfg_for(repo, plan={"overlay": str(Path(__file__).parents[1] / "plan_overlay.toml")})
        reqs = build_requests(cfg)
        reg = load_registry(cfg)
        self.assertEqual(len(reqs), len(reg["dispatch_tasks"]))
        roots = sorted(r.task_id for r in reqs if not r.depends_on)
        self.assertEqual(roots, ["B00/contracts", "B03/evidence_sources", "B07/inventory"])
        by = {r.task_id: r for r in reqs}
        # graph, not packet numbers: B01/ground_platform waits on powertrain; B00/runtime_followup on B05 design
        self.assertIn("B01/ground_powertrain", by["B01/ground_platform"].depends_on)
        self.assertIn("B05/experience_loop", by["B00/runtime_followup"].depends_on)
        self.assertEqual(by["B00/contracts"].model_profile, "DEEP")
        self.assertIn("capabilities/ground_vehicles/primitives/chassis/", by["B01/ground_platform"].write_scope)
        self.assertEqual(by["B07/inventory"].write_scope, ["docs/game/reports/B07_inventory/"])
        self.assertTrue(by["B07/inventory"].read_only)
        waves = compute_waves(reqs)
        self.assertEqual(waves["B00/contracts"], 0)
        self.assertGreater(waves["B09/final_integration"], waves["B06/character_social"])
        db = DB(":memory:")
        r1 = import_plan(cfg, db)
        r2 = import_plan(cfg, db)
        self.assertEqual(len(r1["added"]), len(reqs))
        self.assertEqual(len(r2["unchanged"]), len(reqs))   # idempotent

    def test_tank_context_isolation(self):
        """Tank agent gets invariants + ground vehicle domain + ground_platform role + B01 slice; nothing naval/aviation."""
        repo = init_repo(self.tmp)
        copy_real_plan(repo)
        cfg = cfg_for(repo, plan={"overlay": ""})
        reg = load_registry(cfg)
        tank = next(r for r in build_requests(cfg) if r.task_id == "B01/ground_platform")
        pack = ContextBuilder(cfg, reg).build(tank, [])
        inline = [i.path for i in pack.items if i.mode == "inline"]
        self.assertIn("context/game/global/INVARIANTS.md", inline)
        self.assertIn("context/game/domains/ground_vehicles/DOMAIN.md", inline)
        self.assertIn("context/game/domains/ground_vehicles/roles/ground_platform.md", inline)
        self.assertIn("context/game/build_packets/B01/BRIEF.md", inline)
        excluded = [i.path for i in pack.items if i.mode == "excluded"]
        self.assertIn("context/game/domains/ground_vehicles/roles/ground_powertrain.md", excluded)
        for i in pack.items:
            if i.mode in ("inline", "reference"):
                self.assertNotRegex(i.path, r"naval|aviation|weapons_effects/roles")
        naval = (repo / "context/game/domains/naval/DOMAIN.md").read_text()
        self.assertNotIn(naval.strip().splitlines()[0], pack.prompt)
        self.assertLess(pack.total_bytes, 60000)
        slice_json = json.loads(pack.prompt.split("<<<BEGIN registry:dispatch_tasks[B01/ground_platform]")[1]
                                .split(">>>", 1)[1].split("<<<END")[0])
        self.assertEqual({i["lego_id"] for i in slice_json["lego_items"]}, set(tank.lego_ids))

    def test_b06_task_gets_only_own_domain(self):
        repo = init_repo(self.tmp)
        copy_real_plan(repo)
        cfg = cfg_for(repo, plan={"overlay": ""})
        t = next(r for r in build_requests(cfg) if r.task_id == "B06/ai_perception")
        pack = ContextBuilder(cfg, load_registry(cfg)).build(t, [])
        inline = [i.path for i in pack.items if i.mode == "inline"]
        self.assertIn("context/game/domains/ai_navigation/roles/ai_perception.md", inline)
        self.assertFalse(any("/infantry/" in p or "/characters/" in p for p in inline))


class PlanValidation(TmpTestCase):
    def test_cycle_detected(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/", "depends_on": ["B/1"]},
                         {"task_id": "B/1", "owner": "b", "scope": "y/", "depends_on": ["A/1"]}])
        with self.assertRaises(PlanError):
            build_requests(cfg_for(repo, plan={"overlay": ""}))

    def test_unknown_dependency(self):
        repo = init_repo(self.tmp)
        mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "x/", "depends_on": ["Z/9"]}])
        with self.assertRaises(PlanError):
            build_requests(cfg_for(repo, plan={"overlay": ""}))


class FitRouting(TmpTestCase):
    """Routing is by fit only: provider never matters, quota only filters / breaks exact ties."""
    def setUp(self):
        super().setUp()
        self.cfg = cfg_for(self.tmp)
        self.db = DB(":memory:")
        self.q = QuotaManager(self.db, self.cfg.section("quota"))

    def test_best_fit_wins_regardless_of_provider(self):
        for profile, want in (("DESIGN", "sonnet"), ("REPAIR_TEXT", "sonnet"), ("RESEARCH", "opus"),
                              ("PLAN", None)):
            d = select_route(self.cfg, self.q, req(profile=profile), approvals={"opus": "approved"})
            self.assertEqual(d.kind, RUN)
            if want:
                self.assertEqual(d.model_key, want, profile)

    def test_extract_picks_a_cheap_extractor(self):
        d = select_route(self.cfg, self.q, req(profile="EXTRACT"), approvals={})
        self.assertIn(d.model_key, {"luna", "haiku"})

    def test_equal_fit_prefers_more_headroom_not_codex(self):
        t = req(profile="IMPLEMENT")                       # sol and sonnet score the same
        self.q.record_signal(QuotaSignal("codex", "*", "SNAPSHOT", "weekly", utcnow() + dt.timedelta(days=3), 80.0))
        self.q._update("codex", "*", weekly_used_percent=80.0, weekly_reset_at=(utcnow() + dt.timedelta(days=3)).isoformat())
        self.assertEqual(select_route(self.cfg, self.q, t, approvals={}).model_key, "sonnet")
        self.q._update("claude", "*", weekly_used_percent=95.0, weekly_reset_at=(utcnow() + dt.timedelta(days=3)).isoformat())
        self.assertEqual(select_route(self.cfg, self.q, t, approvals={}).model_key, "sol")

    def test_headroom_ignores_windows_that_already_reset(self):
        past = (utcnow() - dt.timedelta(hours=1)).isoformat()
        self.q._update("claude", "*", session_used_percent=94.0, session_reset_at=past)
        self.assertEqual(self.q.headroom("claude", "sonnet"), 100.0)

    def test_weak_models_are_never_fallbacks_for_implementation(self):
        self.q.record_signal(QuotaSignal("codex", "*", "LIMIT_HIT", "weekly", utcnow() + dt.timedelta(hours=5)))
        self.q.record_signal(QuotaSignal("claude", "sonnet", "LIMIT_HIT", "weekly", utcnow() + dt.timedelta(hours=2)))
        self.assertEqual(select_route(self.cfg, self.q, req(profile="IMPLEMENT"), approvals={}).kind, WAIT_QUOTA)

    def test_explicit_routing_pin_overrides_fit(self):
        cfg = cfg_for(self.tmp, routing={"IMPLEMENT": ["sonnet", "sol"]})
        self.assertEqual(select_route(cfg, self.q, req(profile="IMPLEMENT"), approvals={}).model_key, "sonnet")

    def test_sonnet_uses_the_current_model_id(self):
        self.assertEqual(self.cfg.model("sonnet").model, "claude-sonnet-5-5")

    def test_rejected_model_is_reprobed_after_an_hour(self):
        self.q.set_status("claude", ProviderStatus.MODEL_UNAVAILABLE, "old cli", family="model:claude-sonnet-5-5")
        self.assertFalse(self.q.availability("claude", "sonnet", "claude-sonnet-5-5").usable)
        old = (utcnow() - dt.timedelta(minutes=61)).isoformat()
        self.q._update("claude", "model:claude-sonnet-5-5", last_checked_at=old)
        self.assertTrue(self.q.availability("claude", "sonnet", "claude-sonnet-5-5").usable)

    def test_claude_event_updates_both_windows(self):
        info = {"status": "allowed_warning", "resetsAt": 1790834400, "rateLimitType": "seven_day", "utilization": 0.91,
                "unifiedWindows": {"five_hour": {"utilization": 0.04, "resetsAt": 1790637000},
                                   "seven_day": {"utilization": 0.91, "resetsAt": 1790834400}}}
        self.q.record_signal(claude_rate_limit_event(info))
        row = self.q.row("claude")
        self.assertAlmostEqual(row["session_used_percent"], 4.0)
        self.assertAlmostEqual(row["weekly_used_percent"], 91.0)
        self.assertAlmostEqual(row["used_percent"], 91.0)
        self.assertIsNotNone(row["session_reset_at"])


class QuotaAndRouting(TmpTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = cfg_for(self.tmp)
        self.db = DB(":memory:")
        self.q = QuotaManager(self.db, self.cfg.section("quota"))

    def test_unknown_is_usable_and_has_no_percent(self):
        av = self.q.availability("claude", "opus")
        self.assertTrue(av.usable)
        self.assertEqual(self.q.row("claude")["status"], "UNKNOWN")
        self.assertIsNone(self.q.row("claude")["used_percent"])

    def test_limit_with_reset_blocks_until_reset_then_probe(self):
        now = utcnow()
        reset = now + dt.timedelta(minutes=30)
        self.q.record_signal(QuotaSignal("codex", "*", "LIMIT_HIT", "session", reset))
        av = self.q.availability("codex", now=now)
        self.assertFalse(av.usable)
        self.assertEqual(av.status, ProviderStatus.BLOCKED_SESSION)
        self.assertGreaterEqual(av.until, reset)
        later = reset + dt.timedelta(minutes=5)
        self.assertTrue(self.q.availability("codex", now=later).usable)   # reset passed: probe allowed
        self.assertEqual(self.q.next_reset(now), av.until)

    def test_unknown_reset_bounded_backoff(self):
        now = utcnow()
        for expected in (15, 30, 60, 120, 120):
            self.q.record_signal(QuotaSignal("claude", "*", "LIMIT_HIT", "unknown", None))
            until = dt.datetime.fromisoformat(self.q.row("claude")["blocked_until"])
            mins = (until - now).total_seconds() / 60
            self.assertAlmostEqual(mins, expected, delta=1.0)
        self.assertEqual(self.q.row("claude")["confidence"], "low")

    def test_model_family_block_is_partial(self):
        reset = utcnow() + dt.timedelta(days=2)
        self.q.record_signal(QuotaSignal("claude", "opus", "LIMIT_HIT", "weekly", reset))
        self.assertFalse(self.q.availability("claude", "opus").usable)
        self.assertTrue(self.q.availability("claude", "sonnet").usable)     # Sonnet still available

    def test_fallback_selection_when_codex_blocked(self):
        t = req(profile="IMPLEMENT")
        self.assertEqual(select_route(self.cfg, self.q, t, approvals={}).model_key, "sol")
        self.q.record_signal(QuotaSignal("codex", "*", "LIMIT_HIT", "weekly", utcnow() + dt.timedelta(hours=5)))
        d = select_route(self.cfg, self.q, t, approvals={})
        self.assertEqual((d.kind, d.model_key), (RUN, "sonnet"))
        self.assertIn("quota blocked", d.chain[0]["verdict"])

    def test_wait_quota_when_all_blocked_with_earliest_reset(self):
        t = req(profile="IMPLEMENT")
        r1, r2 = utcnow() + dt.timedelta(hours=5), utcnow() + dt.timedelta(hours=2)
        self.q.record_signal(QuotaSignal("codex", "*", "LIMIT_HIT", "weekly", r1))
        self.q.record_signal(QuotaSignal("claude", "sonnet", "LIMIT_HIT", "weekly", r2))
        d = select_route(self.cfg, self.q, t, approvals={})
        self.assertEqual(d.kind, WAIT_QUOTA)
        self.assertLess(abs((d.until - (r2 + dt.timedelta(seconds=120))).total_seconds()), 5)   # + safety margin

    def test_fallback_disabled(self):
        cfg = cfg_for(self.tmp, fallback={"enabled": False})
        self.q.record_signal(QuotaSignal("codex", "*", "LIMIT_HIT", "weekly", utcnow() + dt.timedelta(hours=5)))
        self.assertEqual(select_route(cfg, self.q, req(), approvals={}).kind, WAIT_QUOTA)

    def test_astra_requires_approval_and_rejection_moves_on(self):
        t = req(profile="DEEP")
        d = select_route(self.cfg, self.q, t, approvals={})
        self.assertEqual((d.kind, d.model_key), (WAIT_APPROVAL, "astra"))
        d = select_route(self.cfg, self.q, t, approvals={"astra": "rejected"})
        self.assertEqual((d.kind, d.model_key), (WAIT_APPROVAL, "opus"))    # DEEP: manual Astra or Opus
        d = select_route(self.cfg, self.q, t, approvals={"astra": "approved"})
        self.assertEqual((d.kind, d.model_key), (RUN, "astra"))

    def test_opus_automatic_for_research(self):
        d = select_route(self.cfg, self.q, req(profile="RESEARCH"), approvals={})
        self.assertEqual((d.kind, d.model_key), (RUN, "opus"))
        cfg = cfg_for(self.tmp, approvals={"opus": "required"})
        self.assertEqual(select_route(cfg, self.q, req(profile="RESEARCH"), approvals={}).kind, WAIT_APPROVAL)

    def test_provider_disabled_and_auth_error(self):
        cfg = cfg_for(self.tmp, providers={"codex": {"enabled": False}})
        self.assertEqual(select_route(cfg, self.q, req(), approvals={}).model_key, "sonnet")
        self.q.set_status("claude", ProviderStatus.AUTH_ERROR, "not logged in")
        d = select_route(cfg, self.q, req(), approvals={})
        self.assertEqual(d.kind, WAIT_PROVIDER)
        self.assertIn("AUTH_ERROR", d.reason)

    def test_retry_affinity_prefers_same_model(self):
        d = select_route(self.cfg, self.q, req(profile="IMPLEMENT"), approvals={}, last_model_key="sonnet",
                         retry_affinity=True)
        self.assertEqual(d.model_key, "sonnet")

    def test_codex_snapshot_maps_real_shape(self):
        res = {"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 80, "windowDurationMins": 10080,
                                                             "resetsAt": 1791047417}, "planType": "plus"},
               "rateLimitsByLimitId": {"codex": {"limitId": "codex", "primary": {
                   "usedPercent": 80, "windowDurationMins": 10080, "resetsAt": 1791047417}, "planType": "plus"}}}
        self.q.record_codex_snapshot(res, 90, 100)
        r = self.q.row("codex")
        self.assertEqual((r["status"], r["used_percent"]), ("AVAILABLE", 80))
        self.assertTrue(r["weekly_reset_at"].startswith("2026-10-03"))
        res["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] = 100
        self.q.record_codex_snapshot(res, 90, 100)
        self.assertEqual(self.q.row("codex")["status"], "BLOCKED_WEEKLY")


class Parsing(unittest.TestCase):
    def test_result_parsing_variants(self):
        good = {k: [] for k in ("changed_files", "artifacts")}
        good.update(task_id="A/1", status="completed", summary="s")
        h, st, _ = parse_result("A/1", None, "blah\n```json\n" + json.dumps(good) + "\n```\n")
        self.assertEqual(st, MALFORMED)          # missing keys are filled but reported
        self.assertEqual(h["summary"], "s")
        self.assertEqual(h["tests_run"], [])
        h, st, p = parse_result("A/1", None, "no json here at all")
        self.assertEqual((h, st), (None, MALFORMED))
        self.assertEqual(parse_result("A/1", None, "")[1], MISSING)
        from wwii_build.prompts import RESULT_SCHEMA
        full = {k: ([] if v.get("type") == "array" else (False if v.get("type") == "boolean" else ""))
                for k, v in RESULT_SCHEMA["properties"].items()}
        full.update(task_id="A/1", status="completed", report_markdown=None)
        self.assertEqual(parse_result("A/1", full, None)[1], VALID)
        self.assertEqual(parse_result("A/1", json.dumps(full), None)[1], VALID)
        text = "Summary follows. " + json.dumps(full) + " trailing"
        self.assertEqual(parse_result("A/1", None, text)[1], VALID)

    def test_codex_limit_text(self):
        now = dt.datetime(2026, 9, 27, 10, 0, tzinfo=dt.timezone.utc)
        s = codex_limit_from_text("You've hit your usage limit. Try again at 3:40 PM.", now)
        self.assertEqual((s.kind, s.provider), ("LIMIT_HIT", "codex"))
        self.assertIsNotNone(s.reset_at)
        self.assertGreater(s.reset_at, now)
        s = codex_limit_from_text("You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage", now)
        self.assertIsNone(s.reset_at)      # no reset time -> backoff, never a guess
        self.assertIsNone(codex_limit_from_text("compilation error in foo.rs", now))

    def test_claude_rate_limit_event(self):
        s = claude_rate_limit_event({"status": "rejected", "resetsAt": 1791047417, "rateLimitType": "seven_day_opus"})
        self.assertEqual((s.kind, s.family, s.window), ("LIMIT_HIT", "opus", "weekly"))
        s = claude_rate_limit_event({"status": "rejected", "resetsAt": 1791047417, "rateLimitType": "five_hour"})
        self.assertEqual((s.family, s.window), ("*", "session"))
        s = claude_rate_limit_event({"status": "allowed", "isUsingOverage": True, "rateLimitType": "five_hour"})
        self.assertEqual(s.kind, "OVERAGE")
        self.assertIsNone(claude_rate_limit_event({"status": "allowed", "rateLimitType": "five_hour"}))
        s = claude_limit_from_text("Claude AI usage limit reached|1791047417", utcnow(), "*")
        self.assertEqual(int(s.reset_at.timestamp()), 1791047417)

    def test_model_errors_seen_live(self):
        from wwii_build.providers.limits import is_model_error
        live = ('{"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The \'gpt-6-astra\' '
                'model requires a newer version of Codex. Please upgrade to the latest app or CLI and try again."}}')
        self.assertTrue(is_model_error(live))                 # -> MODEL_UNAVAILABLE + fallback, not a retry loop
        self.assertTrue(is_model_error('[claude-code:unrecognized_model] {"model":"claude-sonnet-5-5"}'))
        self.assertFalse(is_model_error("SyntaxError: invalid syntax in model.py"))

    def test_time_phrases(self):
        now = dt.datetime(2026, 9, 27, 10, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(parse_time_phrase("in 5 minutes".replace("in ", ""), now), now + dt.timedelta(minutes=5))
        self.assertIsNone(parse_time_phrase("sometime soon", now))


class Security(unittest.TestCase):
    def test_child_env_drops_keys_and_host_session(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-secret", "OPENAI_API_KEY": "sk-x",
                                          "CLAUDE_CODE_MESSAGING_TOKEN": "t", "ANTHROPIC_BASE_URL": "http://x"}):
            env = child_env({"ANTHROPIC_API_KEY": "leak", "SAFE": "1"})
        self.assertFalse(any(k.startswith(("ANTHROPIC", "OPENAI", "CLAUDE_CODE")) for k in env))
        self.assertEqual(env["SAFE"], "1")

    def test_redact(self):
        self.assertNotIn("abcdef1234567890abcd", redact("api_key=abcdef1234567890abcd"))  # gitleaks:allow (fake key: proves redaction)
        self.assertNotIn("sk-ant-api03-xxxxxxxxxxxxxxxx", redact("key sk-ant-api03-xxxxxxxxxxxxxxxx end"))

    def test_scope_overlap(self):
        self.assertTrue(scopes_overlap(["game/runtime/simulation_runtime/"], ["game/runtime/simulation_runtime/save/"]))
        self.assertFalse(scopes_overlap(["capabilities/a/"], ["capabilities/ab/"]))
        self.assertTrue(scopes_overlap(["game/contracts.py"], ["game/contracts.py"]))


if __name__ == "__main__":
    unittest.main()


class FullAutoApproval(TmpTestCase):
    def test_everything_pending_is_approved_but_retry_loops_are_capped(self):
        from wwii_build import control
        cfg = cfg_for(self.tmp)
        db = DB(":memory:")
        now = utcnow().isoformat()
        for i in range(5):
            db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
                 ("T/x", "escalation", None, "pending", "r", now))
            db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
                 (f"T/{i}", "model", "opus", "pending", "premium", now))
        self.assertEqual(control.auto_approve_pending(db, cfg), [])          # mode off: nothing
        db.set_flag("review_auto_approve_all", "1")
        with mock.patch.object(db, "set_task_state"):
            control.auto_approve_pending(db, cfg)
        n = lambda kind, st: db.one("SELECT COUNT(*) n FROM approvals WHERE kind=? AND status=?", (kind, st))["n"]
        self.assertEqual(n("model", "approved"), 5)
        self.assertEqual(n("escalation", "approved"), 3)                     # approvals.auto_max_per_task
        self.assertEqual(n("escalation", "rejected"), 2)                     # auto_after_cap = reject: nothing waits
        self.assertEqual(n("escalation", "pending"), 0)


class PublicGraphUrlTests(unittest.TestCase):
    """The public build never reaches a local or private graph service."""

    def test_only_public_https_endpoints_are_accepted(self):
        from wwii_build.graph_rag import GraphRagError, GraphRagService
        ok = GraphRagService._public_url("https://ww2-atlas-api.example.workers.dev/", "x")
        self.assertEqual(ok, "https://ww2-atlas-api.example.workers.dev")
        self.assertEqual(GraphRagService._public_url("", "x"), "")
        for bad in ("http://ww2-atlas-api.example.workers.dev", "http://127.0.0.1:8766", "https://127.0.0.1",
                    "https://localhost:8766", "https://10.0.0.5", "https://192.168.1.2", "https://[::1]",
                    "https://neo4j.local", "bolt://127.0.0.1:7687", "file:///etc/passwd"):
            with self.assertRaises(GraphRagError, msg=bad):
                GraphRagService._public_url(bad, "x")
