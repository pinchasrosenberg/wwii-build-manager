"""Browser app shell: GET / (token injected), GET /app/<file> (safe static serving) and the /classic/... pages.

Rows written here are synthetic fixtures. The client modules are also unit-tested under node (tests/js) when node exists.
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import unittest
from pathlib import Path

from helpers import FakeEnv, TmpTestCase, init_repo
from test_ws_transport import TinyClient

from wwii_build.dashboard import APP_DIR, CSS, Dashboard, classic_html, classic_url, static_file

NOW = "2026-01-01T00:00:00+00:00"
HERE = Path(__file__).resolve().parent


class PureHelpers(unittest.TestCase):
    def test_css_lives_in_app_css_and_old_pages_use_it(self):
        self.assertEqual(CSS, (APP_DIR / "app.css").read_text(encoding="utf-8"))
        self.assertIn("--bg:#050d19", CSS)
        self.assertIn(".offline-banner", CSS)

    def test_classic_html_rewrites_only_page_links_and_get_forms(self):
        page = ("<a href='/'>a</a><a href=\"/task?id=A/1\">b</a><a href='/deliver?id=X'>c</a><a href='/delivers'>d</a>"
                "<form method='get' action='/events'></form><form method='post' action='/action'></form>"
                "<a href='/api/state'>e</a><a href='/artifact/3'>f</a><a href='/log/1/stdout'>g</a>"
                "<a href='https://example.com/task'>h</a><a href='/taskx'>i</a><a href='/review?id=Z'>j</a>")
        out = classic_html(page)
        for expected in ("href='/classic/'", 'href="/classic/task?id=A/1"', "href='/classic/deliver?id=X'",
                         "href='/classic/delivers'", "action='/classic/events'", "href='/classic/review?id=Z'"):
            self.assertIn(expected, out)
        for untouched in ("action='/action'", "href='/api/state'", "href='/artifact/3'", "href='/log/1/stdout'",
                          "href='https://example.com/task'", "href='/taskx'"):
            self.assertIn(untouched, out)

    def test_classic_url(self):
        self.assertEqual(classic_url("/"), "/classic/")
        self.assertEqual(classic_url("/plan"), "/classic/plan")
        self.assertEqual(classic_url("/task?id=A%2F1"), "/classic/task?id=A%2F1")
        self.assertEqual(classic_url("/delivers"), "/classic/delivers")
        for other in ("/api/state", "/app/app.js", "//evil.example/", "https://example.com/", "/classic/", "/taskx", ""):
            self.assertEqual(classic_url(other), other)

    def test_static_file_is_confined_to_its_root(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            (root / "sub").mkdir(parents=True)
            (root / "ok.js").write_text("1")
            (root / "sub" / "deep.css").write_text("2")
            outside = Path(tmp) / "secret.txt"
            outside.write_text("secret")
            (root / "link.txt").symlink_to(outside)
            self.assertEqual(static_file(root, "ok.js"), (root / "ok.js").resolve())
            self.assertEqual(static_file(root, "sub/deep.css"), (root / "sub" / "deep.css").resolve())
            self.assertEqual(static_file(root, "%6Fk.js"), (root / "ok.js").resolve())     # percent-decoding is allowed
            for bad in ("", "sub", "sub/", "missing.js", "../secret.txt", "sub/../../secret.txt", "%2e%2e/secret.txt",
                        "..%2fsecret.txt", "sub/%2e%2e/%2e%2e/secret.txt", "/secret.txt", "//ok.js", "./ok.js",
                        "ok.js\x00.png", "ok.js%00", "..\\secret.txt", "sub\\deep.css", "link.txt", "sub//deep.css"):
                self.assertIsNone(static_file(root, bad), bad)


class AppServerCase(TmpTestCase):
    def setUp(self):
        super().setUp()
        init_repo(self.tmp)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.dash = Dashboard(FakeEnv(self.tmp, overrides={"dashboard": {"port": self.port}}).cfg)
        self.dash.serve_in_thread()
        self.clients: list[TinyClient] = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.dash.shutdown()
        super().tearDown()

    def request(self, path: str, method: str = "GET", body: str | None = None, headers: dict | None = None):
        """Raw request (no redirect following, no client-side path normalisation): (status, headers, body bytes)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host="Host" in (headers or {}))
            for k, v in (headers or {}).items():
                conn.putheader(k, v)
            data = body.encode() if body is not None else None
            if data is not None:
                conn.putheader("Content-Type", "application/x-www-form-urlencoded")
                conn.putheader("Content-Length", str(len(data)))
            conn.endheaders(data)
            res = conn.getresponse()
            return res.status, {k.lower(): v for k, v in res.getheaders()}, res.read()
        finally:
            conn.close()


