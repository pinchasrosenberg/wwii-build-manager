"""Durable activation generation and restart decisions for long-running manager processes."""
from __future__ import annotations

from .db import DB


MARKER_KEY = "manager_activation_id"


def activation_id(db: DB) -> int:
    """Return the durable activation generation, tolerating databases created before it existed."""
    raw = db.get_flag(MARKER_KEY, "0")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def record_activation(db: DB) -> int:
    """Atomically advance and persist the manager activation generation."""
    with db.tx():
        row = db.conn.execute("SELECT value FROM scheduler_state WHERE key=?", (MARKER_KEY,)).fetchone()
        try:
            current = max(0, int(row["value"])) if row else 0
        except (TypeError, ValueError):
            current = 0
        new_id = current + 1
        db.conn.execute(
            "INSERT INTO scheduler_state(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (MARKER_KEY, str(new_id)),
        )
    return new_id


def restart_decision(seen: int, current: int, *, busy: bool = False) -> str:
    """Pure restart policy shared by persistent dashboard and scheduler loops."""
    if current == seen:
        return "unchanged"
    return "wait" if busy else "restart"
