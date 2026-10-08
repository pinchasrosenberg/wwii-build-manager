"""Daily model discovery changes only eligible, locally usable model profiles."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import FakeEnv, init_repo, mini_plan
from wwii_build.config import Config, DEFAULTS, load_config
from wwii_build.db import DB
from wwii_build.explanations import deliver_description_he, deliver_implementation_he, task_he
from wwii_build.manual import create_tasks
from wwii_build.model_watch import ModelWatch, read_overrides


OPENAI = "gpt-6.1-sol gpt-6-luna"
CLAUDE = "claude-sonnet-5-5 claude-haiku-4-5-20251001"


class ModelWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.cfg = Config(repo=self.repo, data=copy.deepcopy(DEFAULTS), path=None)
        self.cfg.data["models"]["sonnet"]["model"] = "claude-sonnet-5"   # an older install the watcher upgrades
        self.cfg.state_dir.mkdir()
        self.db = DB(self.cfg.db_path)

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    def test_daily_check_updates_claude_and_waits_for_local_codex(self):
        def page(url):
            return OPENAI if "openai.com" in url else CLAUDE

        with mock.patch("wwii_build.model_watch._official_page", side_effect=page), \
             mock.patch("wwii_build.model_watch._codex_available", return_value={"gpt-5.6-sol"}), \
             mock.patch("wwii_build.model_watch._claude_accepts_model", return_value=True):
            result = ModelWatch(self.cfg, self.db).check()
            self.assertEqual(ModelWatch(self.cfg, self.db).check(), result)

        self.assertEqual(result["updated"]["sonnet"]["model"], "claude-sonnet-5-5")
        self.assertEqual(result["waiting_for_local_access"]["sol"], "gpt-6.1-sol")
        self.assertEqual(self.cfg.model("sonnet").model, "claude-sonnet-5-5")
        self.assertEqual(self.cfg.model("sol").model, "gpt-5.6-sol")
        self.assertEqual(load_config(self.repo).model("sonnet").model, "claude-sonnet-5-5")
        self.assertTrue(ModelWatch(self.cfg, self.db).rollback_on_model_error("sonnet", "claude-sonnet-5-5"))
        self.assertEqual(self.cfg.model("sonnet").model, "claude-sonnet-5")
        self.assertNotIn("sonnet", read_overrides(self.cfg))
        self.assertEqual(read_overrides(self.cfg)["_rejected"]["sonnet"], "claude-sonnet-5-5")
        self.assertEqual(ModelWatch(self.cfg, self.db).status()["rolled_back"]["sonnet"]["restored_model"],
                         "claude-sonnet-5")
        with mock.patch("wwii_build.model_watch._official_page", side_effect=page), \
             mock.patch("wwii_build.model_watch._codex_available", return_value=set()), \
             mock.patch("wwii_build.model_watch._claude_accepts_model", return_value=True):
            retry = ModelWatch(self.cfg, self.db).check(force=True)
        self.assertNotIn("sonnet", retry["updated"])
        self.assertEqual(retry["waiting_for_local_access"]["sonnet"], "claude-sonnet-5-5")

    def test_explicit_model_config_is_never_overwritten(self):
        config_path = self.cfg.state_dir / "config.toml"
        config_path.write_text('[models.sonnet]\nmodel = "claude-sonnet-5"\n')
        self.cfg.path = config_path
        with mock.patch("wwii_build.model_watch._official_page", return_value=CLAUDE), \
             mock.patch("wwii_build.model_watch._codex_available", return_value=set()), \
             mock.patch("wwii_build.model_watch._claude_accepts_model", return_value=True):
            result = ModelWatch(self.cfg, self.db).check()
        self.assertNotIn("sonnet", result["updated"])


class ExplanationTests(unittest.TestCase):
    def test_existing_deliver_translation_and_live_implementation(self):
        db = DB(":memory:")
        cfg = Config(repo=Path("/tmp"), data=copy.deepcopy(DEFAULTS), path=None)
        deliver = {"deliver_id": "weather.snow_research", "description":
                   "Resolve snow type, depth/range, timing, surface condition and uncertainty from scoped historical evidence.",
                   "execution_kind": "llm_research", "implementation_ref": "planned:weather", "availability": "planned"}
        self.assertIn("ראיות היסטוריות", deliver_description_he(cfg, db, deliver))
        before = deliver_implementation_he(db, deliver)
        deliver["implementation_ref"] = "game/weather/snow.py"
        deliver["availability"] = "available"
        after = deliver_implementation_he(db, deliver)
        self.assertNotEqual(before, after)
        self.assertIn("game/weather/snow.py", after)
        deliver["description"] = "Changed purpose"
        self.assertIn("נדרש הסבר בעברית", deliver_description_he(cfg, db, deliver))
        db.conn.close()

    def test_manual_description_is_hebrew_and_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = init_repo(root)
            mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "mod_a/"}])
            env = FakeEnv(root)
            db = DB(env.cfg.db_path)
            [tid] = create_tasks(db, env.cfg, [{"title": "Tank HUD", "instructions": "Build the HUD",
                                                "description_he": "בונה תצוגת מצב לטנק.",
                                                "model_key": "sonnet", "write_scope": ["hud/"]}])
            self.assertEqual(task_he(env.cfg, db.task(tid)), "בונה תצוגת מצב לטנק.")
            db.conn.close()