class ServeApp(AppServerCase):
    def test_root_is_the_app_with_this_processs_token(self):
        status, headers, body = self.request("/")
        page = body.decode()
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        self.assertIn(f'<meta name="wwii-token" content="{self.dash.token}">', page)
        self.assertNotIn("__WWII_TOKEN__", page)
        self.assertIn('<script type="module" src="/app/app.js">', page)
        self.assertIn('lang="he" dir="rtl"', page)
        self.assertIn("מתחבר מחדש…", page)
        self.assertNotIn("location.reload", page)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(self.request("/?msg=x")[0], 200)

    def test_app_index_file_gets_the_token_too_and_the_token_is_per_process(self):
        status, _, body = self.request("/app/index.html")
        self.assertEqual(status, 200)
        self.assertIn(self.dash.token, body.decode())
        self.assertNotIn(self.dash.token, (APP_DIR / "index.html").read_text(encoding="utf-8"))   # the file on disk is a template

    def test_static_files_and_content_types(self):
        expected = {"app.js": "text/javascript", "socket.js": "text/javascript", "store.js": "text/javascript",
                    "router.js": "text/javascript", "pages/overview.js": "text/javascript", "app.css": "text/css"}
        for name, ctype in expected.items():
            status, headers, body = self.request(f"/app/{name}")
            self.assertEqual(status, 200, name)
            self.assertTrue(headers["content-type"].startswith(ctype), (name, headers["content-type"]))
            self.assertEqual(headers["x-content-type-options"], "nosniff")
            self.assertEqual(body, (APP_DIR / name).read_bytes())

    def test_every_module_the_app_imports_is_served(self):
        import re
        for js in APP_DIR.rglob("*.js"):
            for rel in re.findall(r"""(?:from\s+|import\()\s*['"](\.{1,2}/[^'"]+)['"]""", js.read_text(encoding="utf-8")):
                target = (js.parent / rel).resolve()
                self.assertTrue(target.is_file(), f"{js.name} imports missing {rel}")
                url = "/app/" + target.relative_to(APP_DIR.resolve()).as_posix()
                self.assertEqual(self.request(url)[0], 200, url)

    def test_traversal_directories_and_missing_files_are_404(self):
        for path in ("/app/../dashboard.py", "/app/%2e%2e/dashboard.py", "/app/..%2fdashboard.py",
                     "/app/%2e%2e%2f%2e%2e%2fconfig.py", "/app/pages/../../dashboard.py", "/app/..\\dashboard.py",
                     "/app/%5c..%5cdashboard.py", "/app//etc/passwd", "/app/%2fetc/passwd", "/app/a%00.js",
                     "/app/", "/app/pages", "/app/pages/", "/app/nope.js", "/app/.", "/app/pages/%2e%2e/%2e%2e/db.py"):
            status, _, body = self.request(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"import ", body, path)

    def test_wrong_host_is_refused_on_every_app_route(self):
        for path in ("/", "/app/app.js", "/app/index.html", "/classic/"):
            status, _, _ = self.request(path, headers={"Host": "evil.example"})
            self.assertEqual(status, 403, path)
        self.assertEqual(self.request("/app/app.js", headers={"Host": f"localhost:{self.port}"})[0], 200)

    def test_only_versioned_service_restart_can_reload_the_page(self):
        for js in APP_DIR.rglob("*.js"):
            text = js.read_text(encoding="utf-8")
            expected_reloads = 1 if js.name == "socket.js" else 0
            self.assertEqual(text.count("location.reload"), expected_reloads, js.name)
            for forbidden in ("location.href", "location.assign", "location.replace", "innerHTML"):
                self.assertNotIn(forbidden, text, f"{js.name} uses {forbidden}")


