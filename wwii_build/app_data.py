"""JSON data for the live app's pages: the task:<id>, rag, plan and subtasks topics, the deliver:<id> detail block and
the extra read-only endpoints (new-task options, event facets, RAG health, task diff).

Everything here reads the same tables the server-rendered pages read (wwii_build.dashboard.page_*), so the app and
the classic pages show the same facts. Functions take the Dashboard and return plain JSON-able dicts/lists.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .explanations import task_he
from .sanitize import redact

TASK_FIELDS = ("task_id", "packet", "owner", "domain", "mode", "model_profile", "wave", "state", "state_reason",
               "attempts_count", "failed_attempts", "branch", "kind", "parent_task_id", "repair_no", "failure_class",
               "failure_summary", "repairs_count", "dispatch_priority", "preferred_model_key", "last_model_key")
ATTEMPT_FIELDS = ("id", "kind", "attempt_no", "provider", "model", "effort", "status", "failure_class", "started_at",
                  "ended_at", "input_tokens", "cached_input_tokens", "output_tokens", "reported_cost_usd", "pid",
                  "web_enabled")
BRIEF_MAX_CHARS = 60_000
DIFF_MAX_CHARS = 120_000
CELL_MAX_CHARS = 3000
RESULT_MAX_ROWS = 200
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _json(raw, default):
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return default if value is None else value


def _pick(row, fields) -> dict:
    return {k: row[k] for k in fields}


def attempt_item(row) -> dict:
    return _pick(row, ATTEMPT_FIELDS)


def artifact_item(row) -> dict:
    path = str(row["path"] or "")
    kind = "image" if row["kind"] == "screenshot" or path.lower().endswith(IMAGE_SUFFIXES) else \
        "video" if row["kind"] == "video" else "file"
    return {"id": row["id"], "task_id": row["task_id"], "kind": row["kind"], "source_path": row["source_path"],
            "description": row["description"], "media": kind}


def _state_of(dash, task_id: str) -> str | None:
    row = dash.db.task(task_id)
    return row["state"] if row else None


# ---------------------------------------------------------------------------------------------------- task detail
def _attempt_line(row) -> dict:
    item = attempt_item(row)
    return {k: item[k] for k in ("provider", "model", "status", "failure_class", "input_tokens", "cached_input_tokens",
                                 "output_tokens", "reported_cost_usd")}


def _checks(rows) -> list[dict]:
    return [{"name": r["name"], "passed": bool(r["passed"])} for r in rows]


def _repair_chain(dash, t) -> dict | None:
    db = dash.db
    if t["kind"] == "repair":
        parent = db.task(t["parent_task_id"])
        ctx = _json(t["repair_context"], {})
        return {"role": "repair", "parent_task_id": t["parent_task_id"], "parent_state": parent["state"] if parent else None,
                "repair_no": t["repair_no"], "failure_class": t["failure_class"], "model_profile": t["model_profile"],
                "failure_summary": t["failure_summary"], "violating_paths": list(ctx.get("violating_paths") or [])}
    repairs = db.q("SELECT * FROM tasks WHERE parent_task_id=? AND kind='repair' ORDER BY repair_no", (t["task_id"],))
    if not repairs and not t["repairs_count"]:
        return None
    from .repair import budget
    steps = []
    for a in db.q("SELECT * FROM task_attempts WHERE task_id=? AND kind='execute' ORDER BY id", (t["task_id"],)):
        checks = db.q("SELECT name, passed FROM test_results WHERE attempt_id=? AND via_task_id IS NULL ORDER BY id",
                      (a["id"],))
        steps.append({"type": "execute", "attempt_no": a["attempt_no"], "attempt": _attempt_line(a),
                      "checks": _checks(checks)})
    for r in repairs:
        attempts = db.q("SELECT * FROM task_attempts WHERE task_id=? ORDER BY id", (r["task_id"],))
        checks = db.q("SELECT name, passed FROM test_results WHERE via_task_id=? ORDER BY id", (r["task_id"],))
        steps.append({"type": "repair", "task_id": r["task_id"], "repair_no": r["repair_no"], "state": r["state"],
                      "failure_class": r["failure_class"], "failure_summary": (r["failure_summary"] or "")[:200],
                      "attempts": [_attempt_line(a) for a in attempts], "checks": _checks(checks)})
    return {"role": "parent", "repairs_count": t["repairs_count"], "budget": budget(dash.cfg, t),
            "failure_class": t["failure_class"], "state": t["state"], "steps": steps}


def _lineage(dash, task_id: str) -> dict:
    db = dash.db
    parents = db.q(
        "SELECT o.parent_task_id,p.reuse_count,p.promotion_threshold,p.promotion_status,p.promoted_deliver_id "
        "FROM subtask_occurrences o JOIN subtask_patterns p ON p.pattern_hash=o.pattern_hash "
        "WHERE o.child_task_id=? ORDER BY o.created_at DESC", (task_id,))
    children = db.q(
        "SELECT o.child_task_id,p.reuse_count,p.promotion_threshold FROM subtask_occurrences o "
        "JOIN subtask_patterns p ON p.pattern_hash=o.pattern_hash WHERE o.parent_task_id=? "
        "ORDER BY o.created_at DESC", (task_id,))
    out_children = []
    for row in children:
        child = db.task(row["child_task_id"]) if row["child_task_id"] else None
        extra = _json(child["extra"], {}) if child else {}
        out_children.append({"task_id": row["child_task_id"], "state": child["state"] if child else None,
                             "model_key": (child["preferred_model_key"] if child else None),
                             "mcp": list(extra.get("mcp") or []), "tools": list(extra.get("allowed_tools") or []),
                             "reuse_count": row["reuse_count"], "promotion_threshold": row["promotion_threshold"]})
    return {"parents": [dict(r) for r in parents], "children": out_children}


def task_detail(dash, tid: str) -> tuple[list[dict], dict]:
    """(attempts as items, everything else as meta) for the task:<id> topic."""
    db = dash.db
    t = db.task(tid)
    if not t:
        return [], {"exists": False, "task_id": tid}
    extra = _json(t["extra"], {})
    system = None
    if extra.get("system_task"):
        release = db.one("SELECT * FROM system_repair_releases WHERE task_id=?", (tid,))
        system = {"status": release["status"] if release else None,
                  "changed_count": len(_json(release["changed_files_json"], [])) if release else 0}
    bindings = [dict(r) for r in db.q(
        "SELECT b.source_key,b.active,c.title,c.origin_kind,c.origin_ref FROM task_context_bindings b "
        "JOIN context_sources c ON c.source_key=b.source_key WHERE b.task_id=? ORDER BY c.title", (tid,))]
    attempts = db.q("SELECT * FROM task_attempts WHERE task_id=? ORDER BY id DESC", (tid,))
    last = attempts[0] if attempts else None
    pack = None
    if last and last["context_pack_id"]:
        cp = db.one("SELECT * FROM context_packs WHERE id=?", (last["context_pack_id"],))
        if cp:
            manifest = _json(cp["manifest"], {})
            pack = {"total_bytes": cp["total_bytes"], "sha": (cp["prompt_sha256"] or "")[:16],
                    "items": [{k: i.get(k) for k in ("mode", "layer", "path", "bytes", "reason")}
                              for i in manifest.get("items") or []]}
    brief = ""
    if t["brief_path"] and (dash.cfg.repo / t["brief_path"]).is_file():
        brief = redact((dash.cfg.repo / t["brief_path"]).read_text(errors="replace")[:BRIEF_MAX_CHARS])
    is_deliver = bool(db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (tid,)))
    meta = {
        "exists": True,
        "task": {**_pick(t, TASK_FIELDS), "write_scope": _json(t["write_scope"], [])},
        "description_he": task_he(dash.cfg, t),
        "system": system,
        "allow_web": bool(extra.get("allow_web")),
        "deps": [{"task_id": d, "state": _state_of(dash, d)} for d in db.deps(tid)],
        "task_options": [dict(r) for r in db.q(
            "SELECT task_id,state FROM tasks WHERE task_id<>? AND kind<>'repair' ORDER BY wave,task_id", (tid,))],
        "context_options": [dict(r) for r in db.q(
            "SELECT source_key,title FROM context_sources WHERE active=1 ORDER BY title,source_key")],
        "bindings": bindings,
        "context_request": str(extra.get("context_request") or "").strip(),
        "planned_files": list(extra.get("evidence") or []),
        "approvals": [{k: a[k] for k in ("id", "kind", "subject", "reason")} for a in db.q(
            "SELECT * FROM approvals WHERE task_id=? AND status='pending' ORDER BY id", (tid,))],
        "chain": _repair_chain(dash, t),
        "lineage": _lineage(dash, tid),
        "is_deliver": is_deliver,
        "graph_access": dash.graph_rag.access(tid) if is_deliver else None,
        "handoff": _json(last["handoff"], None) if last else None,
        "brief": brief,
        "artifacts": [artifact_item(a) for a in db.q("SELECT * FROM artifacts WHERE task_id=? ORDER BY id DESC", (tid,))],
        "tests": [{"name": r["name"], "kind": r["kind"], "passed": bool(r["passed"]), "exit_code": r["exit_code"],
                   "duration_s": r["duration_s"], "output_tail": redact(r["output_tail"] or "")}
                  for r in db.q("SELECT * FROM test_results WHERE task_id=? ORDER BY id DESC LIMIT 30", (tid,))],
        "context_pack": pack,
        "models": dash.models_info(),
    }
    return [attempt_item(a) for a in attempts], meta


def task_diff(dash, tid: str) -> dict:
    """Changed files and unified diff of a task's worktree against its base commit (empty when there is none)."""
    t = dash.db.task(tid)
    if not t:
        return {"exists": False, "files": [], "diff": ""}
    last = dash.db.one("SELECT base_commit FROM task_attempts WHERE task_id=? ORDER BY id DESC LIMIT 1", (tid,))
    files, diff = [], ""
    if t["worktree"] and Path(t["worktree"]).exists() and last and last["base_commit"]:
        try:
            files = dash.wt.changed_files(Path(t["worktree"]), last["base_commit"])
            diff = redact(dash.wt.diff(Path(t["worktree"]), last["base_commit"], DIFF_MAX_CHARS))
        except Exception as exc:                      # a half-removed worktree must not break the page
            diff = f"(diff unavailable: {exc})"
    return {"exists": True, "files": list(files), "diff": diff}


