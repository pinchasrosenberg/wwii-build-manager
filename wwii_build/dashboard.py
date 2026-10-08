"""Local dashboard: http://127.0.0.1:<port> (stdlib only, server-rendered HTML).

Binds to localhost only, checks the Host header (DNS-rebinding guard) and requires a
per-process CSRF token on every POST. All actions go through `control` — the same
code path as the CLI.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import html
import re
import json
import mimetypes
import os
import secrets
import signal
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import app_data
from . import control
from . import i18n
from . import live
from . import manual as mn
from . import planner_uploads
from . import ws
from .config import Config
from .i18n import localize, state_label, t as _t
from .db import DB
from .quota import QuotaManager
from .models import AttemptStatus, RunSpec, TaskRequest, TaskState, parse_iso, utcnow
from .providers import build_providers
from .sanitize import redact
from .supervisor import Supervisor
from . import state_chat
from .worktrees import WorktreeManager
from .jev import JevClient, JevError, JevService
from .credentials import API_KEY_ENV, CredentialError, TypeSafeCredentialStore
from .graph_rag import GraphRagError, GraphRagService
from .explanations import task_he, deliver_description_he, deliver_implementation_he
from .model_watch import ModelWatch

E = html.escape
STATE_ORDER = ["RUNNING", "PAUSING", "REVIEWING", "CODE_READY", "WAITING_REPAIR", "ARCHITECTURE_REVIEW_REQUIRED",
               "READY", "WAITING_APPROVAL", "REVIEW_REQUIRED",
               "WAITING_QUOTA", "WAITING_PROVIDER", "BLOCKED", "PENDING", "WAITING_DEPENDENCY", "PAUSED", "FAILED",
               "CANCELLED", "PASSED"]
CSS = (Path(__file__).parent / "static/app/app.css").read_text(encoding="utf-8")
# the classic pages are static (no polling, no reload): this only wires the drag-and-drop upload zones
CLASSIC_JS = """<script>
function initUploadZones(){document.querySelectorAll('.upload-zone').forEach(z=>{const i=document.getElementById(z.dataset.input),l=z.querySelector('.upload-list');if(!i||z.dataset.ready)return;z.dataset.ready='1';
const draw=()=>{l.innerHTML='';[...i.files].forEach(f=>{const s=document.createElement('span');s.className='upload-chip';s.textContent=f.name+' · '+(f.size/1048576).toFixed(f.size>1048576?1:2)+'MB';l.appendChild(s)})};
z.addEventListener('click',e=>{if(e.target!==i)i.click()});z.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();i.click()}});i.addEventListener('change',draw);
['dragenter','dragover'].forEach(n=>z.addEventListener(n,e=>{e.preventDefault();z.classList.add('dragging')}));['dragleave','drop'].forEach(n=>z.addEventListener(n,e=>{e.preventDefault();z.classList.remove('dragging')}));z.addEventListener('drop',e=>{i.files=e.dataTransfer.files;draw()});});}
initUploadZones()</script>"""


APP_DIR = Path(__file__).parent / "static/app"
TOKEN_PLACEHOLDER = "__WWII_TOKEN__"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2",
}
# server-rendered pages: reachable at /classic/<route> (and still at the bare route, except "/" which is the app)
CLASSIC_ROUTES = ("new", "battle", "plan", "task", "events", "rag", "subtasks", "delivers", "deliver", "review")
_CLASSIC_LINK = re.compile(r"""((?:href|action)=['"])/((?:%s)?)(?=[?'"#])""" % "|".join(CLASSIC_ROUTES))


def app_version(root: Path = APP_DIR) -> str:
    """Content version of the browser app; changes exactly when a served app asset changes."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


APP_VERSION = app_version()


def classic_html(page: str) -> str:
    """Point the internal page links/forms of a server-rendered page at /classic/... (API, log, artifact links stay)."""
    return _CLASSIC_LINK.sub(lambda m: f"{m.group(1)}/classic/{m.group(2)}", page)


def local_path(url: str | None) -> str:
    """A redirect target from a form: same-origin absolute paths only, never another host."""
    url = (url or "/").strip()
    if not url.startswith("/") or url.startswith("//") or "\\" in url or any(ord(c) < 32 for c in url):
        return "/"
    return url


def classic_url(url: str) -> str:
    """The /classic/ form of a page URL ('/task?id=x' -> '/classic/task?id=x'); anything else is returned unchanged."""
    path, sep, rest = url.partition("?")
    route = path.strip("/")
    if path.startswith("/") and not path.startswith("//") and route in ("",) + CLASSIC_ROUTES:
        return "/classic/" + route + sep + rest
    return url


def static_file(root: Path, rel: str) -> Path | None:
    """`rel` (percent-decoded URL path below the static root) -> an existing regular file inside `root`, else None.

    Backslashes, NULs, `..` segments and symlinks that leave the root are rejected; directories are never served,
    so there is no directory listing.
    """
    rel = urllib.parse.unquote(rel)
    parts = rel.split("/")
    if not rel or "\\" in rel or "\0" in rel or any(p in ("", ".", "..") for p in parts):
        return None
    try:
        base = root.resolve()
        path = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    return path if path.is_relative_to(base) and path.is_file() else None


def local(ts: str | None) -> str:
    d = parse_iso(ts)
    return d.astimezone().strftime("%Y-%m-%d %H:%M") if d else "unknown"


_LANG = threading.local()
MCP_NOTE = "Only servers of the chosen model's provider are used. Nothing is enabled unless you tick it."


def lang() -> str:
    return getattr(_LANG, "v", "he")


def ago(ts: str | None) -> str:
    d = parse_iso(ts)
    if not d:
        return "unknown"
    sec = int((dt.datetime.now(dt.timezone.utc) - d).total_seconds())
    he = lang() == "he"
    if sec < 90:
        return f"לפני {sec} שנ׳" if he else f"{sec}s ago"
    if sec < 5400:
        return f"לפני {sec // 60} דק׳" if he else f"{sec // 60} min ago"
    return f"לפני {sec // 3600} שע׳" if he else f"{sec // 3600} h ago"


def fmt_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            digits = 0 if unit == "B" else 1
            return f"{size:.{digits}f} {unit}"
        size /= 1024
    return "0 B"


def pill(s: str | None) -> str:
    s = s or "UNKNOWN"
    return f'<span class="pill s-{E(s)}" title="{E(s)}">{E(state_label(s, lang()))}</span>'


WEB_FORM_NOTE = ("כבוי כברירת מחדל. כשמסומן, העובד מקבל חיפוש ושליפת דפי רשת לריצה הזו בלבד; תוכן מהרשת הוא מידע ולא "
                 "הוראות, כל טענה מצוטטת עם URL, ותוכן המאגר, סודות והרשאות לעולם אינם נשלחים לאתר. "
                 "לא זמין לתיקון מערכת ניהול המשימות.")
WEB_BADGE = '<span class="pill s-WEB" title="מחקר עם גישה לרשת (allow_web)">web</span>'


def web_badge(extra) -> str:
    """The 'web' badge for a task that opted in to web research (extra JSON text or dict)."""
    if isinstance(extra, str):
        try:
            extra = json.loads(extra or "{}")
        except ValueError:
            extra = {}
    return f" {WEB_BADGE}" if isinstance(extra, dict) and extra.get("allow_web") else ""


def _run_async_now(coro):
    """Run one provider coroutine from either an HTTP thread or an async test.

    Dashboard handlers normally have no event loop. Tests and embedded callers
    sometimes do, so in that case a short-lived thread owns the private loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result, failure = [], []

    def target():
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # propagated to the calling thread below
            failure.append(exc)

    worker = threading.Thread(target=target, name="graph-query-provider", daemon=True)
    worker.start()
    worker.join()
    if failure:
        raise failure[0]
    return result[0]


ALREADY_RUNNING = "כבר רץ"       # the answer to a second unstick / onboard request while one runs
MANIFEST_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,80}")


