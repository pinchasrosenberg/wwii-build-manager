"""SQLite access, migrations and the event log."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .models import iso, utcnow
from .sanitize import redact

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if f.name in done:
            continue
        conn.execute("BEGIN")
        try:
            # executescript() would commit implicitly, so statements run one by one.
            for stmt in _split_sql(f.read_text()):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (f.name, iso(utcnow())))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(f.name)
    return applied


def _split_sql(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


class DB:
    """Thin wrapper; one connection guarded by a lock (daemon + dashboard threads)."""

    def __init__(self, path: Path | str):
        self.path = path
        self.conn = connect(path)
        self.lock = threading.RLock()
        migrate(self.conn)

    # --- generic helpers -------------------------------------------------
    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(sql, tuple(params)))

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def x(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, tuple(params))
            return cur.lastrowid

    def tx(self):
        return _Tx(self)

    # --- key/value scheduler state --------------------------------------
    def get_flag(self, key: str, default: str | None = None) -> str | None:
        r = self.one("SELECT value FROM scheduler_state WHERE key=?", (key,))
        return r["value"] if r else default

    def set_flag(self, key: str, value: str | None) -> None:
        if value is None:
            self.x("DELETE FROM scheduler_state WHERE key=?", (key,))
        else:
            self.x("INSERT INTO scheduler_state(key,value) VALUES(?,?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # --- event log --------------------------------------------------------
    def event(self, event: str, task_id: str | None = None, attempt_id: int | None = None,
              provider: str | None = None, **detail: Any) -> int:
        """Persist one audit event and return its durable database id.

        ``event_log`` is the authoritative journal for the Task Manager.  Keep
        redaction here, at the write boundary, so no dashboard, CLI or MCP read
        can accidentally recover a secret from a raw event payload.
        """
        return self.x("INSERT INTO event_log(at,event,task_id,attempt_id,provider,detail) VALUES(?,?,?,?,?,?)",
                      (iso(utcnow()), event, task_id, attempt_id, provider,
                       redact(json.dumps(detail, ensure_ascii=False, default=str)) if detail else None))

    def events(self, *, limit: int = 100, before_id: int | None = None,
               task_id: str | None = None, provider: str | None = None,
               event: str | None = None, search: str | None = None) -> list[sqlite3.Row]:
        """Read a filtered page from the durable event journal.

        Every consumer uses this method so the dashboard, JSON API, CLI and MCP
        all observe the same database ordering and filtering rules.
        """
        where: list[str] = []
        params: list[Any] = []
        if before_id is not None:
            where.append("id < ?")
            params.append(int(before_id))
        if task_id:
            where.append("task_id = ?")
            params.append(task_id)
        if provider:
            where.append("provider = ?")
            params.append(provider)
        if event:
            where.append("event = ?")
            params.append(event)
        if search:
            where.append("(event LIKE ? OR COALESCE(task_id,'') LIKE ? OR COALESCE(provider,'') LIKE ? "
                         "OR COALESCE(detail,'') LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle, needle, needle])
        sql = "SELECT * FROM event_log"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return self.q(sql, params)

    def event_count(self, *, task_id: str | None = None, provider: str | None = None,
                    event: str | None = None, search: str | None = None) -> int:
        where: list[str] = []
        params: list[Any] = []
        if task_id:
            where.append("task_id = ?")
            params.append(task_id)
        if provider:
            where.append("provider = ?")
            params.append(provider)
        if event:
            where.append("event = ?")
            params.append(event)
        if search:
            where.append("(event LIKE ? OR COALESCE(task_id,'') LIKE ? OR COALESCE(provider,'') LIKE ? "
                         "OR COALESCE(detail,'') LIKE ?)")
            needle = f"%{search}%"
            params.extend([needle, needle, needle, needle])
        sql = "SELECT COUNT(*) n FROM event_log"
        if where:
            sql += " WHERE " + " AND ".join(where)
        row = self.one(sql, params)
        return int(row["n"] if row else 0)

    # --- tasks ------------------------------------------------------------
    def task(self, task_id: str) -> sqlite3.Row | None:
        return self.one("SELECT * FROM tasks WHERE task_id=?", (task_id,))

    def set_task_state(self, task_id: str, state: str, reason: str | None = None, **fields: Any) -> None:
        cols = {"state": state, "state_reason": reason, "updated_at": iso(utcnow()), **fields}
        sets = ", ".join(f"{k}=?" for k in cols)
        self.x(f"UPDATE tasks SET {sets} WHERE task_id=?", (*cols.values(), task_id))

    def deps(self, task_id: str) -> list[str]:
        return [r["depends_on"] for r in self.q(
            "SELECT depends_on FROM task_dependencies WHERE task_id=? ORDER BY depends_on", (task_id,))]

    def dependents(self, task_id: str) -> list[str]:
        return [r["task_id"] for r in self.q(
            "SELECT task_id FROM task_dependencies WHERE depends_on=? ORDER BY task_id", (task_id,))]

    def update_attempt(self, attempt_id: int, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE task_attempts SET {sets} WHERE id=?", (*fields.values(), attempt_id))

    def close(self) -> None:
        with self.lock:
            self.conn.close()


class _Tx:
    def __init__(self, db: DB):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, et, ev, tb):
        try:
            self.db.conn.execute("ROLLBACK" if et else "COMMIT")
        finally:
            self.db.lock.release()
        return False