# -------------------------------------------------------------------------------------------------- deliver detail
def deliver_detail(dash, did: str) -> dict:
    """What the Deliver page needs beyond the delivers topic row: economics, metrics, history, access, contexts."""
    db = dash.db
    econ = db.one("SELECT * FROM deliver_economics WHERE deliver_id=?", (did,))
    task = db.task(did)
    context = db.one(
        "SELECT COUNT(*) n,COALESCE(SUM(LENGTH(CAST(excerpt AS BLOB))),0) b FROM context_sources "
        "WHERE active=1 AND (deliver_id=? OR (deliver_id IS NULL AND task_id IS NULL))", (did,))
    own = db.one("SELECT COUNT(*) n FROM context_sources WHERE active=1 AND deliver_id=?", (did,))
    packs = db.one(
        "SELECT COUNT(*) n,COALESCE(SUM(total_bytes),0) b,"
        "COALESCE((SELECT total_bytes FROM context_packs WHERE task_id=? ORDER BY id DESC LIMIT 1),0) latest "
        "FROM context_packs WHERE task_id=?", (did, did))
    cost = db.one(
        "SELECT COUNT(*) n,COALESCE(SUM(reported_cost_usd),0) usd,"
        "SUM(CASE WHEN ended_at IS NOT NULL AND reported_cost_usd IS NULL THEN 1 ELSE 0 END) unknown "
        "FROM task_attempts WHERE task_id=?", (did,))
    active = db.one("SELECT COUNT(*) n FROM listener_activations WHERE status IN ('SELECTED','RUNNING') "
                    "AND (source_deliver_id=? OR target_deliver_id=?)", (did, did))
    return {
        "economics": dict(econ) if econ else None,
        "has_task": task is not None,
        "metrics": {"context_sources": int(context["n"]), "context_bytes": int(context["b"]),
                    "own_context_sources": int(own["n"]), "pack_count": int(packs["n"]),
                    "pack_bytes": int(packs["b"]), "latest_pack_bytes": int(packs["latest"]),
                    "attempt_count": int(cost["n"]), "reported_cost_usd": float(cost["usd"] or 0),
                    "unknown_cost_attempts": int(cost["unknown"] or 0), "active_listeners": int(active["n"])},
        "other_delivers": [r["deliver_id"] for r in db.q(
            "SELECT deliver_id FROM deliver_catalog WHERE enabled=1 AND deliver_id<>? ORDER BY deliver_id", (did,))],
        "graph_access": dash.graph_rag.access(did),
        "attempts": [attempt_item(a) for a in db.q("SELECT * FROM task_attempts WHERE task_id=? ORDER BY id DESC", (did,))],
        "artifacts": [artifact_item(a) for a in db.q("SELECT * FROM artifacts WHERE task_id=? ORDER BY id DESC", (did,))],
        "events": [{"id": e["id"], "at": e["at"], "event": e["event"], "detail": redact(e["detail"] or "")}
                   for e in db.q("SELECT * FROM event_log WHERE task_id=? ORDER BY id DESC LIMIT 100", (did,))],
        "contexts": [{k: c[k] for k in ("source_key", "title", "origin_kind", "origin_ref", "graph_entity_id",
                                        "excerpt")} | {"sha": (c["content_sha256"] or "")[:12]}
                     for c in db.q("SELECT * FROM context_sources WHERE active=1 AND (deliver_id=? OR "
                                   "(deliver_id IS NULL AND task_id IS NULL)) ORDER BY deliver_id DESC,updated_at DESC",
                                   (did,))],
        "runs": [dict(r) for r in db.q(
            "SELECT run_id,status,episode_id,started_at,completed_at,input_bytes,output_bytes,detail_json "
            "FROM deterministic_deliver_runs WHERE deliver_id=? ORDER BY started_at DESC LIMIT 100", (did,))],
        "models": dash.models_info(),
    }