class Dashboard:
    def __init__(self, cfg: Config, wake=None):
        self.cfg = cfg
        self.db = DB(cfg.db_path)
        self.wt = WorktreeManager(cfg)
        self.jev = JevService(cfg, self.db)
        self.graph_rag = GraphRagService(cfg, self.db)
        self.providers = build_providers(cfg)
        self.token = secrets.token_urlsafe(24)
        self.wake = wake or self._wake_daemon
        self.host = cfg.section("dashboard").get("host", "127.0.0.1")
        self.port = int(cfg.section("dashboard").get("port", 8765))
        self.httpd: ThreadingHTTPServer | None = None
        self.hub = ws.Hub(lambda: self.token, version=APP_VERSION)
        self.live = live.LiveState(self)
        self._progress_local = threading.local()      # the progress callback of the action this thread is running
        self._flight_lock = threading.Lock()
        self._flights: set[str] = set()               # long operations that may only run one at a time

    # ------------------------------------------------------------------ progress streaming
    @contextlib.contextmanager
    def progress_to(self, callback):
        """Within the block, ``self.progress(line)`` of THIS thread goes to ``callback`` (the socket's action id)."""
        previous = getattr(self._progress_local, "callback", None)
        self._progress_local.callback = callback
        try:
            yield
        finally:
            self._progress_local.callback = previous

    def progress(self, line: str) -> None:
        """Report one line of a long operation; a no-op outside a streaming action (HTML form posts, CLI, tests)."""
        callback = getattr(self._progress_local, "callback", None)
        if callback is not None:
            try:
                callback(line)
            except Exception:                         # a closed socket must not abort the operation itself
                self._progress_local.callback = None

    def run_exclusive(self, key: str, fn) -> str:
        """Run ``fn() -> message`` unless an operation with the same key is already running (-> ALREADY_RUNNING)."""
        with self._flight_lock:
            if key in self._flights:
                return ALREADY_RUNNING
            self._flights.add(key)
        try:
            return fn()
        finally:
            with self._flight_lock:
                self._flights.discard(key)

    def _wake_daemon(self) -> None:
        pid = control.daemon_pid(self.cfg)
        if pid and pid != os.getpid():
            try:
                os.kill(pid, signal.SIGUSR1)
            except (ProcessLookupError, PermissionError):
                pass

    # ------------------------------------------------------------------ server
    def serve_in_thread(self) -> threading.Thread:
        dash = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _host_ok(self) -> bool:
                h = (self.headers.get("Host") or "").split(":")[0]
                return h in ("127.0.0.1", "localhost", "[::1]")

            def do_GET(self):
                self._classic = False
                if not self._host_ok():
                    return self._send(403, "forbidden host", "text/plain")
                if urllib.parse.urlparse(self.path).path == ws.PATH:   # the socket lives in this handler thread
                    return dash.hub.handle_upgrade(self, self.server.server_address[1])
                try:
                    dash.route_get(self)
                except Exception as e:
                    self._send(500, f"<pre>{E(repr(e))}</pre>")

            def do_POST(self):
                if not self._host_ok():
                    return self._send(403, "forbidden host", "text/plain")
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if n < 0:
                        return self._send(400, "bad Content-Length", "text/plain")
                    if n > planner_uploads.MAX_REQUEST_BYTES:
                        return self._send(413, "הבקשה גדולה מדי; אפשר לצרף עד 25MB", "text/plain; charset=utf-8")
                    multi, uploads = planner_uploads.parse_post_body(
                        self.headers.get("Content-Type") or "application/x-www-form-urlencoded", self.rfile.read(n))
                except (ValueError, planner_uploads.PlannerUploadError) as exc:
                    return self._send(400, str(exc), "text/plain; charset=utf-8")
                form = {k: v[-1] for k, v in multi.items()}
                if not secrets.compare_digest(form.get("token", ""), dash.token):
                    return self._send(403, "bad token", "text/plain")
                dash._set_lang(self)
                if "application/json" in (self.headers.get("Accept") or ""):
                    # the app's multipart uploads: same code path, the answer is JSON instead of a redirect
                    ok, msg = dash.run_form(form, multi, uploads)
                    return self._send(200, json.dumps({"ok": ok, "message": msg[:2000]}, ensure_ascii=False),
                                      "application/json; charset=utf-8")
                if form.get("action") == "add_task":
                    ok, msg, page = dash.add_task_post(form, multi)
                    if not ok:                        # keep what the user typed
                        return self._send(200, classic_html(page))
                    form["back"] = "/plan" if msg.startswith("PLAN/") else "/task?id=" + urllib.parse.quote(msg)
                    msg = (f"context plan queued {msg}" if msg.startswith("PLAN/") else f"created {msg}")
                else:
                    msg = dash.action(form, uploads)
                back = classic_url(local_path(form.get("back")))   # only the old server-rendered pages post forms
                sep = "&" if "?" in back else "?"
                self.send_response(303)
                self.send_header("Location", back + sep + "msg=" + urllib.parse.quote(msg[:300]))
                self.end_headers()

            def _send(self, code, body, ctype="text/html; charset=utf-8", sandbox=False, nosniff=False):
                if getattr(self, "_classic", False) and isinstance(body, str) and ctype.startswith("text/html") and not sandbox:
                    body = classic_html(body)
                b = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                if nosniff:
                    self.send_header("X-Content-Type-Options", "nosniff")
                if sandbox:     # model-generated files run in an opaque origin: they can never drive the dashboard
                    self.send_header("Content-Security-Policy", "sandbox")
                    self.send_header("X-Content-Type-Options", "nosniff")
                else:           # no other site may frame the dashboard (clickjacking on approve/start buttons)
                    self.send_header("X-Frame-Options", "SAMEORIGIN")
                    self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
                self.send_header("Referrer-Policy", "no-referrer")
                if getattr(self, "_cookie", None):
                    self.send_header("Set-Cookie", self._cookie)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)

        self.httpd = ThreadingHTTPServer((self.host, self.port), H)
        t = threading.Thread(target=self.httpd.serve_forever, name="dashboard", daemon=True)
        t.start()
        self.live.start()
        return t

    def shutdown(self, *, service_restart: bool = False) -> None:
        if self.httpd:
            self.live.stop()
            if service_restart:
                self.hub.close_all(code=ws.CLOSE_SERVICE_RESTART, reason="service restart")
            else:
                self.hub.close_all()
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def run_graph_console_query(self, mode: str, query: str, model_key: str | None = None,
                                parameters: dict | None = None, max_rows: int = 100) -> dict:
        """Persist and run/queue a graph-console request without exposing credentials."""
        mode = (mode or "").strip()
        query = (query or "").strip()
        model_key = (model_key or "local").strip()
        if mode not in {"cypher", "natural"}:
            raise ValueError("מצב השאילתה חייב להיות Cypher או שפה חופשית")
        if not query:
            raise ValueError("השאילתה ריקה")
        if mode == "natural" and model_key != "local" and model_key not in self.cfg.data["models"]:
            raise ValueError("המודל שנבחר אינו קיים")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        qid = self.db.x(
            "INSERT INTO graph_console_queries(created_at,updated_at,mode,query_text,model_key,status) "
            "VALUES(?,?,?,?,?,?)", (now, now, mode, query, model_key if mode == "natural" else None, "RUNNING"))
        started = time.monotonic()
        self.progress(f"שאילתה #{qid} נשמרה")
        try:
            if mode == "cypher":
                self.progress("מריץ Cypher לקריאה בלבד")
                result = self.graph_rag.query_cypher(query, parameters or {}, max_rows)
                elapsed = int((time.monotonic() - started) * 1000)
                self.db.x("UPDATE graph_console_queries SET status='READY',updated_at=?,result_json=?,elapsed_ms=? WHERE id=?",
                          (dt.datetime.now(dt.timezone.utc).isoformat(),
                           json.dumps(result, ensure_ascii=False, default=str), elapsed, qid))
                self.db.event("GRAPH_CONSOLE_QUERY", source="dashboard", query_id=qid, mode=mode,
                              query_sha256=hashlib.sha256(query.encode()).hexdigest(), rows=result.get("count"),
                              elapsed_ms=elapsed)
                return {"id": qid, "status": "READY", "rows": result.get("count", 0)}
            if model_key == "local":
                self.progress("שואל את Graph RAG המקומי")
                result = self.graph_rag.query_natural(query)
                elapsed = int((time.monotonic() - started) * 1000)
                self.db.x("UPDATE graph_console_queries SET status='READY',updated_at=?,generated_cypher=?,"
                          "result_json=?,elapsed_ms=? WHERE id=?",
                          (dt.datetime.now(dt.timezone.utc).isoformat(), result.get("cypher") or None,
                           json.dumps(result, ensure_ascii=False, default=str), elapsed, qid))
                self.db.event("GRAPH_CONSOLE_QUERY", source="dashboard", query_id=qid, mode=mode,
                              model="graph-rag-local", query_sha256=hashlib.sha256(query.encode()).hexdigest(),
                              elapsed_ms=elapsed)
                return {"id": qid, "status": "READY", "model": "graph-rag-local"}

            return self._run_graph_llm_query(qid, query, model_key, started)
        except Exception as exc:
            self.db.x("UPDATE graph_console_queries SET status='FAILED',updated_at=?,elapsed_ms=?,error=? WHERE id=?",
                      (dt.datetime.now(dt.timezone.utc).isoformat(), int((time.monotonic() - started) * 1000),
                       str(exc)[:1000], qid))
            self.db.event("GRAPH_CONSOLE_QUERY_FAILED", source="dashboard", query_id=qid, mode=mode,
                          error=type(exc).__name__)
            raise

    def _run_graph_llm_query(self, qid: int, query: str, model_key: str, started: float) -> dict:
        """Run a selected Codex/Claude graph answer immediately, outside the task queue."""
        model = self.cfg.model(model_key)
        provider = self.providers.get(model.provider)
        if provider is None:
            raise GraphRagError(f"ספק המודל {model.provider} אינו זמין")

        self.progress("Jev בוחר מקורות מהגרף")
        selection = self.graph_rag.selected_query(
            self.jev, f"graph-console:{qid}", query, planner=True)
        self.progress(f"נבחרו {len(selection.get('selected') or [])} מתוך {selection.get('candidate_count')} "
                      f"מקורות; ממתין לתשובה מ־{model_key}")
        if selection["candidate_count"] and not selection["selected"]:
            raise GraphRagError("Jev לא אישר אף מקטע קונטקסט לשאילתה")
        selected = selection["selected"]
        evidence = "\n\n".join(
            f"SOURCE_ID {item['id']} · {item.get('source_key') or ''} "
            f"({item.get('origin_ref') or item.get('origin_kind') or ''}):\n{item.get('excerpt') or ''}"
            for item in selected) or "(Jev did not select graph evidence; answer only that the graph has no admitted evidence.)"
        prompt = "\n".join([
            f"TASK_ID: PLAN/GRAPH/{qid}",
            "You answer one read-only graph question immediately. Do not edit files and do not create tasks.",
            "Use only the JEV-SELECTED GRAPH EVIDENCE below. State unknowns and evidence limits.",
            "Return one JSON object matching the schema: summary, questions[], tasks[]. tasks must be [].",
            "", "## QUESTION", query,
            "", "## JEV-SELECTED GRAPH EVIDENCE", evidence,
        ]) + "\n"
        run_dir = self.cfg.state_dir / "graph_console" / str(qid)
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = run_dir / "prompt.md"
        schema_path = run_dir / "result.schema.json"
        prompt_path.write_text(prompt)
        schema_path.write_text(json.dumps(mn.PLAN_SCHEMA, ensure_ascii=False, indent=1))
        task = TaskRequest(
            task_id=f"PLAN/GRAPH/{qid}", packet="GRAPH", owner="graph_console", domain="knowledge",
            mode="read_only_graph_query", model_profile="PLAN", lego_ids=[], write_scope=[], depends_on=[],
            context_entry=None, brief_path=None, note=query[:500], extra={"graph_console_query_id": qid}, kind="plan")
        spec = RunSpec(
            task=task, attempt_id=qid, attempt_no=1, model=model, worktree=str(self.cfg.repo),
            prompt_path=str(prompt_path), run_dir=str(run_dir), result_schema_path=str(schema_path),
            kind="plan", schema=mn.PLAN_SCHEMA)
        timeout = max(30.0, min(float(self.cfg.section("graph_rag").get("llm_timeout_seconds", 180)), 600.0))
        run = _run_async_now(provider.run_task(spec, Supervisor(), timeout=timeout))
        if run.status != AttemptStatus.SUCCEEDED:
            raise GraphRagError((run.error or run.failure_class or run.status.value)[:500])
        payload = run.structured if isinstance(run.structured, dict) else None
        if payload is None and run.final_text:
            from .result_parser import _candidates
            for candidate in _candidates(run.final_text):
                try:
                    parsed = json.loads(candidate)
                except ValueError:
                    continue
                if isinstance(parsed, dict):
                    payload = parsed
                    break
        if not isinstance(payload, dict):
            raise GraphRagError("המודל לא החזיר תשובת JSON תקינה")
        self.progress("התשובה התקבלה ונשמרת")
        payload["tasks"] = []
        payload["evidence_source_ids"] = [item["id"] for item in selected]
        payload["usage"] = {
            "input_tokens": run.input_tokens, "cached_input_tokens": run.cached_input_tokens,
            "output_tokens": run.output_tokens, "reported_cost_usd": run.reported_cost_usd,
        }
        elapsed = int((time.monotonic() - started) * 1000)
        self.db.x(
            "UPDATE graph_console_queries SET status='READY',updated_at=?,model_key=?,provider=?,result_json=?,"
            "elapsed_ms=?,input_tokens=?,cached_input_tokens=?,output_tokens=?,reported_cost_usd=? WHERE id=?",
            (dt.datetime.now(dt.timezone.utc).isoformat(), model_key, model.provider,
             json.dumps(payload, ensure_ascii=False, default=str), elapsed, run.input_tokens,
             run.cached_input_tokens, run.output_tokens, run.reported_cost_usd, qid))
        self.db.event("GRAPH_CONSOLE_QUERY", source="dashboard", query_id=qid, mode="natural",
                      execution="immediate", model_key=model_key, provider=model.provider,
                      candidate_count=selection["candidate_count"], selected_count=len(selected),
                      query_sha256=hashlib.sha256(query.encode()).hexdigest(), elapsed_ms=elapsed,
                      input_tokens=run.input_tokens, cached_input_tokens=run.cached_input_tokens,
                      output_tokens=run.output_tokens, reported_cost_usd=run.reported_cost_usd)
        return {"id": qid, "status": "READY", "model": model_key, "provider": model.provider,
                "elapsed_ms": elapsed}

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    # ------------------------------------------------------------------ actions
    def action(self, f: dict, uploads: list[planner_uploads.IncomingUpload] | None = None) -> str:
        a = f.get("action", "")
        tid = f.get("task_id") or None
        uploads = list(uploads or [])
        try:
            if a == "pause":
                r = control.pause(self.db, self.cfg, False, "dashboard")
            elif a == "pause_interrupt":
                r = control.pause(self.db, self.cfg, True, "dashboard")
            elif a == "resume":
                r = control.resume(self.db, self.cfg, clear_emergency=f.get("clear") == "1", source="dashboard")
            elif a == "stop":
                if control.daemon_pid(self.cfg):
                    control.enqueue(self.db, self.cfg, "stop", {}, "dashboard")
                    r = "stop requested: no new tasks; running workers get SIGINT, then TERM/KILL after timeout"
                else:
                    r = "daemon not running; nothing to stop"
            elif a == "kill":
                if control.daemon_pid(self.cfg):
                    control.enqueue(self.db, self.cfg, "kill", {}, "dashboard")
                else:
                    self.db.set_flag("emergency_stop", dt.datetime.now(dt.timezone.utc).isoformat())
                    control.kill_recorded_workers(self.db, "dashboard emergency kill")
                r = "EMERGENCY KILL requested; scheduler disabled until resume --clear-emergency"
            elif a in ("approve", "reject"):
                r = control.decide(self.db, self.cfg, int(f["approval_id"]), a == "approve", f.get("note") or None,
                                   f.get("model_key") or None, "dashboard")
            elif a == "set_auto_approve_all":
                enabled = f.get("enabled") == "1"
                self.db.set_flag("review_auto_approve_all", "1" if enabled else "0")
                approved = 0
                if enabled:
                    approved = len(control.auto_approve_pending(self.db, self.cfg, "dashboard"))
                self.db.event("AUTO_APPROVAL_MODE_CHANGED", source="dashboard", enabled=enabled,
                              pending_reviews_approved=approved)
                self.wake()
                r = ("אישור אוטומטי לכל המשימות והצעות המתכנן הופעל" +
                     (f"; {approved} אישורים ממתינים בוצעו" if approved else "")) if enabled else \
                    "אישור אוטומטי לכל המשימות כובה"
            elif a == "retry":
                r = control.retry(self.db, tid, "dashboard")
            elif a == "expedite":
                r = control.expedite(self.db, tid, "dashboard")
            elif a == "skip":
                r = control.skip(self.db, self.cfg, tid, f.get("satisfy") == "1", "dashboard")
            elif a == "set_provider":
                r = control.set_provider(self.db, self.cfg, tid, f["model_key"], "dashboard")
            elif a == "set_deliver_model":
                did = self._safe_graph_id(f.get("deliver_id", ""), "Deliver ID")
                if not self.db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (did,)):
                    raise ValueError("ה־Deliver המבוקש אינו קיים")
                model_key = (f.get("model_key") or "").strip() or None
                if model_key and model_key not in self.cfg.data["models"]:
                    raise ValueError(f"פרופיל המודל {model_key} אינו קיים")
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                if self.db.task(did):
                    if model_key:
                        control.set_provider(self.db, self.cfg, did, model_key, "dashboard")
                    else:
                        task = self.db.task(did)
                        if task["state"] in {"RUNNING", "REVIEWING", "PAUSING"}:
                            raise ValueError("אי אפשר לשנות מודל בזמן שהמשימה רצה")
                        self.db.x("UPDATE tasks SET preferred_model_key=NULL,updated_at=? WHERE task_id=?", (now, did))
                self.db.x("UPDATE deliver_catalog SET preferred_model_key=?,updated_at=? WHERE deliver_id=?",
                          (model_key, now, did))
                self.db.event("DELIVER_MODEL_CHANGED", task_id=did, source="dashboard",
                              model_key=model_key or "automatic")
                r = f"המודל של {did} עודכן ל־{model_key or 'בחירה אוטומטית'}"
            elif a == "recheck":
                r = control.recheck(self.db, tid, "dashboard")
            elif a in ("plan", "scoped_plan"):
                mcps = [name.strip() for name in (f.get("mcp_servers") or "").split(",") if name.strip()]
                prompt = f.get("prompt", "")
                if a == "scoped_plan":
                    scope_kind = f.get("scope_kind") or "task"
                    scope_id = self._safe_graph_id(f.get("scope_id", ""), "target ID")
                    exists = (self.db.task(scope_id) if scope_kind == "task" else
                              self.db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (scope_id,)))
                    if not exists:
                        raise ValueError("היעד המבוקש אינו קיים")
                    prompt = (f"TARGET {scope_kind.upper()}: {scope_id}\n"
                              "Apply the requested Task Manager change to this existing target. Inspect only its "
                              "definition, direct dependencies, direct listeners, explicit context grants and the "
                              "small graph shortlist admitted by Jev. Infer small enabling changes that are required, "
                              "but do not load unrelated repository or conversation context. Prefer a deterministic "
                              "change when it can satisfy the request.\n\nUSER REQUEST:\n" + prompt)
                tid = mn.create_plan(self.db, self.cfg, prompt, f.get("model_key") or None,
                                     f.get("prompt_mode") or "plan_build", mcps)
                records = planner_uploads.store(self.db, self.cfg, tid, uploads) if uploads else []
                r = f"בקשת התכנון {tid} נוספה לתור"
                if records:
                    r += f" עם {len(records)} קבצים; Jev יחליט אילו מהם ייכנסו לקונטקסט"
            elif a == "reset_done":
                r = control.provider_reset_done(self.db, self.cfg, f.get("provider"), "dashboard")
            elif a == "refresh":
                control.enqueue(self.db, self.cfg, "refresh", {"provider": f.get("provider")}, "dashboard")
                r = f"refresh {f.get('provider')} queued" + ("" if control.daemon_pid(self.cfg) else
                                                             " (daemon not running: use `wwii-build provider refresh`)")
            elif a == "save_typesafe_key":
                candidate = (f.get("typesafe_key") or "").strip()
                if not candidate:
                    raise ValueError("יש להכניס מפתח TypeSafe")
                probe = JevClient(timeout_seconds=float(self.cfg.section("jev").get("timeout_seconds", 8)),
                                  credential_store=TypeSafeCredentialStore(env={API_KEY_ENV: candidate}))
                try:
                    probe.list_models(self.jev.model)
                except JevError as exc:
                    raise ValueError("המפתח החדש לא אומת ב־TypeSafe; המפתח הקודם נשאר שמור "
                                     f"({exc.kind})") from None
                self.jev.credentials.set(candidate)
                result = self.jev.health_check()
                released = control.release_jev_backoff(self.db, "dashboard:key-saved") if result["status"] == "READY" else 0
                if released:
                    self.wake()
                r = (f"TypeSafe credential saved securely; Jev status: {result['status']}"
                     + (f"; {released} delayed tasks released" if released else ""))
            elif a == "jev_health":
                result = self.jev.health_check()
                released = control.release_jev_backoff(self.db, "dashboard:health") if result["status"] == "READY" else 0
                if released:
                    self.wake()
                r = (f"Jev health check: {result['status']}"
                     + (f"; {released} delayed tasks released" if released else ""))
            elif a == "model_watch_check":
                threading.Thread(target=lambda: ModelWatch(self.cfg, DB(self.cfg.db_path)).check(force=True),
                                 name="model-watch-manual", daemon=True).start()
                r = "בדיקת מודלים רשמית ל־Codex ול־Claude התחילה ברקע"
            elif a == "save_graph_rag_config":
                self.graph_rag.configure(f.get("graph_rag_url", ""))
                if (f.get("graph_cypher_url") or "").strip():
                    self.graph_rag.configure_cypher(f.get("graph_cypher_url", ""))
                result = self.graph_rag.health()
                r = f"כתובת גרף ה־RAG נשמרה; מצב: {result['status']}"
            elif a == "graph_rag_health":
                result = self.graph_rag.health()
                r = f"בדיקת גרף RAG: {result['status']}"
            elif a == "unstick":
                from . import unstick as us
                r = self.run_exclusive("unstick", lambda: us.summary_he(
                    us.unstick(self.cfg, self.db, "dashboard", progress=self.progress)))
            elif a == "system_onboard":
                r = self.run_exclusive("system_onboard", lambda: self._system_onboard(f))
            elif a == "battle_request":
                r = self._battle_request(f)
            elif a == "state_chat":
                conv = int(f["conversation_id"]) if (f.get("conversation_id") or "").isdigit() else None
                self.progress("thinking")
                result = state_chat.ask(self, conv, f.get("message", ""), f.get("model_key") or None, _run_async_now,
                                        progress=self.progress)
                self.db.set_flag("state_chat_new", "0")
                r = f"תשובה התקבלה ({result['model_key']})"
            elif a == "state_chat_new":
                self.db.set_flag("state_chat_new", "1")
                r = "שיחה חדשה: ההודעה הבאה תפתח שיחה חדשה"
            elif a == "graph_console_query":
                mode = f.get("query_mode") or "natural"
                parameters = {}
                if mode == "cypher" and (f.get("parameters") or "").strip():
                    parameters = json.loads(f["parameters"])
                    if not isinstance(parameters, dict):
                        raise ValueError("פרמטרים חייבים להיות אובייקט JSON")
                result = self.run_graph_console_query(
                    mode, f.get("query", ""), f.get("model_key") or "local", parameters,
                    int(f.get("max_rows") or 100))
                r = f"שאילתת גרף #{result['id']} הושלמה מיד"
            elif a == "save_deliver_graph_access":
                did = self._safe_graph_id(f.get("deliver_id", ""), "Deliver ID")
                self.graph_rag.save_access(
                    did, f.get("access_mode", "none"), f.get("scope_text", ""),
                    int(f.get("max_chunks") or 6), int(f.get("max_chars") or 6000))
                r = f"הרשאת גרף ה־RAG של {did} נשמרה"
            elif a == "save_deliver":
                did = self._safe_graph_id(f.get("deliver_id", ""), "Deliver ID")
                execution = f.get("execution_kind") or "worker"
                if execution not in {"worker", "deterministic", "llm_research", "context_bundle", "review"}:
                    raise ValueError("invalid execution kind")
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                description = (f.get("description") or "").strip()
                if not any("\u0590" <= ch <= "\u05ff" for ch in description):
                    raise ValueError("יש לכתוב הסבר ברור בעברית על תפקיד ה־Deliver")
                digest = hashlib.sha256(json.dumps({"id": did, "description": description,
                                                    "execution": execution}, sort_keys=True).encode()).hexdigest()
                self.db.x(
                    "INSERT INTO deliver_catalog(deliver_id,owner,domain,description,source_kind,source_ref,execution_kind,definition_hash,enabled,availability,updated_at) "
                    "VALUES(?,?,?,?,?,'dashboard',?,?,1,'available',?) ON CONFLICT(deliver_id) DO UPDATE SET "
                    "owner=excluded.owner,domain=excluded.domain,description=excluded.description,execution_kind=excluded.execution_kind,"
                    "definition_hash=excluded.definition_hash,enabled=1,updated_at=excluded.updated_at",
                    (did, (f.get("owner") or "").strip(), (f.get("domain") or "").strip(), description,
                     "dashboard", execution, digest, now))
                self.db.event("DELIVER_SAVED", task_id=did, source="dashboard", execution_kind=execution)
                r = f"Deliver {did} saved"
            elif a == "toggle_deliver":
                did = self._safe_graph_id(f.get("deliver_id", ""), "Deliver ID")
                enabled = 1 if f.get("enabled") == "1" else 0
                self.db.x("UPDATE deliver_catalog SET enabled=?,updated_at=? WHERE deliver_id=?",
                          (enabled, dt.datetime.now(dt.timezone.utc).isoformat(), did))
                self.db.event("DELIVER_TOGGLED", task_id=did, source="dashboard", enabled=bool(enabled))
                r = f"Deliver {did} {'enabled' if enabled else 'disabled'}"
            elif a == "add_listener":
                source = self._safe_graph_id(f.get("source_deliver_id", ""), "source Deliver")
                target = self._safe_graph_id(f.get("target_deliver_id", ""), "target Deliver")
                lid = self._safe_graph_id(f.get("listener_id", ""), "listener ID")
                event_type = self._safe_graph_id(f.get("event_type", "DELIVER_PASSED"), "event type")
                selector = json.loads((f.get("context_selector") or "{}").strip())
                if not isinstance(selector, dict):
                    raise ValueError("context selector must be a JSON object")
                self._require_delivers(source, target)
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                self.db.x(
                    "INSERT INTO deliver_listener_edges(listener_id,source_deliver_id,target_deliver_id,event_type,context_selector,source_kind,edge_type,jev_gate,enabled,proposal_reason,source_lego_id,updated_at) "
                    "VALUES(?,?,?,?,?,'dashboard','listener',1,1,?,?,?) ON CONFLICT(listener_id) DO UPDATE SET "
                    "source_deliver_id=excluded.source_deliver_id,target_deliver_id=excluded.target_deliver_id,event_type=excluded.event_type,"
                    "context_selector=excluded.context_selector,jev_gate=1,enabled=1,proposal_reason=excluded.proposal_reason,"
                    "source_lego_id=excluded.source_lego_id,updated_at=excluded.updated_at",
                    (lid, source, target, event_type, json.dumps(selector, ensure_ascii=False, sort_keys=True),
                     (f.get("proposal_reason") or "").strip(), (f.get("source_lego_id") or "").strip() or None, now))
                self.db.event("LISTENER_SAVED", task_id=source, listener_id=lid, target=target, source="dashboard")
                r = f"Listener {lid} saved; activation remains Jev-gated"
            elif a == "toggle_listener":
                lid = self._safe_graph_id(f.get("listener_id", ""), "listener ID")
                enabled = 1 if f.get("enabled") == "1" else 0
                self.db.x("UPDATE deliver_listener_edges SET enabled=?,updated_at=? WHERE listener_id=? AND edge_type='listener'",
                          (enabled, dt.datetime.now(dt.timezone.utc).isoformat(), lid))
                self.db.event("LISTENER_TOGGLED", listener_id=lid, enabled=bool(enabled), source="dashboard")
                r = f"Listener {lid} {'enabled' if enabled else 'disabled'}"
            elif a == "add_dependency":
                dependency = self._safe_graph_id(f.get("depends_on", ""), "dependency")
                target = self._safe_graph_id(f.get("target_deliver_id", ""), "target Deliver")
                self._require_delivers(dependency, target)
                if dependency == target or self._prerequisite_reaches(target, dependency):
                    raise ValueError("dependency would create a cycle")
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                lid = "prerequisite:" + hashlib.sha256(f"{dependency}->{target}".encode()).hexdigest()[:24]
                self.db.x(
                    "INSERT INTO deliver_listener_edges(listener_id,source_deliver_id,target_deliver_id,event_type,source_kind,edge_type,jev_gate,enabled,updated_at) "
                    "VALUES(?,?,?,'PREREQUISITE_PASSED','dashboard','prerequisite',0,1,?) ON CONFLICT(listener_id) DO UPDATE SET enabled=1,updated_at=excluded.updated_at",
                    (lid, dependency, target, now))
                if self.db.task(dependency) and self.db.task(target):
                    self.db.x("INSERT OR IGNORE INTO task_dependencies(task_id,depends_on) VALUES(?,?)", (target, dependency))
                self.db.event("DEPENDENCY_SAVED", task_id=target, depends_on=dependency, source="dashboard")
                r = f"Dependency {dependency} → {target} saved"
            elif a == "add_task_dependency":
                dependency = self._safe_graph_id(f.get("depends_on", ""), "dependency")
                target = self._safe_graph_id(f.get("task_id", ""), "task")
                target_row, dep_row = self.db.task(target), self.db.task(dependency)
                if not target_row or not dep_row:
                    raise ValueError("אחת המשימות אינה קיימת")
                if target_row["state"] in {"RUNNING", "REVIEWING", "PAUSING"}:
                    raise ValueError("אי אפשר לשנות תלויות בזמן שהמשימה רצה")
                if dependency == target or self._task_dependency_reaches(dependency, target):
                    raise ValueError("התלות תיצור מעגל")
                self.db.x("INSERT OR IGNORE INTO task_dependencies(task_id,depends_on) VALUES(?,?)", (target, dependency))
                if self.db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (target,)) and self.db.one(
                        "SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (dependency,)):
                    now = dt.datetime.now(dt.timezone.utc).isoformat()
                    lid = "prerequisite:" + hashlib.sha256(f"{dependency}->{target}".encode()).hexdigest()[:24]
                    self.db.x("INSERT OR IGNORE INTO deliver_listener_edges(listener_id,source_deliver_id,target_deliver_id,event_type,source_kind,edge_type,jev_gate,enabled,updated_at) "
                              "VALUES(?,?,?,'PREREQUISITE_PASSED','dashboard','prerequisite',0,1,?)",
                              (lid, dependency, target, now))
                self.db.event("TASK_DEPENDENCY_SAVED", task_id=target, depends_on=dependency, source="dashboard")
                r = f"התלות במשימה {dependency} נוספה"
            elif a == "add_context":
                deliver_id = (f.get("deliver_id") or "").strip() or None
                if deliver_id and not self.db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (deliver_id,)):
                    raise ValueError("unknown Deliver for context")
                requested_task_id = (f.get("task_id") or "").strip() or None
                if requested_task_id and not self.db.task(requested_task_id):
                    raise ValueError("המשימה המבוקשת אינה קיימת")
                task_id = requested_task_id or (deliver_id if deliver_id and self.db.task(deliver_id) else None)
                source_key = self._safe_graph_id(f.get("source_key", ""), "context source key")
                excerpt = (f.get("excerpt") or "").strip()
                if not excerpt:
                    raise ValueError("context is empty")
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                digest = hashlib.sha256(excerpt.encode()).hexdigest()
                self.db.x(
                    "INSERT INTO context_sources(source_key,task_id,deliver_id,origin_kind,origin_ref,graph_entity_id,title,excerpt,content_sha256,tags_json,active,created_at,updated_at) "
                    "VALUES(?,?,?,'dashboard',?,?,?,?,?,'[]',1,?,?) ON CONFLICT(source_key) DO UPDATE SET "
                    "task_id=excluded.task_id,deliver_id=excluded.deliver_id,origin_ref=excluded.origin_ref,graph_entity_id=excluded.graph_entity_id,title=excluded.title,"
                    "excerpt=excluded.excerpt,content_sha256=excluded.content_sha256,active=1,updated_at=excluded.updated_at",
                    (source_key, task_id, deliver_id, (f.get("origin_ref") or "dashboard").strip(),
                     (f.get("graph_entity_id") or "").strip() or None, (f.get("title") or source_key).strip(),
                     excerpt, digest, now, now))
                if requested_task_id:
                    self.db.x("INSERT INTO task_context_bindings(task_id,source_key,active,created_at,updated_at) VALUES(?,?,1,?,?) "
                              "ON CONFLICT(task_id,source_key) DO UPDATE SET active=1,updated_at=excluded.updated_at",
                              (requested_task_id, source_key, now, now))
                self.db.event("CONTEXT_CANDIDATE_SAVED", task_id=task_id or deliver_id, source_key=source_key,
                              routing="Jev required before LLM dispatch")
                r = f"Context candidate {source_key} saved for Jev selection"
            elif a == "bind_task_context":
                target = self._safe_graph_id(f.get("task_id", ""), "task")
                source_key = self._safe_graph_id(f.get("source_key", ""), "context source")
                if not self.db.task(target) or not self.db.one(
                        "SELECT 1 FROM context_sources WHERE source_key=? AND active=1", (source_key,)):
                    raise ValueError("המשימה או מקור הקונטקסט אינם קיימים")
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                self.db.x("INSERT INTO task_context_bindings(task_id,source_key,active,created_at,updated_at) VALUES(?,?,1,?,?) "
                          "ON CONFLICT(task_id,source_key) DO UPDATE SET active=1,updated_at=excluded.updated_at",
                          (target, source_key, now, now))
                self.db.event("TASK_CONTEXT_GRANTED", task_id=target, source_key=source_key,
                              routing="candidate only; Jev selection required")
                r = f"הגישה למקור {source_key} נוספה כמועמד ל־Jev"
            elif a == "toggle_task_context":
                target = self._safe_graph_id(f.get("task_id", ""), "task")
                source_key = self._safe_graph_id(f.get("source_key", ""), "context source")
                enabled = 1 if f.get("enabled") == "1" else 0
                self.db.x("UPDATE task_context_bindings SET active=?,updated_at=? WHERE task_id=? AND source_key=?",
                          (enabled, dt.datetime.now(dt.timezone.utc).isoformat(), target, source_key))
                self.db.event("TASK_CONTEXT_ACCESS_CHANGED", task_id=target, source_key=source_key, enabled=bool(enabled))
                r = f"הגישה למקור {source_key} {'הופעלה' if enabled else 'הושבתה'}"
            elif a == "create_subtask":
                parent_id = self._safe_graph_id(f.get("parent_task_id", ""), "parent task")
                lines = lambda name: [x.strip() for x in (f.get(name) or "").splitlines() if x.strip()]
                commas = lambda name: [x.strip() for x in (f.get(name) or "").split(",") if x.strip()]
                spec = {
                    "key": f.get("key") or f.get("title"), "title": f.get("title", ""),
                    "instructions": f.get("instructions", ""), "owner": f.get("owner", ""),
                    "model_key": f.get("model_key") or "", "fallback": f.get("fallback") == "1",
                    "depends_on": [], "write_scope": lines("write_scope"),
                    "read_only": f.get("read_only") == "1", "context_files": lines("context_files"),
                    "reference_files": lines("reference_files"), "mcp_servers": commas("mcp_servers"),
                    "tool_names": commas("tool_names"), "acceptance_commands": lines("acceptance_commands"),
                }
                ids = mn.create_subtasks(self.db, self.cfg, parent_id, [spec], self._mcp_cached(), "dashboard")
                r = f"תת־המשימה {ids[0]} נשמרה; היא עדיין אינה Deliver"
            elif a == "promote_subtask":
                pattern_hash = (f.get("pattern_hash") or "").strip()
                if not re.fullmatch(r"[a-f0-9]{64}", pattern_hash):
                    raise ValueError("invalid subtask pattern hash")
                did = self._safe_graph_id(f.get("deliver_id", ""), "Deliver ID")
                mn.promote_subtask_pattern(self.db, self.cfg, pattern_hash, did,
                                           (f.get("owner") or "").strip(), (f.get("domain") or "").strip(),
                                           (f.get("description") or "").strip())
                r = f"הדפוס קוּדם ל־Deliver {did} עם חוזה הביצוע שנלמד"
            elif a == "save_economics":
                did = self._safe_graph_id(f.get("deliver_id", ""), "Deliver ID")
                self._require_delivers(did)
                number = lambda name: (None if not (f.get(name) or "").strip() else float(f[name]))
                fixed, valuation, budget = number("fixed_price"), number("valuation_amount"), number("budget_allocated")
                if any(v is not None and v < 0 for v in (fixed, valuation, budget)):
                    raise ValueError("prices and budgets must be nonnegative")
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                self.db.x(
                    "INSERT INTO deliver_economics(deliver_id,currency,fixed_price,valuation_amount,valuation_as_of,valuation_source_url,valuation_basis,budget_allocated,status,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(deliver_id) DO UPDATE SET currency=excluded.currency,fixed_price=excluded.fixed_price,"
                    "valuation_amount=excluded.valuation_amount,valuation_as_of=excluded.valuation_as_of,valuation_source_url=excluded.valuation_source_url,"
                    "valuation_basis=excluded.valuation_basis,budget_allocated=excluded.budget_allocated,status=excluded.status,updated_at=excluded.updated_at",
                    (did, (f.get("currency") or "USD").upper()[:3], fixed, valuation,
                     (f.get("valuation_as_of") or "").strip() or None, (f.get("valuation_source_url") or "").strip() or None,
                     (f.get("valuation_basis") or "").strip() or None, budget,
                     "PRICED" if fixed is not None else "UNPRICED", now))
                self.db.event("DELIVER_ECONOMICS_SAVED", task_id=did, source="dashboard")
                r = f"Economics for {did} saved"
            else:
                r = f"unknown action {a}"
        except (control.ControlError, mn.ManualError, CredentialError, GraphRagError, state_chat.ChatError, ValueError,
                json.JSONDecodeError) as e:
            r = f"error: {e}"
        self.wake()
        return r

    def run_form(self, form: dict, multi: dict, uploads: list | None = None) -> tuple[bool, str]:
        """One action as (ok, message) — what the socket and the app's JSON POSTs answer with."""
        try:
            if form.get("action") == "add_task":
                ok, message, _page = self.add_task_post(form, multi)
                if ok:
                    message = (f"context plan queued {message}" if message.startswith("PLAN/") else f"created {message}")
                return ok, message
            message = self.action(form, uploads)
        except Exception as exc:
            return False, f"error: {exc}"
        return not (message.startswith("error:") or message.startswith("unknown action")
                    or message == ALREADY_RUNNING), message

    def _battle_request(self, f: dict) -> str:
        """The 'בקשת קרב' form / action: the whole battle-builder task chain from one request."""
        from . import battle_request as br
        text = lambda key: (f.get(key) or "").strip()
        result = br.request_battle(self.db, self.cfg, title=text("title"), battle_key=text("battle_key"),
                                   date=text("date"), date_end=text("date_end"), bbox=text("bbox"),
                                   place=text("place"), notes=f.get("notes") or "")
        return br.message_he(result)

    def _manifest_path(self, value: str) -> Path:
        """A system manifest by name (tools/build_manager/systems/<name>.toml) or by a toml path inside the repo."""
        from . import onboarding as ob
        value = (value or "").strip()
        if not value:
            raise ValueError("יש לציין מניפסט של מערכת")
        if MANIFEST_NAME_RE.fullmatch(value):                 # a bare name: the systems directory first
            named = ob.SYSTEMS_DIR / (value if value.endswith(".toml") else f"{value}.toml")
            if named.is_file():
                return named
        repo = self.cfg.repo.resolve()
        path = (repo / value).resolve()
        if not path.is_relative_to(repo) or path.suffix != ".toml":
            raise ValueError("המניפסט חייב להיות קובץ toml בתוך הריפו או שם מניפסט ידוע")
        if not path.is_file():
            raise ValueError(f"המניפסט לא נמצא: {value}")
        return path

    def _system_onboard(self, f: dict) -> str:
        """`wwii-build onboard <manifest> [--no-graph]`, streaming the same progress lines the CLI prints."""
        from . import onboarding as ob
        path = self._manifest_path(f.get("manifest", ""))
        graph = {"1": True, "0": False}.get((f.get("graph") or "").strip())      # unset: the manifest decides
        self.progress(f"טוען את המניפסט {path.name}")
        report = ob.onboard(self.cfg, self.db, path, graph=graph, progress=self.progress)
        caps = sum((report.get("capabilities") or {}).values())
        self.progress(f"נשמרו {len(report['components'])} קבצי הקשר, {caps} יכולות")
        self.wake()
        return f"המערכת {report['system']} הוטמעה: {len(report['components'])} קבצי הקשר, {caps} יכולות"

    @staticmethod
    def _safe_graph_id(value: str, label: str) -> str:
        value = (value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:/@-]{1,200}", value):
            raise ValueError(f"invalid {label}")
        return value

    def _require_delivers(self, *deliver_ids: str) -> None:
        missing = [did for did in deliver_ids if not self.db.one(
            "SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (did,))]
        if missing:
            raise ValueError("unknown Deliver: " + ", ".join(missing))

    def _prerequisite_reaches(self, source: str, target: str) -> bool:
        return bool(self.db.one(
            "WITH RECURSIVE reach(id) AS (SELECT target_deliver_id FROM deliver_listener_edges "
            "WHERE source_deliver_id=? AND edge_type='prerequisite' AND enabled=1 UNION "
            "SELECT e.target_deliver_id FROM deliver_listener_edges e JOIN reach r ON e.source_deliver_id=r.id "
            "WHERE e.edge_type='prerequisite' AND e.enabled=1) SELECT 1 FROM reach WHERE id=? LIMIT 1",
            (source, target)))

    def _task_dependency_reaches(self, source: str, target: str) -> bool:
        """Whether `source` already depends on `target`, directly or transitively."""
        return bool(self.db.one(
            "WITH RECURSIVE reach(id) AS (SELECT depends_on FROM task_dependencies WHERE task_id=? UNION "
            "SELECT d.depends_on FROM task_dependencies d JOIN reach r ON d.task_id=r.id) "
            "SELECT 1 FROM reach WHERE id=? LIMIT 1", (source, target)))

    # ------------------------------------------------------------------ pages
    def _set_lang(self, h, q: dict | None = None) -> None:
        # This product is operated in Hebrew. Keep identifiers, paths and model
        # names in their original form, but make the entire control surface RTL.
        _LANG.v = "he"
        h._cookie = "wwii_lang=he; Path=/; SameSite=Lax"

    def t(self, text: str) -> str:
        return _t(text, lang())

    def route_get(self, h) -> None:
        """/ is the live app, /app/<file> its static files, /classic/<page> the server-rendered pages."""
        u = urllib.parse.urlparse(h.path)
        if u.path == "/":
            return self.serve_app_index(h)
        if u.path.startswith("/app/"):
            return self.serve_app_file(h, u.path[len("/app/"):])
        if u.path == "/classic" or u.path.startswith("/classic/"):
            h._classic = True                       # H._send points the page's internal links at /classic/ too
            h.path = (u.path[len("/classic"):] or "/") + ("?" + u.query if u.query else "")
        return self.route_classic(h)

    def serve_app_index(self, h) -> None:
        """index.html of the app with this process's token injected (the socket's hello and nothing else reads it)."""
        page = (APP_DIR / "index.html").read_text(encoding="utf-8").replace(TOKEN_PLACEHOLDER, self.token)
        h._send(200, page, nosniff=True)

    def serve_app_file(self, h, rel: str) -> None:
        path = static_file(APP_DIR, rel)
        if path is None:
            return h._send(404, "not found", "text/plain")
        if path == (APP_DIR / "index.html").resolve():
            return self.serve_app_index(h)
        ctype = STATIC_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        h._send(200, path.read_bytes(), ctype, nosniff=True)

    def models_info(self) -> dict:
        """Model profiles for the app's selects. The scheduler (another process) may upgrade them, so they are re-read
        from the config at most every few seconds, like route_classic does for every page."""
        now = time.monotonic()
        if now - getattr(self, "_models_at", -1e9) > 5:
            self._models_at = now
            from .config import load_config
            try:
                self.cfg.data["models"] = load_config(self.cfg.repo, self.cfg.path).data["models"]
            except Exception:                       # a config being rewritten must not stall the live overview
                pass
        return {key: {"provider": value["provider"], "model": value["model"]}
                for key, value in self.cfg.data["models"].items()}

    def route_classic(self, h) -> None:
        # A standalone dashboard and scheduler may run in different processes.
        # Refresh persisted model upgrades before rendering choices and details.
        from .config import load_config
        self.cfg.data["models"] = load_config(self.cfg.repo, self.cfg.path).data["models"]
        u = urllib.parse.urlparse(h.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        self._set_lang(h, q)
        if u.path == "/review":
            return h._send(200, self.page_review(q.get("id", ""), q.get("msg")))
        if u.path == "/game-preview":
            p = Path(__file__).parent / "static/game/index.html"
            return h._send(200, p.read_bytes())
        if u.path.startswith("/game-static/"):
            root = (Path(__file__).parent / "static/game").resolve()
            p = (root / urllib.parse.unquote(u.path[len("/game-static/"):])).resolve()
            if not p.is_relative_to(root) or not p.is_file():
                return h._send(404, "not found", "text/plain")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return h._send(200, p.read_bytes(), ctype)
        if u.path == "/wtfile":
            return self.serve_worktree_file(h, q.get("task", ""), q.get("path", ""), q.get("raw") == "1")
        if u.path == "/new":
            return h._send(200, self.page_new(q.get("msg")))
        if u.path == "/battle":
            return h._send(200, self.page_battle(q.get("msg")))
        if u.path == "/plan":
            return h._send(200, self.page_plan(q.get("msg")))
        if u.path == "/":
            return h._send(200, self.page_overview(q.get("msg")))
        if u.path == "/task":
            return h._send(200, self.page_task(q.get("id", ""), q.get("msg")))
        if u.path == "/events":
            return h._send(200, self.page_events(q))
        if u.path == "/rag":
            return h._send(200, self.page_graph_rag(q.get("msg")))
        if u.path == "/subtasks":
            return h._send(200, self.page_subtasks(q.get("msg")))
        if u.path == "/delivers":
            return h._send(200, self.page_delivers(q.get("msg")))
        if u.path == "/deliver":
            return h._send(200, self.page_deliver(q.get("id", ""), q.get("msg")))
        if u.path == "/api/i18n":
            return h._send(200, json.dumps(i18n.catalog(), ensure_ascii=False), "application/json; charset=utf-8")
        if u.path == "/api/new-task-options":
            return h._send(200, json.dumps(app_data.new_task_options(self), ensure_ascii=False, default=str),
                           "application/json; charset=utf-8")
        if u.path == "/api/battle-request-options":
            return h._send(200, json.dumps(app_data.battle_request_options(self), ensure_ascii=False, default=str),
                           "application/json; charset=utf-8")
        if u.path == "/api/events/facets":
            return h._send(200, json.dumps(app_data.event_facets(self), ensure_ascii=False, default=str),
                           "application/json; charset=utf-8")
        if u.path == "/api/rag/health":
            return h._send(200, json.dumps(self.graph_rag.health(), ensure_ascii=False, default=str),
                           "application/json; charset=utf-8")
        if u.path == "/api/task/diff":
            if not app_data.valid_id(q.get("id", "")):
                return h._send(400, json.dumps({"error": "invalid task id"}), "application/json; charset=utf-8")
            return h._send(200, json.dumps(app_data.task_diff(self, q["id"]), ensure_ascii=False, default=str),
                           "application/json; charset=utf-8")
        if u.path == "/api/delivers":
            return h._send(200, json.dumps(self.delivers_json(), default=str), "application/json")
        if u.path == "/api/events":
            return h._send(200, json.dumps(self.events_json(q), ensure_ascii=False, default=str),
                           "application/json; charset=utf-8")
        if u.path == "/api/state":
            return h._send(200, json.dumps(self.state_json(), default=str), "application/json")
        if u.path.startswith("/artifact/"):
            row = self.db.one("SELECT * FROM artifacts WHERE id=?", (int(u.path.rsplit("/", 1)[1]),))
            if not row or not Path(row["path"]).is_file():
                return h._send(404, "not found", "text/plain")
            p = Path(row["path"])
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") and p.suffix not in (".html", ".htm") or p.suffix in (".md", ".json", ".tscn", ".gd"):
                return h._send(200, redact(p.read_text(errors="replace")), "text/plain; charset=utf-8", sandbox=True)
            return h._send(200, p.read_bytes(), ctype, sandbox=True)
        if u.path.startswith("/log/"):
            _, _, aid, which = u.path.split("/")
            a = self.db.one("SELECT * FROM task_attempts WHERE id=?", (int(aid),))
            path = {"stdout": a and a["stdout_path"], "stderr": a and a["stderr_path"],
                    "message": a and a["last_message_path"]}.get(which)
            if which == "prompt" and a and a["context_pack_id"]:
                cp = self.db.one("SELECT prompt_path FROM context_packs WHERE id=?", (a["context_pack_id"],))
                path = cp and cp["prompt_path"]
            if which == "diff" and a:
                rd = Path(a["stdout_path"]).parent / "diff.patch" if a["stdout_path"] else None
                path = str(rd) if rd and rd.exists() else None
            if not path or not Path(path).is_file():
                return h._send(404, "not found", "text/plain")
            return h._send(200, redact(Path(path).read_text(errors="replace")), "text/plain; charset=utf-8")
        h._send(404, "not found", "text/plain")

    def _form(self, action: str, label: str, cls: str = "", confirm: str | None = None, back: str = "/", **fields) -> str:
        hidden = "".join(f'<input type="hidden" name="{E(k)}" value="{E(str(v))}">' for k, v in fields.items())
        onsub = f' onsubmit="return confirm({E(json.dumps(confirm))})"' if confirm else ""
        return (f'<form method="post" action="/action"{onsub}><input type="hidden" name="token" value="{self.token}">'
                f'<input type="hidden" name="action" value="{action}"><input type="hidden" name="back" value="{E(back)}">'
                f'{hidden}<button class="{cls}">{E(label)}</button></form>')

    @staticmethod
    def _planner_upload_box(uid: str) -> str:
        input_id = f"planner-files-{uid}"
        return (f"<div class='upload-zone' data-input='{E(input_id)}' role='button' tabindex='0' "
                f"aria-label='העלאת קבצים ותמונות למתכנן'><span class='upload-icon'>＋</span>"
                f"<strong>גררו לכאן תמונות וקבצים, או לחצו לבחירה</strong>"
                f"<small>עד 8 קבצים, 10MB לקובץ ו־25MB בסך הכול. רק פריטים ש־Jev יבחר יגיעו למודל.</small>"
                f"<input id='{E(input_id)}' type='file' name='planner_files' multiple hidden "
                f"accept='image/png,image/jpeg,image/gif,image/webp,text/*,.md,.json,.yaml,.yml,.toml,.csv,.tsv,.pdf'>"
                f"<div class='upload-list' aria-live='polite'></div></div>")

    def _layout(self, title: str, body: str, msg: str | None) -> str:
        L = "he"
        live_banner = ("<div class='banner classic-banner'>זהו המסך הקלאסי הסטטי — הוא אינו מתרענן מעצמו. "
                       "<a class='live-app-link' href='/app/index.html'>למעבר לאפליקציה החיה</a> · "
                       "<a class='live-app-link' href='/app/index.html#/tasks?view=active'>פעילות וממתינות</a> · "
                       "<a class='live-app-link' href='/app/index.html#/tasks?view=problems'>נכשלו / נחסמו</a> · "
                       "<a class='live-app-link' href='/app/index.html#/tasks?view=history'>היסטוריה</a> · לרענון לחצו F5.</div>")
        flash = f'<div class="flash">{E(msg)}</div>' if msg else ""
        nav = ("<nav class='top'><a href='/'>סקירה</a><a href='/delivers'>מרכז ה־Delivers</a><a href='/subtasks'>תתי־משימות ודפוסים</a><a href='/rag'>גרף RAG</a>"
               "<a href='/new'>+ משימה חדשה</a><a href='/battle'>בקשת קרב</a><a href='/plan'>פרומפט למשימות</a><a href='/events'>יומן אירועים</a>"
               f"<form method='post' action='/action' class='nav-unstick'><input type='hidden' name='token' value='{self.token}'>"
               "<input type='hidden' name='action' value='unstick'><input type='hidden' name='back' value='/'>"
               "<button class='go' title='מאבחן למה הריצה תקועה ומשחרר את מה שאפשר אוטומטית'>⟳ למה תקוע? המשך</button></form></nav>")
        prompt_bar = (f"<div class='card prompt-console'><div class='prompt-console-head'><b>מתכנן המערכת</b>"
                      f"<span>כתוב משימה רחבה ומפורטת. ברירת המחדל בוחרת את המודל המתאים ביותר לתכנון; המתכנן יבחר פירוק, מודלים, קונטקסט, כלים ותלויות.</span></div>"
                      f"<form class='prompt-grid' method='post' action='/action' enctype='multipart/form-data'>"
                      f"<input type='hidden' name='token' value='{self.token}'><input type='hidden' name='action' value='plan'>"
                      f"<input type='hidden' name='back' value='/plan'><textarea class='planner-main-prompt' name='prompt' required "
                      f"aria-label='פרומפט רחב למתכנן' placeholder='תאר כאן את המטרה המלאה, הדרישות, המגבלות והתוצאה הרצויה. המתכנן יפרק אותה למשימות ויבחר עבור כל אחת את המודל, הקונטקסט, הכלים והתלויות.'></textarea>"
                      f"{self._planner_upload_box('global')}"
                      f"<div class='planner-controls'><select name='prompt_mode' aria-label='מה המתכנן יעשה'>"
                      f"<option value='plan_build'>תכנן משימה רחבה לביצוע</option><option value='advise_next'>ייעוץ בלבד: הצעד הבא</option>"
                      f"<option value='graph_query'>תשובה מהגרף</option></select>"
                      f"<span class='muted'>האישור האוטומטי קובע אם ההצעה נעצרת לאישורך.</span>"
                      f"<button class='big go'>שלח למתכנן</button>"
                      f"<details><summary>עקיפות מתקדמות — בדרך כלל המתכנן בוחר לבד</summary><div class='advanced-grid'>"
                      f"<select name='model_key' aria-label='עקיפת מודל המתכנן'><option value=''>אוטומטי: המודל המתאים ביותר</option>{self._model_options('')}</select>"
                      f"<input type='text' name='mcp_servers' aria-label='עקיפת שרתי MCP' placeholder='MCP ידני, רק אם חייבים'></div></details>"
                      f"</div></form></div>")
        banner = ""
        if control.daemon_pid(self.cfg) and int(self.db.get_flag("daemon_code_version") or 0) < mn.CODE_VERSION:
            banner = ("<div class='banner'>restart required: the running daemon predates manual/planner tasks. "
                      "pause → wait for running tasks → stop → start → resume.</div>")
        html_ = (f"<!doctype html><html lang='he' dir='rtl'><head><meta charset='utf-8'>"
                 f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{E(title)}</title>"
                 f"<style>{CSS}</style></head><body><main>{live_banner}{nav}{prompt_bar}{banner}{flash}{body}</main>"
                 f"{CLASSIC_JS}</body></html>")
        return localize(html_, L)

    def task_rows(self) -> list[dict]:
        """Task rows as the dashboard shows them, without the derived Hebrew description."""
        rows = [dict(r) for r in self.db.q("SELECT task_id, packet, owner, wave, state, state_reason, last_model_key, "
                                           "title,note,extra,lego_ids, "
                                           "not_before, kind, parent_task_id, repair_no, failure_class, repairs_count, "
                                           "active_repair_id,dispatch_priority FROM tasks ORDER BY wave, task_id")]
        for row in rows:
            row["allow_web"] = bool(web_badge(row["extra"]))
        return rows

    def worker_rows(self) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT * FROM workers")]

    def pending_approval_rows(self) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT * FROM approvals WHERE status='pending'")]

    def quota_rows(self) -> list[dict]:
        return QuotaManager(self.db, self.cfg.section("quota")).accounts()

    def state_json(self) -> dict:
        tasks = self.task_rows()
        for task in tasks:
            task["description_he"] = task_he(self.cfg, task)
        return {"daemon_pid": control.daemon_pid(self.cfg), "paused": bool(self.db.get_flag("paused")),
                "emergency_stop": self.db.get_flag("emergency_stop"), "idle_reason": self.db.get_flag("idle_reason"),
                "next_wakeup_at": self.db.get_flag("next_wakeup_at"),
                "review_auto_approve_all": self.db.get_flag("review_auto_approve_all") == "1", "tasks": tasks,
                "workers": self.worker_rows(), "quota": self.quota_rows(),
                "approvals": self.pending_approval_rows(),
                "jev": self.jev.status(), "model_watch": ModelWatch(self.cfg, self.db).status(),
                "models": {key: {"provider": value["provider"], "model": value["model"]}
                           for key, value in self.cfg.data["models"].items()}}

    @staticmethod
    def _event_query(q: dict) -> dict:
        def clean(name: str, maximum: int = 200) -> str | None:
            value = (q.get(name) or "").strip()
            return value[:maximum] or None

        try:
            limit = max(1, min(int(q.get("limit") or 100), 400))
        except (TypeError, ValueError):
            limit = 100
        try:
            before_id = int(q["before_id"]) if q.get("before_id") else None
        except (TypeError, ValueError):
            before_id = None
        return {"limit": limit, "before_id": before_id, "task_id": clean("task_id"),
                "provider": clean("provider"), "event": clean("event"), "search": clean("search", 300)}

    @staticmethod
    def event_item(row) -> dict:
        """One event_log row with its JSON detail decoded (shared by /api/events and the live socket)."""
        item = dict(row)
        raw = item.pop("detail", None)
        try:
            item["detail"] = json.loads(raw) if raw else None
        except (TypeError, json.JSONDecodeError):
            item["detail"] = raw
        return item

    def events_json(self, q: dict | None = None) -> dict:
        """Return one journal page sourced directly from SQLite."""
        filters = self._event_query(q or {})
        rows = self.db.events(**filters)
        items = [self.event_item(row) for row in rows]
        count_filters = {k: filters[k] for k in ("task_id", "provider", "event", "search")}
        return {"source": "sqlite:event_log", "database": str(self.cfg.db_path),
                "total": self.db.event_count(**count_filters), "limit": filters["limit"],
                "next_before_id": items[-1]["id"] if len(items) == filters["limit"] else None,
                "events": items}

    def delivers_json(self) -> dict:
        delivers = [dict(r) for r in self.db.q(
            "SELECT c.*,t.state,t.state_reason,t.preferred_model_key task_preferred_model_key,t.last_model_key,t.wave,e.fixed_price,e.valuation_amount,e.valuation_as_of,e.valuation_source_url,e.budget_allocated,e.budget_reserved,e.budget_spent,e.status economics_status "
            "FROM deliver_catalog c LEFT JOIN tasks t ON t.task_id=c.deliver_id LEFT JOIN deliver_economics e ON e.deliver_id=c.deliver_id ORDER BY COALESCE(t.wave,999),c.deliver_id")]
        context_by_deliver = {row["deliver_id"]: dict(row) for row in self.db.q(
            "SELECT deliver_id,COUNT(*) context_source_count,"
            "COALESCE(SUM(LENGTH(CAST(excerpt AS BLOB))),0) context_source_bytes "
            "FROM context_sources WHERE active=1 AND deliver_id IS NOT NULL GROUP BY deliver_id")}
        global_context = self.db.one(
            "SELECT COUNT(*) context_source_count,COALESCE(SUM(LENGTH(CAST(excerpt AS BLOB))),0) context_source_bytes "
            "FROM context_sources WHERE active=1 AND deliver_id IS NULL")
        global_count = int(global_context["context_source_count"] if global_context else 0)
        global_bytes = int(global_context["context_source_bytes"] if global_context else 0)
        packs_by_deliver = {row["task_id"]: dict(row) for row in self.db.q(
            "SELECT p.task_id,COUNT(*) context_pack_count,COALESCE(SUM(p.total_bytes),0) context_pack_bytes,"
            "(SELECT p2.total_bytes FROM context_packs p2 WHERE p2.task_id=p.task_id ORDER BY p2.id DESC LIMIT 1) latest_context_bytes "
            "FROM context_packs p GROUP BY p.task_id")}
        cost_by_deliver = {row["task_id"]: dict(row) for row in self.db.q(
            "SELECT task_id,COUNT(*) attempt_count,COALESCE(SUM(reported_cost_usd),0) reported_cost_usd,"
            "SUM(CASE WHEN ended_at IS NOT NULL AND reported_cost_usd IS NULL THEN 1 ELSE 0 END) unknown_cost_attempts,"
            "COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(cached_input_tokens),0) cached_input_tokens,"
            "COALESCE(SUM(output_tokens),0) output_tokens FROM task_attempts GROUP BY task_id")}
        deterministic_by_deliver = {row["deliver_id"]: dict(row) for row in self.db.q(
            "SELECT deliver_id,COUNT(*) deterministic_run_count,"
            "SUM(CASE WHEN status='RUNNING' THEN 1 ELSE 0 END) deterministic_running_count,"
            "COALESCE(SUM(input_bytes),0) deterministic_input_bytes,COALESCE(SUM(output_bytes),0) deterministic_output_bytes "
            "FROM deterministic_deliver_runs GROUP BY deliver_id")}
        for deliver in delivers:
            deliver["description_he"] = deliver_description_he(self.cfg, self.db, deliver)
            deliver["implementation_he"] = deliver_implementation_he(self.db, deliver)
            own = context_by_deliver.get(deliver["deliver_id"], {})
            pack = packs_by_deliver.get(deliver["deliver_id"], {})
            costs = cost_by_deliver.get(deliver["deliver_id"], {})
            deterministic = deterministic_by_deliver.get(deliver["deliver_id"], {})
            deliver.update({
                "context_source_count": int(own.get("context_source_count") or 0),
                "context_source_bytes": int(own.get("context_source_bytes") or 0),
                "global_context_source_count": global_count,
                "global_context_bytes": global_bytes,
                "context_pack_count": int(pack.get("context_pack_count") or 0),
                "context_pack_bytes": int(pack.get("context_pack_bytes") or 0),
                "latest_context_bytes": int(pack.get("latest_context_bytes") or 0),
                "attempt_count": int(costs.get("attempt_count") or 0),
                "reported_cost_usd": float(costs.get("reported_cost_usd") or 0),
                "unknown_cost_attempts": int(costs.get("unknown_cost_attempts") or 0),
                "input_tokens": int(costs.get("input_tokens") or 0),
                "cached_input_tokens": int(costs.get("cached_input_tokens") or 0),
                "output_tokens": int(costs.get("output_tokens") or 0),
                "deterministic_run_count": int(deterministic.get("deterministic_run_count") or 0),
                "deterministic_running_count": int(deterministic.get("deterministic_running_count") or 0),
                "deterministic_input_bytes": int(deterministic.get("deterministic_input_bytes") or 0),
                "deterministic_output_bytes": int(deterministic.get("deterministic_output_bytes") or 0),
            })
        activations = [dict(r) for r in self.db.q("SELECT * FROM listener_activations ORDER BY created_at DESC LIMIT 200")]
        active_activations = [dict(r) for r in self.db.q(
            "SELECT a.*,e.event_type FROM listener_activations a "
            "LEFT JOIN deliver_state_events e ON e.event_id=a.event_id "
            "WHERE a.status IN ('SELECTED','RUNNING') ORDER BY a.created_at DESC")]
        context_totals = self.db.one(
            "SELECT COUNT(*) source_count,COALESCE(SUM(LENGTH(CAST(excerpt AS BLOB))),0) source_bytes "
            "FROM context_sources WHERE active=1")
        pack_totals = self.db.one(
            "SELECT COUNT(*) pack_count,COALESCE(SUM(total_bytes),0) pack_bytes FROM context_packs")
        attempt_cost = self.db.one(
            "SELECT COUNT(*) attempt_count,COALESCE(SUM(reported_cost_usd),0) reported_cost_usd,"
            "SUM(CASE WHEN ended_at IS NOT NULL AND reported_cost_usd IS NULL THEN 1 ELSE 0 END) unknown_cost_attempts,"
            "COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(cached_input_tokens),0) cached_input_tokens,"
            "COALESCE(SUM(output_tokens),0) output_tokens FROM task_attempts")
        jev_cost = self.db.one(
            "SELECT COUNT(*) request_count,COALESCE(SUM(input_tokens),0) input_tokens,"
            "COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(estimated_cost),0) estimated_cost,"
            "SUM(CASE WHEN uncertain=1 OR (input_tokens IS NULL OR output_tokens IS NULL) THEN 1 ELSE 0 END) uncertain_requests,"
            "MIN(unit) unit FROM jev_usage_requests")
        worker_context = self.db.one("SELECT COUNT(*) worker_count,COALESCE(SUM(context_bytes),0) context_bytes FROM workers")
        deterministic_totals = self.db.one(
            "SELECT COUNT(*) run_count,SUM(CASE WHEN status='RUNNING' THEN 1 ELSE 0 END) running_count,"
            "COALESCE(SUM(input_bytes),0) input_bytes,COALESCE(SUM(output_bytes),0) output_bytes "
            "FROM deterministic_deliver_runs")
        runtime = {
            "context": {"source_count": int(context_totals["source_count"] if context_totals else 0),
                        "source_bytes": int(context_totals["source_bytes"] if context_totals else 0),
                        "global_source_count": global_count, "global_source_bytes": global_bytes,
                        "pack_count": int(pack_totals["pack_count"] if pack_totals else 0),
                        "pack_bytes": int(pack_totals["pack_bytes"] if pack_totals else 0),
                        "active_worker_count": int(worker_context["worker_count"] if worker_context else 0),
                        "active_worker_bytes": int(worker_context["context_bytes"] if worker_context else 0)},
            "cost_memory": {"reported_cost_usd": float(attempt_cost["reported_cost_usd"] if attempt_cost else 0),
                            "unknown_cost_attempts": int((attempt_cost["unknown_cost_attempts"] if attempt_cost else 0) or 0),
                            "attempt_count": int(attempt_cost["attempt_count"] if attempt_cost else 0),
                            "input_tokens": int(attempt_cost["input_tokens"] if attempt_cost else 0),
                            "cached_input_tokens": int(attempt_cost["cached_input_tokens"] if attempt_cost else 0),
                            "output_tokens": int(attempt_cost["output_tokens"] if attempt_cost else 0),
                            "jev_requests": int(jev_cost["request_count"] if jev_cost else 0),
                            "jev_input_tokens": int(jev_cost["input_tokens"] if jev_cost else 0),
                            "jev_output_tokens": int(jev_cost["output_tokens"] if jev_cost else 0),
                            "jev_estimated_cost": float(jev_cost["estimated_cost"] if jev_cost else 0),
                            "jev_unit": str(jev_cost["unit"] or "tokens") if jev_cost else "tokens",
                            "jev_uncertain_requests": int((jev_cost["uncertain_requests"] if jev_cost else 0) or 0)},
            "listeners": {"active_count": len(active_activations),
                          "running_count": sum(a["status"] == "RUNNING" for a in active_activations),
                          "selected_count": sum(a["status"] == "SELECTED" for a in active_activations),
                          "total_count": len(activations)},
            "deterministic": {"deliver_count": sum(d["execution_kind"] == "deterministic" for d in delivers),
                              "run_count": int(deterministic_totals["run_count"] if deterministic_totals else 0),
                              "running_count": int((deterministic_totals["running_count"] if deterministic_totals else 0) or 0),
                              "input_bytes": int(deterministic_totals["input_bytes"] if deterministic_totals else 0),
                              "output_bytes": int(deterministic_totals["output_bytes"] if deterministic_totals else 0)},
        }
        return {"delivers": delivers,
                "edges": [dict(r) for r in self.db.q("SELECT * FROM deliver_listener_edges ORDER BY edge_type,source_deliver_id,target_deliver_id")],
                "active_listeners": [r["listener_id"] for r in activations if r["status"] in ("SELECTED", "RUNNING")],
                "activations": activations,
                "active_activations": active_activations,
                "runtime": runtime,
                "deliver_events": [dict(r) for r in self.db.q("SELECT * FROM deliver_state_events ORDER BY created_at DESC LIMIT 100")],
                "episode_states": [dict(r) for r in self.db.q("SELECT * FROM episode_build_states ORDER BY updated_at DESC LIMIT 50")],
                "running": [r["task_id"] for r in self.db.q("SELECT task_id FROM workers")],
                "context_sources": [dict(r) for r in self.db.q("SELECT * FROM context_sources WHERE active=1 ORDER BY updated_at DESC LIMIT 200")],
                "jev": self.jev.status(),
                "decisions": [dict(r) for r in self.db.q("SELECT * FROM jev_route_decisions ORDER BY id DESC LIMIT 100")],
                "usage_events": [dict(r) for r in self.db.q("SELECT * FROM jev_usage_events ORDER BY id DESC LIMIT 50")]}

    def _deliver_graph(self, data: dict) -> str:
        nodes = data["delivers"]
        if not nodes:
            return "<p class='muted'>No Delivers imported yet. Run import-plan.</p>"
        by_wave: dict[int, list[dict]] = {}
        for n in nodes:
            by_wave.setdefault(int(n["wave"] if n.get("wave") is not None else 99), []).append(n)
        pos: dict[str, tuple[int, int]] = {}
        for col, wave in enumerate(sorted(by_wave)):
            for row, n in enumerate(by_wave[wave]):
                pos[n["deliver_id"]] = (90 + col * 190, 45 + row * 72)
        width = max(x for x, _ in pos.values()) + 110
        height = max(y for _, y in pos.values()) + 55
        edges = []
        active_listeners = set(data.get("active_listeners", []))
        for edge in data["edges"]:
            if edge["source_deliver_id"] not in pos or edge["target_deliver_id"] not in pos:
                continue
            x1, y1 = pos[edge["source_deliver_id"]]; x2, y2 = pos[edge["target_deliver_id"]]
            cls = ("edge listener active" if edge["listener_id"] in active_listeners else
                   "edge listener pending" if edge["edge_type"] == "listener" and not edge["enabled"] else
                   "edge listener" if edge["edge_type"] == "listener" else "edge")
            start_x, end_x = x1 + 62, x2 - 62
            bend = max(45, abs(end_x - start_x) * .42)
            c1 = start_x + bend if end_x >= start_x else start_x - bend
            c2 = end_x - bend if end_x >= start_x else end_x + bend
            edges.append(f"<path class='{cls}' fill='none' marker-end='url(#arrow)' d='M {start_x} {y1} C {c1} {y1}, {c2} {y2}, {end_x} {y2}'>"
                         f"<title>{E(edge['edge_type'])}: {E(edge['source_deliver_id'])} → {E(edge['target_deliver_id'])}</title></path>")
        running = set(data["running"])
        boxes = []
        for n in nodes:
            x, y = pos[n["deliver_id"]]; state = n.get("state") or "CATALOG"
            cls = "node running" if n["deliver_id"] in running else "node passed" if state == "PASSED" else "node"
            label = n["deliver_id"] if len(n["deliver_id"]) <= 22 else n["deliver_id"][:20] + "…"
            href = "/deliver?id=" + urllib.parse.quote(n["deliver_id"])
            boxes.append(f"<a href='{href}'><rect class='{cls}' x='{x-64}' y='{y-22}' width='128' height='44' rx='7'>"
                         f"<title>{E(n['deliver_id'])} · {E(n['execution_kind'])} · {E(state)} · לחץ לפרטים</title></rect>"
                         f"<text class='nlabel' x='{x}' y='{y-2}' text-anchor='middle'>{E(label)}</text>"
                         f"<text class='nlabel' x='{x}' y='{y+13}' text-anchor='middle'>{E(n['execution_kind'])} · {E(state)}</text></a>")
        defs = "<defs><marker id='arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='5' markerHeight='5' orient='auto-start-reverse'><path d='M 0 0 L 10 5 L 0 10 z' fill='#88a8c9'/></marker></defs>"
        return f"<svg class='graph' viewBox='0 0 {width} {height}' role='img'>{defs}{''.join(edges)}{''.join(boxes)}</svg>"

    def page_delivers(self, msg: str | None) -> str:
        data = self.delivers_json(); js = data["jev"]; usage = js["usage"]
        runtime = data["runtime"]; context_runtime = runtime["context"]
        cost_memory = runtime["cost_memory"]; listener_runtime = runtime["listeners"]
        deterministic_runtime = runtime["deterministic"]
        he_status = {
            "READY": "מוכן", "MISSING_CREDENTIAL": "חסר מפתח", "AUTH_FAILED": "האימות נכשל",
            "API_UNREACHABLE": "השירות אינו נגיש", "RATE_LIMITED": "הגעת למגבלת קצב",
            "NO_CREDITS": "אין יתרה", "INVALID_RESPONSE": "תשובה לא תקינה", "reachable": "נגיש",
            "unknown": "לא ידוע", "present": "קיים", "missing": "חסר", "OK": "תקין",
            "not_checked": "טרם נבדק", "NOT_CHECKED": "טרם נבדק", "healthy": "תקין",
            "tokens": "טוקנים", "LOCAL_ESTIMATE": "הערכה מקומית", "local_estimate": "הערכה מקומית",
        }
        execution_he = {"worker": "סוכן ביצוע", "deterministic": "פונקציה דטרמיניסטית",
                        "llm_research": "מחקר מודל", "context_bundle": "חבילת קונטקסט", "review": "בקרת איכות"}
        translate = lambda value: he_status.get(str(value), state_label(str(value), "he"))
        official = "זמין" if usage.get("official_balance_available") else "לא קיים בתיעוד הרשמי"
        credential = (f"שמור ב־{js['credential_source']}" if js.get("credential_present") else "חסר")
        jev_card = (f"<div class='counts'><div class='count'><span>מצב ניתוב Jev</span><b>{E(translate(js['routing']))}</b></div>"
                    f"<div class='count'><span>מפתח גישה</span><b>{E(credential)}</b><small>הערך לעולם אינו מוצג</small></div>"
                    f"<div class='count'><span>API ואימות</span><b>{E(translate(js['api']))}</b><small>{E(translate(js['authentication']))}</small></div>"
                    f"<div class='count'><span>מודל Jev</span><b class='mono'>{E(js.get('model') or 'לא ידוע')}</b></div>"
                    f"<div class='count'><span>מצב שימוש</span><b>{E(translate(usage['state']))}</b></div>"
                    f"<div class='count'><span>יתרה משוערת</span><b>{E(str(usage['remaining']) if usage['remaining'] is not None else 'לא ידוע')}</b><small>{E(usage['unit'])} · {E(usage['basis'])}</small></div>"
                    f"<div class='count'><span>API רשמי ליתרה</span><b>{E(official)}</b></div></div>")
        jev_memory = (f"{cost_memory['jev_input_tokens'] + cost_memory['jev_output_tokens']:,} טוקנים"
                      if cost_memory["jev_unit"] == "tokens" else
                      f"{cost_memory['jev_estimated_cost']:.4f} {cost_memory['jev_unit']}")
        runtime_panel = (
            "<h2>מצב הריצה וזיכרון מצטבר</h2><div class='runtime-strip'>"
            f"<div class='runtime-metric'><span>שכבת קונטקסט רשומה</span><strong>{fmt_bytes(context_runtime['source_bytes'])}</strong>"
            f"<small>{context_runtime['source_count']} מקורות פעילים · {context_runtime['global_source_count']} גלובליים</small></div>"
            f"<div class='runtime-metric'><span>Context Packs שנבנו</span><strong>{fmt_bytes(context_runtime['pack_bytes'])}</strong>"
            f"<small>{context_runtime['pack_count']} חבילות שמורות במסד</small></div>"
            f"<div class='runtime-metric{' live' if context_runtime['active_worker_count'] else ''}'><span>קונטקסט בריצה עכשיו</span>"
            f"<strong>{fmt_bytes(context_runtime['active_worker_bytes'])}</strong><small>{context_runtime['active_worker_count']} workers פעילים</small></div>"
            f"<div class='runtime-metric'><span>עלות מדווחת שמורה</span><strong>${cost_memory['reported_cost_usd']:.4f}</strong>"
            f"<small>{cost_memory['attempt_count']} ניסיונות · {cost_memory['unknown_cost_attempts']} ללא מחיר מדווח</small></div>"
            f"<div class='runtime-metric'><span>זיכרון טוקנים של workers</span><strong>{cost_memory['input_tokens'] + cost_memory['cached_input_tokens'] + cost_memory['output_tokens']:,}</strong>"
            f"<small>{cost_memory['input_tokens']:,} קלט · {cost_memory['cached_input_tokens']:,} מטמון · {cost_memory['output_tokens']:,} פלט</small></div>"
            f"<div class='runtime-metric'><span>שימוש Jev שמור</span><strong>{E(jev_memory)}</strong>"
            f"<small>{cost_memory['jev_requests']} בקשות · {cost_memory['jev_uncertain_requests']} עם שימוש לא ודאי</small></div>"
            f"<div class='runtime-metric{' live' if listener_runtime['active_count'] else ''}'><span>Listeners פעילים</span>"
            f"<strong>{listener_runtime['active_count']}</strong><small>{listener_runtime['running_count']} רצים · "
            f"{listener_runtime['selected_count']} נבחרו וממתינים</small></div>"
            f"<div class='runtime-metric'><span>Delivers דטרמיניסטיים</span><strong>{deterministic_runtime['deliver_count']}</strong>"
            f"<small>{deterministic_runtime['run_count']} הרצות שמורות · עלות מודל $0</small></div></div>")
        live_listener_cards = "".join(
            f"<div class='listener-live {E(a['status'].lower())}'><div class='bar'><b class='mono'>{E(a['listener_id'])}</b>{pill(a['status'])}</div>"
            f"<span class='route mono'>{E(a['source_deliver_id'])} → {E(a['target_deliver_id'])}</span>"
            f"<small>{E(a.get('event_type') or '')} · אירוע {E(a['event_id'])} · גרסת מצב {a['selected_state_version']} · {E(ago(a['created_at']))}</small></div>"
            for a in data["active_activations"])
        live_listener_content = live_listener_cards or (
            "<div class='listener-empty'>אין כרגע listener שנבחר או רץ. ההיסטוריה נשמרת במסד.</div>")
        live_listeners = (
            "<section><div class='shelf-title'><h2>Listeners שנבחרו או רצים בפועל</h2>"
            "<small>SELECTED ממתין להפעלה · RUNNING מבצע עבודה עכשיו</small></div>"
            f"<div class='listener-live-grid'>{live_listener_content}</div></section>")
        key_form = (f"<div class='card'><div class='grid2'><form method='post' action='/action'>"
                    f"<input type='hidden' name='token' value='{self.token}'><input type='hidden' name='action' value='save_typesafe_key'>"
                    f"<input type='hidden' name='back' value='/delivers'><label class='blk'>מפתח API של TypeSafe</label>"
                    f"<input type='password' name='typesafe_key' autocomplete='new-password' required placeholder='נשמר ב־Keychain: typesafe-delivers'>"
                    f"<p><button class='go'>שמור מפתח והרץ בדיקה חיה</button></p></form><div>"
                    f"<p>המפתח מועבר בזיכרון בלבד ל־SDK הרשמי של TypeSafe. הוא אינו נשמר במסד הנתונים, בקובצי הגדרות, בלוגים, בכתובות או בריפו.</p>"
                    f"{self._form('jev_health', 'הרץ בדיקת תקינות חיה', '', back='/delivers')}</div></div></div>")
        outgoing: dict[str, list[dict]] = {}
        for edge in data["edges"]:
            if edge["edge_type"] == "listener":
                outgoing.setdefault(edge["source_deliver_id"], []).append(edge)
        shelves: dict[int, list[str]] = {}
        deterministic_cards: list[str] = []
        system_shelves: dict[str, list[str]] = {}
        cap_counts = {r["deliver_id"]: (r["g"], r["n"]) for r in self.db.q(
            "SELECT deliver_id, COUNT(DISTINCT group_name) g, COUNT(*) n FROM deliver_capabilities WHERE active=1 "
            "GROUP BY deliver_id")}
        for d in data["delivers"]:
            did = d["deliver_id"]
            wave = int(d["wave"] if d.get("wave") is not None else 99)
            state = d.get("state") or ("AVAILABLE" if d.get("enabled") else "PAUSED")
            palette = int(hashlib.sha256(did.encode()).hexdigest()[:2], 16) % 6
            mark = did.rsplit("/", 1)[-1].rsplit(".", 1)[-1][:18]
            listener_count = len(outgoing.get(did, []))
            model = ("פונקציה מקומית" if d["execution_kind"] == "deterministic" else
                     d.get("preferred_model_key") or d.get("task_preferred_model_key") or
                     d.get("last_model_key") or "בחירה אוטומטית")
            price = str(d["fixed_price"]) if d.get("fixed_price") is not None else "טרם תומחר"
            spent = float(d.get("budget_spent") or 0); allocated = float(d.get("budget_allocated") or 0)
            pct = min(100, round((spent / allocated) * 100)) if allocated > 0 else 0
            search = " ".join(str(d.get(k) or "") for k in ("deliver_id", "owner", "domain", "description", "execution_kind")).lower()
            if d.get("source_kind") == "system_manifest":
                groups_n, caps_n = cap_counts.get(did, (0, 0))
                system_shelves.setdefault(d.get("packet") or "system", []).append(
                    f"<a class='deliver-tile palette-{palette}' data-deliver-card data-search='{E(search)}' href='/deliver?id={urllib.parse.quote(did)}'>"
                    f"<div class='deliver-cover'><div class='cover-top'><span class='cover-wave'>{E(d.get('domain') or '')}</span>"
                    f"<span class='cover-kind'>{E(execution_he.get(d['execution_kind'], d['execution_kind']))}</span></div>"
                    f"<div class='deliver-mark mono'>{E(mark)}</div></div><div class='deliver-info'>"
                    f"<h3>{E(did)}</h3><div>{pill(d.get('availability', 'available').upper())}</div>"
                    f"<div class='deliver-description'>{E(d['description_he'])}</div>"
                    f"<div class='deliver-meta'><div class='meta-item'><span>יכולות</span><b>{groups_n}</b></div>"
                    f"<div class='meta-item'><span>תתי־יכולות</span><b>{caps_n}</b></div>"
                    f"<div class='meta-item'><span>אחראי</span><b>{E(d.get('owner') or 'טרם הוקצה')}</b></div>"
                    f"<div class='meta-item'><span>מודל או מנוע</span><b>{E(model)}</b></div>"
                    f"<div class='meta-item'><span>קונטקסט זמין</span><b>{fmt_bytes(d['context_source_bytes'] + d['global_context_bytes'])}</b></div>"
                    f"<div class='meta-item'><span>מאזינים מוצעים</span><b>{listener_count}</b></div></div></div></a>")
                continue
            if d["execution_kind"] == "deterministic":
                deterministic_cards.append(
                    f"<a class='deterministic-tile' data-deliver-card data-search='{E(search)}' href='/deliver?id={urllib.parse.quote(did)}'>"
                    f"<div class='bar'><span class='cover-kind'>פונקציה מקומית · שמור ב־DB</span>{pill(state)}</div>"
                    f"<h3>{E(did)}</h3><div class='deliver-description'>{E(d['description_he'])}</div>"
                    f"<div class='mini-grid'><div><span>קונטקסט זמין</span><b>{fmt_bytes(d['context_source_bytes'] + d['global_context_bytes'])}</b></div>"
                    f"<div><span>הרצות שמורות</span><b>{d['deterministic_run_count']}</b></div>"
                    f"<div><span>עלות מודל</span><b>$0</b></div></div></a>")
                continue
            card = (f"<a class='deliver-tile palette-{palette}' data-deliver-card data-search='{E(search)}' href='/deliver?id={urllib.parse.quote(did)}'>"
                    f"<div class='deliver-cover'><div class='cover-top'><span class='cover-wave'>גל {wave if wave != 99 else 'קטלוג'}</span>"
                    f"<span class='cover-kind'>{E(execution_he.get(d['execution_kind'], d['execution_kind']))}</span></div>"
                    f"<div class='deliver-mark mono'>{E(mark)}</div></div><div class='deliver-info'>"
                    f"<h3>{E(did)}</h3><div>{pill(state)}</div>"
                    f"<div class='deliver-description'>{E(d['description_he'])}</div>"
                    f"<div class='deliver-meta'><div class='meta-item'><span>תחום</span><b>{E(d.get('domain') or 'כללי')}</b></div>"
                    f"<div class='meta-item'><span>אחראי</span><b>{E(d.get('owner') or 'טרם הוקצה')}</b></div>"
                    f"<div class='meta-item'><span>מודל או מנוע</span><b>{E(model)}</b></div>"
                    f"<div class='meta-item'><span>מאזינים מוצעים</span><b>{listener_count}</b></div>"
                    f"<div class='meta-item'><span>קונטקסט זמין</span><b>{fmt_bytes(d['context_source_bytes'] + d['global_context_bytes'])}</b></div>"
                    f"<div class='meta-item'><span>פרומפט אחרון</span><b>{fmt_bytes(d['latest_context_bytes'])}</b></div>"
                    f"<div class='meta-item'><span>מחיר קבוע</span><b>{E(price)}</b></div>"
                    f"<div class='meta-item'><span>ניצול תקציב</span><b>{E(str(d.get('budget_spent') or 0))}</b></div></div>"
                    f"<div class='budget-track' title='ניצול תקציב: {pct}%'><span class='budget-fill' style='width:{pct}%'></span></div>"
                    f"</div></a>")
            shelves.setdefault(wave, []).append(card)
        catalog = "".join(
            f"<section class='deliver-shelf' data-shelf><div class='shelf-title'><h2>{'גל ' + str(wave) if wave != 99 else 'Deliverים מהקטלוג'}</h2>"
            f"<small>{len(cards)} רכיבים</small></div><div class='deliver-rail'>{''.join(cards)}</div></section>"
            for wave, cards in sorted(shelves.items()))
        system_catalog = "".join(
            f"<section class='deliver-shelf' data-shelf><div class='shelf-title'><h2>{E(self.db.get_flag('onboarding_title:' + sid) or sid)}</h2>"
            f"<small>{len(cards)} רכיבים · {sum(cap_counts.get(c, (0, 0))[1] for c in [r['deliver_id'] for r in data['delivers'] if r.get('packet') == sid])} תתי־יכולות · "
            f"הוכנסו ב־<span class='mono'>wwii-build onboard {E(sid)}</span></small></div><div class='deliver-rail'>{''.join(cards)}</div></section>"
            for sid, cards in sorted(system_shelves.items()))
        deterministic_catalog = (
            "<section class='deliver-shelf' data-shelf><div class='shelf-title'><h2>Delivers דטרמיניסטיים</h2>"
            "<small>חוזה קל: פונקציה, קונטקסט, listeners והיסטוריית הרצות · ללא מודל או תמחור LLM</small></div>"
            f"<div class='deterministic-rail'>{''.join(deterministic_cards)}</div></section>")
        crows = "".join(f"<tr><td class='mono'>{E(c['source_key'])}</td><td>{E(c['origin_kind'])}</td><td class='mono'>{E(c['origin_ref'])}</td><td>{E(c['graph_entity_id'] or '')}</td><td class='mono'>{E(c['content_sha256'][:12])}</td><td>{E(c['title'])}</td></tr>" for c in data["context_sources"])
        rrows = ""
        for r in data["decisions"]:
            try:
                pretty = json.dumps(json.loads(r.get("request_preview_json") or "{}"), ensure_ascii=False, indent=1)
            except Exception:
                pretty = "{}"
            rrows += (f"<tr><td>{local(r['created_at'])}</td><td>{E(r['route_kind'])}</td><td class='mono'>{E(r['selected_id'] or r['fallback_id'] or '')}</td><td>{E(translate(r['status']))}</td><td>{E(r['model'] or '—')}</td><td>{r['input_tokens'] if r['input_tokens'] is not None else 'לא ידוע'} / {r['output_tokens'] if r['output_tokens'] is not None else 'לא ידוע'}</td><td>{r['latency_ms']} מילישניות</td><td><details><summary>בקשה והסתברויות</summary><pre>{E(pretty)}\n\n{E(r['probabilities_json'] or 'לא ידוע')}</pre></details></td></tr>")
        arows = "".join(
            f"<tr><td>{local(a['created_at'])}</td><td class='mono'>{E(a['event_id'])}</td><td class='mono'>{E(a['listener_id'])}</td><td class='mono'>{E(a['source_deliver_id'])} → {E(a['target_deliver_id'])}</td><td>{pill(a['status'])}</td><td>{a['selected_state_version']}</td></tr>"
            for a in data["activations"])
        erows = "".join(
            f"<tr><td>{local(e['created_at'])}</td><td>{E(e['episode_id'])}</td><td class='mono'>{E(e['source_deliver_id'])}</td><td>{E(e['event_type'])}</td><td>{e['state_version']}</td><td>{pill(e['status'])}</td></tr>"
            for e in data["deliver_events"])
        srows = ""
        for s in data["episode_states"]:
            snapshot = json.dumps({"episode": json.loads(s["episode_state_json"]),
                                   "build": json.loads(s["build_state_json"]),
                                   "context_refs": json.loads(s["context_refs_json"])}, ensure_ascii=False, indent=1)
            srows += (f"<tr><td>{E(s['episode_id'])}</td><td>{s['version']}</td><td>{E(s['phase'])}</td>"
                      f"<td>{E(s['objective'])}</td><td class='mono'>{E(s['updated_by_deliver_id'] or '')}</td>"
                      f"<td><details><summary>state + provenance</summary><pre>{E(snapshot)}</pre></details></td></tr>")
        deliver_form = (f"<details class='hold'><summary>הוספה או עדכון של Deliver</summary><div class='card'><form method='post' action='/action'>"
                        f"<input type='hidden' name='token' value='{self.token}'><input type='hidden' name='action' value='save_deliver'>"
                        f"<input type='hidden' name='back' value='/delivers'><div class='grid2'><div><label class='blk'>מזהה Deliver</label>"
                        f"<input type='text' name='deliver_id' required placeholder='weather.snow_research'><label class='blk'>אחראי</label>"
                        f"<input type='text' name='owner'><label class='blk'>תחום</label><input type='text' name='domain'></div>"
                        f"<div><label class='blk'>סוג ביצוע</label><select class='w' name='execution_kind'>"
                        f"<option value='worker'>סוכן ביצוע</option><option value='deterministic'>פונקציה דטרמיניסטית</option>"
                        f"<option value='llm_research'>מחקר מודל</option><option value='context_bundle'>חבילת קונטקסט</option>"
                        f"<option value='review'>בקרת איכות</option>"
                        f"</select><label class='blk'>מה ה־Deliver עושה — בעברית</label><textarea name='description' rows='5' required></textarea></div></div>"
                        f"<p><button class='go'>שמור Deliver</button></p></form></div></details>")
        global_context_form = (f"<details class='hold'><summary>הוספת מועמד קונטקסט גלובלי</summary><div class='card'><form method='post' action='/action'>"
                               f"<input type='hidden' name='token' value='{self.token}'><input type='hidden' name='action' value='add_context'>"
                               f"<input type='hidden' name='back' value='/delivers'><label class='blk'>מפתח מקור</label><input type='text' name='source_key' required>"
                               f"<label class='blk'>כותרת</label><input type='text' name='title' required><label class='blk'>מקור, כתובת או הפניה לגרף</label>"
                               f"<input type='text' name='origin_ref'><label class='blk'>קונטקסט</label><textarea name='excerpt' rows='8' required></textarea>"
                               f"<p class='muted'>נשמר כמועמד בלבד. הוא יגיע למודל רק אם Jev יבחר בו עבור המשימה.</p>"
                               f"<button class='go'>שמור מועמד קונטקסט</button></form></div></details>")
        body = ("<div id='deliverWorkspace'><section class='deliver-hero'><div><div class='hero-kicker'>מערכת בנייה ותזמור</div>"
                "<h1>מרכז השליטה של ה־Delivers</h1><p>כל יכולת מוצגת כרכיב עצמאי עם בעלות, מודל, תקציב, מאזינים והיסטוריית ביצוע. "
                "Jev מקבל רק מועמדים שנמצאו בגרף ובוחר את הקונטקסט והנתיב המדויקים לכל פעולה.</p></div>"
                "<div class='mode-switch' role='group' aria-label='מצב תצוגה'><button type='button' id='catalogMode'>כרטיסים בלבד</button>"
                "<button type='button' id='arcsMode'>הצג קשרים וקשתות</button></div></section>" + jev_card
                + runtime_panel + live_listeners
                + "<div class='catalog-tools'><input id='deliverSearch' type='text' placeholder='חיפוש לפי מזהה, תחום, אחראי או תיאור' aria-label='חיפוש Delivers'>"
                + f"<span class='result-count'><b id='visibleDeliverCount'>{len(data['delivers'])}</b> מתוך {len(data['delivers'])} רכיבים</span></div>"
                + system_catalog + deterministic_catalog + catalog + "<div id='emptyDeliverFilter' class='empty-filter'>לא נמצאו רכיבים שמתאימים לחיפוש.</div>"
                + "<section class='graph-shell'><div class='shelf-title'><h2>מפת הקשרים</h2><small>קו מלא: תלות קשיחה · קו מקווקו: מאזין שעובר דרך Jev</small></div>"
                + "<div class='card graph-stage'>" + self._deliver_graph(data) + "</div></section>"
                + "<h2>חיבור Jev וניהול הקטלוג</h2>" + key_form + deliver_form + global_context_form
                + "<details class='hold'><summary>נתוני תפעול, מקור והיסטוריה</summary>"
                + "<h2>מצב בניית האפיזודה</h2><div class='card'><table><tr><th>אפיזודה</th><th>גרסה</th><th>שלב</th><th>מטרה</th><th>Deliver אחרון</th><th>מצב</th></tr>" + srows + "</table></div>"
                + "<h2>הפעלת מאזינים שנבחרו בידי Jev</h2><div class='card'><table><tr><th>זמן</th><th>אירוע</th><th>מאזין</th><th>נתיב</th><th>מצב</th><th>גרסת מצב</th></tr>" + arows + "</table></div>"
                + "<h2>אירועי מצב של Delivers</h2><div class='card'><table><tr><th>זמן</th><th>אפיזודה</th><th>Deliver מקור</th><th>אירוע</th><th>גרסה</th><th>ניתוב</th></tr>" + erows + "</table></div>"
                + "<h2>מקורות הקונטקסט</h2><div class='card'><table><tr><th>מקור</th><th>סוג</th><th>הפניה</th><th>ישות בגרף</th><th>חתימה</th><th>כותרת</th></tr>" + crows + "</table></div>"
                + "<h2>מה נשלח ל־Jev</h2><div class='card'><table><tr><th>זמן</th><th>סוג</th><th>בחירה</th><th>מצב</th><th>מודל</th><th>טוקנים נכנסו/יצאו</th><th>זמן תגובה</th><th>בקשה</th></tr>" + rrows + "</table></div></details>"
                + "<p class='muted'>רכיב נשאר ללא מחיר עד שיש מקור מתועד ומדיניות שמירת תקציב. הערכת שימוש מקומית אינה מוצגת כיתרה רשמית של TypeSafe.</p></div>"
                + """<script>(()=>{const root=document.getElementById('deliverWorkspace');const catalog=document.getElementById('catalogMode');
const arcs=document.getElementById('arcsMode');function setMode(mode){root.classList.toggle('catalog-only',mode==='catalog');
catalog.classList.toggle('active',mode==='catalog');arcs.classList.toggle('active',mode==='arcs');catalog.setAttribute('aria-pressed',mode==='catalog');
arcs.setAttribute('aria-pressed',mode==='arcs');localStorage.setItem('wwii-deliver-view',mode)}
catalog.onclick=()=>setMode('catalog');arcs.onclick=()=>setMode('arcs');setMode(localStorage.getItem('wwii-deliver-view')||'catalog');
const search=document.getElementById('deliverSearch'),cards=[...document.querySelectorAll('[data-deliver-card]')],count=document.getElementById('visibleDeliverCount'),empty=document.getElementById('emptyDeliverFilter');
search.addEventListener('input',()=>{const q=search.value.trim().toLowerCase();let visible=0;cards.forEach(card=>{const show=!q||card.dataset.search.includes(q);card.style.display=show?'':'none';if(show)visible++});
document.querySelectorAll('[data-shelf]').forEach(s=>s.style.display=[...s.querySelectorAll('[data-deliver-card]')].some(c=>c.style.display!=='none')?'':'none');count.textContent=visible;empty.style.display=visible?'none':'block'});})();</script>""")
        return self._layout("מרכז ה־Delivers", body, msg)

    def _graph_access_form(self, deliver_id: str, back: str, compact: bool = False) -> str:
        access = self.graph_rag.access(deliver_id)
        mode = access["access_mode"]
        option = lambda value, label: f"<option value='{value}'{' selected' if value == mode else ''}>{label}</option>"
        grid = "" if compact else "<div class='grid2'><div>"
        mid = "" if compact else "</div><div>"
        end = "" if compact else "</div></div>"
        return (f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                f"<input type='hidden' name='action' value='save_deliver_graph_access'>"
                f"<input type='hidden' name='deliver_id' value='{E(deliver_id)}'><input type='hidden' name='back' value='{E(back)}'>{grid}"
                f"<label class='blk'>רמת גישה לגרף</label><select class='w' name='access_mode'>"
                f"{option('none', 'ללא גישה')}{option('limited', 'גישה מוגבלת')}{option('full', 'גישה מלאה')}</select>"
                f"<label class='blk'>תחום מותר בגישה מוגבלת</label><input type='text' name='scope_text' "
                f"value='{E(access.get('scope_text') or '')}' placeholder='לדוגמה: טנקים, בליסטיקה, החזית המזרחית'>{mid}"
                f"<label class='blk'>מספר מקטעים מרבי</label><input type='number' name='max_chunks' min='1' max='50' value='{int(access['max_chunks'])}'>"
                f"<label class='blk'>מספר תווים מרבי</label><input type='number' name='max_chars' min='500' max='100000' value='{int(access['max_chars'])}'>{end}"
                f"<p class='section-note'>ההרשאה קובעת מה ניתן לשלוף. כל מקטע שנשלף נשאר מועמד עד ש־Jev בוחר בו במפורש.</p>"
                f"<button class='go'>שמור הרשאת גרף</button></form>")

    def _subtask_form(self, parent_id: str | None, back: str) -> str:
        parent_select = ""
        if parent_id:
            parent_select = f"<input type='hidden' name='parent_task_id' value='{E(parent_id)}'>"
        else:
            options = "".join(
                f"<option value='{E(row['task_id'])}'>{E(row['task_id'])} · {E(row['title'] or row['note'] or '')}</option>"
                for row in self.db.q(
                    "SELECT task_id,title,note FROM tasks WHERE kind<>'repair' AND state NOT IN "
                    "('RUNNING','REVIEWING','PAUSING','PASSED','CANCELLED') ORDER BY updated_at DESC LIMIT 200"))
            parent_select = ("<label class='blk'>משימת אב</label><select class='w' name='parent_task_id' required>"
                             f"{options}</select>")
        return (
            f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
            f"<input type='hidden' name='action' value='create_subtask'><input type='hidden' name='back' value='{E(back)}'>"
            f"{parent_select}<label class='blk'>שם תת־המשימה</label><input type='text' name='title' required>"
            "<label class='blk'>הוראות ממוקדות</label><textarea name='instructions' rows='5' required></textarea>"
            f"<div class='grid2'><div><label class='blk'>מודל</label><select class='w' name='model_key'>"
            f"{self._model_options('', 'automatic: best fit')}</select></div><div><label class='blk'>אחראי</label>"
            "<input type='text' name='owner' placeholder='ריק = אחראי חדש לתת־המשימה'></div></div>"
            "<label><input type='checkbox' name='fallback' value='1' checked> אפשר ניתוב חלופי אם המודל אינו זמין</label>"
            "<label class='blk'>תחום כתיבה — נתיב יחסי אחד בכל שורה</label>"
            "<textarea name='write_scope' rows='2' dir='ltr'></textarea>"
            "<label><input type='checkbox' name='read_only' value='1'> קריאה בלבד</label>"
            "<details class='hold'><summary>קונטקסט וכלים ייחודיים לתת־המשימה</summary>"
            "<label class='blk'>קבצי קונטקסט — אחד בכל שורה</label><textarea name='context_files' rows='3' dir='ltr'></textarea>"
            "<label class='blk'>קבצי עזר — אחד בכל שורה</label><textarea name='reference_files' rows='2' dir='ltr'></textarea>"
            "<label class='blk'>שרתי MCP — מופרדים בפסיק</label><input type='text' name='mcp_servers' dir='ltr'>"
            "<label class='blk'>כלים מורשים — מופרדים בפסיק</label><input type='text' name='tool_names' dir='ltr' "
            "placeholder='Read, Grep, Bash(pytest *)'>"
            "<label class='blk'>בדיקות קבלה — פקודה בכל שורה</label>"
            "<textarea name='acceptance_commands' rows='3' dir='ltr'></textarea></details>"
            "<p class='section-note'>תת־המשימה נשמרת בתור עם חוזה עצמאי. היא אינה הופכת ל־Deliver. "
            "קונטקסט שיגיע למודל עדיין עובר דרך שער Jev.</p>"
            "<button class='go'>צור תת־משימה שמורה</button></form>")

    def _subtask_lineage_html(self, task_id: str) -> str:
        parents = self.db.q(
            "SELECT o.parent_task_id,o.source,o.created_at,p.pattern_hash,p.reuse_count,p.promotion_threshold,"
            "p.promotion_status,p.promoted_deliver_id FROM subtask_occurrences o JOIN subtask_patterns p "
            "ON p.pattern_hash=o.pattern_hash WHERE o.child_task_id=? ORDER BY o.created_at DESC", (task_id,))
        children = self.db.q(
            "SELECT o.child_task_id,o.source,o.created_at,p.pattern_hash,p.reuse_count,p.promotion_threshold,"
            "p.promotion_status FROM subtask_occurrences o JOIN subtask_patterns p ON p.pattern_hash=o.pattern_hash "
            "WHERE o.parent_task_id=? ORDER BY o.created_at DESC", (task_id,))
        if not parents and not children:
            return "<p class='muted'>עדיין אין קשרי פירוק שמורים למשימה הזו.</p>"
        rows = []
        for row in parents:
            promoted = (f" · קוּדם ל־<a href='/deliver?id={urllib.parse.quote(row['promoted_deliver_id'])}'>"
                        f"{E(row['promoted_deliver_id'])}</a>" if row["promoted_deliver_id"] else "")
            rows.append(f"<div class='subtask-node'>תת־משימה של <a class='mono' href='/task?id="
                        f"{urllib.parse.quote(row['parent_task_id'])}'>{E(row['parent_task_id'])}</a> · "
                        f"שימוש {row['reuse_count']}/{row['promotion_threshold']} · {E(row['promotion_status'])}{promoted}</div>")
        for row in children:
            child = self.db.task(row["child_task_id"]) if row["child_task_id"] else None
            extra = json.loads(child["extra"] or "{}") if child else {}
            rows.append(
                f"<div class='subtask-node'><b>תת־משימה</b> · <a class='mono' href='/task?id="
                f"{urllib.parse.quote(row['child_task_id'] or '')}'>{E(row['child_task_id'] or '—')}</a> "
                f"{pill(child['state']) if child else ''}<br><small>מודל {E((child['preferred_model_key'] if child else '') or 'אוטומטי')} · "
                f"MCP {E(', '.join(extra.get('mcp') or []) or 'ללא')} · כלים "
                f"{E(', '.join(extra.get('allowed_tools') or []) or 'ברירת מחדל')} · דפוס "
                f"{row['reuse_count']}/{row['promotion_threshold']}</small></div>")
        return "<div class='subtask-tree'>" + "".join(rows) + "</div>"

    def page_subtasks(self, msg: str | None) -> str:
        patterns = self.db.q("SELECT * FROM subtask_patterns ORDER BY "
                             "CASE promotion_status WHEN 'eligible' THEN 0 WHEN 'learning' THEN 1 ELSE 2 END,"
                             "last_seen_at DESC")
        cards = []
        for row in patterns:
            spec = json.loads(row["spec_json"])
            pct = min(100, round(100 * int(row["reuse_count"]) / max(1, int(row["promotion_threshold"]))))
            tags = [f"מודל {spec.get('model_key') or 'אוטומטי'}",
                    f"{len(spec.get('context_files') or [])} קבצי קונטקסט",
                    f"{len(spec.get('mcp_servers') or [])} שרתי MCP",
                    f"{len(spec.get('tool_names') or [])} כלים"]
            tag_html = "".join(f"<span>{E(tag)}</span>" for tag in tags)
            occurrences = self.db.q(
                "SELECT parent_task_id,child_task_id,source,created_at FROM subtask_occurrences "
                "WHERE pattern_hash=? ORDER BY created_at DESC LIMIT 8", (row["pattern_hash"],))
            occ_html = "".join(
                f"<li><a class='mono' href='/task?id={urllib.parse.quote(o['child_task_id'] or '')}'>"
                f"{E(o['child_task_id'] or '—')}</a> מתוך <span class='mono'>{E(o['parent_task_id'])}</span> · "
                f"{E(o['source'])}</li>" for o in occurrences)
            promotion = ""
            if row["promotion_status"] == "eligible":
                suggestion = "reusable." + mn.slugify(row["title"], "subtask").replace("-", ".")
                promotion = (
                    "<div class='promotion-box'><b>הדפוס כשיר לקידום</b><p class='muted'>בדוק את החוזה ובחר מזהה קבוע. "
                    "הקידום ייצור Deliver אמיתי; הוא אינו מתבצע אוטומטית.</p>"
                    f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                    "<input type='hidden' name='action' value='promote_subtask'><input type='hidden' name='back' value='/subtasks'>"
                    f"<input type='hidden' name='pattern_hash' value='{E(row['pattern_hash'])}'>"
                    f"<label class='blk'>מזהה Deliver</label><input type='text' name='deliver_id' value='{E(suggestion)}' required>"
                    f"<div class='grid2'><input type='text' name='owner' value='{E(spec.get('owner') or '')}' placeholder='אחראי'>"
                    "<input type='text' name='domain' placeholder='תחום'></div>"
                    f"<label class='blk'>תיאור</label><input type='text' name='description' value='{E(row['title'])}'>"
                    "<button class='go'>קדם ל־Deliver</button></form></div>")
            elif row["promotion_status"] == "promoted":
                promotion = (f"<p class='section-note'>קוּדם ל־<a class='mono' href='/deliver?id="
                             f"{urllib.parse.quote(row['promoted_deliver_id'])}'>{E(row['promoted_deliver_id'])}</a></p>")
            cards.append(
                f"<div class='card pattern-card {E(row['promotion_status'])}'><div class='bar'><b>{E(row['title'])}</b>"
                f"{pill(row['promotion_status'].upper())}</div><p>{E(spec.get('instructions') or 'אין הוראות')}</p>"
                f"<div class='contract-tags'>{tag_html}</div><div class='reuse-meter'><span style='width:{pct}%'></span></div>"
                f"<p><b>{row['reuse_count']}</b> שימושים בפועל מתוך <b>{row['promotion_threshold']}</b> שנדרשים לקידום</p>"
                f"<details class='hold'><summary>חוזה מלא והיסטוריית שימוש</summary><pre>"
                f"{E(json.dumps(spec, ensure_ascii=False, indent=2))}</pre><ul>{occ_html}</ul></details>{promotion}</div>")
        total = len(patterns)
        eligible = sum(row["promotion_status"] == "eligible" for row in patterns)
        promoted = sum(row["promotion_status"] == "promoted" for row in patterns)
        body = (
            "<section class='control-hero'><div class='eyebrow'>למידה לפני הפיכה ליכולת קבועה</div>"
            "<h1>תתי־משימות ודפוסי שימוש חוזר</h1><p>סוכן רשאי לפרק עבודה לתת־משימות שמורות, ולכל אחת לבחור מודל, "
            "קונטקסט, MCP וכלים אחרים. רק מופעים שנוצרו בפועל נספרים. אחרי שימוש חוזר הדפוס נעשה כשיר, "
            "ורק קידום מפורש יוצר ממנו Deliver עם חוזה קבוע.</p></section>"
            f"<div class='counts'><div class='count'><span>דפוסים שנלמדו</span><b>{total}</b></div>"
            f"<div class='count'><span>ממתינים להחלטת קידום</span><b>{eligible}</b></div>"
            f"<div class='count'><span>קודמו ל־Deliver</span><b>{promoted}</b></div>"
            f"<div class='count'><span>סף ברירת מחדל</span><b>{int(self.cfg.section('subtasks').get('promotion_threshold', 3))} שימושים</b></div></div>"
            "<div class='grid2'><div><h2>צור תת־משימה ידנית</h2><div class='card'>"
            f"{self._subtask_form(None, '/subtasks')}</div></div><div><h2>כלל ההפרדה</h2><div class='card'>"
            "<p><b>Task / Subtask</b> הוא מופע עבודה עם הקשר וכלים נקודתיים.</p>"
            "<p><b>Pattern</b> הוא חוזה זהה שנצפה בשימוש אמיתי כמה פעמים.</p>"
            "<p><b>Deliver</b> הוא יכולת קבועה, מתומחרת ומנוהלת, שנוצרה רק לאחר בדיקה וקידום.</p>"
            "<p class='section-note'>הספירה אינה כוללת הצעות שנדחו או שלא אושרו.</p></div></div></div>"
            "<h2>דפוסים שנלמדו</h2><div class='pattern-grid'>"
            + ("".join(cards) if cards else "<div class='card'><p class='muted'>עדיין אין דפוסי שימוש. הם יופיעו לאחר שמתכנן או סוכן ייצרו תתי־משימות בפועל.</p></div>")
            + "</div>")
        return self._layout("תתי־משימות ודפוסים", body, msg)

    def _graph_console_result_html(self, row) -> str:
        item = dict(row)
        status = item.get("status") or "UNKNOWN"
        task_state = item.get("task_state")
        if status in {"QUEUED", "RUNNING"} and task_state:
            status = task_state
        try:
            result = json.loads(item.get("result_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            result = {}
        mode_label = "Cypher ישיר" if item.get("mode") == "cypher" else "שפה חופשית"
        model = item.get("model_key") or "Neo4j"
        if model == "local":
            model = "Graph RAG מקומי"
        task_link = (f" · <a class='mono' href='/task?id={urllib.parse.quote(item['task_id'])}'>{E(item['task_id'])}</a>"
                     if item.get("task_id") else "")
        generated = item.get("generated_cypher") or result.get("cypher") or ""
        content = ""
        if item.get("error"):
            content = f"<div class='err'>{E(item['error'])}</div>"
        elif item.get("mode") == "cypher" and result:
            result_rows = result.get("rows") if isinstance(result.get("rows"), list) else []
            columns = result.get("columns") if isinstance(result.get("columns"), list) else []
            if not columns and result_rows and isinstance(result_rows[0], dict):
                columns = list(result_rows[0])
            headers = "".join(f"<th>{E(str(c))}</th>" for c in columns)
            values = "".join(
                "<tr>" + "".join(
                    f"<td><pre>{E(json.dumps(r.get(c), ensure_ascii=False, default=str)[:3000])}</pre></td>"
                    for c in columns) + "</tr>"
                for r in result_rows[:200] if isinstance(r, dict))
            content = (f"<div class='result-table'><table><tr>{headers}</tr>{values}</table></div>"
                       if result_rows else "<p class='muted'>השאילתה הושלמה ללא שורות.</p>")
        elif result:
            answer = result.get("summary") or result.get("context") or result.get("answer") or ""
            entities = result.get("used_entity_names") or []
            evidence_ids = result.get("evidence_source_ids") or []
            content = (f"<div class='query-answer'>{E(str(answer))}</div>"
                       + (f"<p class='muted'>ישויות שנעשה בהן שימוש: {E(', '.join(map(str, entities)))}</p>" if entities else "")
                       + (f"<p class='muted'>מקורות שאושרו ב־Jev: {E(', '.join(map(str, evidence_ids)))}</p>" if evidence_ids else ""))
        elif status in {"PENDING", "QUEUED", "RUNNING", "WAITING_PROVIDER", "WAITING_QUOTA", "PAUSED"}:
            content = ("<p class='muted'>זו שאילתה ישנה שנוצרה לפני המעבר למסלול המיידי והיא עדיין בתור. "
                       "שאילתות חדשות מתבצעות מיד.</p>")
        else:
            content = "<p class='muted'>עדיין אין תוצאה שמורה.</p>"
        return (
            f"<article class='card graph-result {'ready' if status in {'READY','PASSED'} else 'failed' if status=='FAILED' else ''}'>"
            f"<div class='result-meta'><b>#{item['id']}</b>{pill(status)}<span>{E(mode_label)}</span>"
            f"<span class='mono'>{E(model)}</span><span>{int(item.get('elapsed_ms') or 0)} מ״ש</span>"
            f"<span>טוקנים {int(item.get('input_tokens') or 0)}/{int(item.get('cached_input_tokens') or 0)}/"
            f"{int(item.get('output_tokens') or 0)}</span>{task_link}</div>"
            f"<div class='query-preview'>{E(item.get('query_text') or '')}</div>"
            + (f"<details class='hold'><summary>Cypher שנוצר או בוצע</summary><pre>{E(generated)}</pre></details>" if generated else "")
            + content + "</article>")

    def page_graph_rag(self, msg: str | None) -> str:
        health = self.graph_rag.health()
        access_rows = self.db.q(
            "SELECT c.deliver_id,c.owner,c.domain,c.execution_kind,"
            "COALESCE(a.access_mode,'none') access_mode,COALESCE(a.scope_text,'') scope_text,"
            "COALESCE(a.max_chunks,6) max_chunks,COALESCE(a.max_chars,6000) max_chars "
            "FROM deliver_catalog c LEFT JOIN deliver_graph_access a ON a.deliver_id=c.deliver_id "
            "WHERE c.enabled=1 ORDER BY c.domain,c.deliver_id")
        rows = "".join(
            f"<tr><td><a class='mono' href='/deliver?id={urllib.parse.quote(r['deliver_id'])}'>{E(r['deliver_id'])}</a></td>"
            f"<td>{E(r['domain'] or '—')}</td><td>{E(r['owner'] or '—')}</td><td>{E(r['execution_kind'])}</td>"
            f"<td>{'מלאה' if r['access_mode']=='full' else 'מוגבלת' if r['access_mode']=='limited' else 'ללא גישה'}</td>"
            f"<td>{E(r['scope_text'] or '—')}</td><td>{r['max_chunks']} / {r['max_chars']}</td>"
            f"<td><details class='hold'><summary>עריכת הרשאה</summary>{self._graph_access_form(r['deliver_id'], '/rag', compact=True)}</details></td></tr>"
            for r in access_rows)
        history = "".join(
            f"<tr><td>{local(r['created_at'])}</td><td class='mono'>{E(r['scope_id'])}</td><td>{E(r['access_mode'])}</td>"
            f"<td>{r['candidate_count']} / {r['selected_count']}</td><td>{E(r['status'])}</td><td>{r['latency_ms'] or 0} מ״ש</td></tr>"
            for r in self.db.q("SELECT * FROM graph_rag_queries ORDER BY id DESC LIMIT 50"))
        console_history = "".join(self._graph_console_result_html(r) for r in self.db.q(
            "SELECT q.*,t.state task_state FROM graph_console_queries q LEFT JOIN tasks t ON t.task_id=q.task_id "
            "ORDER BY q.id DESC LIMIT 20"))
        local_model = health.get("model") or "המודל המקומי של Graph RAG"
        natural_models = (f"<option value='local'>מקומי ומיידי — {E(local_model)}</option>" +
                          self._model_options(None))
        query_console = (
            "<section><div class='bar'><div><h2>קונסולת שאילתות לגרף</h2>"
            "<p class='muted'>Cypher, המודל המקומי ו־Codex/Claude מתבצעים מיד ואינם נכנסים לתור המשימות.</p></div></div>"
            "<div class='graph-query-grid'><article class='graph-query-card cypher'><h3>שאילתת Neo4j בשפת Cypher</h3>"
            "<p class='muted'>מבוצעת ישירות בגשר הקריאה בלבד. פעולות כתיבה, מחיקה, CALL וניהול חסומות לפני הביצוע.</p>"
            f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
            "<input type='hidden' name='action' value='graph_console_query'><input type='hidden' name='back' value='/rag'>"
            "<input type='hidden' name='query_mode' value='cypher'><textarea class='query ltr' name='query' required "
            "placeholder='MATCH (n) RETURN labels(n) AS labels, count(*) AS count ORDER BY count DESC LIMIT 25'></textarea>"
            "<label class='blk'>פרמטרים כאובייקט JSON (לא חובה)</label><textarea class='params ltr' name='parameters' "
            "placeholder='{" + '"name": "Stalingrad"' + "}'></textarea>"
            "<label class='blk'>מספר שורות מרבי</label><input type='number' name='max_rows' min='1' max='200' value='100'>"
            "<p><button class='big go'>הרץ Cypher לקריאה</button></p></form></article>"
            "<article class='graph-query-card'><h3>שאלה חופשית דרך LLM</h3>"
            "<p class='muted'>כל מודל שנבחר רץ מיד. Codex או Claude מקבל רק מקורות ש־Jev בחר ומחזיר תשובה מנומקת באותה בקשה.</p>"
            f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
            "<input type='hidden' name='action' value='graph_console_query'><input type='hidden' name='back' value='/rag'>"
            "<input type='hidden' name='query_mode' value='natural'><textarea class='query' name='query' required "
            "placeholder='לדוגמה: אילו יחידות משוריינות מתועדות באזור סטלינגרד בינואר 1943, ומה רמת הביטחון של כל מקור?'></textarea>"
            f"<label class='blk'>המודל שיענה</label><select class='w' name='model_key'>{natural_models}</select>"
            "<p><button class='big go'>שאל עכשיו</button></p></form></article></div></section>"
            "<h2>תוצאות אחרונות</h2>" + (console_history or "<div class='card muted'>עדיין לא הורצו שאילתות מהקונסולה.</div>"))
        body = ("<section class='control-hero'><div class='eyebrow'>ידע ושליפה</div><h1>מרכז השליטה של גרף ה־RAG</h1>"
                "<p>מתכנן המשימות מקבל גישה מלאה לגרף. לכל Deliver ניתן להגדיר ללא גישה, גישה מוגבלת או גישה מלאה. "
                "התוצאה אינה נכנסת ישירות לפרומפט: היא מפוצלת למועמדים ורק Jev רשאי לבחור מהם.</p></section>"
                f"<div class='counts'><div class='count'><span>מצב השירות</span><b>{E(health['status'])}</b></div>"
                f"<div class='count'><span>צמתים</span><b>{health.get('nodes') if health.get('nodes') is not None else 'לא ידוע'}</b></div>"
                f"<div class='count'><span>קשרים</span><b>{health.get('relationships') if health.get('relationships') is not None else 'לא ידוע'}</b></div>"
                f"<div class='count'><span>מודל שליפה</span><b>{E(health.get('model') or 'לא זמין')}</b></div></div>"
                f"{query_console}"
                "<div class='grid2'><div><h2>חיבור לשירות המקומי</h2><div class='card'>"
                f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                f"<input type='hidden' name='action' value='save_graph_rag_config'><input type='hidden' name='back' value='/rag'>"
                f"<label class='blk'>כתובת שירות Graph RAG</label><input class='ltr' type='text' name='graph_rag_url' value='{E(self.graph_rag.base_url)}'>"
                "<p class='muted'>כתובת ה־API הציבורי של הגרף (HTTPS בלבד; כתובות מקומיות נחסמות).</p>"
                f"<label class='blk'>כתובת גשר Cypher לקריאה בלבד</label><input class='ltr' type='text' name='graph_cypher_url' value='{E(self.graph_rag.cypher_base_url)}'>"
                "<p class='muted'>קונסולת Cypher לקריאה בלבד; דורשת WW2_GRAPH_CONSOLE_KEY בסביבה. ה־API מאמת את השאילתה ומגביל זמן ושורות.</p>"
                "<button class='go'>שמור ובדוק חיבור</button></form> "
                f"{self._form('graph_rag_health', 'הרץ בדיקת תקינות', back='/rag')}</div></div>"
                "<div><h2>מה פירוש גישה מלאה למתכנן?</h2><div class='card'><b>חופש חיפוש, לא חופש ביצוע.</b> "
                "המתכנן רשאי לחפש בכל הגרף בחיפוש וקטורי ובשאילתת Cypher כדי למצוא מועמדי קונטקסט. "
                "Jev עדיין בוחר אילו מקטעים נכנסים לפרומפט, ומגבלות המקטעים והתווים נשארות פעילות. "
                "ההרשאה אינה נותנת למתכנן גישה לסודות, ל־shell, לכתיבה בריפו או לעקיפת אישור משימות.</div></div></div>"
                "<h2>הרשאות לפי Deliver</h2><div class='card'><table><tr><th>Deliver</th><th>תחום</th><th>אחראי</th>"
                f"<th>סוג</th><th>גישה</th><th>תחום מוגבל</th><th>מקטעים / תווים</th><th>ניהול</th></tr>{rows}</table></div>"
                "<h2>היסטוריית שאילתות</h2><div class='card'><table><tr><th>זמן</th><th>יעד</th><th>גישה</th>"
                f"<th>מועמדים / נבחרו</th><th>מצב</th><th>זמן</th></tr>{history or '<tr><td colspan=6>אין עדיין שאילתות</td></tr>'}</table></div>")
        return self._layout("גרף RAG", body, msg)

    def _capabilities_html(self, deliver_id: str) -> str:
        """Capability tree of a Deliver (from system onboarding): capabilities -> sub-capabilities."""
        rows = self.db.q("SELECT * FROM deliver_capabilities WHERE deliver_id=? AND active=1 "
                         "ORDER BY rowid", (deliver_id,))
        if not rows:
            return ""
        kind_he = {"files": "קובץ", "py_functions": "פונקציה", "mcp_tools": "כלי MCP", "http_routes": "נתיב HTTP",
                   "argparse": "פקודה", "js_functions": "פונקציה", "declared": "מוצהר"}
        groups: dict[str, list] = {}
        for r in rows:
            groups.setdefault(r["group_name"], []).append(r)
        blocks = "".join(
            f"<details class='cap-group hold'{' open' if len(groups) <= 3 else ''}><summary><b>{E(g)}</b> "
            f"<span class='muted'>({len(items)})</span></summary><table class='cap-table'>"
            + "".join(f"<tr><td class='mono'>{E(r['name'])}</td><td>{E(kind_he.get(r['kind'], r['kind']))}</td>"
                      f"<td>{E(r['description'] or '')}</td><td class='mono muted'>{E(r['source_ref'] or '')}</td></tr>"
                      for r in items) + "</table></details>"
            for g, items in groups.items())
        return (f"<h2>יכולות ותתי־יכולות <span class='muted'>({len(groups)} יכולות · {len(rows)} תתי־יכולות)</span></h2>"
                f"<div class='card capabilities'>{blocks}<p class='muted'>התגלו אוטומטית מהקוד של הרכיב בהכנסת המערכת "
                f"(<span class='mono'>wwii-build onboard</span>). כל תת־יכולת רשומה גם בגרף ה־RAG.</p></div>")

    def page_deliver(self, deliver_id: str, msg: str | None) -> str:
        drow = self.db.one(
            "SELECT c.*,t.state,t.state_reason,t.preferred_model_key task_preferred_model_key,t.last_model_key,t.worktree,t.passed_commit,"
            "e.currency,e.fixed_price,e.valuation_amount,e.valuation_as_of,e.valuation_source_url,e.valuation_basis,"
            "e.budget_allocated,e.budget_reserved,e.budget_spent,e.status economics_status "
            "FROM deliver_catalog c LEFT JOIN tasks t ON t.task_id=c.deliver_id "
            "LEFT JOIN deliver_economics e ON e.deliver_id=c.deliver_id WHERE c.deliver_id=?", (deliver_id,))
        if not drow:
            return self._layout("Unknown Deliver", "<h1>Unknown Deliver</h1>", msg)
        d = dict(drow); back = "/deliver?id=" + urllib.parse.quote(deliver_id)
        description_he = deliver_description_he(self.cfg, self.db, d)
        implementation_he = deliver_implementation_he(self.db, d)
        explanation_card = (f"<section class='card'><h2>מה הרכיב עושה</h2><p>{E(description_he)}</p>"
                            f"<h2>איך הוא מיושם כעת</h2><p>{E(implementation_he)}</p>"
                            "<p class='muted'>הסבר המימוש מחושב ממצב המשימה, נתיבי התוצרים, סוג ההרצה והמאזינים העדכניים.</p></section>")
        deliver_context = self.db.one(
            "SELECT COUNT(*) source_count,COALESCE(SUM(LENGTH(CAST(excerpt AS BLOB))),0) source_bytes "
            "FROM context_sources WHERE active=1 AND (deliver_id=? OR (deliver_id IS NULL AND task_id IS NULL))",
            (deliver_id,))
        deliver_packs = self.db.one(
            "SELECT COUNT(*) pack_count,COALESCE(SUM(total_bytes),0) pack_bytes,"
            "COALESCE((SELECT total_bytes FROM context_packs WHERE task_id=? ORDER BY id DESC LIMIT 1),0) latest_bytes "
            "FROM context_packs WHERE task_id=?", (deliver_id, deliver_id))
        deliver_cost = self.db.one(
            "SELECT COUNT(*) attempt_count,COALESCE(SUM(reported_cost_usd),0) reported_cost_usd,"
            "SUM(CASE WHEN ended_at IS NOT NULL AND reported_cost_usd IS NULL THEN 1 ELSE 0 END) unknown_cost_attempts "
            "FROM task_attempts WHERE task_id=?", (deliver_id,))
        active_for_deliver = int(self.db.one(
            "SELECT COUNT(*) n FROM listener_activations WHERE status IN ('SELECTED','RUNNING') "
            "AND (source_deliver_id=? OR target_deliver_id=?)", (deliver_id, deliver_id))["n"])
        deliver_runtime_metrics = (
            "<div class='runtime-strip'>"
            f"<div class='runtime-metric'><span>קונטקסט זמין ל־Deliver</span><strong>{fmt_bytes(deliver_context['source_bytes'])}</strong>"
            f"<small>{deliver_context['source_count']} מקורות פעילים, כולל גלובליים</small></div>"
            f"<div class='runtime-metric'><span>Context Packs בפועל</span><strong>{fmt_bytes(deliver_packs['pack_bytes'])}</strong>"
            f"<small>{deliver_packs['pack_count']} חבילות · אחרונה {fmt_bytes(deliver_packs['latest_bytes'])}</small></div>"
            f"<div class='runtime-metric'><span>עלות מדווחת שמורה</span><strong>${float(deliver_cost['reported_cost_usd'] or 0):.4f}</strong>"
            f"<small>{deliver_cost['attempt_count']} ניסיונות · {deliver_cost['unknown_cost_attempts'] or 0} ללא מחיר</small></div>"
            f"<div class='runtime-metric{' live' if active_for_deliver else ''}'><span>Listeners פעילים סביב הרכיב</span>"
            f"<strong>{active_for_deliver}</strong><small>נבחרו או רצים כעת</small></div></div>")
        all_delivers = [r["deliver_id"] for r in self.db.q(
            "SELECT deliver_id FROM deliver_catalog WHERE enabled=1 ORDER BY deliver_id")]
        options = "".join(f"<option value='{E(x)}'>{E(x)}</option>" for x in all_delivers if x != deliver_id)
        incoming = [dict(r) for r in self.db.q(
            "SELECT * FROM deliver_listener_edges WHERE target_deliver_id=? ORDER BY edge_type,listener_id", (deliver_id,))]
        outgoing = [dict(r) for r in self.db.q(
            "SELECT * FROM deliver_listener_edges WHERE source_deliver_id=? ORDER BY edge_type,listener_id", (deliver_id,))]
        edge_rows = ""
        for edge in incoming + outgoing:
            direction = (f"{edge['source_deliver_id']} ← ה־Deliver הזה" if edge["target_deliver_id"] == deliver_id else
                         f"ה־Deliver הזה ← {edge['target_deliver_id']}")
            toggle = ""
            if edge["edge_type"] == "listener":
                toggle = self._form("toggle_listener", "השבת" if edge["enabled"] else "הפעל", back=back,
                                    listener_id=edge["listener_id"], enabled="0" if edge["enabled"] else "1")
            edge_kind = "מאזין" if edge["edge_type"] == "listener" else "תלות קשיחה"
            edge_rows += (f"<tr><td>{edge_kind}</td><td class='mono'>{E(edge['listener_id'])}</td>"
                          f"<td class='mono'>{E(direction)}</td><td>{E(edge['event_type'])}</td>"
                          f"<td>{'בחירת Jev' if edge['jev_gate'] else 'חובה מוקדמת'}</td>"
                          f"<td>{pill('AVAILABLE' if edge['enabled'] else 'PAUSED')} {toggle}</td></tr>")
        attempts = self.db.q("SELECT * FROM task_attempts WHERE task_id=? ORDER BY id DESC", (deliver_id,))
        attempt_rows = ""
        for a in attempts:
            inspect_links = " ".join(
                f"<a href='/log/{a['id']}/{which}'>{which}</a>"
                for which in ("prompt", "stdout", "stderr", "message", "diff"))
            attempt_rows += (
                f"<tr><td>{a['id']}</td><td>{E(a['kind'])} #{a['attempt_no']}</td><td>{E(a['provider'])}</td>"
                f"<td class='mono'>{E(a['model'])}</td><td>{pill(a['status'])}</td><td>{local(a['started_at'])}</td>"
                f"<td>{inspect_links}</td></tr>")
        artifacts = "".join(self._artifact_html(a) for a in self.db.q(
            "SELECT * FROM artifacts WHERE task_id=? ORDER BY id DESC", (deliver_id,)))
        events = "".join(
            f"<tr><td>{local(e['at'])}</td><td>{E(e['event'])}</td><td><pre>{E(e['detail'] or '')}</pre></td></tr>"
            for e in self.db.q("SELECT * FROM event_log WHERE task_id=? ORDER BY id DESC LIMIT 100", (deliver_id,)))
        contexts = "".join(
            f"<details><summary>{E(c['title'])} · <span class='mono'>{E(c['source_key'])}</span></summary>"
            f"<p class='muted'>{E(c['origin_kind'])}: {E(c['origin_ref'])} · graph {E(c['graph_entity_id'] or '—')} · sha {E(c['content_sha256'][:12])}</p>"
            f"<pre>{E(c['excerpt'])}</pre></details>"
            for c in self.db.q("SELECT * FROM context_sources WHERE active=1 AND (deliver_id=? OR (deliver_id IS NULL AND task_id IS NULL)) ORDER BY deliver_id DESC,updated_at DESC", (deliver_id,)))
        if d["execution_kind"] == "deterministic":
            context_stats = self.db.one(
                "SELECT COUNT(*) source_count,COALESCE(SUM(LENGTH(CAST(excerpt AS BLOB))),0) source_bytes "
                "FROM context_sources WHERE active=1 AND (deliver_id=? OR (deliver_id IS NULL AND task_id IS NULL))",
                (deliver_id,))
            own_context_stats = self.db.one(
                "SELECT COUNT(*) source_count,COALESCE(SUM(LENGTH(CAST(excerpt AS BLOB))),0) source_bytes "
                "FROM context_sources WHERE active=1 AND deliver_id=?", (deliver_id,))
            runs = self.db.q(
                "SELECT * FROM deterministic_deliver_runs WHERE deliver_id=? ORDER BY started_at DESC LIMIT 100",
                (deliver_id,))
            run_rows = "".join(
                f"<tr><td class='mono'>{E(run['run_id'])}</td><td>{pill(run['status'])}</td>"
                f"<td>{E(run['episode_id'] or '—')}</td><td>{local(run['started_at'])}</td>"
                f"<td>{local(run['completed_at']) if run['completed_at'] else '…'}</td>"
                f"<td>{fmt_bytes(run['input_bytes'])} / {fmt_bytes(run['output_bytes'])}</td><td>$0</td>"
                f"<td><details><summary>פרטים</summary><pre>{E(run['detail_json'])}</pre></details></td></tr>"
                for run in runs)
            light_edit = (
                f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                f"<input type='hidden' name='action' value='save_deliver'><input type='hidden' name='back' value='{E(back)}'>"
                f"<input type='hidden' name='deliver_id' value='{E(deliver_id)}'><input type='hidden' name='execution_kind' value='deterministic'>"
                f"<div class='grid2'><div><label class='blk'>אחראי</label><input type='text' name='owner' value='{E(d.get('owner') or '')}'>"
                f"<label class='blk'>תחום</label><input type='text' name='domain' value='{E(d.get('domain') or '')}'></div>"
                f"<div><label class='blk'>מה הפונקציה עושה — בעברית</label><textarea name='description' rows='5' required>{E(description_he)}</textarea>"
                f"<button class='go'>שמור חוזה קל</button></div></div></form>")
            light_context_form = (
                f"<details class='hold'><summary>הוסף מועמד קונטקסט לפונקציה</summary><form method='post' action='/action'>"
                f"<input type='hidden' name='token' value='{self.token}'><input type='hidden' name='action' value='add_context'>"
                f"<input type='hidden' name='back' value='{E(back)}'><input type='hidden' name='deliver_id' value='{E(deliver_id)}'>"
                "<label class='blk'>מפתח מקור</label><input type='text' name='source_key' required>"
                "<label class='blk'>כותרת</label><input type='text' name='title' required>"
                "<label class='blk'>מקור או הפניה</label><input type='text' name='origin_ref'>"
                "<label class='blk'>תוכן</label><textarea name='excerpt' rows='5' required></textarea>"
                "<button class='go'>שמור קונטקסט</button></form></details>")
            own_sources = int(own_context_stats["source_count"] if own_context_stats else 0)
            all_sources = int(context_stats["source_count"] if context_stats else 0)
            context_bytes = int(context_stats["source_bytes"] if context_stats else 0)
            running_runs = sum(run["status"] == "RUNNING" for run in runs)
            body = (
                f"<p><a href='/delivers'>→ חזרה למפת ה־Delivers</a></p><section class='control-hero light-contract'>"
                f"<div class='eyebrow'>Deliver דטרמיניסטי · חוזה קל ושמור</div><h1 class='mono'>{E(deliver_id)}</h1>"
                f"<p>{pill(d.get('state') or ('AVAILABLE' if d['enabled'] else 'PAUSED'))} · פונקציה מקומית · "
                f"עלות מודל $0 · <span class='mono'>{E(d.get('implementation_ref') or d.get('source_ref') or 'ללא מימוש רשום')}</span></p></section>"
                f"<div class='runtime-strip'><div class='runtime-metric'><span>קונטקסט זמין</span><strong>{fmt_bytes(context_bytes)}</strong>"
                f"<small>{all_sources} מקורות · {own_sources} ייחודיים ל־Deliver</small></div>"
                f"<div class='runtime-metric{' live' if running_runs else ''}'><span>הרצות דטרמיניסטיות</span><strong>{len(runs)}</strong>"
                f"<small>{running_runs} רצות עכשיו · נשמרות ב־SQLite</small></div>"
                f"<div class='runtime-metric'><span>עלות LLM</span><strong>$0</strong><small>אין בחירת מודל ואין טוקנים</small></div>"
                f"<div class='runtime-metric'><span>Listeners מחוברים</span><strong>{len(incoming) + len(outgoing)}</strong>"
                f"<small>{len(outgoing)} יוצאים · {len(incoming)} נכנסים</small></div></div>"
                f"<div class='grid2'><div><h2>חוזה קל</h2><div class='card'>{light_edit}</div></div>"
                f"<div><h2>קונטקסט</h2><div class='card'>{light_context_form}</div></div></div>"
                f"<h2>קשרים ו־Listeners</h2><div class='card'><table><tr><th>סוג</th><th>מזהה</th><th>נתיב</th>"
                f"<th>אירוע</th><th>שער</th><th>מצב</th></tr>{edge_rows or '<tr><td colspan=6 class=muted>אין עדיין קשרים</td></tr>'}</table></div>"
                f"<h2>הרצות שמורות</h2><div class='card'><table><tr><th>מזהה</th><th>מצב</th><th>אפיזודה</th>"
                f"<th>התחלה</th><th>סיום</th><th>קלט / פלט</th><th>עלות</th><th>פרטים</th></tr>"
                f"{run_rows or '<tr><td colspan=8 class=muted>עדיין לא נרשמה הרצה דטרמיניסטית.</td></tr>'}</table></div>"
                f"<h2>מועמדי קונטקסט ומקורם</h2><div class='card'>{contexts or '<span class=muted>אין מועמדי קונטקסט</span>'}</div>"
                f"<h2>היסטוריית ה־Deliver</h2><div class='card'><table><tr><th>זמן</th><th>אירוע</th><th>פרטים</th></tr>"
                f"{events or '<tr><td colspan=3 class=muted>אין עדיין אירועים.</td></tr>'}</table></div>")
            return self._layout(deliver_id, explanation_card + self._capabilities_html(deliver_id) + body, msg)
        selected_model = d.get("preferred_model_key") or d.get("task_preferred_model_key") or ""
        task_links = ""
        if self.db.task(deliver_id):
            task_links = (f" <a class='btnlink' href='/task?id={urllib.parse.quote(deliver_id)}'>ניהול המשימה</a> "
                          f"<a class='btnlink' href='/review?id={urllib.parse.quote(deliver_id)}'>הצג מה נבנה</a>")
        model_control = (f"<form class='inline-control' method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                         f"<input type='hidden' name='action' value='set_deliver_model'><input type='hidden' name='deliver_id' value='{E(deliver_id)}'>"
                         f"<input type='hidden' name='back' value='{E(back)}'><label>מודל קבוע ל־Deliver</label> "
                         f"<select name='model_key'><option value=''>בחירה אוטומטית</option>{self._model_options(selected_model)}</select>"
                         f"<button>שמור מודל</button></form>{task_links}")
        graph_access = self._graph_access_form(deliver_id, back)
        scoped_prompt = (f"<div class='card command-card'><h2>בקש שינוי ב־Deliver הזה</h2>"
                         f"<p class='muted'>המודל יקבל את הגדרת הרכיב, הקשרים הישירים ורשימת מועמדים קצרה מהגרף. Jev יחליט איזה קונטקסט ייכנס בפועל.</p>"
                         f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                         f"<input type='hidden' name='action' value='scoped_plan'><input type='hidden' name='scope_kind' value='deliver'>"
                         f"<input type='hidden' name='scope_id' value='{E(deliver_id)}'><input type='hidden' name='back' value='{E(back)}'>"
                         f"<input type='hidden' name='prompt_mode' value='plan_build'><label class='blk'>מה לשנות?</label>"
                         f"<textarea name='prompt' required placeholder='לדוגמה: הוסף מאזין שמפעיל בדיקת מזג אוויר כאשר מיקום ותאריך האפיזודה ידועים'></textarea>"
                         f"<div class='form-actions'><select name='model_key'><option value=''>בחירת מודל אוטומטית</option>{self._model_options('')}</select>"
                         f"<input type='text' name='mcp_servers' placeholder='שרתי MCP, אם צריך'>"
                         f"<button class='go'>תכנן את השינוי</button></div></form></div>")
        execution_labels = {"worker": "סוכן ביצוע", "deterministic": "פונקציה דטרמיניסטית",
                            "llm_research": "מחקר מודל", "context_bundle": "חבילת קונטקסט",
                            "review": "בקרת איכות"}
        edit = (f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                f"<input type='hidden' name='action' value='save_deliver'><input type='hidden' name='back' value='{E(back)}'>"
                f"<input type='hidden' name='deliver_id' value='{E(deliver_id)}'><div class='grid2'><div>"
                f"<label class='blk'>אחראי</label><input type='text' name='owner' value='{E(d.get('owner') or '')}'>"
                f"<label class='blk'>תחום</label><input type='text' name='domain' value='{E(d.get('domain') or '')}'>"
                f"<label class='blk'>סוג ביצוע</label><select class='w' name='execution_kind'>" + "".join(
                    f"<option value='{x}'{' selected' if x == d['execution_kind'] else ''}>{execution_labels[x]}</option>" for x in
                    ("worker", "deterministic", "llm_research", "context_bundle", "review")) + "</select></div>"
                f"<div><label class='blk'>מה ה־Deliver עושה — בעברית</label><textarea name='description' rows='8' required>{E(description_he)}</textarea>"
                f"<p><button class='go'>שמור Deliver</button> "
                f"{self._form('toggle_deliver', 'השבת' if d['enabled'] else 'הפעל', back=back, deliver_id=deliver_id, enabled='0' if d['enabled'] else '1')}</p></div></div></form>")
        listener_form = (f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                         f"<input type='hidden' name='action' value='add_listener'><input type='hidden' name='back' value='{E(back)}'>"
                         f"<input type='hidden' name='source_deliver_id' value='{E(deliver_id)}'><div class='grid2'><div>"
                         f"<label class='blk'>מזהה מאזין</label><input type='text' name='listener_id' required placeholder='{E(deliver_id)}::signal'>"
                         f"<label class='blk'>מזהה רכיב הלגו המקורי</label><input type='text' name='source_lego_id'>"
                         f"<label class='blk'>סוג אירוע</label><input type='text' name='event_type' value='DELIVER_PASSED' required>"
                         f"<label class='blk'>Deliver יעד</label><select class='w' name='target_deliver_id'>{options}</select></div><div>"
                         f"<label class='blk'>למה להציע את ההפעלה</label><textarea name='proposal_reason' rows='3' required></textarea>"
                         f"<label class='blk'>בורר דטרמיניסטי, JSON</label><textarea name='context_selector' rows='6'>{{}}</textarea>"
                         f"<p class='muted'>המאזין נשמר כמועמד. Jev עדיין מחליט בכל אירוע אם להפעיל אותו.</p>"
                         f"<button class='go'>שמור מאזין</button></div></div></form>")
        dependency_form = (f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                           f"<input type='hidden' name='action' value='add_dependency'><input type='hidden' name='back' value='{E(back)}'>"
                           f"<input type='hidden' name='target_deliver_id' value='{E(deliver_id)}'><label class='blk'>Deliver נדרש</label>"
                           f"<select class='w' name='depends_on'>{options}</select><p><button>הוסף תלות קשיחה</button></p></form>")
        context_form = (f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                        f"<input type='hidden' name='action' value='add_context'><input type='hidden' name='back' value='{E(back)}'>"
                        f"<input type='hidden' name='deliver_id' value='{E(deliver_id)}'><label class='blk'>מפתח מקור קונטקסט</label>"
                        f"<input type='text' name='source_key' required><label class='blk'>כותרת</label><input type='text' name='title' required>"
                        f"<label class='blk'>מקור, כתובת או הפניה לגרף</label><input type='text' name='origin_ref'>"
                        f"<label class='blk'>מזהה ישות בגרף</label><input type='text' name='graph_entity_id'>"
                        f"<label class='blk'>מועמד הקונטקסט</label><textarea name='excerpt' rows='8' required></textarea>"
                        f"<p class='muted'>המתזמן חושף אותו כמועמד בלבד; Jev חייב לבחור בו לפני שייכנס לפרומפט של מודל.</p>"
                        f"<button class='go'>שמור מועמד קונטקסט</button></form>")
        economics = (f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                     f"<input type='hidden' name='action' value='save_economics'><input type='hidden' name='back' value='{E(back)}'>"
                     f"<input type='hidden' name='deliver_id' value='{E(deliver_id)}'><div class='grid2'><div>"
                     f"<label class='blk'>מטבע</label><input type='text' name='currency' value='{E(d.get('currency') or 'USD')}'>"
                     f"<label class='blk'>מחיר קבוע</label><input type='text' name='fixed_price' value='{E(str(d.get('fixed_price') or ''))}'>"
                     f"<label class='blk'>תקציב מוקצה</label><input type='text' name='budget_allocated' value='{E(str(d.get('budget_allocated') or ''))}'></div><div>"
                     f"<label class='blk'>שווי נוכחי</label><input type='text' name='valuation_amount' value='{E(str(d.get('valuation_amount') or ''))}'>"
                     f"<label class='blk'>תאריך הערכת שווי</label><input type='text' name='valuation_as_of' value='{E(d.get('valuation_as_of') or '')}'>"
                     f"<label class='blk'>כתובת מקור להערכת שווי</label><input type='text' name='valuation_source_url' value='{E(d.get('valuation_source_url') or '')}'>"
                     f"<label class='blk'>בסיס להערכת השווי</label><textarea name='valuation_basis' rows='3'>{E(d.get('valuation_basis') or '')}</textarea></div></div>"
                     f"<button class='go'>שמור נתונים כלכליים</button></form>")
        body = (f"<p><a href='/delivers'>→ חזרה למפת ה־Delivers</a></p><section class='control-hero'>"
                f"<div class='eyebrow'>ניהול רכיב</div><h1 class='mono'>{E(deliver_id)}</h1>"
                f"<p>{pill(d.get('state') or ('AVAILABLE' if d['enabled'] else 'PAUSED'))} · {E(d['execution_kind'])} · "
                f"מקור <span class='mono'>{E(d.get('source_ref') or d.get('source_kind') or '')}</span></p>{model_control}</section>"
                f"{deliver_runtime_metrics}"
                f"<div class='control-grid'>{scoped_prompt}<div><h2>הגדרת ה־Deliver</h2><div class='card'>{edit}</div></div></div>"
                f"<h2>גישה לגרף ה־RAG</h2><div class='card'>{graph_access}</div>"
                f"<div class='grid2'><div><h2>קשרים, תלויות ומאזינים</h2><div class='card'><table><tr><th>סוג</th><th>מזהה</th><th>נתיב</th><th>אירוע</th><th>שער</th><th>מצב</th></tr>"
                f"{edge_rows or '<tr><td colspan=6 class=muted>אין עדיין קשרים</td></tr>'}</table></div></div>"
                f"<div><h2>נתונים כלכליים ותקציב</h2><div class='card'>{economics}</div></div></div>"
                f"<div class='grid2'><div><h2>הוספת מאזין שעובר דרך Jev</h2><div class='card'>{listener_form}</div></div>"
                f"<div><h2>הוספת תלות קשיחה</h2><div class='card'>{dependency_form}</div><h2>הוספת מועמד קונטקסט</h2><div class='card'>{context_form}</div></div></div>"
                f"<h2>מה ה־Deliver בנה</h2><div class='card'>{artifacts or '<span class=muted>עדיין לא נשמרו תוצרים.</span>'}</div>"
                f"<h2>היסטוריית בנייה</h2><div class='card'><table><tr><th>ניסיון</th><th>סוג</th><th>ספק</th><th>מודל</th><th>מצב</th><th>התחלה</th><th>בדיקה</th></tr>"
                f"{attempt_rows or '<tr><td colspan=7 class=muted>עדיין לא היו ניסיונות בנייה.</td></tr>'}</table></div>"
                f"<h2>מועמדי קונטקסט ומקורם</h2><div class='card'>{contexts or '<span class=muted>אין מועמדי קונטקסט</span>'}</div>"
                f"<h2>היסטוריית ה־Deliver</h2><div class='card'><table><tr><th>זמן</th><th>אירוע</th><th>פרטים</th></tr>{events}</table></div>")
        return self._layout(deliver_id, explanation_card + self._capabilities_html(deliver_id) + body, msg)

    def page_overview(self, msg: str | None) -> str:
        st = self.state_json()
        pid, paused, emerg = st["daemon_pid"], st["paused"], st["emergency_stop"]
        counts: dict[str, int] = {}
        plan_tasks = [t for t in st["tasks"] if t["kind"] != "repair"]
        for t in plan_tasks:
            counts[t["state"]] = counts.get(t["state"], 0) + 1
        open_waves = [t["wave"] for t in plan_tasks if t["state"] not in ("PASSED", "CANCELLED")]
        wave = min(open_waves) if open_waves else "done"
        status = ("EMERGENCY STOP" if emerg else "PAUSED" if paused else "RUNNING" if pid else "DAEMON NOT RUNNING")
        idle = st["idle_reason"] or ""
        nw = st["next_wakeup_at"]
        controls = (self._form("resume", "RESUME", "big go") if paused and not emerg else
                    self._form("pause", "PAUSE", "big pause")) + " " + \
            self._form("stop", "STOP", "big stop", confirm="Stop: no new tasks; running workers are interrupted "
                                                            "gracefully and their work is kept. Continue?")
        advanced = ("<details><summary>Advanced</summary><p>" +
                    self._form("pause_interrupt", "Pause + interrupt running", "pause",
                               confirm="Interrupt running workers now? Work stays in their worktrees.") + " " +
                    self._form("kill", "EMERGENCY KILL", "stop",
                               confirm="SIGKILL all workers immediately and disable the scheduler?") + " " +
                    (self._form("resume", "Clear emergency + resume", "", clear="1") if emerg else "") +
                    "</p></details>")
        head = (f'<div class="bar"><div><h1>WWII Build Manager</h1><div class="muted mono" dir="ltr">{E(str(self.cfg.repo))}</div>'
                f'<div>{pill(status)} {self.t("daemon pid")} {pid or "-"} · {self.t("wave")} <b>{wave}</b>'
                f'{" · " + E(idle) if idle else ""}{" · " + self.t("next wakeup") + " " + local(nw) if nw else ""}'
                f'</div></div>'
                f'<div>{controls}{advanced}</div></div>')
        groups = [("completed", ["PASSED"]), ("running", ["RUNNING", "PAUSING", "REVIEWING", "CODE_READY"]),
                  ("ready", ["READY"]), ("waiting", ["WAITING_DEPENDENCY", "WAITING_QUOTA", "WAITING_PROVIDER",
                                                    "WAITING_APPROVAL", "PENDING", "PAUSED"]),
                  ("repairing", ["WAITING_REPAIR"]), ("review", ["REVIEW_REQUIRED", "ARCHITECTURE_REVIEW_REQUIRED"]),
                  ("blocked", ["BLOCKED"]), ("failed", ["FAILED"]),
                  ("cancelled", ["CANCELLED"])]
        cnt = "".join(f'<div class="count"><span class="muted">{g}</span><b>{sum(counts.get(s, 0) for s in ss)}</b></div>'
                      for g, ss in groups)
        # workers
        now = dt.datetime.now(dt.timezone.utc)
        wrows = ""
        for w in st["workers"]:
            started = parse_iso(w["started_at"])
            rt = str(now - started).split(".")[0] if started else "-"
            wrows += (f"<tr><td><a href='/task?id={urllib.parse.quote(w['task_id'])}'>{E(w['task_id'])}</a></td>"
                      f"<td>{E(w['provider'])}</td><td class='mono'>{E(w['model'])}</td><td>{rt}</td><td>{w['pid'] or '-'}</td>"
                      f"<td>{w['context_bytes'] or 'unknown'} B</td><td class='mono'>{E(w['worktree'] or '')}</td></tr>")
        workers = ("<table><tr><th>task</th><th>provider</th><th>model</th><th>runtime</th><th>PID</th><th>context</th>"
                   f"<th>worktree</th></tr>{wrows or '<tr><td colspan=7 class=muted>no workers running</td></tr>'}</table>")
        # quotas
        qrows = ""
        def win(v, reset):
            """Used percent of one quota window; a window whose reset time already passed is back to unused."""
            r = parse_iso(reset) if reset else None
            if r is not None and r <= utcnow():
                return "<b>0%</b> <span class='muted'>(reset)</span>"
            return f"<b>{v:.0f}%</b>" if v is not None else "unknown"
        for q in st["quota"]:
            weekly = q['weekly_used_percent'] if q['weekly_used_percent'] is not None else (
                q['used_percent'] if q['session_used_percent'] is None else None)
            qrows += (f"<tr><td>{E(q['provider'])}</td>"
                      f"<td>{pill(q['status'])}{''.join(f'<br><small class=muted>{E(n)}</small>' for n in q['notes'])}</td>"
                      f"<td>{win(q['session_used_percent'], q['session_reset_at'])}</td>"
                      f"<td>{local(q['session_reset_at']) if q['session_reset_at'] else 'unknown'}</td>"
                      f"<td>{win(weekly, q['weekly_reset_at'])}</td>"
                      f"<td>{local(q['weekly_reset_at']) if q['weekly_reset_at'] else 'unknown'}</td>"
                      f"<td>{local(q['blocked_until']) if q['blocked_until'] else '-'}</td>"
                      f"<td>{ago(q['data_at'] or q['last_checked_at'])}</td>"
                      f"<td class='muted'>{E(q['source'] or '-')} ({E(q['confidence'])})</td></tr>")
        models = "".join(f"<li>{E(k)}: {E(m['provider'])} <span class='mono'>{E(m['model'])}</span> "
                         f"({E(str(m.get('effort')))}){' — manual approval' if not m.get('automatic', True) or self.cfg.section('approvals').get(k) == 'required' else ''}</li>"
                         for k, m in self.cfg.data["models"].items())
        refresh = " ".join(self._form("refresh", f"refresh {p}", provider=p) for p in self.cfg.data["providers"])
        refresh += "<br><span class='muted'>Used a usage reset inside the Claude/Codex app? Tell the manager "\
                   "(it never performs or buys a reset itself):</span> " + " ".join(
            self._form("reset_done", f"I did a {p} usage reset in the app", "go", provider=p,
                       confirm=f"Confirm you performed a {p} usage reset in its own app. The manager clears its {p} "
                               "quota block and re-checks.") for p in self.cfg.data["providers"])
        quotas = ("<table><tr><th>provider</th><th>status</th><th>5-hour used</th><th>5-hour reset</th>"
                  "<th>weekly used</th><th>weekly reset</th><th>blocked until</th><th>updated</th><th>source</th></tr>"
                  f"{qrows or '<tr><td colspan=9 class=muted>no data yet (unknown)</td></tr>'}</table>"
                  f"<details><summary>model profiles</summary><ul>{models}</ul></details><p>{refresh}</p>")
        # approvals
        arows = ""
        for a in self.db.q("SELECT * FROM approvals WHERE status='pending' ORDER BY id"):
            extra = ""
            if a["kind"] in ("escalation", "astra_recommended", "repair_limit", "architecture_review"):
                opts = "".join(f"<option value='{E(k)}'>{E(k)}</option>" for k in self.cfg.data["models"])
                extra = f"<select name='model_key'><option value=''>same route</option>{opts}</select>"
            approve = (f'<form method="post" action="/action"><input type="hidden" name="token" value="{self.token}">'
                       f'<input type="hidden" name="action" value="approve"><input type="hidden" name="approval_id" '
                       f'value="{a["id"]}">{extra}<button class="go">Approve</button></form>')
            reject = (f'<form method="post" action="/action"><input type="hidden" name="token" value="{self.token}">'
                      f'<input type="hidden" name="action" value="reject"><input type="hidden" name="approval_id" '
                      f'value="{a["id"]}"><input name="note" placeholder="note"><button>Reject</button></form>')
            tl = f"<a href='/task?id={urllib.parse.quote(a['task_id'] or '')}'>{E(a['task_id'] or '-')}</a>"
            if a["kind"] == "plan_proposal":
                tl += " · <a href='/plan'>" + E(self.t("Proposed tasks")) + "</a>"
            if a["kind"] in ("review", "architecture_review", "repair_limit") and a["task_id"]:
                tl += (f"<br><a class='btnlink' href='/review?id={urllib.parse.quote(a['task_id'])}'>"
                       f"{E(self.t('View what was created'))}</a>")
            arows += (f"<tr><td>#{a['id']}</td><td>{tl}</td><td>{E(a['kind'])}</td><td class='mono'>{E(a['subject'] or '')}</td>"
                      f"<td>{E(a['reason'] or '')}</td><td>{approve} {reject}</td></tr>")
        approvals = ("<table><tr><th>#</th><th>task</th><th>kind</th><th>subject</th><th>reason</th><th></th></tr>"
                     f"{arows or '<tr><td colspan=6 class=muted>nothing waiting for you</td></tr>'}</table>")
        auto_all = self.db.get_flag("review_auto_approve_all") == "1"
        auto_approval = (f"<div class='card' style='border-color:{'#67d9bf' if auto_all else '#ffd85a'}'>"
                         f"<div class='bar'><div><h2 style='margin:0'>אישור אוטומטי לכל המשימות</h2>"
                         f"<p class='muted'>{'פעיל: כל אישור מאושר אוטומטית — review, מודלים פרימיום (Opus/Astra), הצעות מתכנן, escalation, תיקונים וסקירות ארכיטקטורה.' if auto_all else 'כבוי: אישורים ממתינים לך.'} "
                         f"כשל בבדיקות עדיין עוצר משימה; אישור שמוביל לסבב תיקון נוסף מאושר עד {int(self.cfg.section('approvals').get('auto_max_per_task', 3))} פעמים למשימה ואז נדחה אוטומטית — שום דבר לא מחכה לך; הכפתור 'למה תקוע? המשך' מנסה שוב משימות שנתקעו. חיוב API ושימוש נוסף בתשלום לעולם לא מאושרים.</p></div>"
                         f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                         f"<input type='hidden' name='action' value='set_auto_approve_all'>"
                         f"<input type='hidden' name='enabled' value='{'0' if auto_all else '1'}'>"
                         f"<input type='hidden' name='back' value='/'>"
                         f"<button class='big {'bad' if auto_all else 'go'}'>{'כבה אישור אוטומטי' if auto_all else 'הפעל אישור אוטומטי להכול'}</button>"
                         f"</form></div></div>")
        # tasks
        trows = ""
        repairs: dict[str, list] = {}
        for t in st["tasks"]:
            if t["kind"] == "repair":
                repairs.setdefault(t["parent_task_id"], []).append(t)
        for t in sorted(plan_tasks, key=lambda t: (t["wave"], STATE_ORDER.index(t["state"]) if t["state"] in STATE_ORDER else 99, t["task_id"])):
            rc = f" · repairs {t['repairs_count']}" if t["repairs_count"] else ""
            priority = int(t.get("dispatch_priority") or 0)
            expedite = (self._form("expedite", "דחוף עכשיו" if not priority else "דחוף שוב", "go", back="/",
                                   task_id=t["task_id"]) if t["state"] == "READY" else "")
            priority_note = f" · עדיפות {priority}" if priority else ""
            description_he = t["description_he"]
            trows += (f"<tr><td>{t['wave']}</td><td><a href='/task?id={urllib.parse.quote(t['task_id'])}'>{E(t['task_id'])}</a>"
                      f"{f' {WEB_BADGE}' if t.get('allow_web') else ''}<br><small>{E(description_he[:240])}</small></td>"
                      f"<td>{E(t['owner'])}</td><td>{pill(t['state'])}</td><td class='mono'>{E(t['last_model_key'] or '')}</td>"
                      f"<td>{E((t['state_reason'] or '')[:160])}{rc}{priority_note}</td><td>{expedite} "
                      f"<a class='btnlink' href='/task?id={urllib.parse.quote(t['task_id'])}'>ניהול מודל, קונטקסט ותלויות</a></td></tr>")
            for r in sorted(repairs.get(t["task_id"], []), key=lambda r: r["repair_no"]):
                trows += (f"<tr class='repair'><td></td><td>└─ <a href='/task?id={urllib.parse.quote(r['task_id'])}'>Repair "
                          f"#{r['repair_no']}</a></td><td class='muted'>{E(r['failure_class'] or '')}</td><td>{pill(r['state'])}</td>"
                          f"<td class='mono'>{E(r['last_model_key'] or '')}</td><td>{E((r['state_reason'] or '')[:160])}</td><td></td></tr>")
        tasks = f"<table><tr><th>גל</th><th>משימה</th><th>אחראי</th><th>מצב</th><th>מודל</th><th>סיבה</th><th>שליטה</th></tr>{trows}</table>"
        # artifacts + gaps
        arts = ""
        for a in self.db.q("SELECT * FROM artifacts ORDER BY id DESC LIMIT 12"):
            arts += self._artifact_html(a)
        gaps = "".join(f"<tr><td>{E(g['task_id'])}</td><td>{E(g['kind'])}</td><td>{E(g['text'][:300])}</td></tr>"
                       for g in self.db.q("SELECT * FROM capability_gaps ORDER BY id DESC LIMIT 40"))
        watch = st["model_watch"]
        updated = ", ".join(f"{key}: {item['model']}" for key, item in watch.get("updated", {}).items()) or "אין שינוי בבדיקה האחרונה"
        waiting = ", ".join(f"{key}: {model}" for key, model in watch.get("waiting_for_local_access", {}).items()) or "אין"
        rolled_back = ", ".join(f"{key}: {item['rejected_model']} → {item['restored_model']}"
                                for key, item in watch.get("rolled_back", {}).items()) or "אין"
        review = ", ".join(f"{key}: {model}" for key, model in watch.get("review_candidates", {}).items()) or "אין"
        active_models = ", ".join(f"{key}: {profile['model']}" for key, profile in st["models"].items())
        model_card = (f"<h2>בדיקת מודלים יומית</h2><div class='card'><p>בדיקה אחרונה: {E(local(watch.get('checked_at')))} · "
                      f"מצב: {E(watch.get('status', 'טרם נבדק'))}</p>"
                      f"<p>עודכנו: {E(updated)} · פורסמו אך אינם זמינים מקומית: {E(waiting)}</p>"
                      f"<p>הוחזרו בעקבות שגיאת מודל: {E(rolled_back)}</p>"
                      f"<p>דגמים חדשים למשפחות אחרות או בתמחור גבוה, לבדיקה ידנית: {E(review)}</p>"
                      f"<p>מודלים פעילים: {E(active_models)}</p>"
                      f"{self._form('model_watch_check', 'בדוק עכשיו', back='/')}"
                      "<p class='muted'>עדכון אוטומטי חל רק על מודלים מקבילים ברמת עלות רגילה או חסכונית; "
                      "שגיאת מודל מחזירה את הדגם הקודם.</p></div>")
        body = (head + f"<h2>Overview</h2><div class='counts'>{cnt}</div>{self._unstick_card()}{auto_approval}{model_card}"
                f"<h2>שיחה על המצב</h2><div class='card'>{self._state_chat_box(st)}</div>"
                f"<h2>Current workers</h2><div class='card'>{workers}</div>"
                f"<h2>Waiting for you</h2><div class='card'>{approvals}</div>"
                f"<h2>Quotas</h2><div class='card'>{quotas}</div>"
                f"<h2>Latest artifacts</h2><div class='card'>{arts or '<span class=muted>none yet</span>'}</div>"
                f"<h2>Tasks</h2><div class='card'>{tasks}</div>"
                f"<h2>Capability gaps &amp; cross-domain requests</h2><div class='card'><table>{gaps or '<tr><td class=muted>none reported</td></tr>'}</table></div>"
                f"<p><a href='/events'>event log</a> · <a href='/api/state'>api/state</a></p>")
        return self._layout("WWII Build Manager", body, msg)

    def _unstick_card(self) -> str:
        try:
            rep = json.loads(self.db.get_flag("unstick_last_report") or "null")
        except ValueError:
            rep = None
        button = (f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                  "<input type='hidden' name='action' value='unstick'><input type='hidden' name='back' value='/'>"
                  "<button class='big go'>⟳ בדוק למה הריצה תקועה והמשך</button></form>")
        if not rep:
            body = "<p class='muted'>לחיצה מאבחנת את המצב (מתזמן, השהיה, אישורים, המתנות, מכסות, תלויות שנכשלו, " \
                   "התנגשויות merge) ומבצעת את מה שאפשר כדי שהריצה תמשיך. כל פעולה נרשמת ביומן.</p>"
        else:
            lst = lambda items: "".join(f"<li>{E(x)}</li>" for x in items)
            body = (f"<p class='muted'>בדיקה אחרונה: {local(rep['at'])}</p>"
                    + (f"<b>מה מצאתי</b><ul>{lst(rep['findings'])}</ul>" if rep["findings"] else "")
                    + (f"<b>מה עשיתי</b><ul>{lst(rep['actions'])}</ul>" if rep["actions"] else "")
                    + (f"<b style='color:var(--warn)'>דורש החלטה שלך</b><ul>{lst(rep['needs_you'])}</ul>" if rep["needs_you"] else ""))
        return (f"<div class='card unstick'><div class='bar'><div><h2 style='margin:0'>למה הריצה תקועה?</h2></div>"
                f"{button}</div>{body}</div>")

    def _state_chat_box(self, st: dict) -> str:
        new = self.db.get_flag("state_chat_new") == "1"
        conv = None if new else state_chat.latest_conversation(self.db)
        msgs = state_chat.history(self.db, conv) if conv else []
        bubbles = "".join(
            f"<div class='chat-msg {E(m['role'])}'><small class='muted'>"
            f"{'אתה' if m['role'] == 'user' else E((m['model_key'] or '') + ' · ' + (m['model'] or ''))} · {local(m['created_at'])}"
            f"</small><div style='white-space:pre-wrap'>{E(m['content'])}</div></div>" for m in msgs[-20:])
        intro = ("<p class='muted'>שאל כל דבר על המצב: מה רץ, מה תקוע ולמה, מה לעשות עכשיו. "
                 "התשובה מיידית, לקריאה בלבד, ולא נכנסת לתור המשימות.</p>")
        return (f"<div class='state-chat'>{bubbles or intro}"
                f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                f"<input type='hidden' name='action' value='state_chat'><input type='hidden' name='back' value='/'>"
                f"<input type='hidden' name='conversation_id' value='{conv or ''}'>"
                f"<textarea class='state-chat-input w' name='message' rows='3' required "
                f"placeholder='למשל: למה שום משימה לא רצה עכשיו?'></textarea>"
                f"<div class='planner-controls'><select name='model_key' aria-label='מודל לשיחה'>"
                f"{self._model_options('', 'automatic: best fit')}</select>"
                f"<button>שלח</button></div></form>"
                f"{self._form('state_chat_new', 'שיחה חדשה', back='/') if msgs else ''}</div>")

    def _artifact_html(self, a) -> str:
        label = f"{E(a['task_id'])} · {E(a['kind'])} · {E(a['source_path'] or '')}"
        if a["kind"] == "screenshot" or str(a["path"]).lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return f"<div><a href='/artifact/{a['id']}'><img class='thumb' src='/artifact/{a['id']}'></a><div class='muted'>{label}</div></div>"
        if a["kind"] == "video":
            return f"<div><video class='thumb' controls src='/artifact/{a['id']}'></video><div class='muted'>{label}</div></div>"
        return f"<div><a href='/artifact/{a['id']}'>{label}</a> <span class='muted'>{E(a['description'] or '')}</span></div>"

    def page_task(self, tid: str, msg: str | None) -> str:
        t = self.db.task(tid)
        if not t:
            return self._layout("not found", f"<p>unknown task {E(tid)}</p><p><a href='/'>back</a></p>", msg)
        back = f"/task?id={urllib.parse.quote(tid)}"
        task_extra = json.loads(t["extra"] or "{}")
        is_system_task = bool(task_extra.get("system_task"))
        system_release = self.db.one("SELECT * FROM system_repair_releases WHERE task_id=?", (tid,)) \
            if is_system_task else None
        system_card = ""
        if is_system_task:
            release_state = system_release["status"] if system_release else "טרם הוכן release"
            changed_count = len(json.loads(system_release["changed_files_json"] or "[]")) if system_release else 0
            system_card = (
                "<div class='card' style='border-color:#ffd85a'><h2>תיקון מערכת מוגן</h2>"
                f"<p><b>מצב הפצה:</b> {E(release_state)} · קבצים בחבילה: {changed_count}</p>"
                "<p class='muted'>העבודה מתבצעת בצילום מבודד של מנהל המשימות. הפעלה מתרחשת רק אחרי כל בדיקות "
                "המערכת, בדיקת drift והתרוקנות העובדים הפעילים. הגרסה הקודמת נשמרת לגיבוי וה־daemon מופעל מחדש בחן.</p></div>")
        deps = self.db.deps(tid)
        dep_html = "".join(f"<li><a href='/task?id={urllib.parse.quote(d)}'>{E(d)}</a> {pill(self.db.task(d)['state'])}</li>"
                           for d in deps) or "<li class='muted'>none (root)</li>"
        task_options = "".join(
            f"<option value='{E(r['task_id'])}'>{E(r['task_id'])} · {E(state_label(r['state'], 'he'))}</option>"
            for r in self.db.q("SELECT task_id,state FROM tasks WHERE task_id<>? AND kind<>'repair' ORDER BY wave,task_id", (tid,)))
        context_options = "".join(
            f"<option value='{E(r['source_key'])}'>{E(r['title'])} · {E(r['source_key'])}</option>"
            for r in self.db.q("SELECT source_key,title FROM context_sources WHERE active=1 ORDER BY title,source_key"))
        bindings = self.db.q(
            "SELECT b.*,c.title,c.origin_kind,c.origin_ref FROM task_context_bindings b "
            "JOIN context_sources c ON c.source_key=b.source_key WHERE b.task_id=? ORDER BY c.title", (tid,))
        binding_rows = "".join(
            f"<div class='access-row'><div><b>{E(r['title'])}</b><br><span class='mono'>{E(r['source_key'])}</span> "
            f"<small>{E(r['origin_kind'])} · {E(r['origin_ref'])}</small></div>"
            f"{self._form('toggle_task_context', 'השבת גישה' if r['active'] else 'הפעל גישה', back=back, task_id=tid, source_key=r['source_key'], enabled='0' if r['active'] else '1')}</div>"
            for r in bindings) or "<p class='muted'>לא ניתנו הרשאות קונטקסט מפורשות. החיפוש עדיין יכול להציע מקורות גלובליים ל־Jev.</p>"
        context_request = str(task_extra.get("context_request") or "").strip()
        planned_files = task_extra.get("evidence") or []
        context_plan_card = ""
        if context_request:
            sources = "".join(
                f"<li><b>{E(r['title'])}</b> · <span class='mono'>{E(r['source_key'])}</span> · "
                f"{E(r['origin_kind'])} · {E(r['origin_ref'])}</li>" for r in bindings if r["active"])
            files = "".join(f"<li class='mono'>{E(path)}</li>" for path in planned_files)
            context_plan_card = (
                f"<div class='card'><h2>בקשת הקונטקסט שתוכננה</h2><p>{E(context_request)}</p>"
                f"<h3>קובצי Markdown שנבחרו</h3><ul>{files or '<li class=muted>לא נבחר קובץ</li>'}</ul>"
                f"<h3>מקורות גרף שנבחרו דרך Jev</h3><ul>{sources or '<li class=muted>לא נבחר מקור גרף</li>'}</ul>"
                f"<p class='section-note'>המקורות יופיעו גם במניפסט הקונטקסט של כל ניסיון ביצוע.</p></div>")
        dependency_control = (f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                              f"<input type='hidden' name='action' value='add_task_dependency'><input type='hidden' name='task_id' value='{E(tid)}'>"
                              f"<input type='hidden' name='back' value='{E(back)}'><label class='blk'>משימה שחייבת להסתיים קודם</label>"
                              f"<select class='w' name='depends_on' required>{task_options}</select><div class='form-actions'>"
                              f"<button>הוסף תלות לתור</button></div></form>")
        context_control = (f"<div class='access-list'>{binding_rows}</div><form method='post' action='/action'>"
                           f"<input type='hidden' name='token' value='{self.token}'><input type='hidden' name='action' value='bind_task_context'>"
                           f"<input type='hidden' name='task_id' value='{E(tid)}'><input type='hidden' name='back' value='{E(back)}'>"
                           f"<label class='blk'>תן גישה למקור קיים מהגרף</label><select class='w' name='source_key' required>{context_options}</select>"
                           f"<p class='section-note'>הגישה מוסיפה מועמד בלבד. Jev עדיין חייב לבחור בו לפני שיגיע למודל.</p>"
                           f"<button>הוסף לרשימת המועמדים</button></form>"
                           f"<details class='hold'><summary>צור מקור קונטקסט חדש למשימה</summary><form method='post' action='/action'>"
                           f"<input type='hidden' name='token' value='{self.token}'><input type='hidden' name='action' value='add_context'>"
                           f"<input type='hidden' name='task_id' value='{E(tid)}'><input type='hidden' name='back' value='{E(back)}'>"
                           f"<label class='blk'>מפתח מקור</label><input type='text' name='source_key' required>"
                           f"<label class='blk'>כותרת</label><input type='text' name='title' required>"
                           f"<label class='blk'>הפניה לגרף או מקור</label><input type='text' name='origin_ref'>"
                           f"<label class='blk'>תוכן מוצע</label><textarea name='excerpt' rows='6' required></textarea>"
                           f"<button class='go'>שמור כמועמד ל־Jev</button></form></details>")
        task_prompt = (f"<div class='card command-card'><h2>בקש מהמודל לשנות את המשימה</h2>"
                       f"<p class='muted'>מתאים לשינוי מודל, הוספת תלות, שינוי גישה לקונטקסט, הוספת MCP או השלמת עבודה חסרה.</p>"
                       f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                       f"<input type='hidden' name='action' value='scoped_plan'><input type='hidden' name='scope_kind' value='task'>"
                       f"<input type='hidden' name='scope_id' value='{E(tid)}'><input type='hidden' name='back' value='{E(back)}'>"
                       f"<input type='hidden' name='prompt_mode' value='plan_build'><textarea name='prompt' required "
                       f"placeholder='תאר את השינוי הרצוי. המודל ישלים את הצעדים החסרים וישתמש בקונטקסט מינימלי שנבחר דרך Jev.'></textarea>"
                       f"<div class='form-actions'><select name='model_key'><option value=''>בחירת מודל אוטומטית</option>{self._model_options('')}</select>"
                       f"<input type='text' name='mcp_servers' placeholder='שרתי MCP, אם צריך'><button class='go'>תכנן את השינוי</button>"
                       f"</div></form></div>")
        brief = ""
        if t["brief_path"] and (self.cfg.repo / t["brief_path"]).is_file():
            brief = (self.cfg.repo / t["brief_path"]).read_text(errors="replace")
        attempts = self.db.q("SELECT * FROM task_attempts WHERE task_id=? ORDER BY id DESC", (tid,))
        arows = ""
        for a in attempts:
            tok = "/".join(str(a[k]) if a[k] is not None else "null" for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
            links = " ".join(f"<a href='/log/{a['id']}/{w}'>{w}</a>" for w in ("prompt", "stdout", "stderr", "message", "diff"))
            arows += (f"<tr><td>{a['id']}</td><td>{E(a['kind'])} #{a['attempt_no']}{f' {WEB_BADGE}' if a['web_enabled'] else ''}</td>"
                      f"<td>{E(a['provider'])}</td>"
                      f"<td class='mono'>{E(a['model'])} ({E(str(a['effort']))})</td><td>{pill(a['status'])}</td>"
                      f"<td>{E(a['failure_class'] or '')}</td><td>{local(a['started_at'])} → {local(a['ended_at']) if a['ended_at'] else '…'}</td>"
                      f"<td class='mono'>{tok}</td><td>{a['reported_cost_usd'] if a['reported_cost_usd'] is not None else 'null'}</td>"
                      f"<td>{a['pid'] or '-'}</td><td>{links}</td></tr>")
        last = attempts[0] if attempts else None
        ctx = ""
        if last and last["context_pack_id"]:
            cp = self.db.one("SELECT * FROM context_packs WHERE id=?", (last["context_pack_id"],))
            man = json.loads(cp["manifest"])
            ctx = "".join(f"<tr><td>{E(i['mode'])}</td><td>{E(i['layer'])}</td><td class='mono'>{E(i['path'])}</td>"
                          f"<td>{i['bytes']}</td><td class='muted'>{E(i['reason'])}</td></tr>" for i in man["items"])
            ctx = f"<p class='muted'>prompt {cp['total_bytes']} bytes, sha256 {cp['prompt_sha256'][:16]}</p><table>{ctx}</table>"
        tests = "".join(f"<tr><td>{E(r['name'])}</td><td>{E(r['kind'])}</td><td>{'pass' if r['passed'] else '<b class=s-FAILED>FAIL</b>'}</td>"
                        f"<td>{r['exit_code'] if r['exit_code'] is not None else ''}</td><td>{r['duration_s'] or ''}</td>"
                        f"<td><details><summary>output</summary><pre>{E(r['output_tail'] or '')}</pre></details></td></tr>"
                        for r in self.db.q("SELECT * FROM test_results WHERE task_id=? ORDER BY id DESC LIMIT 30", (tid,)))
        diff, files = "", []
        if t["worktree"] and Path(t["worktree"]).exists() and last and last["base_commit"]:
            try:
                files = self.wt.changed_files(Path(t["worktree"]), last["base_commit"])
                diff = self.wt.diff(Path(t["worktree"]), last["base_commit"], 120000)
            except Exception as e:
                diff = f"(diff unavailable: {e})"
        arts = "".join(self._artifact_html(a) for a in self.db.q("SELECT * FROM artifacts WHERE task_id=? ORDER BY id DESC", (tid,)))
        handoff = json.loads(last["handoff"]) if last and last["handoff"] else None
        opts = "".join(f"<option value='{E(k)}'>{E(k)} — {E(m['provider'])}/{E(m['model'])}</option>"
                       for k, m in self.cfg.data["models"].items())
        change = (f'<form method="post" action="/action"><input type="hidden" name="token" value="{self.token}">'
                  f'<input type="hidden" name="action" value="set_provider"><input type="hidden" name="task_id" value="{E(tid)}">'
                  f'<input type="hidden" name="back" value="{E(back)}"><select name="model_key">{opts}</select>'
                  f'<button>שמור מודל למשימה</button></form>')
        actions = " ".join([
            f"<a class='btnlink' href='/review?id={urllib.parse.quote(tid)}'>{E(self.t('View what was created'))}</a>",
            self._form("expedite", "דחוף עכשיו", "go", back=back, task_id=tid) if t["state"] == "READY" else "",
            self._form("retry", "נסה שוב", back=back, task_id=tid),
            self._form("skip", "בטל משימה", back=back, task_id=tid, confirm="לבטל את המשימה? המשימות התלויות בה יישארו חסומות."),
            self._form("recheck", "הרץ בדיקות קבלה מחדש", back=back, task_id=tid), change])
        pend = self.db.q("SELECT * FROM approvals WHERE task_id=? AND status='pending'", (tid,))
        pend_html = "".join(f"<p>{pill('WAITING_APPROVAL')} #{a['id']} {E(a['kind'])} {E(a['subject'] or '')}: {E(a['reason'] or '')} "
                            f"{self._form('approve', 'Approve', 'go', back=back, approval_id=a['id'])} "
                            f"{self._form('reject', 'Reject', back=back, approval_id=a['id'])}</p>" for a in pend)
        chain_html = self._repair_chain_html(t)
        subtask_lineage = self._subtask_lineage_html(tid)
        subtask_control = (f"<h2>פירוק לתת־משימות</h2><div class='card'><p class='muted'>כל תת־משימה מקבלת "
                           f"חוזה עצמאי של מודל, קונטקסט וכלים, ונשמרת בלי להפוך ל־Deliver.</p>"
                           f"{subtask_lineage}<details class='hold'><summary>הוסף תת־משימה למשימה הזו</summary>"
                           f"{self._subtask_form(tid, back)}</details></div>")
        graph_access = (f"<h2>גישה לגרף ה־RAG של ה־Deliver</h2><div class='card'>"
                        f"{self._graph_access_form(tid, back)}</div>" if
                        self.db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (tid,)) else "")
        body = (f"<p><a href='/'>→ חזרה לתור המשימות</a></p><section class='control-hero'><div class='eyebrow'>"
                f"{'תיקון מערכת ניהול המשימות' if is_system_task else 'ניהול משימה בתור'}</div>"
                f"<h1 class='mono'>{E(tid)}</h1><p>{pill(t['state'])}{web_badge(task_extra)} · {E(t['state_reason'] or '')}</p>"
                f"<div class='card'><h2>מה המשימה עושה</h2><p>{E(task_he(self.cfg, t))}</p></div>"
                f"<p class='muted'>חבילה {E(t['packet'])} · אחראי {E(t['owner'])} · תחום {E(t['domain'] or '')} · "
                f"מצב עבודה {E(t['mode'])} · פרופיל {E(t['model_profile'])} · גל {t['wave']} · "
                f"ניסיונות {t['attempts_count']} (נכשלו {t['failed_attempts']}) · ענף <span class='mono'>{E(t['branch'] or '-')}</span></p>"
                f"{pend_html}<div class='form-actions'>{actions}</div></section>{system_card}{context_plan_card}{task_prompt}{chain_html}"
                f"<div class='control-grid'><div><h2>תלויות המשימה</h2><div class='card'><ul>{dep_html}</ul>{dependency_control}</div></div>"
                f"<div><h2>גישה לקונטקסט דרך Jev</h2><div class='card'>{context_control}</div></div></div>"
                f"{subtask_control}{graph_access}"
                f"<div class='grid2'><div><h2>תחום כתיבה</h2><div class='card mono'>{'<br>'.join(E(s) for s in json.loads(t['write_scope']))}</div></div>"
                f"<div><h2>העברת עבודה</h2><div class='card'><pre>{E(json.dumps(handoff, ensure_ascii=False, indent=1)) if handoff else 'אין'}</pre></div></div></div>"
                f"<h2>ניסיונות ביצוע</h2><div class='card'><table><tr><th>מזהה</th><th>סוג</th><th>ספק</th><th>מודל</th><th>מצב</th>"
                f"<th>כשל</th><th>זמן</th><th>טוקנים נכנסו/מטמון/יצאו</th><th>עלות מדווחת</th><th>תהליך</th><th>לוגים</th></tr>{arows}</table></div>"
                f"<h2>תוצרים</h2><div class='card'>{arts or '<span class=muted>אין עדיין תוצרים</span>'}</div>"
                f"<h2>בדיקות</h2><div class='card'><table>{tests or '<tr><td class=muted>עדיין לא הורצו בדיקות</td></tr>'}</table></div>"
                f"<h2>קבצים שהשתנו ({len(files)})</h2><div class='card mono'>{'<br>'.join(E(f) for f in files) or '-'}</div>"
                f"<details class='hold'><summary>הבדלים בקוד</summary><div class='card'><pre>{E(diff)}</pre></div></details>"
                f"<h2>הקונטקסט שנשלח בניסיון האחרון</h2><div class='card'>{ctx or '<span class=muted>עדיין לא נבנה קונטקסט</span>'}</div>"
                f"<details class='hold'><summary>תדריך המשימה</summary><div class='card'><pre>{E(brief)}</pre></div></details>")
        return self._layout(tid, body, msg)

    def _attempt_line(self, a) -> str:
        tok = "/".join(str(a[k]) if a[k] is not None else "null" for k in ("input_tokens", "cached_input_tokens",
                                                                          "output_tokens"))
        return (f"{E(a['provider'])} <span class='mono'>{E(a['model'])}</span> {pill(a['status'])} "
                f"{E(a['failure_class'] or '')} · טוקנים נכנסו/מטמון/יצאו {tok}"
                + (f" · עלות מדווחת ${a['reported_cost_usd']:.2f}" if a["reported_cost_usd"] is not None else ""))

    def _checks_line(self, rows) -> str:
        if not rows:
            return "<span class='muted'>לא הורצה בדיקת קבלה</span>"
        return " ".join(("✓ " if r["passed"] else "<b class='s-FAILED'>✗ ") + E(r["name"]) + ("" if r["passed"] else "</b>")
                        for r in rows)

    def _repair_chain_html(self, t) -> str:
        if t["kind"] == "repair":
            ctx = json.loads(t["repair_context"] or "{}")
            parent = self.db.task(t["parent_task_id"])
            viol = "".join(f"<li class='mono'>{E(p)}</li>" for p in ctx.get("violating_paths", []))
            return (f"<h2>תיקון של "
                    f"<a href='/task?id={urllib.parse.quote(t['parent_task_id'])}'>{E(t['parent_task_id'])}</a> "
                    f"{pill(parent['state'])}</h2><div class='card'>תיקון #{t['repair_no']} · סוג כשל "
                    f"<b>{E(t['failure_class'] or '')}</b> · פרופיל {E(t['model_profile'])}<br>{E(t['failure_summary'] or '')}"
                    f"{'<ul>' + viol + '</ul>' if viol else ''}</div>")
        reps = self.db.q("SELECT * FROM tasks WHERE parent_task_id=? AND kind='repair' ORDER BY repair_no", (t["task_id"],))
        if not reps and not t["repairs_count"]:
            return ""
        from .repair import budget
        steps = []
        for a in self.db.q("SELECT * FROM task_attempts WHERE task_id=? AND kind='execute' ORDER BY id", (t["task_id"],)):
            checks = self.db.q("SELECT name, passed FROM test_results WHERE attempt_id=? AND via_task_id IS NULL ORDER BY id",
                               (a["id"],))
            steps.append(f"<div class='step'><b>ביצוע מקורי "
                         f"#{a['attempt_no']}</b> — {self._attempt_line(a)}<br>"
                         f"קבלה: {self._checks_line(checks)}</div>")
        for r in reps:
            ra = self.db.q("SELECT * FROM task_attempts WHERE task_id=? ORDER BY id", (r["task_id"],))
            runs = "<br>".join(self._attempt_line(a) for a in ra) or "<span class='muted'>not started</span>"
            checks = self.db.q("SELECT name, passed FROM test_results WHERE via_task_id=? ORDER BY id", (r["task_id"],))
            steps.append(f"<div class='step'>↓<br><b><a href='/task?id={urllib.parse.quote(r['task_id'])}'>"
                         f"תיקון #{r['repair_no']}</a></b> {pill(r['state'])} — "
                         f"סיבה: {E(r['failure_class'] or '')}: "
                         f"{E((r['failure_summary'] or '')[:200])}<br>{runs}<br>"
                         f"קבלה אחרי התיקון: {self._checks_line(checks)}</div>")
        return (f"<h2>שרשרת תיקונים</h2><div class='card'>תיקונים {t['repairs_count']} "
                f"מתוך {budget(self.cfg, t)} · סוג כשל אחרון "
                f"<b>{E(t['failure_class'] or '-')}</b> · הורה {pill(t['state'])}"
                f"<div class='chain'>{''.join(steps)}</div></div>")

    # ------------------------------------------------------------------ manual tasks & planner
    def _mcp_cached(self) -> dict:
        now = dt.datetime.now().timestamp()
        if not hasattr(self, "_mcp_cache") or now - self._mcp_cache[0] > 60:
            from .mcp import available
            try:
                self._mcp_cache = (now, available(self.cfg))
            except Exception:
                self._mcp_cache = (now, {})
        return self._mcp_cache[1]

    def _context_index(self) -> list[str]:
        out = []
        for root, pat in (("context/game", "**/*.md"), ("docs/game", "*.md")):
            base = self.cfg.repo / root
            if base.is_dir():
                out += sorted(str(p.relative_to(self.cfg.repo)) for p in base.glob(pat) if p.is_file())
        return out

    def _model_options(self, selected: str | None, blank: str | None = None) -> str:
        opts = f"<option value=''>{E(self.t(blank))}</option>" if blank else ""
        for k, m in self.cfg.data["models"].items():
            sel = " selected" if k == selected else ""
            opts += f"<option value='{E(k)}'{sel}>{E(k)} — {E(m['provider'])}/{E(m['model'])} ({E(m.get('tier', ''))})</option>"
        return opts

    def page_new(self, msg: str | None, pre: dict | None = None, multi: dict | None = None) -> str:
        pre, multi = pre or {}, multi or {}
        sel = lambda k, v: " checked" if v in multi.get(k, []) else ""
        try:
            reg = json.loads((self.cfg.repo / self.cfg.data["plan"]["registry"]).read_text())
            owners = sorted((reg.get("owner_roles") or {}).items())
        except (OSError, ValueError):
            owners = []
        owner_opts = f"<option value=''>{E(self.t('(new owner for this task)'))}</option>" + "".join(
            f"<option value='{E(o)}'{' selected' if o == pre.get('owner') else ''}>{E(o)} ({E(v.get('domain') or '')})</option>"
            for o, v in owners)
        deps = "".join(
            f"<label><input type='checkbox' name='deps' value='{E(r['task_id'])}'{sel('deps', r['task_id'])}> "
            f"<span class='mono'>{E(r['task_id'])}</span> {pill(r['state'])}</label>"
            for r in self.db.q("SELECT task_id, state FROM tasks WHERE kind='task' ORDER BY wave, task_id"))
        ctx = "".join(f"<label><input type='checkbox' name='ctx' value='{E(p)}'{sel('ctx', p)}> "
                      f"<span class='mono'>{E(p)}</span></label>" for p in self._context_index())
        mcps = ""
        for prov, servers in self._mcp_cached().items():
            items = "".join(f"<label><input type='checkbox' name='mcp' value='{E(prov)}:{E(n)}'{sel('mcp', prov + ':' + n)}> "
                            f"<span class='mono'>{E(n)}</span>{' <span class=warn>(' + E(self.t('writes')) + ')</span>' if d.get('writes') else ''}</label>"
                            for n, d in sorted(servers.items()))
            mcps += f"<div><b>{E(prov)}</b>{items or '<div class=muted>' + E(self.t('no servers configured')) + '</div>'}</div>"
        v = lambda k: E(pre.get(k, ""))
        auto_all = self.db.get_flag("review_auto_approve_all") == "1"
        auto_panel = (f"<section class='card' style='border-color:{'#67d9bf' if auto_all else '#ffd85a'}'>"
                      f"<h2>מצב אישור אוטומטי לכל המשימות</h2>"
                      f"<p><b>{'פעיל' if auto_all else 'כבוי'}</b> — כשהמצב פעיל, הצעות תקינות של המתכנן יוצרות משימות "
                      f"אוטומטית, ומשימות עוברות אחרי שהבדיקות עברו. כשל בדיקה עדיין עוצר את המשימה. כשהמצב כבוי, "
                      f"המתכנן עוצר ומבקש את אישורך לפני יצירת המשימות.</p>"
                      f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                      f"<input type='hidden' name='action' value='set_auto_approve_all'>"
                      f"<input type='hidden' name='enabled' value='{'0' if auto_all else '1'}'>"
                      f"<input type='hidden' name='back' value='/new'>"
                      f"<button class='big {'bad' if auto_all else 'go'}'>{'כבה מצב גלובלי' if auto_all else 'הפעל אישור אוטומטי להכול'}</button>"
                      f"</form></section>")
        planner_policy = self.graph_rag.access("planner", planner=True)
        role_guide = (
            "<section><h1>יצירת משימת ביצוע</h1><p class='muted'>המסך הזה מיועד לעובד אחד שמבצע עבודה מוגדרת. "
            "לבקשה רחבה שצריך לפרק, משתמשים במתכנן המערכת שבראש המסך.</p>"
            "<div class='role-guide'><article class='role-card'><h3>1. מתכנן המערכת</h3>"
            "<p><strong>מקבל יעד רחב.</strong> הוא מציע משימות, סדר, תלויות, מודלים וכלים. "
            "הוא אינו משנה קוד בעצמו; ההצעה הופכת למשימות רק לאחר אישור או מדיניות אישור אוטומטי.</p></article>"
            "<article class='role-card context'><h3>2. מתכנן הקונטקסט</h3>"
            "<p><strong>מקבל בקשת ידע למשימה הזאת בלבד.</strong> הוא מאתר מקורות ב־Neo4j וב־Markdown. "
            "מותר לו לבחור מקורות בלבד; הוראות העובד, המודל, הכלים, התלויות והרשאות הכתיבה נשארים נעולים.</p></article>"
            "<article class='role-card worker'><h3>3. העובד</h3>"
            "<p><strong>מבצע משימה אחת.</strong> הוא מקבל את ההוראות שלמטה ואת הקונטקסט ש־Jev אישר, "
            "ועובד רק עם המודל, הכלים ותחום הכתיבה שהוגדרו לו.</p></article></div></section>")
        access_explainer = (
            "<details class='hold' style='margin-top:12px'><summary>מה משתנה כשנותנים למתכנן יותר גישה?</summary>"
            "<div class='permission-table'><div class='permission-level'><b>ללא גישה</b><small>לא מתבצעת שאילתת Graph RAG.</small></div>"
            "<div class='permission-level'><b>גישה מוגבלת</b><small>חיפוש וקטורי רק בתחום שהוגדר ובמגבלת גודל.</small></div>"
            "<div class='permission-level'><b>גישה מלאה</b><small>חיפוש וקטורי וגם Cypher בכל הגרף, עדיין בתוך מגבלות.</small></div></div>"
            f"<ul class='boundary-list'><li>למתכנן הקונטקסט יש כרגע גישת חיפוש מלאה, עד {int(planner_policy['max_chunks'])} מקטעים "
            f"ו־{int(planner_policy['max_chars']):,} תווים לפני סינון.</li>"
            "<li>יותר גישה מגדילה רק את מאגר המועמדים. Jev מחליט מה נכנס בפועל לפרומפט.</li>"
            "<li>החלפת מודל משנה יכולת ועלות, לא הרשאות. אישור אוטומטי משנה את שלב האישור, לא את הגישה לגרף.</li>"
            "<li>גישה לגרף לעולם אינה מעניקה סודות, shell או הרשאת כתיבה.</li></ul></details>")
        body = (f"{role_guide}{auto_panel}<form method='post' action='/action'>"
                f"<input type='hidden' name='token' value='{self.token}'><input type='hidden' name='action' value='add_task'>"
                f"<section class='card' style='border-color:#5b91d1'><h2>יעד המשימה</h2>"
                f"<select class='w' name='task_target'><option value='project'{' selected' if pre.get('task_target', 'project') == 'project' else ''}>פרויקט המשחק והתוכן</option>"
                f"<option value='task_manager'{' selected' if pre.get('task_target') == 'task_manager' else ''}>תיקון מערכת ניהול המשימות</option></select>"
                f"<p class='muted'><b>תיקון מערכת</b> מצלם את מנהל המשימות הפעיל לעותק מבודד, מגביל כתיבה ל־"
                f"<span class='mono'>tools/build_manager/</span>, מריץ קומפילציה, את כל בדיקות המנהל ובדיקת עלייה של ה־CLI. "
                f"רק אחרי הצלחה הוא מוודא שהמקור לא השתנה, ממתין ששאר העובדים יסיימו, מפעיל עם גיבוי ומבצע restart חינני.</p></section>"
                f"<label class='blk'>{E(self.t('Title'))}</label><input type='text' name='title' value='{v('title')}' required>"
                f"<label class='blk'>מה המשימה עושה — הסבר ברור בעברית</label>"
                f"<textarea name='description_he' rows='3' required placeholder='לדוגמה: בונה מערכת מזג אוויר שמייצגת הצטברות שלג והשפעתה על הקרקע.'>{v('description_he')}</textarea>"
                f"<label class='blk'>{E(self.t('Short id (optional)'))}</label><input type='text' name='name' value='{v('name')}' dir='ltr'>"
                f"<label class='blk'>הוראות ביצוע לעובד — מה עליו להשלים במשימה הזאת?</label>"
                f"<p class='muted'>זהו חוזה הביצוע של עובד יחיד: תאר תוצאה רצויה, מגבלות וקריטריונים. "
                f"אם עדיין צריך להחליט אילו משימות נדרשות, השתמש במתכנן המערכת למעלה.</p>"
                f"<textarea name='instructions' rows='7' placeholder='לדוגמה: הוסף למנוע מזג האוויר הצטברות שלג לפי הטמפרטורה והמשקעים, ועדכן את בדיקות היחידה.'>{v('instructions')}</textarea>"
                f"<label class='blk'>{E(self.t('Model'))}</label><select class='w' name='model_key'>"
                f"{self._model_options(pre.get('model_key') or '', 'automatic: best fit')}</select>"
                f"<label><input type='checkbox' name='fallback' value='1'{'' if pre and not pre.get('fallback') else ' checked'}> "
                f"{E(self.t('allow fallback to the routing chain if this model is unavailable'))}</label>"
                f"<label class='blk'>{E(self.t('Owner'))}</label><select class='w' name='owner'>{owner_opts}</select>"
                f"<label class='blk'>{E(self.t('Dependencies'))}</label><div class='picklist'>{deps}</div>"
                f"<label class='blk'>{E(self.t('Write scope (one path per line; directories end with /)'))}</label>"
                f"<textarea name='write_scope' rows='3' dir='ltr'>{v('write_scope')}</textarea>"
                f"<label><input type='checkbox' name='read_only' value='1'{' checked' if pre.get('read_only') else ''}> "
                f"{E(self.t('read-only (report only; the manager files it)'))}</label>"
                f"<label><input type='checkbox' name='allow_web' value='1'{' checked' if pre.get('allow_web') else ''}> "
                f"מחקר עם גישה לרשת</label><div class='muted'>{E(WEB_FORM_NOTE)}</div>"
                f"<label class='blk'>{E(self.t('Context files (inlined in the prompt)'))}</label><div class='picklist'>{ctx}</div>"
                f"<section class='card' style='margin-top:18px;border-color:#ffd85a'><h2>בקשת קונטקסט בשפה חופשית</h2>"
                f"<p class='muted'>כתוב איזה ידע המשימה צריכה. מודל התכנון יחפש ב־Neo4j Graph RAG ובקובצי Markdown, "
                f"Jev יבחר את המועמדים המינימליים, ורק המקורות שנבחרו יצורפו למשימה עם מקור מלא.</p>"
                f"<textarea name='context_request' rows='5' placeholder='לדוגמה: תן למשימה את מצב מזג האוויר, השלג, הקרקע והיחידות באזור ובתאריך הרלוונטיים בלבד.'>{v('context_request')}</textarea>"
                f"<label class='blk'>מודל תכנון הקונטקסט</label><select class='w' name='context_planner_model_key'>"
                f"{self._model_options(pre.get('context_planner_model_key'), 'בחירה אוטומטית לפי נתיב PLAN')}</select>"
                f"{access_explainer}</section>"
                f"<label class='blk'>{E(self.t('More context paths (one per line)'))}</label>"
                f"<textarea name='ctx_extra' rows='2' dir='ltr'>{v('ctx_extra')}</textarea>"
                f"<label class='blk'>{E(self.t('Reference paths (listed, not inlined)'))}</label>"
                f"<textarea name='refs' rows='2' dir='ltr'>{v('refs')}</textarea>"
                f"<label class='blk'>{E(self.t('MCP servers'))}</label><div class='muted'>"
                f"{E(self.t(MCP_NOTE))}</div>"
                f"<div class='picklist'>{mcps}</div>"
                f"<label class='blk'>כלים ייעודיים למשימה, מופרדים בפסיק</label>"
                f"<input type='text' name='tool_names' value='{v('tool_names')}' dir='ltr' placeholder='Read, Grep, Bash(pytest *)'>"
                f"<label class='blk'>{E(self.t('Acceptance commands (one shell command per line)'))}</label>"
                f"<textarea name='checks' rows='3' dir='ltr'>{v('checks')}</textarea><div class='muted'>"
                f"<label><input type='checkbox' name='auto_approve' value='1'{' checked' if pre.get('auto_approve') else ''}> "
                f"אשר את המשימה הזו אוטומטית אחרי שכל הבדיקות הזמינות עברו</label>"
                f"<div class='muted'>בלי פקודת קבלה אפשר לבחור אישור אוטומטי למשימה, או להפעיל את המצב הגלובלי למעלה. "
                f"בדיקות בעלות, diff וסודות תמיד נשארות פעילות.</div></div>"
                f"<p><button class='big go'>{E(self.t('Create task'))}</button></p></form>")
        return self._layout(self.t("New task"), body, msg)

    def add_task_post(self, f: dict, multi: dict) -> tuple[bool, str, str | None]:
        lines = lambda k: [x.strip() for x in (f.get(k) or "").splitlines() if x.strip()]
        model = f.get("model_key") or ""
        prov = self.cfg.model(model).provider if model in self.cfg.data["models"] else None
        picked = [x.split(":", 1) for x in multi.get("mcp", []) if ":" in x]
        spec = {"key": f.get("name") or f.get("title"), "title": f.get("title", ""),
                "description_he": f.get("description_he", ""),
                "instructions": f.get("instructions", ""), "model_key": model, "fallback": f.get("fallback") == "1",
                "task_target": f.get("task_target") or "project",
                "owner": f.get("owner", ""), "depends_on": multi.get("deps", []), "write_scope": lines("write_scope"),
                "read_only": f.get("read_only") == "1", "context_files": multi.get("ctx", []) + lines("ctx_extra"),
                "reference_files": lines("refs"), "mcp_servers": [n for p, n in picked if p == prov],
                "tool_names": [x.strip() for x in (f.get("tool_names") or "").split(",") if x.strip()],
                "acceptance_commands": lines("checks"), "auto_approve": f.get("auto_approve") == "1",
                "allow_web": f.get("allow_web") == "1",
                "context_request": (f.get("context_request") or "").strip()}
        other = [n for p, n in picked if p != prov]
        try:
            if spec["context_request"]:
                tid = mn.create_context_plan(
                    self.db, self.cfg, spec, spec["context_request"],
                    f.get("context_planner_model_key") or None, self._mcp_cached())
                ids = [tid]
            else:
                ids = mn.create_tasks(self.db, self.cfg, [spec], "manual", self._mcp_cached())
        except mn.ManualError as e:
            return False, str(e), self.page_new(f"error: {e}", f, multi)
        if other:
            self.db.event("MCP_IGNORED", task_id=ids[0], servers=other, reason=f"not {prov} servers")
        self.wake()
        return True, ids[0], None

    def page_battle(self, msg: str | None) -> str:
        """'בקשת קרב': one form creates the whole battle-builder task chain (same action as the live app)."""
        data = app_data.battle_request_options(self)
        field = lambda name, label, extra="", tag="input": (
            f"<label class='blk'>{E(label)}</label>" + (
                f"<textarea name='{name}' rows='4' {extra}></textarea>" if tag == "textarea"
                else f"<input type='text' name='{name}' {extra}>"))
        stages = "".join(
            f"<tr><td class='mono'>{E(s['stage'])}</td><td>{E(s['title'])}</td><td class='mono'>{E(s['deliver'])}</td>"
            f"<td class='mono'>{E(s['model_key'] or 'auto')}</td><td>{'כן' if s['allow_web'] else 'לא'}</td>"
            f"<td class='mono'>{E(', '.join(s['depends_on']) or '-')}</td></tr>" for s in data["stages"])
        chains = "".join(
            f"<div class='card'><b class='mono'>{E(c['battle_key'])}</b> {E(c['title'])}<div>" + " ".join(
                f"<a href='/task?id={urllib.parse.quote(t['task_id'])}'>{E(t['stage'])}</a> {pill(t['state'])}"
                for t in c["tasks"]) + "</div></div>" for c in data["chains"]) or "<div class='muted'>עוד לא נוצרו שרשראות קרב.</div>"
        template_note = (f"<div class='banner'>{E(data['error'])}</div>" if data.get("error") else
                         f"<table><tr><th>שלב</th><th>משימה</th><th>מודול</th><th>מודל</th><th>גישה לרשת</th><th>אחרי</th></tr>"
                         f"{stages}</table>")
        body = (f"<h1>בקשת קרב — שרשרת הבנייה המלאה בפעולה אחת</h1><div class='section-note'>"
                f"הקלט הוא כותרת, תאריך (או טווח) ואופציונלית מקום, bbox והערות. הפעולה יוצרת את כל השרשרת: תיק ראיות ← מחקר מפות "
                f"(חובה) ← מחקר LLM ברשת עם חיפוש מונחה פערים ← שחזור ← חבילת אפיזודה. לכל משימה תחום כתיבה תחת "
                f"<span class='mono'>game/episodes/&lt;battle_key&gt;/</span> בלבד, מודל לפי התאמה, ובדיקות קבלה על הקבצים שנוצרו. "
                f"רק משימת המחקר מקבלת גישה לרשת. בקשה כפולה לשרשרת פעילה של אותו battle_key נדחית. "
                f"התבניות נערכות בקובץ <span class='mono'>tools/build_manager/systems/battle_request_templates.toml</span>.</div>"
                f"<form method='post' action='/action'><input type='hidden' name='token' value='{self.token}'>"
                f"<input type='hidden' name='action' value='battle_request'><input type='hidden' name='back' value='/battle'>"
                + field("title", "שם הקרב", "required placeholder='Brécourt Manor assault'")
                + field("battle_key", "battle_key (slug; נוצר מהכותרת אם ריק)", "dir='ltr' placeholder='brecourt-manor-assault'")
                + field("date", "תאריך או טווח (YYYY-MM-DD או YYYY-MM-DD..YYYY-MM-DD)", "required dir='ltr' placeholder='1944-06-06'")
                + field("bbox", "bbox (מערב,דרום,מזרח,צפון; לא חובה)", "dir='ltr' placeholder='-1.3,49.3,-1.1,49.5'")
                + field("place", "מקום (לא חובה)")
                + field("notes", "הערות לחוקרים (לא חובה)", tag="textarea")
                + f"<p><button class='big go'>צור שרשרת קרב</button></p></form>"
                f"<h2>השרשרת שתיווצר</h2>{template_note}<h2>שרשראות שנוצרו</h2>{chains}")
        return self._layout("בקשת קרב", body, msg)

    def page_plan(self, msg: str | None) -> str:
        form = (f"<h1>מתכנן המערכת — בקשה רחבה למשימות</h1><div class='section-note'>"
                f"כאן מתארים יעד שעדיין צריך לפרק. המתכנן מחזיר הצעה של משימות, תלויות, מודלים וכלים; "
                f"עובדי המשימות יבצעו אותה רק אחרי אישור. לביצוע ישיר ומוגדר של משימה אחת משתמשים ב־<a href='/new'>משימת ביצוע חדשה</a>."
                f"</div><form class='prompt-grid' method='post' action='/action' enctype='multipart/form-data'><input type='hidden' name='token' value='{self.token}'>"
                f"<input type='hidden' name='action' value='plan'><input type='hidden' name='back' value='/plan'>"
                f"<label class='blk'>מה התוצאה הרחבה שצריך לתכנן?</label><textarea class='planner-main-prompt' name='prompt' rows='8' required "
                f"placeholder='לדוגמה: תכנן את כל רכיבי הלגו הדרושים למערכת מזג אוויר היסטורית באפיזודה.'></textarea>"
                f"{self._planner_upload_box('plan-page')}"
                f"<label class='blk'>{E(self.t('Planner model'))}</label><select class='w' name='model_key'>"
                f"{self._model_options(None, 'default (strong planner in routing PLAN)')}</select>"
                f"<p><button class='big go'>{E(self.t('Send to planner'))}</button></p></form>")
        blocks = []
        for pt in self.db.q("SELECT * FROM tasks WHERE kind='plan' ORDER BY created_at DESC LIMIT 20"):
            extra = json.loads(pt["extra"] or "{}")
            attached = [dict(row) for row in self.db.q(
                "SELECT original_name,media_type,size_bytes,selected_at FROM planner_attachments "
                "WHERE plan_task_id=? ORDER BY id", (pt["task_id"],))]
            attachment_html = ""
            if attached:
                attachment_html = ("<div class='attachment-history'><b>קבצים מצורפים:</b>" + "".join(
                    f"<span class='upload-chip{' selected' if item['selected_at'] else ''}' "
                    f"title='{'נבחר על ידי Jev' if item['selected_at'] else 'לא נבחר עדיין'}'>"
                    f"{E(item['original_name'])} · {item['size_bytes'] / 1024:.1f}KB"
                    f"{' · נבחר' if item['selected_at'] else ''}</span>" for item in attached) + "</div>")
            block = (f"<div class='card'><b class='mono'>{E(pt['task_id'])}</b> {pill(pt['state'])} "
                     f"<span class='muted'>{E(pt['state_reason'] or '')}</span><pre>{E(extra.get('prompt', ''))}</pre>"
                     f"{attachment_html}")
            for p in self.db.q("SELECT * FROM plan_proposals WHERE plan_task_id=? ORDER BY id DESC", (pt["task_id"],)):
                prop = json.loads(p["proposal"])
                rows = "".join(
                    f"<tr><td class='mono'>{E(t.get('key', ''))}</td><td>{E(t.get('title', ''))}<div class='muted'>"
                    f"{E((t.get('instructions') or '')[:300])}</div></td><td class='mono'>{E(t.get('model_key', ''))}</td>"
                    f"<td class='mono'>{E(', '.join(t.get('depends_on') or []))}</td>"
                    f"<td class='mono'>{E(', '.join(t.get('write_scope') or []))}{' (read-only)' if t.get('read_only') else ''}</td>"
                    f"<td class='mono'>{E(', '.join(t.get('context_files') or []))}"
                    f"<div class='muted'>{E(', '.join(t.get('context_source_ids') or []))}</div></td>"
                    f"<td class='mono'>{E(', '.join(t.get('mcp_servers') or []))}</td>"
                    f"<td class='mono'>{E(' | '.join(t.get('acceptance_commands') or []))}</td></tr>"
                    for t in prop.get("tasks") or [])
                val = "".join(f"<li class='{'err' if m['level'] == 'error' else 'warn'}'>[{E(m['key'])}] {E(m['message'])}</li>"
                              for m in json.loads(p["validation"]))
                ap = self.db.one("SELECT id FROM approvals WHERE kind='plan_proposal' AND subject=? AND status='pending'",
                                 (str(p["id"]),))
                buttons = (self._form("approve", "Approve", "go", back="/plan", approval_id=ap["id"]) + " " +
                           self._form("reject", "Reject", back="/plan", approval_id=ap["id"])) if ap else ""
                created = json.loads(p["created_task_ids"])
                block += (f"<h2>#{p['id']} · {E(self.t('Proposed tasks'))} {pill(p['status'].upper())}</h2>"
                          f"<p>{E(prop.get('summary', ''))}</p>"
                          + (f"<ul>{''.join('<li>' + E(q) + '</li>' for q in prop.get('questions') or [])}</ul>" if prop.get('questions') else "")
                          + f"<table><tr><th>key</th><th>title</th><th>model</th><th>deps</th><th>scope</th><th>context</th>"
                            f"<th>MCP servers</th><th>checks</th></tr>{rows}</table>"
                          + (f"<ul>{val}</ul>" if val else "") + f"<p>{buttons}</p>"
                          + (f"<p>{E(self.t('created'))}: " + ", ".join(
                              f"<a class='mono' href='/task?id={urllib.parse.quote(i)}'>{E(i)}</a>" for i in created) + "</p>"
                             if created else ""))
            blocks.append(block + "</div>")
        body = form + f"<h2>{E(self.t('Plan requests'))}</h2>" + ("".join(blocks) or f"<p class='muted'>{E(self.t('none yet'))}</p>")
        return self._layout(self.t("Prompt → tasks"), body, msg)

    # ------------------------------------------------------------------ review what was created
    VISUAL = {".png": "img", ".jpg": "img", ".jpeg": "img", ".gif": "img", ".webp": "img", ".svg": "img",
              ".mp4": "video", ".webm": "video", ".mov": "video", ".html": "html", ".htm": "html",
              ".glb": "model", ".gltf": "model", ".tscn": "scene"}

    def _change(self, tid: str):
        """(task row, worktree, base, head, changed files) for the task's current candidate."""
        t = self.db.task(tid)
        if not t or not t["worktree"] or not Path(t["worktree"]).exists():
            return t, None, None, None, []
        a = self.db.one("SELECT base_commit FROM task_attempts WHERE task_id=? AND kind='execute' AND base_commit "
                        "IS NOT NULL ORDER BY id DESC LIMIT 1", (tid,))
        if not a:
            return t, None, None, None, []
        wt = Path(t["worktree"])
        try:
            return t, wt, a["base_commit"], self.wt.head(wt), self.wt.changed_files(wt, a["base_commit"])
        except Exception:
            return t, wt, a["base_commit"], None, []

    def serve_worktree_file(self, h, tid: str, rel: str, raw: bool):
        t, wt, base, head, files = self._change(tid)
        if not wt or rel not in files:            # only files that are part of this task's change
            return h._send(404, "not part of this task's change", "text/plain")
        p = (wt / rel).resolve()
        if not str(p).startswith(str(wt.resolve())) or not p.is_file():
            return h._send(404, "not found", "text/plain")
        if raw:
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return h._send(200, p.read_bytes(), ctype, sandbox=True)
        text = redact(p.read_text(errors="replace")) if p.stat().st_size < 2_000_000 else "(file too large to show)"
        body = (f"<p><a href='/review?id={urllib.parse.quote(tid)}'>← {E(self.t('View what was created'))}</a></p>"
                f"<h1 class='mono'>{E(rel)}</h1><p class='muted mono'>{E(tid)} @ {E((head or '')[:12])} · "
                f"<a href='/wtfile?task={urllib.parse.quote(tid)}&path={urllib.parse.quote(rel)}&raw=1'>raw</a></p>"
                f"<div class='card'><pre>{E(text)}</pre></div>")
        return h._send(200, self._layout(rel, body, None))

    @staticmethod
    def _diff_html(diff: str) -> str:
        out, files = [], []
        cur = []
        for ln in diff.splitlines():
            if ln.startswith("diff --git"):
                if cur:
                    files.append(cur)
                cur = [ln]
            else:
                cur.append(ln)
        if cur:
            files.append(cur)
        for block in files:
            name = block[0].split(" b/", 1)[-1] if block[0].startswith("diff --git") else "summary"
            lines = []
            for ln in block:
                cls = ("add" if ln.startswith("+") and not ln.startswith("+++") else
                       "del" if ln.startswith("-") and not ln.startswith("---") else
                       "hunk" if ln.startswith("@@") else "meta" if ln.startswith(("diff", "index", "+++", "---")) else "")
                lines.append(f"<span class='{cls}'>{E(ln)}</span>" if cls else E(ln))
            adds = sum(1 for ln in block if ln.startswith("+") and not ln.startswith("+++"))
            dels = sum(1 for ln in block if ln.startswith("-") and not ln.startswith("---"))
            out.append(f"<details class='hold'><summary class='mono'>{E(name)} <span class='add'>+{adds}</span> "
                       f"<span class='del'>-{dels}</span></summary><pre class='diff'>{chr(10).join(lines)}</pre></details>")
        return "".join(out)

    def page_review(self, tid: str, msg: str | None) -> str:
        t, wt, base, head, files = self._change(tid)
        if not t:
            return self._layout("not found", f"<p>unknown task {E(tid)}</p>", msg)
        q = urllib.parse.quote
        back = f"/review?id={q(tid)}"
        a = self.db.one("SELECT * FROM task_attempts WHERE task_id=? AND kind='execute' ORDER BY id DESC LIMIT 1", (tid,))
        h = json.loads(a["handoff"]) if a and a["handoff"] else {}
        # summary + tests at this head
        tests = self.db.q("SELECT name, passed, output_tail FROM test_results WHERE task_id=? AND commit_sha=? "
                          "ORDER BY id DESC", (tid, head or "")) if head else []
        seen, trows = set(), ""
        for r in tests:
            if r["name"] in seen:
                continue
            seen.add(r["name"])
            trows += (f"<tr><td>{'✓' if r['passed'] else '<b class=err>✗</b>'}</td><td>{E(r['name'])}</td>"
                      f"<td><details><summary>output</summary><pre>{E(r['output_tail'] or '')}</pre></details></td></tr>")
        original_summary = str(h.get("summary") or "")
        has_hebrew_summary = any("\u0590" <= c <= "\u05ff" for c in original_summary)
        if has_hebrew_summary:
            summary_text = original_summary
        else:
            summary_text = (f"המשימה: {task_he(self.cfg, t)} "
                            f"מצב נוכחי: {state_label(t['state'], 'he')}. "
                            f"בדיקות שעברו: {sum(bool(r['passed']) for r in tests)}; "
                            f"בדיקות שלא עברו: {sum(not bool(r['passed']) for r in tests)}. "
                            f"בדוח נרשמו {len(h.get('capability_gaps') or [])} פערי יכולת, "
                            f"{len(h.get('untested_limits') or [])} מגבלות שלא נבדקו "
                            f"ו־{len(h.get('uncertainties') or [])} נקודות אי־ודאות.")
        detail_labels = {"assumptions": "הנחות", "uncertainties": "אי־ודאויות",
                         "untested_limits": "מגבלות שלא נבדקו", "capability_gaps": "פערי יכולת"}
        hebrew_details = ""
        for key, label in detail_labels.items():
            items_he = [item for item in h.get(key) or []
                        if any("\u0590" <= c <= "\u05ff" for c in item)]
            if items_he:
                hebrew_details += f"<div class='muted'><b>{label}</b>: {E('; '.join(items_he))}</div>"
        original_details = "".join(
            f"<p><b>{E(label)}</b>: {E('; '.join(h.get(key) or []))}</p>"
            for key, label in detail_labels.items() if h.get(key))
        original_report = (f"<details><summary>פתיחת הדוח המקורי</summary>"
                           f"<div dir='ltr' class='muted' style='text-align:left'><p>{E(original_summary)}</p>"
                           f"{original_details}</div></details>" if original_summary or original_details else "")
        summary = (f"<div class='card'><p>{E(summary_text)}</p>{hebrew_details}{original_report}"
                   f"<table>{trows}</table></div>")
        # Only browser-renderable media belongs in Visual. Reports remain under Code.
        vis = []
        model_source = None
        for r in self.db.q("SELECT * FROM artifacts WHERE task_id=? ORDER BY id DESC", (tid,)):
            name = r["source_path"] or Path(r["path"]).name
            if self.VISUAL.get(Path(name).suffix.lower()) == "model" and model_source is None:
                model_source = f"/game-preview?artifact={r['id']}"
            if self.VISUAL.get(Path(name).suffix.lower()) in {"img", "video", "html", "model"}:
                vis.append((name, f"/artifact/{r['id']}", r["description"] or r["kind"]))
        for f in files:
            if self.VISUAL.get(Path(f).suffix.lower()) in {"img", "video", "html", "model"} and not any(v[0] == f for v in vis):
                vis.append((f, f"/wtfile?task={q(tid)}&path={q(f)}&raw=1", ""))
                if self.VISUAL.get(Path(f).suffix.lower()) == "model" and model_source is None:
                    model_source = f"/game-preview?task={q(tid)}&path={q(f)}"
        cards = []
        for name, url, desc in vis:
            kind = self.VISUAL.get(Path(name).suffix.lower(), "file")
            if kind == "img":
                media = f"<a href='{url}'><img src='{url}' alt=''></a>"
            elif kind == "video":
                media = f"<video controls src='{url}'></video>"
            elif kind == "html":
                media = f"<iframe sandbox src='{url}'></iframe>"
            elif kind == "model":
                media = f"<a class='btnlink' href='{url}'>קובץ תלת־ממד: {E(Path(name).name)}</a>"
            else:
                media = f"<a class='btnlink' href='{url}'>{E(Path(name).name)}</a>"
            cards.append(f"<figure>{media}<figcaption class='mono'>{E(name)}</figcaption>"
                         f"<div class='muted'>{E(desc)}</div></figure>")
        preview = (f"<iframe class='game-preview' src='{E(model_source)}' title='תצוגת המודל שנוצר במשימה' "
                   f"allow='xr-spatial-tracking'></iframe><p class='muted'>"
                   f"<a href='{E(model_source)}' target='_blank' rel='noopener'>פתח את המודל במסך מלא</a></p>") \
                  if model_source else ""
        visual = preview + (f"<h3>מדיה שנוצרה במשימה הזו</h3><div class='gallery'>{''.join(cards)}</div>" if cards else
                            "<p class='muted'>המשימה הזו יצרה קוד או דוח, אך לא יצרה תוצר חזותי שאפשר להציג. "
                            "התוצרים עצמם מופיעים בלשונית קוד.</p>")
        # code
        flist = "".join(f"<li><a class='mono' href='/wtfile?task={q(tid)}&path={q(f)}'>{E(f)}</a></li>" for f in files)
        diff = self.wt.diff(wt, base, 400000) if wt and base else ""
        code = (f"<ul>{flist or '<li>-</li>'}</ul><h3>Diff</h3>{self._diff_html(diff) or '-'}")
        pend = self.db.q("SELECT * FROM approvals WHERE task_id=? AND status='pending'", (tid,))
        actions = "".join(
            f"<p>{pill('WAITING_APPROVAL')} {E(p['kind'])}: {E(p['reason'] or '')}</p><p>"
            + self._form("approve", "Approve", "big go", back=back, approval_id=p["id"]) + " "
            + self._form("reject", "Reject", "big", back=back, approval_id=p["id"]) + "</p>" for p in pend)
        body = (f"<p><a href='/task?id={q(tid)}'>← {E(tid)}</a></p><h1>{E(self.t('View what was created'))}: "
                f"<span class='mono'>{E(tid)}</span> {pill(t['state'])}</h1>"
                f"<p class='muted mono'>{E((base or '')[:12])}..{E((head or '')[:12])} · {len(files)} files</p>"
                f"<p class='tabs'><a href='#summary'>{E(self.t('Summary'))}</a><a href='#visual'>{E(self.t('Visual'))}</a>"
                f"<a href='#code'>{E(self.t('Code'))}</a><a href='#decide'>{E(self.t('Decide'))}</a></p>"
                f"<h2 id='summary'>{E(self.t('Summary'))}</h2>{summary}"
                f"<h2 id='visual'>{E(self.t('Visual'))}</h2><div class='card'>{visual}</div>"
                f"<h2 id='code'>{E(self.t('Code'))} ({len(files)})</h2><div class='card'>{code}</div>"
                f"<h2 id='decide'>{E(self.t('Decide'))}</h2><div class='card'>"
                f"{actions or '<p class=muted>' + E(self.t('nothing waiting for you')) + '</p>'}</div>")
        return self._layout(f"review {tid}", body, msg)

    def page_events(self, q: dict | None = None) -> str:
        q = q or {}
        data = self.events_json(q)
        filters = self._event_query(q)
        all_types = [r["event"] for r in self.db.q(
            "SELECT event FROM event_log GROUP BY event ORDER BY event")]
        providers = [r["provider"] for r in self.db.q(
            "SELECT provider FROM event_log WHERE provider IS NOT NULL AND provider<>'' "
            "GROUP BY provider ORDER BY provider")]
        task_value = E(filters["task_id"] or "")
        search_value = E(filters["search"] or "")
        event_options = "<option value=''>כל סוגי האירועים</option>" + "".join(
            f"<option value='{E(name)}'{' selected' if name == filters['event'] else ''}>{E(name)}</option>"
            for name in all_types)
        provider_options = "<option value=''>כל הספקים</option>" + "".join(
            f"<option value='{E(name)}'{' selected' if name == filters['provider'] else ''}>{E(name)}</option>"
            for name in providers)
        rows = []
        for item in data["events"]:
            detail = item["detail"]
            if isinstance(detail, (dict, list)):
                detail_text = json.dumps(detail, ensure_ascii=False, indent=2, default=str)
            else:
                detail_text = str(detail or "")
            task = item["task_id"] or ""
            task_html = (f"<a class='mono' href='/task?id={urllib.parse.quote(task)}'>{E(task)}</a>"
                         if task and self.db.task(task) else f"<span class='mono'>{E(task)}</span>")
            rows.append(
                f"<tr><td class='event-id'>#{item['id']}</td><td>{E(local(item['at']))}<br>"
                f"<small>{E(ago(item['at']))}</small></td><td class='event-name'>{E(item['event'])}</td>"
                f"<td>{task_html}</td><td>{E(item['provider'] or '')}</td>"
                f"<td class='mono'>{E(str(item['attempt_id'] or ''))}</td>"
                f"<td class='mono event-detail'>{E(detail_text[:3000])}</td></tr>")
        total_all = self.db.event_count()
        type_count = int(self.db.one("SELECT COUNT(DISTINCT event) n FROM event_log")["n"])
        task_count = int(self.db.one(
            "SELECT COUNT(DISTINCT task_id) n FROM event_log WHERE task_id IS NOT NULL")["n"])
        latest = self.db.one("SELECT id,at FROM event_log ORDER BY id DESC LIMIT 1")
        filter_pairs = [(k, str(v)) for k, v in filters.items()
                        if k not in {"before_id", "limit"} and v]
        next_link = ""
        if data["next_before_id"]:
            params = urllib.parse.urlencode(filter_pairs + [("limit", str(filters["limit"])),
                                                             ("before_id", str(data["next_before_id"]))])
            next_link = f"<a href='/events?{E(params)}'>אירועים ישנים יותר ←</a>"
        active_filters = any(filters[k] for k in ("task_id", "provider", "event", "search"))
        body = (
            "<div class='deliver-hero'><div><div class='hero-kicker'>יומן ביקורת מתמשך</div>"
            "<h1>יומן אירועים</h1><p>כל האירועים בדף נקראים ישירות מטבלת <span class='mono'>event_log</span> "
            "במסד הנתונים. אירוע נכתב למסד לפני שהוא מופיע כאן, והמידע הרגיש מוסתר בזמן הכתיבה.</p></div>"
            "<div class='card'><div class='event-source'><span class='event-live'></span>"
            "<b>מקור נתונים פעיל: SQLite</b></div><p class='mono muted'>.wwii-build/state.sqlite3 · event_log</p>"
            "<a href='/api/events'>פתח API של היומן</a></div></div>"
            f"<div class='counts'><div class='count'><span>אירועים שמורים</span><b>{total_all}</b></div>"
            f"<div class='count'><span>סוגי אירועים</span><b>{type_count}</b></div>"
            f"<div class='count'><span>משימות ביומן</span><b>{task_count}</b></div>"
            f"<div class='count'><span>רשומה אחרונה</span><b>#{latest['id'] if latest else 0}</b>"
            f"<small>{E(local(latest['at'])) if latest else '—'}</small></div></div>"
            "<h2>סינון היומן</h2><form class='card event-filter' method='get' action='/events'>"
            f"<label>חיפוש חופשי<input type='text' name='search' value='{search_value}' "
            "placeholder='אירוע, פרטים, משימה או ספק'></label>"
            f"<label>סוג אירוע<select class='w' name='event'>{event_options}</select></label>"
            f"<label>ספק<select class='w' name='provider'>{provider_options}</select></label>"
            f"<label>מזהה משימה<input type='text' name='task_id' value='{task_value}' dir='ltr'></label>"
            "<button class='go'>סנן מהמסד</button></form>"
            f"<div class='bar'><h2>אירועים ({data['total']}{' מסוננים' if active_filters else ''})</h2>"
            f"<small>מוצגות עד {filters['limit']} רשומות, מהחדשה לישנה</small></div>"
            "<div class='card'><table class='event-table'><thead><tr><th>ID</th><th>זמן</th><th>אירוע</th>"
            "<th>משימה</th><th>ספק</th><th>ניסיון</th><th>פרטים</th></tr></thead><tbody>"
            + ("".join(rows) if rows else "<tr><td colspan='7' class='muted'>לא נמצאו אירועים התואמים לסינון.</td></tr>")
            + f"</tbody></table><div class='pager'><span>{len(rows)} רשומות בדף זה</span>{next_link}</div></div>")
        return self._layout("יומן אירועים", body, None)
