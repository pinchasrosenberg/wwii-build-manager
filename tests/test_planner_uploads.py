from __future__ import annotations

import base64
from pathlib import Path

from helpers import FakeEnv, TmpTestCase, init_repo, mini_plan
from wwii_build import manual as mn
from wwii_build import planner_uploads as pu
from wwii_build.dashboard import Dashboard
from wwii_build.models import RunSpec
from wwii_build.mcp_server import Server
from wwii_build.plan_importer import request_from_row


def base(repo):
    mini_plan(repo, [{"task_id": "A/1", "owner": "a", "scope": "mod_a/"}])


class PlannerUploads(TmpTestCase):
    def test_multipart_parser_keeps_fields_and_multiple_files(self):
        boundary = "----wwii-test-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\nבנה סצנה\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"planner_files\"; filename=\"notes.md\"\r\n"
            "Content-Type: text/markdown\r\n\r\nשלג כבד\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"planner_files\"; filename=\"map.png\"\r\n"
            "Content-Type: image/png\r\n\r\n"
        ).encode() + b"\x89PNG\r\n\x1a\nmap" + f"\r\n--{boundary}--\r\n".encode()
        fields, uploads = pu.parse_post_body(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(fields["prompt"], ["בנה סצנה"])
        self.assertEqual([item.filename for item in uploads], ["notes.md", "map.png"])
        self.assertTrue(uploads[1].data.startswith(b"\x89PNG"))

    def test_uploads_are_persisted_and_only_jev_selected_items_enter_plan(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp, overrides={"jev": {"enabled": True, "require_for_all_llm_context": True}})
        scheduler = env.scheduler()
        plan_id = mn.create_plan(scheduler.db, env.cfg, "תכנן קרב לפי המפה והערות השלג", "sol")
        image = pu.IncomingUpload("planner_files", "battle-map.png", "image/png",
                                  b"\x89PNG\r\n\x1a\nmap-data")
        notes = pu.IncomingUpload("planner_files", "snow.md", "text/markdown",
                                  "שלג כבד, ראות נמוכה וקרקע קפואה".encode())
        records = pu.store(scheduler.db, env.cfg, plan_id, [image, notes])
        self.assertEqual([item["kind"] for item in records], ["image", "text"])
        candidates = pu.candidates(scheduler.db, plan_id)
        chosen = [item["id"] for item in candidates if item["attachment_kind"] == "image"]
        scheduler.svc.jev.select_context_bundles = lambda task_id, items, objective: chosen
        scheduler.svc.graph_rag.retrieve_candidates = lambda *args, **kwargs: []
        pack = scheduler._plan_pack(scheduler.db.task(plan_id))
        self.assertEqual([item["title"] for item in pack.routing["selected_attachments"]], ["battle-map.png"])
        self.assertIn("battle-map.png", pack.prompt)
        self.assertNotIn("שלג כבד", pack.prompt)
        selected = scheduler.db.q(
            "SELECT original_name,selected_at FROM planner_attachments WHERE plan_task_id=? ORDER BY id", (plan_id,))
        self.assertTrue(selected[0]["selected_at"])
        self.assertIsNone(selected[1]["selected_at"])

        req = request_from_row(scheduler.db.task(plan_id), [])
        common = dict(task=req, attempt_id=1, attempt_no=1, worktree=str(env.repo), prompt_path="prompt.md",
                      run_dir=str(self.tmp / "run"), result_schema_path="schema.json", kind="plan",
                      attachment_paths=[records[0]["path"]], image_paths=[records[0]["path"]])
        codex = RunSpec(model=env.cfg.model("sol"), **common)
        codex_args = scheduler.svc.providers["codex"].build_command(codex)
        self.assertEqual(codex_args[codex_args.index("--image") + 1], records[0]["path"])
        claude = RunSpec(model=env.cfg.model("sonnet"), **common)
        claude_args = scheduler.svc.providers["claude"].build_command(claude)
        self.assertEqual(claude_args[claude_args.index("--add-dir") + 1], str(Path(records[0]["path"]).parent))

    def test_dashboard_exposes_drop_zone_and_upload_history(self):
        base(init_repo(self.tmp))
        env = FakeEnv(self.tmp)
        scheduler = env.scheduler()
        dash = Dashboard(env.cfg)
        dash.db = scheduler.db
        dash.wake = lambda: None
        upload = pu.IncomingUpload("planner_files", "brief.md", "text/markdown", b"episode brief")
        message = dash.action({"action": "plan", "prompt": "build an episode", "model_key": "sol"}, [upload])
        self.assertIn("עם 1 קבצים", message)
        overview = dash.page_overview(None)
        plan_page = dash.page_plan(None)
        for page in (overview, plan_page):
            self.assertIn("enctype='multipart/form-data'", page)
            self.assertIn("upload-zone", page)
            self.assertIn("name='planner_files'", page)
        self.assertIn("brief.md", plan_page)
        self.assertIn("רק פריטים ש־Jev יבחר", plan_page)

        server = Server.__new__(Server)
        server.dashboard = dash
        result = server.call("planner_request", {
            "prompt": "use the attached visual", "model_key": "sol",
            "attachments": [{"name": "reference.png", "media_type": "image/png",
                             "content_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nref").decode()}],
        })
        self.assertEqual((result["attachment_count"], result["attachment_gate"]), (1, "jev"))
        self.assertEqual(scheduler.db.one(
            "SELECT kind FROM planner_attachments WHERE plan_task_id=?", (result["task_id"],))["kind"], "image")