def capability_counts(dash) -> dict[str, tuple[int, int]]:
    """{deliver_id: (capability groups, sub-capabilities)} over the active rows from system onboarding."""
    return {r["deliver_id"]: (r["g"], r["n"]) for r in dash.db.q(
        "SELECT deliver_id, COUNT(DISTINCT group_name) g, COUNT(*) n FROM deliver_capabilities WHERE active=1 "
        "GROUP BY deliver_id")}


def shelf_titles(dash, delivers: list[dict]) -> dict[str, str]:
    """Display title of every system shelf (the onboarding packet ids present among the Delivers)."""
    packets = {d.get("packet") or "system" for d in delivers if d.get("source_kind") == "system_manifest"}
    return {sid: dash.db.get_flag("onboarding_title:" + sid) or sid for sid in sorted(packets)}


# ------------------------------------------------------------------------------------------------- graph RAG console
def _console_result(item: dict, result: dict) -> dict:
    """The inline result of one console query: a table for Cypher, an answer for natural-language questions."""
    if item.get("error"):
        return {"kind": "error", "text": item["error"]}
    if item.get("mode") == "cypher" and result:
        rows = result.get("rows") if isinstance(result.get("rows"), list) else []
        columns = result.get("columns") if isinstance(result.get("columns"), list) else []
        if not columns and rows and isinstance(rows[0], dict):
            columns = list(rows[0])
        cells = [[json.dumps(r.get(c), ensure_ascii=False, default=str)[:CELL_MAX_CHARS] for c in columns]
                 for r in rows[:RESULT_MAX_ROWS] if isinstance(r, dict)]
        return {"kind": "table", "columns": [str(c) for c in columns], "rows": cells, "total": len(rows)}
    if result:
        return {"kind": "answer",
                "text": str(result.get("summary") or result.get("context") or result.get("answer") or ""),
                "entities": [str(x) for x in result.get("used_entity_names") or []],
                "evidence_ids": [str(x) for x in result.get("evidence_source_ids") or []]}
    return {"kind": "empty"}


