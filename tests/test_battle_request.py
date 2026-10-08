"""Battle request: one action creates the battle-builder task chain (synthetic data, fake CLIs, no network)."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
from pathlib import Path

from helpers import MANAGER, FakeEnv, TmpTestCase, init_repo, mini_plan

import battle_stage_check as check
from wwii_build import battle_request as br
from wwii_build import cli
from wwii_build import manual as mn
from wwii_build.app_data import battle_request_options
from wwii_build.dashboard import Dashboard
from wwii_build.mcp_server import TOOLS, Server

STAGES = ["evidence", "map_research", "web_research", "reconstruct", "package"]
HEBREW = re.compile(r"[֐-׿]")
ROUTING = {"EXTRACT": ["haiku"], "IMPLEMENT": ["sol", "sonnet"], "RESEARCH": ["opus", "sonnet"], "DESIGN": ["sonnet", "sol"],
           "MANUAL": ["sol", "sonnet"]}


class Base(TmpTestCase):
    def setUp(self):
        super().setUp()
        mini_plan(init_repo(self.tmp), [{"task_id": "A/1", "owner": "a", "scope": "mod_a/"}])
        self.env = FakeEnv(self.tmp, overrides={"routing": ROUTING})
        self.sched = self.env.scheduler()
        self.db, self.cfg = self.sched.db, self.env.cfg

    def request(self, **over):
        args = {"title": "Brécourt Manor assault", "date": "1944-06-06", "bbox": "-1.3,49.3,-1.1,49.5"}
        return br.request_battle(self.db, self.cfg, **{**args, **over})

    def task(self, tid):
        row = self.db.task(tid)
        return row, json.loads(row["extra"]), json.loads(row["write_scope"]), json.loads(row["acceptance"])


class ChainShape(Base):
    def test_one_request_creates_the_five_stage_chain(self):
        result = self.request()
        self.assertTrue(result["created"])
        self.assertEqual(result["battle_key"], "brecourt-manor-assault")
        ids = result["task_ids"]
        self.assertEqual(ids, [f"MANUAL/battle-brecourt-manor-assault-{s}" for s in STAGES])
        for tid in ids:
            row, extra, _, acceptance = self.task(tid)
            self.assertEqual((row["kind"], row["source"], row["mode"]), ("task", "manual", "build"))
            self.assertEqual(extra["task_target"], "project")
            self.assertFalse(extra["system_task"])
            self.assertEqual(extra["battle_request"]["battle_key"], "brecourt-manor-assault")
            self.assertTrue(HEBREW.search(extra["description_he"]), tid)
            self.assertIn("Brécourt Manor assault", extra["title"] + extra["instructions"])
            self.assertTrue(acceptance, tid)
            self.assertTrue(all(a["argv"][:2] == ["/bin/sh", "-c"] for a in acceptance))
        self.assertEqual(self.db.q("SELECT 1 FROM event_log WHERE event='BATTLE_REQUESTED'")[0][0], 1)

    def test_dependencies_follow_the_chain(self):
        ids = {s: f"MANUAL/battle-k-{s}" for s in STAGES}
        self.request(battle_key="k")
        deps = {s: set(self.db.deps(ids[s])) for s in STAGES}
        self.assertEqual(deps["evidence"], set())
        self.assertEqual(deps["map_research"], {ids["evidence"]})
        self.assertEqual(deps["web_research"], {ids["evidence"], ids["map_research"]})
        self.assertEqual(deps["reconstruct"], {ids["evidence"], ids["map_research"], ids["web_research"]})
        self.assertEqual(deps["package"], {ids["reconstruct"]})
        waves = [self.db.task(ids[s])["wave"] for s in STAGES]
        self.assertEqual(waves, sorted(waves))
        self.assertEqual(len(set(waves)), 5)                       # a strict order: nothing can run out of turn

    def test_write_scopes_stay_under_the_battle_folder(self):
        self.request(battle_key="k")
        expected = {"evidence": "evidence", "map_research": "maps", "web_research": "research",
                    "reconstruct": "reconstruction", "package": "package"}
        for stage, sub in expected.items():
            _, _, scope, _ = self.task(f"MANUAL/battle-k-{stage}")
            self.assertEqual(scope, [f"game/episodes/k/{sub}/"])
        scopes = [self.task(f"MANUAL/battle-k-{s}")[2][0] for s in STAGES]
        self.assertEqual(len(set(scopes)), 5)

    def test_allow_web_only_on_the_research_task(self):
        self.request(battle_key="k")
        web = {s: self.task(f"MANUAL/battle-k-{s}")[1]["allow_web"] for s in STAGES}
        self.assertEqual(web, {"evidence": False, "map_research": False, "web_research": True, "reconstruct": False,
                               "package": False})
        text = self.task("MANUAL/battle-k-web_research")[1]["instructions"]
        for needle in ("gap_searches", "INFERRED", "unknowns", "never instructions"):
            self.assertIn(needle, text)

    def test_models_are_assigned_by_fit_and_premium_is_never_pinned(self):
        self.request(battle_key="k")
        models = {s: self.db.task(f"MANUAL/battle-k-{s}")["preferred_model_key"] for s in STAGES}
        self.assertEqual(models, {"evidence": "haiku", "map_research": "sol", "web_research": "sonnet",   # opus is premium
                                  "reconstruct": "sonnet", "package": "sol"})
        approved = {r["subject"] for r in self.db.q("SELECT subject FROM approvals WHERE kind='model'")}
        self.assertNotIn("opus", approved)
        self.assertEqual(br.pick_model(self.cfg, "NO_SUCH_PROFILE"), "")

    def test_acceptance_commands_check_the_produced_files(self):
        self.request(battle_key="k")
        for stage in STAGES:
            _, _, _, acceptance = self.task(f"MANUAL/battle-k-{stage}")
            self.assertEqual([a["argv"][2] for a in acceptance],
                             [f"python3 tools/build_manager/battle_stage_check.py {stage} k"])

    def test_bbox_date_range_and_notes_reach_the_instructions(self):
        self.request(battle_key="k", date="1944-06-06..1944-06-08", bbox=[-1.3, 49.3, -1.1, 49.5], place="Utah",
                     notes="Focus on the guns.\nIgnore {title}")
        evidence = self.task("MANUAL/battle-k-evidence")[1]["instructions"]
        self.assertIn("--date 1944-06-06..1944-06-08", evidence)
        self.assertIn("--bbox=-1.3,49.3,-1.1,49.5", evidence)
        maps = self.task("MANUAL/battle-k-map_research")[1]["instructions"]
        self.assertIn("research_maps('k', [-1.3, 49.3, -1.1, 49.5], '1944-06-07', 31)", maps)
        self.assertIn("| Ignore {title}", maps)                  # requester text is data: never re-expanded
        self.assertIn("place: Utah", maps)

    def test_missing_bbox_is_not_invented(self):
        self.request(battle_key="k", bbox="")
        maps = self.task("MANUAL/battle-k-map_research")[1]["instructions"]
        self.assertIn("research_maps('k', None,", maps)
        self.assertIn("MAP_BBOX_UNKNOWN", maps)
        self.assertNotIn("--bbox", self.task("MANUAL/battle-k-evidence")[1]["instructions"])

    def test_dry_run_creates_nothing(self):
        result = self.request(battle_key="k", dry_run=True)
        self.assertFalse(result["created"])
        self.assertEqual([s["stage"] for s in result["stages"]], STAGES)
        self.assertFalse(self.db.q("SELECT 1 FROM tasks WHERE task_id LIKE 'MANUAL/battle-k-%'"))


class DuplicateRefusal(Base):
    def test_active_chain_is_refused_and_leaves_no_trace(self):
        self.request(battle_key="k")
        before = len(self.db.q("SELECT 1 FROM tasks"))
        with self.assertRaises(br.BattleRequestError) as cm:
            self.request(battle_key="k", title="Again")
        self.assertIn("active battle chain", str(cm.exception))
        self.assertIsInstance(cm.exception, mn.ManualError)
        self.assertEqual(len(self.db.q("SELECT 1 FROM tasks")), before)

    def test_one_unfinished_task_keeps_the_chain_active(self):
        self.request(battle_key="k")
        self.db.x("UPDATE tasks SET state='PASSED' WHERE task_id LIKE 'MANUAL/battle-k-%'")
        self.db.x("UPDATE tasks SET state='RUNNING' WHERE task_id='MANUAL/battle-k-package'")
        with self.assertRaises(br.BattleRequestError):
            self.request(battle_key="k")

    def test_other_battles_and_prefix_keys_are_independent(self):
        self.request(battle_key="a")
        self.request(battle_key="a-b")                           # 'a-b' is not 'a'
        self.request(battle_key="c")
        self.assertEqual({t["battle_key"] for t in br.chain_tasks(self.db)}, {"a", "a-b", "c"})

    def test_a_finished_chain_can_be_requested_again(self):
        self.request(battle_key="k")
        self.db.x("UPDATE tasks SET state='PASSED' WHERE task_id LIKE 'MANUAL/battle-k-%'")
        again = self.request(battle_key="k")
        self.assertEqual(again["task_ids"][0], "MANUAL/battle-k-evidence-2")
        self.assertEqual(len(br.active_chain(self.db, "k")), 5)
        with self.assertRaises(br.BattleRequestError):
            self.request(battle_key="k")


class Normalization(Base):
    def test_key_generation_and_validation(self):
        self.assertEqual(br.generate_key("Brécourt Manor assault"), "brecourt-manor-assault")
        self.assertEqual(br.generate_key("  Hill 400 -- (Hürtgen)!  "), "hill-400-hurtgen")
        self.assertRegex(br.generate_key("קרב ברקור", "1944-06-06"), r"^battle-[0-9a-f]{8}$")
        self.assertEqual(br.generate_key("קרב", "x"), br.generate_key("קרב", "x"))
        self.assertLessEqual(len(br.generate_key("word " * 30)), br.KEY_MAX)
        for bad in ("Upper", "-lead", "has space", "a/b", "x" * 41, "../x"):
            with self.assertRaises(br.BattleRequestError, msg=bad):
                br.normalize_request("t", bad, "1944-06-06")

    def test_dates(self):
        n = br.normalize_request("t", "k", "1944-06-06")
        self.assertEqual((n.date_text, n.window_days(30)), ("1944-06-06", 30))
        n = br.normalize_request("t", "k", "1944-06-06/1944-06-09")
        self.assertEqual((n.date_text, str(n.date_mid), n.window_days(30)), ("1944-06-06..1944-06-09", "1944-06-07", 32))
        self.assertEqual(br.normalize_request("t", "k", "1944-06-06", "1944-06-07").date_text, "1944-06-06..1944-06-07")
        for bad in ("", "1944-13-01", "June 6", "1944-06-06..", "1944-06-06..1944-06-01", "1944-06-06..1944-06-07..1944-06-08"):
            with self.assertRaises(br.BattleRequestError, msg=bad):
                br.normalize_request("t", "k", bad)
        with self.assertRaises(br.BattleRequestError):
            br.normalize_request("t", "k", "1944-06-06..1944-06-07", "1944-06-08")
        with self.assertRaises(br.BattleRequestError):
            br.normalize_request("", "k", "1944-06-06")

    def test_bbox(self):
        self.assertEqual(br.parse_bbox("-1.3, 49.3 ,-1.1;49.5"), (-1.3, 49.3, -1.1, 49.5))
        self.assertIsNone(br.parse_bbox(""))
        for bad in ("1,2,3", "1,2,3,4,5", "a,b,c,d", "2,0,1,1", "0,2,1,1", "-200,0,1,1", "0,-91,1,1", [1, 2, 3]):
            with self.assertRaises(br.BattleRequestError, msg=str(bad)):
                br.parse_bbox(bad)

    def test_invalid_request_creates_nothing(self):
        with self.assertRaises(br.BattleRequestError):
            self.request(date="")
        self.assertFalse(self.db.q("SELECT 1 FROM tasks WHERE source='manual'"))


class Templates(Base):
    def write(self, text):
        path = self.tmp / "templates.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_shipped_templates_are_valid_and_have_the_required_shape(self):
        data = br.load_templates()
        self.assertEqual([s["id"] for s in data["stage"]], STAGES)
        self.assertEqual([s["id"] for s in data["stage"] if s.get("allow_web")], ["web_research"])
        self.assertEqual(data["request"]["episodes_root"], "game/episodes")
        self.assertNotIn("[system]", (MANAGER / "systems/battle_request_templates.toml").read_text())

    def test_edited_templates_change_the_next_chain_without_code(self):
        text = (MANAGER / "systems/battle_request_templates.toml").read_text(encoding="utf-8")
        edited = self.write(text.replace('fit = "EXTRACT"', 'fit = "IMPLEMENT"').replace("תיק ראיות — {title}", "ראיות — {title}"))
        self.request(battle_key="k", templates=br.load_templates(edited))
        self.assertEqual(self.db.task("MANUAL/battle-k-evidence")["preferred_model_key"], "sol")
        self.assertIn("ראיות — Brécourt", self.db.task("MANUAL/battle-k-evidence")["title"])

    def test_bad_templates_are_refused(self):
        text = (MANAGER / "systems/battle_request_templates.toml").read_text(encoding="utf-8")
        no_maps = re.sub(r'\[\[stage\]\]\nid = "map_research".*?(?=\[\[stage\]\])', "", text, flags=re.S)
        cases = [no_maps, text.replace('depends_on = ["evidence"]', 'depends_on = ["later"]', 1),
                 text.replace('subdir = "maps"', 'subdir = "../maps"'), text.replace('episodes_root = "game/episodes"', 'episodes_root = "../x"'),
                 text.replace('acceptance = ["python3 tools/build_manager/battle_stage_check.py evidence {battle_key}"]', "acceptance = []"),
                 "[request]\n", "not toml ["]
        for index, body in enumerate(cases):
            with self.assertRaises(br.BattleRequestError, msg=str(index)):
                br.load_templates(self.write(body))

    def test_templates_are_not_listed_as_onboarding_manifests(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.cmd_onboard(argparse.Namespace(list=True, manifest=None), self.cfg)
        self.assertNotIn("battle_request_templates", buf.getvalue())


class EntryPoints(Base):
    def test_cli(self):
        args = argparse.Namespace(title="Hill 400", key="", date="1944-11-19", date_end=None, bbox="-6.3,50.7,6.4,50.8",
                                  place="", notes="", dry_run=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.cmd_battle_request(args, self.cfg), 0)
        self.assertIn("would create the chain for hill-400", out.getvalue())
        self.assertIn("web=yes", out.getvalue())
        args.dry_run = False
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.cmd_battle_request(args, self.cfg), 0)
        self.assertEqual(len(br.chain_tasks(cli._db(self.cfg), "hill-400")), 5)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.cmd_battle_request(args, self.cfg), 1)
        self.assertIn("active battle chain", err.getvalue())
        parser_help = io.StringIO()
        with contextlib.redirect_stdout(parser_help), self.assertRaises(SystemExit):
            cli.main(["battle-request", "--help"])
        self.assertIn("--bbox", parser_help.getvalue())

    def test_mcp_tool(self):
        tool = next(t for t in TOOLS if t["name"] == "battle_request")
        self.assertEqual(tool["inputSchema"]["required"], ["title", "date"])
        dash = Dashboard(self.cfg)
        dash.db = self.db
        dash.wake = lambda: None
        server = Server.__new__(Server)
        server.dashboard = dash
        result = server.call("battle_request", {"title": "Hill 400", "date": "1944-11-19", "bbox": [-6.3, 50.7, 6.4, 50.8]})
        self.assertEqual(len(result["task_ids"]), 5)
        self.assertEqual(json.loads(json.dumps(result, default=str))["battle_key"], "hill-400")
        with self.assertRaises(br.BattleRequestError):
            server.call("battle_request", {"title": "Hill 400", "date": "1944-11-19"})

    def test_classic_form_and_live_action_share_one_code_path(self):
        dash = Dashboard(self.cfg)
        dash.db = self.db
        dash.wake = lambda: None
        page = dash.page_battle(None)
        for needle in ("name='action' value='battle_request'", "name='title'", "name='battle_key'", "name='date'", "name='bbox'",
                       "name='place'", "name='notes'", "game.battle_builder.map_research", "בקשת קרב", "href='/battle'"):
            self.assertIn(needle, page + dash._layout("x", "", None))
        message = dash.action({"action": "battle_request", "title": "Brécourt Manor assault", "date": "1944-06-06"})
        self.assertIn("MANUAL/battle-brecourt-manor-assault-evidence", message)
        refused = dash.action({"action": "battle_request", "title": "Brécourt Manor assault", "date": "1944-06-06"})
        self.assertTrue(refused.startswith("error:") and "active battle chain" in refused, refused)
        ok, text = dash.run_form({"action": "battle_request", "title": "Other", "battle_key": "other", "date": "1944-06-07",
                                  "bbox": "bad"}, {})
        self.assertFalse(ok)
        self.assertIn("bbox", text)
        self.assertIn("brecourt-manor-assault", dash.page_battle(None))          # the created chain is listed
        options = battle_request_options(dash)
        self.assertEqual([s["stage"] for s in options["stages"]], STAGES)
        self.assertEqual([s["stage"] for s in options["stages"] if s["allow_web"]], ["web_research"])
        self.assertEqual(options["chains"][0]["battle_key"], "brecourt-manor-assault")


class StageCheck(TmpTestCase):
    """battle_stage_check.py on synthetic episode files."""

    def put(self, rel, value):
        path = self.tmp / "game/episodes/k" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return path

    def problems(self, stage):
        return check.check_stage(stage, "k", self.tmp)

    def test_missing_files_fail_every_stage(self):
        for stage in STAGES:
            self.assertTrue(self.problems(stage), stage)

    def test_evidence_and_maps(self):
        self.put("evidence/dossier.json", {"battle_key": "k", "facts": [], "unknowns": [{"id": "u1"}], "sources": []})
        self.assertTrue(self.problems("evidence"))                          # EVIDENCE.md missing
        self.put("evidence/EVIDENCE.md", "# synthetic")
        self.assertEqual(self.problems("evidence"), [])
        self.put("evidence/dossier.json", {"battle_key": "other", "facts": [], "unknowns": [], "sources": []})
        self.assertTrue(any("battle_key" in p for p in self.problems("evidence")))
        self.put("maps/map_evidence.json", {"maps": [], "observations": [], "gaps": [], "acquisition": []})
        self.assertTrue(any("gap" in p for p in self.problems("map_research")))       # no map and no recorded gap
        self.put("maps/map_evidence.json", {"maps": [], "observations": [], "gaps": ["MAP_COVERAGE_GAP"], "acquisition": []})
        self.assertEqual(self.problems("map_research"), [])

    def research(self, **over):
        data = {"schema_version": 1, "battle_key": "k", "units": [{"provenance": "SOURCED", "citation_ids": ["c1"]}], "events": [],
                "citations": [{"id": "c1", "url": "https://example.org/x", "quote": "synthetic quote"}],
                "gap_searches": [{"gap_id": "u1", "query": "q", "outcome": "NOT_FOUND"}],
                "inferred": [{"id": "i1", "provenance": "INFERRED", "rationale": "doctrine", "confidence": 0.4}]}
        self.put("evidence/dossier.json", {"battle_key": "k", "facts": [], "unknowns": [{"id": "u1"}], "sources": []})
        self.put("research/research.json", {**data, **over})

    def test_research_is_gap_driven_and_cited(self):
        self.research()
        self.assertEqual(self.problems("web_research"), [])
        self.research(gap_searches=[])
        self.assertTrue(any("u1" in p for p in self.problems("web_research")))
        self.research(citations=[{"id": "c1", "url": "ftp://x", "quote": ""}])
        self.assertEqual(len(self.problems("web_research")), 2)
        self.research(inferred=[{"id": "i1", "provenance": "SOURCED", "rationale": "", "confidence": 3}])
        self.assertEqual(len(self.problems("web_research")), 3)
        self.research(units=[{"provenance": "SOURCED", "citation_ids": ["nope"]}])
        self.assertTrue(any("citation ids" in p for p in self.problems("web_research")))

    def test_reconstruction_needs_provenance_labels(self):
        self.put("reconstruction/reconstruction.json", {"items": [{"provenance": "SOURCED"}, {"nested": {"provenance": "INFERRED"}}]})
        self.assertEqual(self.problems("reconstruct"), [])
        self.put("reconstruction/reconstruction.json", {"items": [{"provenance": "GUESS"}]})
        self.assertTrue(self.problems("reconstruct"))
        self.put("reconstruction/reconstruction.json", {"items": []})
        self.assertTrue(any("provenance" in p for p in self.problems("reconstruct")))

    def test_package_manifest_locks_the_input_hashes(self):
        inputs = {}
        for rel in check.INPUTS:
            path = self.put(rel, {"synthetic": rel})
            inputs[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.put("package/episode.json", "{}")
        manifest = {"schema_version": 1, "battle_key": "k", "inputs": inputs, "files": ["episode.json"]}
        self.put("package/package_manifest.json", manifest)
        self.assertEqual(self.problems("package"), [])
        self.put("reconstruction/reconstruction.json", {"synthetic": "changed"})        # the package is now stale
        self.assertTrue(any("stale" in p for p in self.problems("package")))
        self.put("package/package_manifest.json", {**manifest, "files": ["../escape.json"]})
        self.assertTrue(any("outside" in p for p in self.problems("package")))

    def test_cli_exit_codes(self):
        self.assertEqual(check.main(["evidence", "k", "--root", str(self.tmp)]), 1)
        self.assertEqual(check.check_stage("evidence", "../x", self.tmp)[0][:10], "battle_key")
        self.assertEqual(check.check_stage("nope", "k", self.tmp)[0][:13], "unknown stage")