class ClassicPages(AppServerCase):
    ROUTES = ("/classic/", "/classic", "/classic/new", "/classic/battle", "/classic/plan", "/classic/events", "/classic/rag",
              "/classic/subtasks", "/classic/delivers", "/classic/task?id=missing", "/classic/deliver?id=missing",
              "/classic/review?id=missing")

    def test_every_old_route_still_renders_under_classic(self):
        # the /rag page probes the (optional, local) Graph RAG service: keep the test off the network
        self.dash.graph_rag.health = lambda: {"status": "UNREACHABLE", "url": "http://127.0.0.1:1", "reachable": False,
                                              "model": None, "nodes": None, "relationships": None, "insights": None,
                                              "latency_ms": 0, "detail": "synthetic"}
        for path in self.ROUTES:
            status, headers, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(headers["content-type"].startswith("text/html"), path)
            self.assertIn("<nav class='top'>", body.decode(), path)

    def test_classic_overview_is_the_old_page_with_its_links_and_forms(self):
        page = self.request("/classic/")[2].decode()
        self.assertIn("מנהל הבנייה — מלחמת העולם השנייה", page)            # the page is served localized (Hebrew)
        self.assertNotIn("location.reload", page)                          # the 6s polling is gone: the page is static
        self.assertIn("--bg:#050d19", page)                               # the CSS from app.css
        for link in ("href='/classic/'", "href='/classic/delivers'", "href='/classic/new'", "href='/classic/events'"):
            self.assertIn(link, page)
        for old in ("href='/'", "href='/delivers'", "href='/new'", "href='/events'"):
            self.assertNotIn(old, page)
        self.assertIn("action='/action'", page)                            # forms still post to /action
        self.assertIn("href='/api/state'", page)                           # JSON/log/artifact links are not classic pages
        self.assertIn(self.dash.token, page)

    def test_no_classic_page_polls_and_each_links_back_to_the_live_app(self):
        self.dash.graph_rag.health = lambda: {"status": "UNREACHABLE", "url": "http://127.0.0.1:1", "reachable": False,
                                              "model": None, "nodes": None, "relationships": None, "insights": None,
                                              "latency_ms": 0, "detail": "synthetic"}
        for path in self.ROUTES:
            page = self.request(path)[2].decode()
            for forbidden in ("location.reload", "setInterval", "http-equiv", "setTimeout"):
                self.assertNotIn(forbidden, page, f"{path} uses {forbidden}")
            self.assertIn("class='live-app-link' href='/app/index.html'", page, path)
            self.assertIn("class='banner classic-banner'", page, path)
        self.assertEqual(self.request("/app/index.html")[0], 200)          # the banner's target is served (with the token)
        self.assertIn("initUploadZones", self.request("/classic/plan")[2].decode())   # upload zones still work without polling

    def test_classic_json_and_bare_old_routes_keep_working(self):
        for path in ("/api/state", "/classic/api/state"):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertIn("tasks", json.loads(body))
        for path in ("/new", "/plan", "/events", "/rag", "/subtasks", "/delivers", "/task?id=x", "/api/events", "/api/delivers"):
            self.assertEqual(self.request(path)[0], 200, path)
        self.assertEqual(self.request("/classicx")[0], 404)
        self.assertEqual(self.request("/classic/nope")[0], 404)
        self.assertEqual(self.request("/classic/app/app.js")[0], 404)

    def test_form_posts_redirect_back_to_the_classic_page(self):
        token = self.dash.token

        def post(fields: str):
            status, headers, _ = self.request("/action", "POST", f"token={token}&{fields}")
            return status, headers.get("location", "")
        status, location = post("action=state_chat_new&back=%2F")
        self.assertEqual(status, 303)
        self.assertTrue(location.startswith("/classic/?msg="), location)
        status, location = post("action=state_chat_new&back=%2Ftask%3Fid%3DA%252F1")
        self.assertTrue(location.startswith("/classic/task?id=A%2F1&msg="), location)
        status, location = post("action=state_chat_new&back=%2Fplan")
        self.assertTrue(location.startswith("/classic/plan?msg="), location)
        status, location = post("action=state_chat_new")
        self.assertTrue(location.startswith("/classic/?msg="), location)
        self.assertEqual(self.request("/action", "POST", "token=wrong&action=pause")[0], 403)
        self.assertEqual(self.request("/action", "POST", "action=pause")[0], 403)
        self.assertEqual(self.request("/action", "POST", f"token={token}&action=pause",
                                      headers={"Host": "evil.example"})[0], 403)
        self.assertIsNone(self.dash.db.get_flag("paused"))


