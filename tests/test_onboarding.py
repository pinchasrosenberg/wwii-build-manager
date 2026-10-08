"""System onboarding: manifest -> RAG context files, Delivers, context sources, graph ingest (idempotent)."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from wwii_build import onboarding as ob
from wwii_build.config import DEFAULTS, Config
from wwii_build.db import DB

MANIFEST = '''
[system]
id = "demo"
title = "Demo system"
context_dir = "context/systems/demo"
description = "A tiny system."
notes = ["deterministic"]

[[components]]
deliver_id = "demo.ui"
title = "UI"
owner = "ui_owner"
domain = "ui"
root = "src"
description = "Front end."
depends_on = ["demo.core"]
graph_access = "none"

[[components]]
deliver_id = "demo.core"
title = "Core"
owner = "core_owner"
domain = "core"
execution_kind = "deterministic"
root = "src"
description = "Core library."
docs = ["README.md"]
code = ["*.py", "*.js"]
run = ["python -m core"]
ports = [9000]
discover = [
  {kind = "py_functions", glob = "*.py", group = "פונקציות"},
  {kind = "files", glob = "*.js", group = "Front", exclude = ["skip*.js"]},
]
capabilities = [{group = "פקודות", name = "#run", description = "run command"}]
'''


class FakeGraph:
    def __init__(self):
        self.calls, self.entities, self.relationships = [], {}, []

    def transport(self, method, path, payload, timeout):
        self.calls.append((method, path))
        if path == "/ingest/structured":
            for e in payload["entities"]:
                self.entities[e["name"]] = e
            names = set(self.entities)
            ok_rels = [r for r in payload["relationships"] if r["from_name"] in names and r["to_name"] in names]
            self.relationships += ok_rels
            return {"ok": True, "entities": len(payload["entities"]), "relationships": len(ok_rels)}
        return {"ok": True, "mode": "test"}


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "README.md").write_text("# Core\n\nDoes things.\n")
        (self.repo / "src" / "core.py").write_text('"""Core module."""\n\ndef run(x, y):\n    """Run it."""\n\ndef _hidden():\n    pass\n')
        (self.repo / "src" / "ui.js").write_text("// UI entry\nexport function render(state) {}\nconst draw = (a) => a;\n")
        (self.repo / "src" / "skip_me.js").write_text("// excluded by the discover rule\n")
        self.manifest = self.repo / "demo.toml"
        self.manifest.write_text(MANIFEST)
        self.cfg = Config(repo=self.repo, data=copy.deepcopy(DEFAULTS), path=None)
        self.db = DB(":memory:")

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_onboard_writes_context_delivers_sources_edges_and_ingests_once(self):
        graph = FakeGraph()
        rep = ob.onboard(self.cfg, self.db, self.manifest, graph_service=graph)
        core = (self.repo / "context/systems/demo/demo.core.md").read_text()
        self.assertIn("`def run(x, y)` — Run it.", core)
        self.assertNotIn("_hidden", core)
        self.assertIn("`render`", core)
        self.assertIn("python -m core", core)
        self.assertTrue((self.repo / "context/systems/demo/demo.index.md").is_file())
        row = self.db.one("SELECT * FROM deliver_catalog WHERE deliver_id='demo.core'")
        self.assertEqual((row["source_kind"], row["execution_kind"], row["packet"]),
                         ("system_manifest", "deterministic", "demo"))
        self.assertEqual(self.db.one("SELECT access_mode FROM deliver_graph_access WHERE deliver_id='demo.ui'")[0], "none")
        self.assertTrue(self.db.one("SELECT 1 FROM deliver_listener_edges WHERE source_deliver_id='demo.core' "
                                    "AND target_deliver_id='demo.ui' AND edge_type='prerequisite'"))
        src = self.db.one("SELECT * FROM context_sources WHERE source_key='system:demo:demo.core'")
        self.assertEqual((src["origin_kind"], src["deliver_id"]), ("system_context", "demo.core"))
        # capabilities and sub-capabilities
        caps = {r["name"]: dict(r) for r in self.db.q("SELECT * FROM deliver_capabilities WHERE deliver_id='demo.core'")}
        self.assertEqual(set(caps), {"run", "ui", "#run"})                     # _hidden and skip*.js are excluded
        self.assertEqual(caps["run"]["description"], "Run it.")
        self.assertIn("## יכולות ותתי־יכולות (3)", core)
        # structured graph tree: system -> deliver -> capability -> sub-capability, plus dependencies
        self.assertTrue(rep["graph"]["ok"])
        self.assertEqual(graph.entities["system:demo"]["type"], "SYSTEM")
        self.assertEqual(graph.entities["demo.core"]["type"], "DELIVER")
        sub = graph.entities[caps["run"]["capability_id"]]
        self.assertEqual(sub["type"], "SUBCAPABILITY")
        group_id = caps["run"]["capability_id"].rsplit("/", 1)[0]
        self.assertEqual(graph.entities[group_id]["type"], "CAPABILITY")
        kinds = {(r["from_name"], r["to_name"], r["rel_type"]) for r in graph.relationships}
        self.assertIn(("system:demo", "demo.core", "HAS_COMPONENT"), kinds)
        self.assertIn(("demo.core", group_id, "HAS_CAPABILITY"), kinds)
        self.assertIn((group_id, caps["run"]["capability_id"], "HAS_SUBCAPABILITY"), kinds)
        self.assertIn(("demo.ui", "demo.core", "DEPENDS_ON"), kinds)
        sent = len(graph.calls)
        ob.onboard(self.cfg, self.db, self.manifest, graph_service=graph)      # unchanged: nothing re-sent
        self.assertEqual(len(graph.calls), sent)
        (self.repo / "src" / "core.py").write_text('"""Core module."""\n\ndef run(x, y):\n    """Run it."""\n\ndef stop():\n    """Stop it."""\n')
        rep = ob.onboard(self.cfg, self.db, self.manifest, graph_service=graph)
        self.assertGreater(len(graph.calls), sent)                             # changed tree is re-sent
        self.assertIn("stop", {r["name"] for r in self.db.q("SELECT name FROM deliver_capabilities WHERE active=1")})
        self.assertEqual([(s["system_id"], s["capabilities"]) for s in ob.systems(self.db)], [("demo", 4)])
        self.assertEqual(self.db.get_flag("onboarding_title:demo"), "Demo system")

    def test_output_is_byte_stable(self):
        m = ob.load_manifest(self.manifest)
        self.assertEqual(ob.render_component(self.cfg, m, m.components[0]),
                         ob.render_component(self.cfg, m, m.components[0]))

    def test_validation(self):
        for bad, needle in ((MANIFEST.replace('execution_kind = "deterministic"', 'execution_kind = "magic"'), "execution_kind"),
                            (MANIFEST.replace('depends_on = ["demo.core"]', 'depends_on = ["ghost"]'), "unknown Delivers"),
                            (MANIFEST.replace('context_dir = "context/systems/demo"', 'context_dir = "../out"'), "context_dir"),
                            (MANIFEST.replace('title = "UI"', 'title = "UI"\ncolour = "red"'), "unknown keys")):
            self.manifest.write_text(bad)
            with self.assertRaises(ob.OnboardingError) as cm:
                ob.onboard(self.cfg, self.db, self.manifest, graph=False)
            self.assertIn(needle, str(cm.exception))

    def test_dry_run_writes_nothing(self):
        ob.onboard(self.cfg, self.db, self.manifest, dry_run=True)
        self.assertFalse((self.repo / "context").exists())
        self.assertIsNone(self.db.one("SELECT 1 FROM deliver_catalog"))

    def test_real_ww2_manifest_is_valid(self):
        m = ob.load_manifest(ob.SYSTEMS_DIR / "ww2_atlas.toml")
        self.assertEqual(m.system_id, "ww2_atlas")
        self.assertGreaterEqual(len(m.components), 10)


class GraphChunkTests(unittest.TestCase):
    def test_chunks_fit_the_service_window_keep_the_title_and_lose_nothing(self):
        body = "# Title\n\n" + "\n".join(f"## Section {i}\n" + ("word " * 300) for i in range(8))
        parts = ob.graph_chunks(body)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= ob.GRAPH_CHUNK_CHARS for p in parts))
        self.assertTrue(all(p.startswith("# Title") for p in parts))
        joined = "".join(parts)
        self.assertTrue(all(f"## Section {i}" in joined for i in range(8)))

    def test_small_file_is_one_part(self):
        self.assertEqual(ob.graph_chunks("# T\n\nshort"), ["# T\n\nshort"])
