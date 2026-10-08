"""Small, server-side task views for the live dashboard.

The live lists deliberately contain no completed history and no dependency
trees.  Expensive evidence and graph traversal are built only for an explicit
request, keeping the normal snapshots bounded as the task database grows.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .models import iso, utcnow
from .sanitize import redact

ACTIVE_STATES = (
    "RUNNING", "PAUSING", "READY", "PENDING", "QUEUED", "WAITING_DEPENDENCY",
    "WAITING_APPROVAL", "WAITING_QUOTA", "WAITING_PROVIDER", "WAITING_REPAIR",
    "CODE_READY", "REVIEWING", "PAUSED",
)
PROBLEM_STATES = (
    "FAILED", "BLOCKED", "ESCALATION_REQUIRED", "ARCHITECTURE_REVIEW_REQUIRED", "REVIEW_REQUIRED",
)
HISTORY_PAGE_SIZE = 50
TAIL_CHARS = 3000

_TASK_COLUMNS = (
    "task_id", "packet", "owner", "domain", "mode", "model_profile", "wave", "state", "state_reason",
    "last_model_key", "preferred_model_key", "title", "note", "not_before", "kind", "parent_task_id",
    "repair_no", "failure_class", "failure_summary", "repairs_count", "active_repair_id", "dispatch_priority",
    "attempts_count", "failed_attempts", "created_at", "updated_at", "extra", "lego_ids",
)


def _row(row) -> dict:
    return {key: row[key] for key in _TASK_COLUMNS}


def _marks(count: int) -> str:
    return ",".join("?" for _ in range(count))


def _model(task: dict) -> str:
    return task.get("last_model_key") or task.get("preferred_model_key") or task.get("model_profile") or ""


def _dependency_wait(db, task_id: str) -> list[dict]:
    return [dict(r) for r in db.q(
        "SELECT d.depends_on task_id,t.title,t.state,t.state_reason,t.not_before "
        "FROM task_dependencies d LEFT JOIN tasks t ON t.task_id=d.depends_on "
        "WHERE d.task_id=? AND (t.task_id IS NULL OR t.state<>'PASSED') ORDER BY d.depends_on", (task_id,))]


def wait_summary(db, task: dict) -> str:
    """One short Hebrew explanation for an active/problem row."""
    state = task.get("state") or ""
    tid = task.get("task_id") or ""
    if state == "WAITING_DEPENDENCY":
        deps = _dependency_wait(db, tid)
        names = [d.get("title") or d["task_id"] for d in deps]
        return "ממתינה ל־" + ", ".join(names) if names else "ממתינה לתלות שטרם הושלמה"
    if state == "WAITING_QUOTA":
        return "ממתינה לאיפוס מכסה" + (f" ב־{task['not_before']}" if task.get("not_before") else " (המועד לא ידוע)")
    if state == "WAITING_PROVIDER":
        return "ממתינה לזמינות ספק או מודל" + (f" עד {task['not_before']}" if task.get("not_before") else "")
    if state in ("WAITING_APPROVAL", "REVIEW_REQUIRED", "ARCHITECTURE_REVIEW_REQUIRED"):
        approval = db.one("SELECT kind,reason FROM approvals WHERE task_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (tid,))
        return "ממתינה לאישור" + (f": {approval['reason'] or approval['kind']}" if approval else "")
    if state == "WAITING_REPAIR":
        repair = db.task(task.get("active_repair_id")) if task.get("active_repair_id") else None
        if repair:
            return f"ממתינה לתיקון #{repair['repair_no']} ({repair['last_model_key'] or repair['model_profile']})"
        return "ממתינה לתיקון"
    if state == "PAUSED":
        return "מושהית; יש להמשיך את התור"
    return (task.get("state_reason") or "").strip()[:240]


def _repair_item(row) -> dict:
    item = _row(row)
    item["model"] = _model(item)
    item["outcome"] = item.get("state_reason") or item.get("state")
    item.pop("extra", None)
    item.pop("lego_ids", None)
    return item


def active_tasks(db) -> list[dict]:
    """Active parent tasks, with repairs nested and never emitted as rows."""
    rows = db.q(f"SELECT {','.join(_TASK_COLUMNS)} FROM tasks WHERE state IN ({_marks(len(ACTIVE_STATES))}) "
                "AND kind<>'repair'", ACTIVE_STATES)
    result = []
    rank = {s: i for i, s in enumerate(("RUNNING", "PAUSING", "REVIEWING", "CODE_READY", "READY"))}
    for source in rows:
        item = _row(source)
        repairs = db.q(f"SELECT {','.join(_TASK_COLUMNS)} FROM tasks WHERE parent_task_id=? AND kind='repair' "
                       "ORDER BY repair_no", (item["task_id"],))
        item["repairs"] = [_repair_item(r) for r in repairs]
        item["wait_summary"] = wait_summary(db, item)
        item["model"] = _model(item)
        result.append(item)

    def key(task):
        state = task["state"]
        group = 0 if state in ("RUNNING", "PAUSING", "REVIEWING", "CODE_READY") else 1 if state == "READY" else 2
        return (group, rank.get(state, 99), task.get("wave") if task.get("wave") is not None else 10**9, task["task_id"])

    return sorted(result, key=key)


def _json(raw):
    try:
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return raw


def _file_tail(path: str | None) -> str:
    if not path:
        return ""
    try:
        p = Path(path)
        if not p.is_file():
            return ""
        return redact(p.read_text(errors="replace")[-TAIL_CHARS:])
    except OSError:
        return ""


def problem_reason(db, task_id: str) -> dict:
    """Assemble a problem explanation exclusively from durable task records."""
    task = db.task(task_id)
    if not task:
        return {"task_id": task_id, "missing": True, "summary": "רשומת המשימה לא נמצאה"}
    task = dict(task)
    latest_test = db.one("SELECT attempt_id,created_at FROM test_results WHERE task_id=? OR via_task_id=? "
                         "ORDER BY id DESC LIMIT 1", (task_id, task_id))
    failed_checks = []
    if latest_test:
        if latest_test["attempt_id"] is None:
            checks = db.q("SELECT name,output_tail,exit_code FROM test_results WHERE (task_id=? OR via_task_id=?) "
                          "AND created_at=? AND passed=0 ORDER BY id", (task_id, task_id, latest_test["created_at"]))
        else:
            checks = db.q("SELECT name,output_tail,exit_code FROM test_results WHERE (task_id=? OR via_task_id=?) "
                          "AND attempt_id=? AND passed=0 ORDER BY id", (task_id, task_id, latest_test["attempt_id"]))
        failed_checks = [{"name": c["name"], "exit_code": c["exit_code"],
                          "output_tail": redact(c["output_tail"] or "")[-TAIL_CHARS:]} for c in checks]
    attempt = db.one("SELECT * FROM task_attempts WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,))
    last_attempt = None
    if attempt:
        last_attempt = {"id": attempt["id"], "status": attempt["status"], "failure_class": attempt["failure_class"],
                        "diagnosis": redact(attempt["diagnosis"] or "")[-TAIL_CHARS:],
                        "stderr_tail": _file_tail(attempt["stderr_path"]), "exit_code": attempt["exit_code"]}
    repairs = []
    parent_id = task["parent_task_id"] if task["kind"] == "repair" else task_id
    for r in db.q("SELECT * FROM tasks WHERE parent_task_id=? AND kind='repair' ORDER BY repair_no", (parent_id,)):
        last = db.one("SELECT handoff,status,diagnosis FROM task_attempts WHERE task_id=? ORDER BY id DESC LIMIT 1", (r["task_id"],))
        outcome = r["state_reason"] or r["state"]
        if last and last["handoff"]:
            handoff = _json(last["handoff"])
            if isinstance(handoff, dict):
                outcome = handoff.get("summary") or handoff.get("status") or outcome
        repairs.append({"task_id": r["task_id"], "repair_no": r["repair_no"],
                        "model": r["last_model_key"] or r["model_profile"], "state": r["state"],
                        "failure_summary": r["failure_summary"], "outcome": outcome})
    approvals = [dict(a) for a in db.q(
        "SELECT id,kind,status,reason,note,created_at,decided_at FROM approvals WHERE task_id=? ORDER BY id", (task_id,))]
    events = []
    for event in db.q("SELECT id,at,event,detail FROM event_log WHERE task_id=? AND (event='UNSTICK_RETRY' "
                      "OR event LIKE 'AUTO_%' OR event LIKE '%MERGE%' OR event LIKE '%PREFLIGHT%' "
                      "OR event='SYSTEM_REPAIR_ACTIVATION_FAILED') ORDER BY id", (task_id,)):
        events.append({"id": event["id"], "at": event["at"], "event": event["event"], "detail": _json(event["detail"])})
    release = db.one("SELECT status,error,release_path,created_at,activated_at FROM system_repair_releases "
                     "WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,))
    release_detail = dict(release) if release else None
    if release_detail and release_detail.get("error"):
        release_detail["error"] = redact(release_detail["error"])[-TAIL_CHARS:]
    pieces = [task.get("state_reason"), task.get("failure_class")]
    if failed_checks:
        pieces.append("בדיקות שנכשלו: " + ", ".join(c["name"] for c in failed_checks))
    if last_attempt and (last_attempt["diagnosis"] or last_attempt["stderr_tail"]):
        pieces.append(last_attempt["diagnosis"] or last_attempt["stderr_tail"])
    summary = " · ".join(str(p).strip() for p in pieces if p and str(p).strip()) or "לא נשמרה סיבה מפורטת"
    return {"task_id": task_id, "missing": False, "state_reason": task.get("state_reason"),
            "failure_class": task.get("failure_class"), "failed_checks": failed_checks, "last_attempt": last_attempt,
            "repairs": repairs, "approvals": approvals, "events": events, "activation_preflight": release_detail,
            "summary": summary[:1000]}


def problem_tasks(db, *, include_all: bool = False, now: dt.datetime | None = None) -> list[dict]:
    params: list[object] = list(PROBLEM_STATES)
    where = [f"state IN ({_marks(len(PROBLEM_STATES))})"]
    if not include_all:
        cutoff = iso((now or utcnow()) - dt.timedelta(days=7))
        where.append("updated_at>=?")
        params.append(cutoff)
        where.append("NOT (kind='repair' AND EXISTS (SELECT 1 FROM tasks p WHERE p.task_id=tasks.parent_task_id AND p.state='PASSED'))")
    rows = db.q(f"SELECT {','.join(_TASK_COLUMNS)} FROM tasks WHERE {' AND '.join(where)} "
                "ORDER BY updated_at DESC,task_id", params)
    result = []
    for source in rows:
        item = _row(source)
        item["model"] = _model(item)
        item["reason"] = problem_reason(db, item["task_id"])
        result.append(item)
    return result


def problem_count(db, *, now: dt.datetime | None = None) -> int:
    cutoff = iso((now or utcnow()) - dt.timedelta(days=7))
    return int(db.one(f"SELECT COUNT(*) n FROM tasks WHERE state IN ({_marks(len(PROBLEM_STATES))}) "
                      "AND updated_at>=? AND NOT (kind='repair' AND EXISTS "
                      "(SELECT 1 FROM tasks p WHERE p.task_id=tasks.parent_task_id AND p.state='PASSED'))",
                      (*PROBLEM_STATES, cutoff))["n"])


def history_search(db, query: str = "", filters: dict | None = None, page: int = 1) -> dict:
    """Search every task with SQL-side filters and fixed 50-row paging."""
    filters = filters if isinstance(filters, dict) else {}
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    where, params = [], []
    query = str(query or "").strip()[:300]
    if query:
        where.append("(t.task_id LIKE ? OR COALESCE(t.title,'') LIKE ? OR COALESCE(t.note,'') LIKE ? OR COALESCE(t.state_reason,'') LIKE ?)")
        params.extend([f"%{query}%"] * 4)
    states = filters.get("state") or filters.get("states") or []
    if isinstance(states, str):
        states = [states]
    states = [str(s)[:80] for s in states if s]
    if states:
        where.append(f"t.state IN ({_marks(len(states))})")
        params.extend(states)
    for field, op in (("date_from", ">="), ("date_to", "<=")):
        if filters.get(field):
            where.append(f"t.updated_at{op}?")
            value = str(filters[field])[:40]
            if field == "date_to" and len(value) == 10:
                value += "T23:59:59.999999+99:99"
            params.append(value)
    if filters.get("owner"):
        where.append("t.owner=?")
        params.append(str(filters["owner"])[:200])
    model = str(filters.get("model") or "").strip()[:200]
    if model:
        where.append("(t.last_model_key LIKE ? OR t.preferred_model_key LIKE ? OR t.model_profile LIKE ? OR EXISTS "
                     "(SELECT 1 FROM task_attempts a WHERE a.task_id=t.task_id AND (a.model_key LIKE ? OR a.model LIKE ?)))")
        params.extend([f"%{model}%"] * 5)
    provider = str(filters.get("provider") or "").strip()[:200]
    if provider:
        where.append("EXISTS (SELECT 1 FROM task_attempts a WHERE a.task_id=t.task_id AND a.provider LIKE ?)")
        params.append(f"%{provider}%")
    if filters.get("has_failed") in (True, 1, "1", "true", "yes"):
        where.append("(t.failed_attempts>0 OR t.state IN ('FAILED','BLOCKED','ESCALATION_REQUIRED','ARCHITECTURE_REVIEW_REQUIRED','REVIEW_REQUIRED') "
                     "OR EXISTS (SELECT 1 FROM test_results tr WHERE tr.task_id=t.task_id AND tr.passed=0) "
                     "OR EXISTS (SELECT 1 FROM task_attempts a WHERE a.task_id=t.task_id AND a.status IN ('FAILED_ATTEMPT','AUTH_ERROR','BILLING_BLOCKED','CRASHED','TIMED_OUT','ORPHANED')))")
    clause = " WHERE " + " AND ".join(where) if where else ""
    total = int(db.one("SELECT COUNT(*) n FROM tasks t" + clause, params)["n"])
    rows = db.q(f"SELECT {','.join('t.' + c for c in _TASK_COLUMNS)} FROM tasks t{clause} "
                "ORDER BY t.updated_at DESC,t.task_id LIMIT ? OFFSET ?", (*params, HISTORY_PAGE_SIZE, (page - 1) * HISTORY_PAGE_SIZE))
    items = []
    for source in rows:
        item = _row(source)
        item["model"] = _model(item)
        item.pop("extra", None)
        item.pop("lego_ids", None)
        items.append(item)
    return {"items": items, "page": page, "page_size": HISTORY_PAGE_SIZE, "total": total,
            "pages": max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)}


def task_dependency_detail(db, task_id: str) -> dict:
    """A cycle-safe transitive prerequisite tree plus direct/downstream dependents."""
    root = db.task(task_id)
    if not root:
        return {"exists": False, "task_id": task_id, "prerequisites": [], "blocking_roots": [],
                "dependents": [], "downstream_more": 0}

    blockers: set[str] = set()

    def node(tid: str, path: tuple[str, ...]) -> dict:
        if tid in path:
            blockers.add(tid)
            return {"task_id": tid, "cycle": True, "missing": False, "state": None, "model": "",
                    "reason": "מחזור בתלויות", "blocking": True, "blocking_root": True, "children": []}
        row = db.task(tid)
        if not row:
            blockers.add(tid)
            return {"task_id": tid, "cycle": False, "missing": True, "state": None, "model": "",
                    "reason": "לא נמצא", "blocking": True, "blocking_root": True, "children": []}
        item = dict(row)
        children = [node(dep, path + (tid,)) for dep in db.deps(tid)]
        unsatisfied_children = [c for c in children if c.get("blocking")]
        own_block = item["state"] != "PASSED"
        exact = own_block and (item["state"] not in ("WAITING_DEPENDENCY", "PENDING", "QUEUED") or not unsatisfied_children)
        blocking = own_block or bool(unsatisfied_children)
        if exact:
            blockers.add(tid)
        return {"task_id": tid, "cycle": False, "missing": False, "state": item["state"],
                "model": item["last_model_key"] or item["preferred_model_key"] or item["model_profile"],
                "reason": wait_summary(db, item), "blocking": blocking, "blocking_root": exact, "children": children}

    prerequisites = [node(dep, (task_id,)) for dep in db.deps(task_id)]
    direct_ids = db.dependents(task_id)
    seen, queue = set(direct_ids), list(direct_ids)
    while queue:
        current = queue.pop(0)
        for dependent in db.dependents(current):
            if dependent != task_id and dependent not in seen:
                seen.add(dependent)
                queue.append(dependent)
    dependents = []
    for tid in direct_ids:
        row = db.task(tid)
        dependents.append({"task_id": tid, "state": row["state"] if row else None,
                           "model": (row["last_model_key"] or row["preferred_model_key"] or row["model_profile"]) if row else "",
                           "reason": wait_summary(db, dict(row)) if row else "לא נמצא"})
    return {"exists": True, "task_id": task_id, "task": {"task_id": task_id, "state": root["state"],
            "model": root["last_model_key"] or root["preferred_model_key"] or root["model_profile"],
            "reason": wait_summary(db, dict(root))}, "prerequisites": prerequisites,
            "blocking_roots": sorted(blockers), "dependents": dependents,
            "downstream_more": max(0, len(seen) - len(direct_ids))}
