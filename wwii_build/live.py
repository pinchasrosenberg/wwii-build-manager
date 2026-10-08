"""Live state over the dashboard WebSocket: change detection, topics, snapshots, patches, actions.

The state lives in SQLite and is written by other processes too (scheduler daemon, CLI, MCP server), so a
dedicated connection polls ``PRAGMA data_version`` (it changes whenever another connection commits). On a change
the topics somebody subscribed to are recomputed from the same queries the HTTP pages use, diffed against what was
last sent and broadcast as a patch to the subscribers of that topic only.

Server -> client messages
    {"type":"snapshot","topic","rev","data":{"key","items":[...],"meta":{...}}}
    {"type":"patch","topic","rev","upsert":[...],"remove":[keys],"meta":{...}}      ("meta" only when it changed)
    {"type":"subscribed","topics","current","rejected"}   ack; "current" = topics whose client rev was up to date
    {"type":"progress","id","line"}        a line from a long action (before its action.result, same worker thread)
    {"type":"action.result","id","ok","message"}
``items`` is a list of objects identified by ``data.key`` (null for the singleton topics overview/unstick, whose
payload is all in ``meta``). ``rev`` grows by one per change of a topic; a client that sees a gap re-subscribes.
Revs start from the creation time in milliseconds, so a rev of an earlier server run or of a dropped topic is
always smaller than the current one and gets a snapshot.

Client -> server messages
    {"type":"subscribe","topics":[...],"revs":{topic:rev}}   snapshot for every topic whose rev is missing or stale
    {"type":"unsubscribe","topics":[...]}
    {"type":"action","id":<client id>,"name":<form 'action' name>,"args":{...}}
    {"type":"search","id", "topic":"tasks.history", "query", "filters", "page"}
    {"type":"task.detail","id", "task_id"}
Actions run through Dashboard.action() (the code path of the HTML forms) in a worker thread; the lines a long action
reports (Dashboard.progress) are pushed as "progress" messages carrying the action id. The CSRF token was
already checked when the socket authenticated (hello). File uploads stay HTTP multipart POSTs.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from collections import Counter

from . import app_data
from . import control
from . import state_chat
from .explanations import task_he
from . import task_views

POLL_SECONDS = 0.25                  # data_version poll
OVERVIEW_REFRESH_SECONDS = 2.0       # daemon liveness is not a DB write, so the overview is re-read regularly
HEAVY_MIN_INTERVAL_SECONDS = 1.0     # delivers topics rebuild at most this often
SNAPSHOT_EVENTS = 100
EVENT_PATCH_MAX = 200                # a larger burst of new events is sent as a fresh snapshot instead
MAX_TOPICS_PER_CONNECTION = 64
MAX_PENDING_ACTIONS = 8              # per connection
MAX_MESSAGE_CHARS = 2000
MAX_PROGRESS_LINES = 500             # per action; the rest is dropped (the result still arrives)
MAX_PROGRESS_CHARS = 600

STATIC_TOPICS = ("overview", "tasks.active", "tasks.problems", "workers", "quota", "approvals", "events", "delivers", "unstick",
                 "rag", "plan", "subtasks")
KEYS = {"tasks.active": "task_id", "tasks.problems": "task_id",
        "workers": "attempt_id", "quota": "provider", "approvals": "id", "events": "id",
        "delivers": "deliver_id", "deliver": "capability_id", "chat": "id", "overview": None, "unstick": None,
        "task": "id", "rag": "id", "plan": "task_id", "subtasks": "pattern_hash"}
HEAVY = ("delivers", "deliver", "task", "plan", "subtasks", "tasks.problems")
ARG_TOPICS = ("deliver", "task")                  # "<kind>:<id>" topics
ID_RE = re.compile(r"[A-Za-z0-9._:/@-]{1,200}")
ACTION_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
COMMA_FIELDS = {"mcp_servers", "tool_names"}      # list arguments the form handlers split on "," (others on lines)


def parse_topic(name) -> tuple[str, str] | None:
    """(kind, argument) of a topic name, or None when it is not a topic this server knows."""
    if not isinstance(name, str):
        return None
    if name in STATIC_TOPICS:
        return name, ""
    kind, sep, arg = name.partition(":")
    if sep and kind in ARG_TOPICS and ID_RE.fullmatch(arg):
        return kind, arg
    if sep and kind == "chat" and arg.isdigit() and len(arg) <= 12:
        return kind, arg
    return None


def _ser(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)


def _digest(obj) -> str:
    return hashlib.sha1(_ser(obj).encode("utf-8")).hexdigest()


class _Sweep:
    """Per-tick memo so topics that share a query (tasks/overview, delivers/deliver:<id>) run it once."""

    def __init__(self, dash):
        self.dash = dash
        self._memo: dict[str, object] = {}

    def _once(self, key: str, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    def task_rows(self) -> list[dict]:
        return self._once("tasks", self.dash.task_rows)

    def active_tasks(self) -> list[dict]:
        return self._once("tasks.active", lambda: task_views.active_tasks(self.dash.db))

    def problem_tasks(self) -> list[dict]:
        return self._once("tasks.problems", lambda: task_views.problem_tasks(self.dash.db))

    def delivers(self) -> dict:
        return self._once("delivers", self.dash.delivers_json)


class _State:
    def __init__(self, rev: int):
        self.rev = rev
        self.fp = None                       # cheap fingerprint of the last build (None = always build)
        self.items: list[dict] = []
        self.ser: dict = {}                  # key -> serialized item
        self.meta: dict = {}
        self.meta_ser = _ser({})
        self.last_id = 0                     # events: highest id sent
        self.dirty = False
        self.last_run = 0.0


class LiveState:
    def __init__(self, dash, poll_seconds: float = POLL_SECONDS):
        self.dash = dash
        self.poll_seconds = poll_seconds
        self._lock = threading.RLock()       # guards _states; held while sending so a client sees snapshot -> patches
        self._states: dict[str, _State] = {}
        self._stop = threading.Event()
        self._wake = threading.Event()       # poke(): re-check now instead of at the next poll
        self._thread: threading.Thread | None = None
        self._overview_at = 0.0
        self._pending_actions: dict = {}
        self._action_lock = threading.Lock()
        self.last_error: str | None = None
        dash.hub.on("subscribe", self.handle_subscribe)
        dash.hub.on("unsubscribe", self.handle_unsubscribe)
        dash.hub.on("action", self.handle_action)
        dash.hub.on("search", self.handle_search)
        dash.hub.on("task.detail", self.handle_task_detail)

    # ------------------------------------------------------------------ detector thread
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dashboard-live", daemon=True)
        self._thread.start()

    def poke(self) -> None:
        """A write by this process: look for the change now instead of waiting for the next poll."""
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(5)
            self._thread = None

    def _run(self) -> None:
        conn = None
        last = None
        while not self._stop.is_set():
            try:
                if conn is None:
                    conn = sqlite3.connect(str(self.dash.db.path), timeout=5)
                version = conn.execute("PRAGMA data_version").fetchone()[0]
                changed = version != last        # first reading counts as a change: nothing is missed before it
                last = version
                self.tick(changed)
            except Exception as exc:             # keep detecting; a broken tick must not end live updates
                self.last_error = repr(exc)
                if conn is not None:
                    conn.close()
                conn, last = None, None
            self._wake.wait(self.poll_seconds)
            self._wake.clear()
        if conn is not None:
            conn.close()

    def tick(self, changed: bool, now: float | None = None) -> None:
        """One detector step: mark topics dirty on a DB change, drop unwatched topics, refresh and broadcast."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if now - self._overview_at >= OVERVIEW_REFRESH_SECONDS:
                self._overview_at = now
                if "overview" in self._states:
                    self._states["overview"].dirty = True
            wanted = self.dash.hub.subscribed_topics()
            for name in [n for n in self._states if n not in wanted]:
                del self._states[name]
            sweep = _Sweep(self.dash)
            for name, st in self._states.items():
                if changed:
                    st.dirty = True
                if not st.dirty:
                    continue
                kind = parse_topic(name)[0]
                if kind in HEAVY and now - st.last_run < HEAVY_MIN_INTERVAL_SECONDS:
                    continue                     # stays dirty; refreshed on a later tick
                st.dirty = False
                st.last_run = now
                try:
                    msg = self._refresh(name, st, sweep)
                except Exception as exc:
                    self.last_error = f"{name}: {exc!r}"
                    continue
                if msg:
                    self.dash.hub.broadcast(name, msg)

    # ------------------------------------------------------------------ topic computation
    def _fingerprint(self, kind: str, arg: str, sweep: _Sweep):
        db = self.dash.db
        if kind == "tasks.active":
            return _digest(sweep.active_tasks())
        if kind == "tasks.problems":
            return _digest(sweep.problem_tasks())
        if kind == "chat":
            row = db.one("SELECT COUNT(*) n, COALESCE(MAX(id),0) m FROM state_chat_messages WHERE conversation_id=?",
                         (int(arg),))
            return (row["n"], row["m"])
        if kind == "unstick":
            return db.get_flag("unstick_last_report")
        return None

    def _build(self, kind: str, arg: str, sweep: _Sweep) -> tuple[list[dict], dict]:
        d, db = self.dash, self.dash.db
        if kind == "overview":
            plan = [t for t in sweep.task_rows() if t["kind"] != "repair"]
            waves = [t["wave"] for t in plan if t["state"] not in ("PASSED", "CANCELLED") and t["wave"] is not None]
            pid, paused, emergency = control.daemon_pid(d.cfg), bool(db.get_flag("paused")), db.get_flag("emergency_stop")
            return [], {"daemon_pid": pid, "paused": paused, "emergency_stop": emergency,
                        "status": ("EMERGENCY STOP" if emergency else "PAUSED" if paused else
                                   "RUNNING" if pid else "DAEMON NOT RUNNING"),
                        "idle_reason": db.get_flag("idle_reason"), "next_wakeup_at": db.get_flag("next_wakeup_at"),
                        "review_auto_approve_all": db.get_flag("review_auto_approve_all") == "1",
                        "auto_max_per_task": int(d.cfg.section("approvals").get("auto_max_per_task", 3)),
                        "wave": min(waves) if waves else "done", "task_total": len(plan),
                        "counts": dict(Counter(t["state"] for t in plan)),
                        "problem_count": task_views.problem_count(db),
                        "models": d.models_info(),
                        # the state-chat conversation the page shows (None right after "new conversation")
                        "chat_conversation_id": (None if db.get_flag("state_chat_new") == "1"
                                                 else state_chat.latest_conversation(db))}
        if kind == "tasks.active":
            items = [dict(t) for t in sweep.active_tasks()]
            for task in items:
                task["description_he"] = task_he(d.cfg, task)
                task.pop("extra", None)
                task.pop("lego_ids", None)
            return items, {}
        if kind == "tasks.problems":
            items = [dict(t) for t in sweep.problem_tasks()]
            for task in items:
                task["description_he"] = task_he(d.cfg, task)
                task.pop("extra", None)
                task.pop("lego_ids", None)
            return items, {"default_window_days": 7}
        if kind == "workers":
            return d.worker_rows(), {}
        if kind == "quota":
            return d.quota_rows(), {}
        if kind == "approvals":
            return d.pending_approval_rows(), {}
        if kind == "delivers":
            data = sweep.delivers()
            caps = app_data.capability_counts(d)
            items = [dict(x, capability_groups=caps.get(x["deliver_id"], (0, 0))[0],
                          capability_count=caps.get(x["deliver_id"], (0, 0))[1]) for x in data["delivers"]]
            return items, {"edges": data["edges"], "active_listeners": data["active_listeners"],
                           "runtime": data["runtime"], "running": data["running"], "jev": data["jev"],
                           "active_activations": data["active_activations"],
                           "shelf_titles": app_data.shelf_titles(d, data["delivers"])}
        if kind == "deliver":
            data = sweep.delivers()
            deliver = next((x for x in data["delivers"] if x["deliver_id"] == arg), None)
            caps = [dict(r) for r in db.q("SELECT * FROM deliver_capabilities WHERE deliver_id=? AND active=1 "
                                          "ORDER BY rowid", (arg,))]
            edges = [e for e in data["edges"] if arg in (e["source_deliver_id"], e["target_deliver_id"])]
            meta = {"exists": deliver is not None, "deliver": deliver, "edges": edges}
            if deliver is not None:
                meta["detail"] = app_data.deliver_detail(d, arg)
            return caps, meta
        if kind == "task":
            return app_data.task_detail(d, arg)
        if kind == "rag":
            return app_data.rag_items(d), app_data.rag_meta(d)
        if kind == "plan":
            return app_data.plan_items(d), {"models": d.models_info()}
        if kind == "subtasks":
            return app_data.subtask_items(d), app_data.subtask_meta(d)
        if kind == "chat":
            return state_chat.history(db, int(arg)), {"conversation_id": int(arg)}
        if kind == "unstick":
            try:
                report = json.loads(db.get_flag("unstick_last_report") or "null")
            except ValueError:
                report = None
            return [], {"report": report}
        raise KeyError(kind)

    def _create(self, name: str, sweep: _Sweep) -> _State:
        kind, arg = parse_topic(name)
        st = _State(time.time_ns() // 1_000_000)
        if kind == "events":
            row = self.dash.db.one("SELECT COALESCE(MAX(id),0) m FROM event_log")
            st.last_id = row["m"]
        else:
            st.fp = self._fingerprint(kind, arg, sweep)
            self._store(st, kind, *self._build(kind, arg, sweep))
        return st

    @staticmethod
    def _store(st: _State, kind: str, items: list[dict], meta: dict) -> None:
        key = KEYS[kind]
        st.items = items
        st.ser = {it[key]: _ser(it) for it in items} if key else {}
        st.meta, st.meta_ser = meta, _ser(meta)

    def _refresh(self, name: str, st: _State, sweep: _Sweep) -> dict | None:
        """Recompute one topic; bump rev and return the patch (or snapshot) message if anything changed."""
        kind, arg = parse_topic(name)
        if kind == "events":
            return self._refresh_events(name, st)
        fp = self._fingerprint(kind, arg, sweep)
        if fp is not None and fp == st.fp:
            return None
        st.fp = fp
        items, meta = self._build(kind, arg, sweep)
        key, old = KEYS[kind], st.ser
        new = {it[key]: _ser(it) for it in items} if key else {}
        upsert = [it for it in items if key and old.get(it[key]) != new[it[key]]]
        remove = [k for k in old if k not in new]
        meta_changed = _ser(meta) != st.meta_ser
        if not (upsert or remove or meta_changed):
            return None
        st.items, st.ser, st.meta, st.meta_ser = items, new, meta, _ser(meta)
        st.rev += 1
        msg = {"type": "patch", "topic": name, "rev": st.rev, "upsert": upsert, "remove": remove}
        if meta_changed:
            msg["meta"] = meta
        return msg

    def _refresh_events(self, name: str, st: _State) -> dict | None:
        """event_log is append-only: send each new row once, in id order."""
        db = self.dash.db
        top = db.one("SELECT COALESCE(MAX(id),0) m FROM event_log")["m"]
        if top == st.last_id:
            return None
        rows = db.q("SELECT * FROM event_log WHERE id>? ORDER BY id LIMIT ?", (st.last_id, EVENT_PATCH_MAX + 1))
        if top < st.last_id or len(rows) > EVENT_PATCH_MAX:      # journal was reset, or a burst: resync everyone
            st.last_id = top
            st.rev += 1
            return self._snapshot(name, st)
        items = [self.dash.event_item(r) for r in rows]
        st.last_id = items[-1]["id"]
        st.rev += 1
        return {"type": "patch", "topic": name, "rev": st.rev, "upsert": items, "remove": []}

    def _snapshot(self, name: str, st: _State) -> dict:
        kind = parse_topic(name)[0]
        if kind == "events":
            rows = self.dash.db.q("SELECT * FROM (SELECT * FROM event_log WHERE id<=? ORDER BY id DESC LIMIT ?) "
                                  "ORDER BY id", (st.last_id, SNAPSHOT_EVENTS))
            items, meta = [self.dash.event_item(r) for r in rows], {}
        else:
            items, meta = st.items, st.meta
        return {"type": "snapshot", "topic": name, "rev": st.rev,
                "data": {"key": KEYS[kind], "items": items, "meta": meta}}

    # ------------------------------------------------------------------ client messages
    def handle_subscribe(self, conn, msg: dict) -> None:
        topics, revs = msg.get("topics"), msg.get("revs")
        if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
            return conn.send_json({"type": "error", "error": "bad_topics", "message_he": "רשימת נושאים לא תקינה"})
        revs = revs if isinstance(revs, dict) else {}
        accepted, current, rejected = [], [], []
        with self._lock:
            have = self.dash.hub.subscriptions(conn)
            sweep = _Sweep(self.dash)
            for name in dict.fromkeys(topics):
                if parse_topic(name) is None or (name not in have and len(have) + len(accepted) >= MAX_TOPICS_PER_CONNECTION):
                    rejected.append(name)
                    continue
                st = self._states.get(name)
                if st is None:
                    st = self._states[name] = self._create(name, sweep)
                else:                            # up to date before comparing; others get the patch if it changed
                    patch = self._refresh(name, st, sweep)
                    st.last_run = time.monotonic()
                    st.dirty = False
                    if patch:
                        self.dash.hub.broadcast(name, patch)
                accepted.append(name)
                if revs.get(name) == st.rev and not isinstance(revs.get(name), bool):
                    current.append(name)
                else:
                    conn.send_json(self._snapshot(name, st))
            self.dash.hub.subscribe(conn, accepted)
            conn.send_json({"type": "subscribed", "topics": accepted, "current": current, "rejected": rejected})

    def handle_unsubscribe(self, conn, msg: dict) -> None:
        topics = msg.get("topics")
        if isinstance(topics, list):
            self.dash.hub.unsubscribe(conn, [t for t in topics if isinstance(t, str)])

    def handle_search(self, conn, msg: dict) -> None:
        """One bounded history page; history is never a subscribed/pushed topic."""
        request_id = msg.get("id")
        if msg.get("topic") == "tasks.problems":
            items = task_views.problem_tasks(self.dash.db, include_all=bool(msg.get("include_all")))
            for item in items:
                item.pop("extra", None)
                item.pop("lego_ids", None)
            return conn.send_json({"type": "search.result", "id": request_id, "topic": "tasks.problems",
                                   "ok": True, "items": items, "total": len(items)})
        if msg.get("topic") != "tasks.history":
            return conn.send_json({"type": "search.result", "id": request_id, "topic": msg.get("topic"),
                                   "ok": False, "error": "unknown_topic"})
        filters = msg.get("filters")
        if filters is not None and not isinstance(filters, dict):
            return conn.send_json({"type": "search.result", "id": request_id, "topic": "tasks.history",
                                   "ok": False, "error": "bad_filters"})
        result = task_views.history_search(self.dash.db, msg.get("query") or "", filters or {}, msg.get("page", 1))
        conn.send_json({"type": "search.result", "id": request_id, "topic": "tasks.history", "ok": True, **result})

    def handle_task_detail(self, conn, msg: dict) -> None:
        """Build the transitive dependency panel only after a row is clicked."""
        request_id, task_id = msg.get("id"), msg.get("task_id")
        if not isinstance(task_id, str) or not ID_RE.fullmatch(task_id):
            return conn.send_json({"type": "task.detail.result", "id": request_id, "ok": False,
                                   "error": "bad_task_id"})
        conn.send_json({"type": "task.detail.result", "id": request_id, "ok": True,
                        "detail": task_views.task_dependency_detail(self.dash.db, task_id)})

    # ------------------------------------------------------------------ actions
    def handle_action(self, conn, msg: dict) -> None:
        aid, name, args = msg.get("id"), msg.get("name"), msg.get("args", {})
        if isinstance(aid, bool) or not isinstance(aid, (str, int)):
            return conn.send_json({"type": "error", "error": "bad_action", "message_he": "מזהה פעולה חסר"})

        def reply(ok: bool, message: str) -> None:
            conn.send_json({"type": "action.result", "id": aid, "ok": ok, "message": message[:MAX_MESSAGE_CHARS]})

        if not isinstance(name, str) or not ACTION_RE.fullmatch(name) or not isinstance(args, dict):
            return reply(False, "error: invalid action request")
        with self._action_lock:
            if self._pending_actions.get(conn, 0) >= MAX_PENDING_ACTIONS:
                return reply(False, "error: too many actions in progress")
            self._pending_actions[conn] = self._pending_actions.get(conn, 0) + 1

        sent = [0]

        def progress(line) -> None:
            sent[0] += 1
            if sent[0] <= MAX_PROGRESS_LINES:
                conn.send_json({"type": "progress", "id": aid, "line": str(line).strip()[:MAX_PROGRESS_CHARS]})

        def work() -> None:
            try:
                with self.dash.progress_to(progress):
                    ok, message = self.run_action(name, args)
                reply(ok, message)
            finally:
                with self._action_lock:
                    left = self._pending_actions.get(conn, 1) - 1
                    if left > 0:
                        self._pending_actions[conn] = left
                    else:
                        self._pending_actions.pop(conn, None)

        threading.Thread(target=work, name=f"ws-action-{name}", daemon=True).start()

    def run_action(self, name: str, args: dict) -> tuple[bool, str]:
        """Run one action through Dashboard.action() (or add_task_post) exactly like the HTML form POST."""
        try:
            form, multi = form_from_args(args)
        except ValueError as exc:
            return False, f"error: {exc}"
        form["action"] = name
        return self.dash.run_form(form, multi)


def form_from_args(args: dict) -> tuple[dict, dict]:
    """Socket ``args`` -> (form dict, multi dict) as the HTTP handler builds them from a POST body.

    The token is not an argument: it was verified at hello. Booleans become "1"/"0", null "", scalars strings and
    lists of scalars one value per line ("," for the fields the handlers split on commas).
    """
    form: dict[str, str] = {}
    multi: dict[str, list[str]] = {}
    for key, value in args.items():
        if key in ("action", "token"):
            continue
        scalar = lambda v: isinstance(v, (str, int, float)) and not isinstance(v, bool)
        if isinstance(value, bool):
            values = ["1" if value else "0"]
        elif value is None:
            values = [""]
        elif scalar(value):
            values = [str(value)]
        elif isinstance(value, list) and all(scalar(v) for v in value):
            values = [str(v) for v in value]
        else:
            raise ValueError(f"invalid argument {key}")
        multi[key] = values
        form[key] = ("," if key in COMMA_FIELDS else "\n").join(values) if isinstance(value, list) else values[0]
    return form, multi