def rag_items(dash) -> list[dict]:
    rows = dash.db.q("SELECT q.*,t.state task_state FROM graph_console_queries q "
                     "LEFT JOIN tasks t ON t.task_id=q.task_id ORDER BY q.id DESC LIMIT 20")
    out = []
    for row in rows:
        item = dict(row)
        status = item["status"]
        if status in {"QUEUED", "RUNNING"} and item.get("task_state"):
            status = item["task_state"]
        result = _json(item.get("result_json"), {})
        out.append({"id": item["id"], "status": status, "mode": item["mode"], "model_key": item["model_key"],
                    "query_text": item["query_text"], "task_id": item["task_id"], "elapsed_ms": item["elapsed_ms"] or 0,
                    "generated_cypher": item.get("generated_cypher") or result.get("cypher") or "",
                    "tokens": [int(item.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens")],
                    "created_at": item["created_at"], "result": _console_result(item, result)})
    return out


def rag_meta(dash) -> dict:
    access = [dict(r) for r in dash.db.q(
        "SELECT c.deliver_id,c.owner,c.domain,c.execution_kind,"
        "COALESCE(a.access_mode,'none') access_mode,COALESCE(a.scope_text,'') scope_text,"
        "COALESCE(a.max_chunks,6) max_chunks,COALESCE(a.max_chars,6000) max_chars "
        "FROM deliver_catalog c LEFT JOIN deliver_graph_access a ON a.deliver_id=c.deliver_id "
        "WHERE c.enabled=1 ORDER BY c.domain,c.deliver_id")]
    history = [dict(r) for r in dash.db.q("SELECT * FROM graph_rag_queries ORDER BY id DESC LIMIT 50")]
    try:
        urls = {"graph_rag_url": dash.graph_rag.base_url, "graph_cypher_url": dash.graph_rag.cypher_base_url}
    except Exception:
        urls = {"graph_rag_url": "", "graph_cypher_url": ""}
    return {"access": access, "history": history, "models": dash.models_info(), **urls}


# ------------------------------------------------------------------------------------------------------- planner
def plan_items(dash) -> list[dict]:
    db = dash.db
    out = []
    for pt in db.q("SELECT * FROM tasks WHERE kind='plan' ORDER BY created_at DESC LIMIT 20"):
        extra = _json(pt["extra"], {})
        proposals = []
        for p in db.q("SELECT * FROM plan_proposals WHERE plan_task_id=? ORDER BY id DESC", (pt["task_id"],)):
            proposal = _json(p["proposal"], {})
            approval = db.one("SELECT id FROM approvals WHERE kind='plan_proposal' AND subject=? AND status='pending'",
                              (str(p["id"]),))
            proposals.append({
                "id": p["id"], "status": p["status"], "summary": proposal.get("summary", ""),
                "questions": list(proposal.get("questions") or []),
                "tasks": [{"key": t.get("key", ""), "title": t.get("title", ""),
                           "instructions": (t.get("instructions") or "")[:300], "model_key": t.get("model_key", ""),
                           "depends_on": list(t.get("depends_on") or []), "write_scope": list(t.get("write_scope") or []),
                           "read_only": bool(t.get("read_only")), "context_files": list(t.get("context_files") or []),
                           "context_source_ids": list(t.get("context_source_ids") or []),
                           "mcp_servers": list(t.get("mcp_servers") or []),
                           "acceptance_commands": list(t.get("acceptance_commands") or [])}
                          for t in proposal.get("tasks") or []],
                "validation": _json(p["validation"], []), "approval_id": approval["id"] if approval else None,
                "created_task_ids": _json(p["created_task_ids"], [])})
        attachments = [{"name": a["original_name"], "media_type": a["media_type"], "size_bytes": a["size_bytes"],
                        "selected": bool(a["selected_at"])} for a in db.q(
            "SELECT original_name,media_type,size_bytes,selected_at FROM planner_attachments "
            "WHERE plan_task_id=? ORDER BY id", (pt["task_id"],))]
        out.append({"task_id": pt["task_id"], "state": pt["state"], "state_reason": pt["state_reason"],
                    "created_at": pt["created_at"], "prompt": extra.get("prompt", ""),
                    "attachments": attachments, "proposals": proposals})
    return out


# ----------------------------------------------------------------------------------------------------- subtasks
def subtask_items(dash) -> list[dict]:
    db = dash.db
    out = []
    rows = db.q("SELECT * FROM subtask_patterns ORDER BY CASE promotion_status WHEN 'eligible' THEN 0 "
                "WHEN 'learning' THEN 1 ELSE 2 END,last_seen_at DESC")
    from . import manual as mn
    for row in rows:
        occurrences = db.q("SELECT parent_task_id,child_task_id,source FROM subtask_occurrences "
                           "WHERE pattern_hash=? ORDER BY created_at DESC LIMIT 8", (row["pattern_hash"],))
        out.append({"pattern_hash": row["pattern_hash"], "title": row["title"], "spec": _json(row["spec_json"], {}),
                    "reuse_count": row["reuse_count"], "promotion_threshold": row["promotion_threshold"],
                    "promotion_status": row["promotion_status"], "promoted_deliver_id": row["promoted_deliver_id"],
                    "suggestion": "reusable." + mn.slugify(row["title"], "subtask").replace("-", "."),
                    "occurrences": [dict(o) for o in occurrences]})
    return out


def subtask_meta(dash) -> dict:
    parents = [dict(r) for r in dash.db.q(
        "SELECT task_id,title,note FROM tasks WHERE kind<>'repair' AND state NOT IN "
        "('RUNNING','REVIEWING','PAUSING','PASSED','CANCELLED') ORDER BY updated_at DESC LIMIT 200")]
    return {"parents": parents, "models": dash.models_info(),
            "default_threshold": int(dash.cfg.section("subtasks").get("promotion_threshold", 3))}


# --------------------------------------------------------------------------------------------- extra endpoints
def new_task_options(dash) -> dict:
    """What the new-task form lists: owners from the registry, context documents and MCP servers per provider."""
    try:
        registry = json.loads((dash.cfg.repo / dash.cfg.data["plan"]["registry"]).read_text())
        owners = sorted((registry.get("owner_roles") or {}).items())
    except (OSError, ValueError, KeyError):
        owners = []
    policy = dash.graph_rag.access("planner", planner=True)
    return {"owners": [{"owner": o, "domain": (v or {}).get("domain") or ""} for o, v in owners],
            "context_files": dash._context_index(),
            "mcp": {prov: {name: {"writes": bool(d.get("writes"))} for name, d in servers.items()}
                    for prov, servers in dash._mcp_cached().items()},
            "planner_max_chunks": int(policy["max_chunks"]), "planner_max_chars": int(policy["max_chars"]),
            "models": dash.models_info()}


def battle_request_options(dash) -> dict:
    """What the 'בקשת קרב' form shows: the chain the templates describe, and the chains created so far."""
    from . import battle_request as br
    out = {"stages": [], "chains": br.overview(dash.db), "error": ""}
    try:
        templates = br.load_templates()
    except br.BattleRequestError as exc:
        out["error"] = str(exc)
        return out
    for st in templates["stage"]:
        out["stages"].append({"stage": st["id"], "title": str(st["title"]).replace("{title}", "<שם הקרב>"),
                              "deliver": st.get("deliver", ""), "model_key": br.pick_model(dash.cfg, str(st["fit"])),
                              "allow_web": bool(st.get("allow_web", False)),
                              "depends_on": list(st.get("depends_on") or [])})
    return out


def event_facets(dash) -> dict:
    """Counts and the distinct values the events filter offers (the journal page itself comes from /api/events)."""
    db = dash.db
    latest = db.one("SELECT id,at FROM event_log ORDER BY id DESC LIMIT 1")
    return {"total": db.event_count(),
            "type_count": int(db.one("SELECT COUNT(DISTINCT event) n FROM event_log")["n"]),
            "task_count": int(db.one("SELECT COUNT(DISTINCT task_id) n FROM event_log WHERE task_id IS NOT NULL")["n"]),
            "latest": {"id": latest["id"], "at": latest["at"]} if latest else None,
            "types": [r["event"] for r in db.q("SELECT event FROM event_log GROUP BY event ORDER BY event")],
            "providers": [r["provider"] for r in db.q(
                "SELECT provider FROM event_log WHERE provider IS NOT NULL AND provider<>'' "
                "GROUP BY provider ORDER BY provider")]}


_SAFE_ID = re.compile(r"[A-Za-z0-9._:/@-]{1,200}")


def valid_id(value: str) -> bool:
    return bool(_SAFE_ID.fullmatch(value or ""))