class OverviewMeta(AppServerCase):
    """What the overview page needs beyond the ws-2 payload: model profiles and the chat conversation to follow."""

    def setUp(self):
        super().setUp()
        self.other = sqlite3.connect(str(self.dash.db.path), timeout=10, isolation_level=None)   # "another process"

    def tearDown(self):
        self.other.close()
        super().tearDown()

    def overview(self, timeout: float = 3.0):
        c = TinyClient(self.port, token=self.dash.token)
        self.clients.append(c)
        c.sock.settimeout(timeout)
        self.assertEqual(c.recv_json()["type"], "welcome")
        c.send_json({"type": "subscribe", "topics": ["overview"], "revs": {}})
        meta = c.recv_json()["data"]["meta"]
        self.assertEqual(c.recv_json()["type"], "subscribed")
        return c, meta

    def test_models_auto_approval_limit_and_no_conversation_yet(self):
        _, meta = self.overview()
        self.assertEqual(meta["chat_conversation_id"], None)
        self.assertEqual(meta["auto_max_per_task"], 3)
        self.assertTrue(meta["models"])
        for profile in meta["models"].values():
            self.assertEqual(sorted(profile), ["model", "provider"])
        self.assertEqual(meta["models"], {k: {"provider": v["provider"], "model": v["model"]}
                                          for k, v in self.dash.cfg.data["models"].items()})

    def test_overview_follows_the_latest_chat_conversation_and_new_chat(self):
        c, meta = self.overview()
        self.assertIsNone(meta["chat_conversation_id"])
        self.other.execute("INSERT INTO state_chat_messages(conversation_id,role,content,created_at) VALUES(4,'user','synthetic',?)", (NOW,))
        patch = c.recv_json()
        self.assertEqual((patch["topic"], patch["meta"]["chat_conversation_id"]), ("overview", 4))
        self.other.execute("INSERT OR REPLACE INTO scheduler_state(key,value) VALUES('state_chat_new','1')")
        self.assertIsNone(c.recv_json()["meta"]["chat_conversation_id"])


def _node_version() -> tuple[int, int]:
    node = shutil.which("node")
    if not node:
        return 0, 0
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
        major, minor = out.lstrip("v").split(".")[:2]
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0, 0


# the .js modules are ES modules without a package.json (that would be a dependency manifest): node detects them from 22.7
@unittest.skipUnless(_node_version() >= (22, 7), "node >= 22.7 is not installed: client unit tests (tests/js) skipped")
class ClientModules(unittest.TestCase):
    """store/socket/format/router modules and the overview page (against a tiny fake DOM) under `node --test`."""

    def test_client_modules_under_node(self):
        files = sorted(str(p) for p in (HERE / "js").glob("*.test.mjs"))
        self.assertTrue(files)
        env = dict(os.environ, NODE_NO_WARNINGS="1")
        run = subprocess.run([shutil.which("node"), "--test", *files], capture_output=True, text=True, env=env, timeout=240)
        self.assertEqual(run.returncode, 0, run.stdout[-6000:] + run.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()


class FramingGuard(AppServerCase):
    def test_other_sites_cannot_frame_the_dashboard(self):
        for path in ("/", "/app/index.html", "/classic/"):
            status, headers, _ = self.request(path)
            self.assertEqual(headers.get("x-frame-options"), "SAMEORIGIN", path)
            self.assertIn("frame-ancestors 'self'", headers.get("content-security-policy", ""), path)
            self.assertEqual(headers.get("referrer-policy"), "no-referrer", path)

    def test_post_cannot_redirect_off_host(self):
        token = self.dash.token
        status, headers, _ = self.request("/action", "POST", f"token={token}&action=noop&back=https://evil.example/")
        self.assertEqual(status, 303)
        self.assertTrue(headers["location"].startswith("/"), headers["location"])
