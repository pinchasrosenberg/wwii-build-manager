"""Manual tasks and prompt-planner proposals.

Manual task: the user picks model (+/- fallback), MCP servers, context files, dependencies,
write scope and acceptance commands. It becomes an ordinary task (kind='task',
source='manual') that the scheduler runs like any plan task.

Planner: a free-text prompt becomes PLAN/<n>, run by a capable model (routing PLAN) in
read-only mode. It returns a *proposal*; the manager validates it deterministically
(dependencies exist, no cycles, scopes, models, MCP names) and creates the tasks only
after the user approves, or immediately when the dashboard's global auto-approval is on.
"""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

from .config import Config
from .db import DB
from .models import TaskState, iso, utcnow

CODE_VERSION = 12         # v12 adds the per-task opt-in web access for research tasks (extra.allow_web)
_SLUG = re.compile(r"[^A-Za-z0-9_\-]+")

_STR_LIST = {"type": "array", "items": {"type": "string"}}
PLAN_SCHEMA: dict = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "questions": _STR_LIST,
        "tasks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "key": {"type": "string"}, "title": {"type": "string"}, "instructions": {"type": "string"},
                "description_he": {"type": "string"},
                "task_target": {"type": "string", "enum": ["project", "task_manager"]},
                "owner": {"type": "string"}, "model_key": {"type": "string"}, "fallback": {"type": "boolean"},
                "depends_on": _STR_LIST, "write_scope": _STR_LIST, "read_only": {"type": "boolean"},
                "context_files": _STR_LIST, "reference_files": _STR_LIST, "mcp_servers": _STR_LIST,
                "context_request": {"type": "string"}, "context_source_ids": _STR_LIST,
                "tool_names": _STR_LIST,
                "acceptance_commands": _STR_LIST,
                "auto_approve": {"type": "boolean"},
                "allow_web": {"type": "boolean"},
            },
            # Codex strict structured outputs require every declared property to
            # appear in ``required``.  Values may still be empty/defaulted, but
            # omitting one here makes the API reject the entire schema before
            # the planner can run.
            "required": ["key", "title", "instructions", "description_he", "task_target", "owner", "model_key", "fallback",
                         "depends_on", "write_scope", "read_only", "context_files", "reference_files",
                         "mcp_servers", "context_request", "context_source_ids", "tool_names",
                         "acceptance_commands", "auto_approve", "allow_web"]}},
    },
    "required": ["summary", "questions", "tasks"],
}


class ManualError(Exception):
    pass


def slugify(text: str, fallback: str = "task") -> str:
    s = _SLUG.sub("-", text.strip()).strip("-").lower()[:48]
    return s or fallback


def require_current_daemon(db: DB, cfg: Config) -> None:
    from .control import daemon_pid
    if daemon_pid(cfg) and int(db.get_flag("daemon_code_version") or 0) < CODE_VERSION:
        raise ManualError("the running daemon predates manual/planner tasks; restart it first "
                          "(wwii-build pause → wait for running tasks → stop → start → resume)")


def flag(value) -> bool:
    """A boolean spec field; form/JSON strings such as "0" or "false" stay False."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _paths(lines, what: str, errors: list, allow_empty=True) -> list[str]:
    out = []
    for p in lines or []:
        p = str(p).strip()
        if not p:
            continue
        if p.startswith("/") or ".." in Path(p).parts or p in (".", "./"):
            errors.append(f"{what}: '{p}' must be a relative path inside the repo")
            continue
        out.append(p.lstrip("./") if p.startswith("./") else p)
    return out


def _registry_owner(cfg: Config, owner: str) -> dict | None:
    try:
        reg = json.loads((cfg.repo / cfg.data["plan"]["registry"]).read_text())
    except (OSError, ValueError):
        return None
    return (reg.get("owner_roles") or {}).get(owner)


def validate(db: DB, cfg: Config, specs: list[dict], mcp_available: dict | None = None,
             id_prefix: str = "MANUAL/") -> tuple[list[dict], list[dict]]:
    """Returns (normalized specs with final ids, messages[{level, key, message}])."""
    msgs: list[dict] = []
    existing = {r["task_id"]: r for r in db.q("SELECT task_id, write_scope, owner, kind, wave FROM tasks WHERE kind='task'")}
    used = set(existing) | {r["task_id"] for r in db.q("SELECT task_id FROM tasks")}
    keys: dict[str, str] = {}
    out = []
    for i, sp in enumerate(specs):
        key = str(sp.get("key") or sp.get("title") or f"t{i + 1}")
        base = id_prefix + slugify(key, f"t{i + 1}")
        tid, n = base, 2
        while tid in used:
            tid, n = f"{base}-{n}", n + 1
        used.add(tid)
        keys[key] = tid
        out.append(dict(sp, key=key, task_id=tid))
    for sp in out:
        errs: list[str] = []
        warns: list[str] = []
        k = sp["key"]
        if not (str(sp.get("instructions") or "").strip() or str(sp.get("title") or "").strip()):
            errs.append("title or instructions are required")
        mk = sp.get("model_key") or ""      # "" = automatic: routed by best fit
        if mk and mk not in cfg.data["models"]:
            errs.append(f"unknown model '{mk}' (known: {', '.join(cfg.data['models'])})")
        sp["model_key"] = mk
        deps = []
        for d in sp.get("depends_on") or []:
            d = str(d).strip()
            if not d:
                continue
            if d in keys:
                deps.append(keys[d])
            elif d in existing:
                deps.append(d)
            else:
                errs.append(f"dependency '{d}' is neither an existing task nor a task in this batch")
        sp["depends_on"] = deps
        sp["read_only"] = bool(sp.get("read_only"))
        sp["write_scope"] = _paths(sp.get("write_scope"), "write scope", errs)
        target = str(sp.get("task_target") or ("task_manager" if sp.get("system_task") else "project")).strip()
        if target not in {"project", "task_manager"}:
            errs.append("task target must be 'project' or 'task_manager'")
            target = "project"
        sp["task_target"] = target
        sp["system_task"] = target == "task_manager"
        if sp["system_task"]:
            from .system_repair import SYSTEM_ROOTS, is_system_path
            if sp["read_only"]:
                errs.append("a Task Manager repair must be a write task")
            if not sp["write_scope"]:
                sp["write_scope"] = list(SYSTEM_ROOTS)
            outside = [path for path in sp["write_scope"] if not is_system_path(path)]
            if outside:
                errs.append("Task Manager repairs may write only under tools/build_manager/")
            sp["owner"] = "task_manager_maintenance"
            sp["full_checkout"] = True
        # Web access is an explicit per-task opt-in for research; the default stays closed.
        sp["allow_web"] = flag(sp.get("allow_web"))
        if sp["allow_web"] and sp["system_task"]:
            errs.append("allow_web (web research access) is not allowed for Task Manager repairs "
                        "(task_target='task_manager')")
        if not sp["write_scope"] and not sp["read_only"]:
            errs.append("a build task needs a write scope (or mark it read-only)")
        for p in sp["write_scope"]:
            for tid, r in existing.items():
                for s in json.loads(r["write_scope"]):
                    a, b = (p if p.endswith("/") else p + "/"), (s if s.endswith("/") else s + "/")
                    if a.startswith(b) or b.startswith(a):
                        warns.append(f"write scope '{p}' overlaps {tid} ({r['owner']}); they will never run in parallel")
        sp["context_files"] = _paths(sp.get("context_files"), "context file", errs)
        sp["reference_files"] = _paths(sp.get("reference_files"), "reference file", errs)
        sp["context_request"] = str(sp.get("context_request") or "").strip()[:6000]
        sp["context_source_ids"] = list(dict.fromkeys(
            str(x).strip() for x in (sp.get("context_source_ids") or []) if str(x).strip()))
        for p in sp["context_files"] + sp["reference_files"]:
            if not (cfg.repo / p).exists():
                warns.append(f"context path '{p}' does not exist in the repo working tree")
        names = [str(x).strip() for x in sp.get("mcp_servers") or sp.get("mcp") or [] if str(x).strip()]
        if names and mcp_available is not None:
            def servers(provider):
                pv = (mcp_available or {}).get(provider) or {}
                return {n: {} for n in pv} if isinstance(pv, list) else pv
            if mk:
                prov = cfg.model(mk).provider if mk in cfg.data["models"] else None
            else:
                # Automatic model: the requested MCP servers are a capability requirement. Providers that lack
                # any of them are not candidates; a single capable provider fixes the provider, and the best-fit
                # model of that provider is chosen.
                capable = [p for p in dict.fromkeys(cfg.model(k).provider for k in cfg.data["models"])
                           if all(n in servers(p) for n in names)]
                prov = capable[0] if len(capable) == 1 else None
                if prov:
                    fits = [k for k in cfg.chain("MANUAL") if cfg.model(k).provider == prov]
                    if fits:
                        sp["model_key"] = mk = fits[0]
                elif not capable:
                    errs.append(f"MCP server(s) {names} are not configured for any provider")
            if prov is not None or mk:
                pv = servers(prov)
                avail = set(pv)
                bad = [x for x in names if x not in avail]
                if bad:
                    errs.append(f"MCP server(s) {bad} not configured for {prov} (available: {sorted(avail) or 'none'})")
                for x in names:
                    if (pv or {}).get(x, {}).get("writes"):
                        warns.append(f"MCP server '{x}' is configured with write access")
        sp["mcp_servers"] = names
        sp["tool_names"] = [str(x).strip() for x in sp.get("tool_names") or [] if str(x).strip()]
        sp["auto_approve"] = bool(sp.get("auto_approve", False))
        sp["acceptance_commands"] = [str(c).strip() for c in sp.get("acceptance_commands") or [] if str(c).strip()]
        if not sp["acceptance_commands"] and not sp["auto_approve"] and db.get_flag("review_auto_approve_all") != "1":
            warns.append("no acceptance command: the task will end in REVIEW_REQUIRED (human review)")
        owner = str(sp.get("owner") or "").strip()
        sp["owner"] = owner or f"manual:{slugify(k)}"
        msgs += [{"level": "error", "key": k, "message": m} for m in errs]
        msgs += [{"level": "warning", "key": k, "message": m} for m in warns]
    # cycles inside the batch
    graph = {sp["task_id"]: [d for d in sp["depends_on"] if d.startswith(id_prefix)] for sp in out}
    state: dict[str, int] = {}

    def visit(n: str) -> bool:
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        cyc = any(visit(m) for m in graph.get(n, []) if m in graph)
        state[n] = 2
        return cyc
    if any(visit(n) for n in graph):
        msgs.append({"level": "error", "key": "*", "message": "dependency cycle inside the proposed tasks"})
    return out, msgs


def _topo(specs: list[dict]) -> list[dict]:
    by = {s["task_id"]: s for s in specs}
    done, order = set(), []

    def go(s):
        if s["task_id"] in done:
            return
        for d in s["depends_on"]:
            if d in by:
                go(by[d])
        done.add(s["task_id"])
        order.append(s)
    for s in specs:
        go(s)
    return order


def create_tasks(db: DB, cfg: Config, specs: list[dict], source: str = "manual", mcp_available: dict | None = None,
                 id_prefix: str = "MANUAL/") -> list[str]:
    require_current_daemon(db, cfg)
    specs, msgs = validate(db, cfg, specs, mcp_available, id_prefix)
    errors = [m for m in msgs if m["level"] == "error"]
    if errors:
        raise ManualError("; ".join(f"[{m['key']}] {m['message']}" for m in errors))
    now = iso(utcnow())
    created = []
    # Direct user tasks without prerequisites are immediately eligible for the
    # fast lane. Preserve the user's list order when several are created at once.
    direct = [sp for sp in _topo(specs) if source == "manual" and not sp["depends_on"]]
    top = int((db.one("SELECT COALESCE(MAX(dispatch_priority),0) top FROM tasks") or {"top": 0})["top"])
    direct_priority = {sp["task_id"]: top + len(direct) - index for index, sp in enumerate(direct)}
    with db.tx():
        for sp in _topo(specs):
            waves = [db.conn.execute("SELECT wave FROM tasks WHERE task_id=?", (d,)).fetchone()[0] for d in sp["depends_on"]]
            role = _registry_owner(cfg, sp["owner"]) or {}
            model_key = sp["model_key"] or None
            extra = {"instructions": sp.get("instructions") or "", "title": sp.get("title") or sp["key"],
                     "description_he": str(sp.get("description_he") or "").strip()[:2000],
                     "evidence": sp["context_files"], "reference_extra": sp["reference_files"],
                     "context_request": sp.get("context_request") or "",
                     "context_source_ids": sp.get("context_source_ids") or [],
                     "planned_graph_context": sp.get("planned_graph_context") or [],
                     "mcp": sp["mcp_servers"], "allowed_tools": sp["tool_names"],
                     "no_fallback": not sp.get("fallback", True), "source": source,
                     "auto_approve": bool(sp.get("auto_approve", False)),
                     "task_target": sp.get("task_target", "project"),
                     "system_task": bool(sp.get("system_task")),
                     "full_checkout": bool(sp.get("full_checkout")),
                     "allow_web": bool(sp.get("allow_web"))}
            if sp.get("battle_request"):      # marks a chain created by battle_request.py (duplicate detection)
                extra["battle_request"] = sp["battle_request"]
            # A built-in check name (e.g. "game-contract-tests") is not a shell command: that check already runs
            # for every task, so listing it again would only fail with "command not found" forever.
            builtin = {str(c.get("name")) for c in cfg.section("acceptance").get("default_commands", [])}
            commands = [c for c in sp["acceptance_commands"] if c.strip() not in builtin]
            acceptance = [{"name": f"check-{i + 1}", "argv": ["/bin/sh", "-c", c]} for i, c in enumerate(commands)]
            if sp.get("system_task"):
                acceptance += [
                    {"name": "system-compile", "argv": ["{python}", "-m", "compileall", "-q",
                                                          "tools/build_manager/wwii_build"],
                     "timeout_seconds": 120},
                    {"name": "system-manager-tests", "argv": ["{python}", "-m", "unittest", "discover", "-s",
                                                                "tools/build_manager/tests", "-p", "test_*.py"],
                     "timeout_seconds": 1200},
                    {"name": "system-cli-smoke", "argv": ["{python}", "-m", "wwii_build", "--help"],
                     "env": {"PYTHONPATH": "{worktree}/tools/build_manager"}, "timeout_seconds": 120},
                ]
            db.conn.execute(
                "INSERT INTO tasks(task_id, packet, owner, domain, mode, model_profile, lego_ids, write_scope, "
                "context_entry, brief_path, note, acceptance, extra, definition_hash, wave, state, state_reason, "
                "created_at, updated_at, kind, source, title, preferred_model_key,dispatch_priority) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sp["task_id"], "SYSTEM" if sp.get("system_task") else "MANUAL", sp["owner"],
                 "task_manager" if sp.get("system_task") else role.get("domain"),
                 "system_repair" if sp.get("system_task") else ("read_only_manual" if sp["read_only"] else "build"),
                 "MANUAL", "[]",
                 json.dumps(sp["write_scope"] or ["docs/game/reports/" + slugify(sp["key"]) + "/"]),
                 role.get("context_entry"), None, (sp.get("title") or sp["key"])[:500],
                 json.dumps(acceptance), json.dumps(extra, ensure_ascii=False), f"{source}-1",
                 1 + max(waves) if waves else 0, TaskState.PENDING.value, f"{source} task", now, now, "task", source,
                 sp.get("title") or sp["key"], model_key, direct_priority.get(sp["task_id"], 0)))
            for d in sp["depends_on"]:
                db.conn.execute("INSERT INTO task_dependencies(task_id, depends_on) VALUES(?,?)", (sp["task_id"], d))
            for item in sp.get("planned_graph_context") or []:
                if item.get("origin_kind") == "markdown" or not item.get("source_key"):
                    continue
                source_key = str(item["source_key"])
                excerpt = str(item.get("excerpt") or "")[:24000]
                digest = str(item.get("content_sha256") or hashlib.sha256(excerpt.encode()).hexdigest())
                if not db.conn.execute("SELECT 1 FROM context_sources WHERE source_key=?", (source_key,)).fetchone():
                    db.conn.execute(
                        "INSERT INTO context_sources(source_key,task_id,origin_kind,origin_ref,graph_entity_id,"
                        "graph_revision,title,excerpt,content_sha256,tags_json,active,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,'[]',1,?,?)",
                        (source_key, sp["task_id"], str(item.get("origin_kind") or "graph"),
                         str(item.get("origin_ref") or "unknown"), item.get("graph_entity_id"),
                         item.get("graph_revision"), str(item.get("title") or item.get("description") or source_key)[:500],
                         excerpt, digest, now, now))
                db.conn.execute(
                    "INSERT INTO task_context_bindings(task_id,source_key,active,created_at,updated_at) VALUES(?,?,1,?,?) "
                    "ON CONFLICT(task_id,source_key) DO UPDATE SET active=1,updated_at=excluded.updated_at",
                    (sp["task_id"], source_key, now, now))
            # The user's explicit model choice is the approval for that model (as with change-provider).
            if model_key:
                db.conn.execute("INSERT INTO approvals(task_id, kind, subject, status, reason, note, created_at, decided_at) "
                                "VALUES(?,?,?,?,?,?,?,?)", (sp["task_id"], "model", model_key, "approved",
                                                            f"chosen when creating the {source} task",
                                                            cfg.model(model_key).tier, now, now))
            created.append(sp["task_id"])
    db.event("MANUAL_TASKS_CREATED", source=source, tasks=created,
             warnings=[m["message"] for m in msgs if m["level"] == "warning"][:20],
             auto_prioritized=[task_id for task_id in created if task_id in direct_priority])
    return created


# ------------------------------------------------------------------------------- persisted subtasks
def _clean_text(value) -> str:
    return " ".join(str(value or "").split())


def _canonical_subtask_spec(spec: dict) -> dict:
    """Stable, reusable task contract. Volatile parent/task ids are intentionally excluded."""
    unique = lambda values: sorted({str(value).strip() for value in (values or []) if str(value).strip()})
    canonical = {
        "title": _clean_text(spec.get("title") or spec.get("key")),
        "instructions": _clean_text(spec.get("instructions")),
        "owner": str(spec.get("owner") or "").strip(),
        "model_key": str(spec.get("model_key") or "").strip(),
        "fallback": bool(spec.get("fallback", True)),
        "read_only": bool(spec.get("read_only")),
        "context_files": unique(spec.get("context_files")),
        "context_request": _clean_text(spec.get("context_request")),
        "context_source_ids": unique(spec.get("context_source_ids")),
        "reference_files": unique(spec.get("reference_files")),
        "mcp_servers": unique(spec.get("mcp_servers") or spec.get("mcp")),
        "tool_names": unique(spec.get("tool_names") or spec.get("allowed_tools")),
        "write_scope": unique(spec.get("write_scope")),
        "acceptance_commands": unique(spec.get("acceptance_commands")),
        "auto_approve": bool(spec.get("auto_approve", False)),
    }
    # Present only when opted in, so the hashes of existing (web-closed) patterns stay unchanged.
    if flag(spec.get("allow_web")):
        canonical["allow_web"] = True
    return canonical


def _subtask_spec_from_row(db: DB, task_id: str) -> dict:
    row = db.task(task_id)
    if not row:
        raise ManualError(f"unknown subtask {task_id}")
    extra = json.loads(row["extra"] or "{}")
    commands = []
    for check in json.loads(row["acceptance"] or "[]"):
        argv = check.get("argv") or []
        if len(argv) >= 3 and argv[:2] == ["/bin/sh", "-c"]:
            commands.append(argv[2])
    return _canonical_subtask_spec({
        "title": row["title"] or row["note"] or task_id,
        "instructions": extra.get("instructions"),
        "owner": row["owner"],
        "model_key": row["preferred_model_key"] or "",
        "fallback": not extra.get("no_fallback", False),
        "read_only": str(row["mode"]).startswith("read_only"),
        "context_files": extra.get("evidence"),
        "context_request": extra.get("context_request"),
        "context_source_ids": extra.get("context_source_ids"),
        "reference_files": extra.get("reference_extra"),
        "mcp_servers": extra.get("mcp"),
        "tool_names": extra.get("allowed_tools"),
        "write_scope": json.loads(row["write_scope"] or "[]"),
        "acceptance_commands": commands,
        "auto_approve": bool(extra.get("auto_approve", False)),
        "allow_web": bool(extra.get("allow_web", False)),
    })


def _subtask_pattern_hash(spec: dict) -> str:
    body = json.dumps(_canonical_subtask_spec(spec), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def record_subtask_usage(db: DB, cfg: Config, parent_task_id: str, child_task_ids: list[str],
                         source: str = "agent") -> list[str]:
    """Record actual task instances. Proposals do not count until they have been created."""
    if not db.task(parent_task_id):
        raise ManualError(f"unknown parent task {parent_task_id}")
    threshold = max(2, int(cfg.section("subtasks").get("promotion_threshold", 3)))
    hashes = []
    now = iso(utcnow())
    with db.tx():
        for child_id in child_task_ids:
            spec = _subtask_spec_from_row(db, child_id)
            pattern_hash = _subtask_pattern_hash(spec)
            db.conn.execute(
                "INSERT INTO subtask_patterns(pattern_hash,title,spec_json,reuse_count,promotion_threshold,"
                "promotion_status,first_seen_at,last_seen_at) VALUES(?,?,?,0,?,'learning',?,?) "
                "ON CONFLICT(pattern_hash) DO UPDATE SET title=excluded.title,spec_json=excluded.spec_json,"
                "promotion_threshold=excluded.promotion_threshold,last_seen_at=excluded.last_seen_at",
                (pattern_hash, spec["title"] or child_id, json.dumps(spec, ensure_ascii=False, sort_keys=True),
                 threshold, now, now))
            cur = db.conn.execute(
                "INSERT OR IGNORE INTO subtask_occurrences(pattern_hash,parent_task_id,child_task_id,source,created_at) "
                "VALUES(?,?,?,?,?)", (pattern_hash, parent_task_id, child_id, source, now))
            if cur.rowcount:
                db.conn.execute(
                    "UPDATE subtask_patterns SET reuse_count=reuse_count+1,last_seen_at=?,"
                    "promotion_status=CASE WHEN reuse_count+1>=promotion_threshold AND promotion_status='learning' "
                    "THEN 'eligible' ELSE promotion_status END WHERE pattern_hash=?", (now, pattern_hash))
            hashes.append(pattern_hash)
    db.event("SUBTASK_USAGE_RECORDED", task_id=parent_task_id, source=source,
             children=child_task_ids, patterns=hashes)
    return hashes


def create_subtasks(db: DB, cfg: Config, parent_task_id: str, specs: list[dict],
                    mcp_available: dict | None = None, source: str = "agent") -> list[str]:
    """Decompose a queued task into saved children with their own context/model/tools."""
    require_current_daemon(db, cfg)
    parent = db.task(parent_task_id)
    if not parent:
        raise ManualError(f"unknown parent task {parent_task_id}")
    if parent["kind"] == "repair" or parent["state"] in {
            TaskState.RUNNING.value, TaskState.REVIEWING.value, TaskState.PAUSING.value,
            TaskState.PASSED.value, TaskState.CANCELLED.value}:
        raise ManualError(f"cannot decompose {parent_task_id} while it is {parent['state']}")
    maxn = max(1, int(cfg.section("subtasks").get("max_per_parent", 12)))
    if not specs or len(specs) > maxn:
        raise ManualError(f"a decomposition must contain 1..{maxn} subtasks")
    inherited = db.deps(parent_task_id)
    prepared = []
    for raw in specs:
        sp = dict(raw)
        requested = [str(x).strip() for x in sp.get("depends_on") or [] if str(x).strip()]
        if parent_task_id in requested:
            raise ManualError("a subtask cannot depend on its parent because the parent waits for the subtask")
        sp["depends_on"] = list(dict.fromkeys([*inherited, *requested]))
        prepared.append(sp)
    prefix = f"MANUAL/sub-{slugify(parent_task_id.replace('/', '-'))}-"
    created = create_tasks(db, cfg, prepared, source="subtask", mcp_available=mcp_available, id_prefix=prefix)
    parent_extra = json.loads(parent["extra"] or "{}")
    depth = int(parent_extra.get("subtask_depth", 0)) + 1
    now = iso(utcnow())
    with db.tx():
        for child_id in created:
            child = db.task(child_id)
            extra = json.loads(child["extra"] or "{}")
            extra.update(subtask_of=parent_task_id, subtask_depth=depth, subtask_source=source)
            db.conn.execute("UPDATE tasks SET extra=? WHERE task_id=?",
                            (json.dumps(extra, ensure_ascii=False), child_id))
            db.conn.execute("INSERT OR IGNORE INTO task_dependencies(task_id,depends_on) VALUES(?,?)",
                            (parent_task_id, child_id))
        max_wave = max(int(db.task(child_id)["wave"] or 0) for child_id in created)
        db.conn.execute("UPDATE tasks SET wave=MAX(wave,?),state=?,state_reason=?,updated_at=? WHERE task_id=?",
                        (max_wave + 1, TaskState.PENDING.value, "waiting for saved subtasks", now, parent_task_id))
    record_subtask_usage(db, cfg, parent_task_id, created, source)
    db.event("SUBTASKS_CREATED", task_id=parent_task_id, source=source, children=created, depth=depth)
    return created


def promote_subtask_pattern(db: DB, cfg: Config, pattern_hash: str, deliver_id: str,
                            owner: str = "", domain: str = "", description: str = "") -> str:
    """Explicitly promote an eligible reused pattern to a governed Deliver template."""
    pattern = db.one("SELECT * FROM subtask_patterns WHERE pattern_hash=?", (pattern_hash,))
    if not pattern:
        raise ManualError("unknown subtask pattern")
    if pattern["promotion_status"] == "promoted":
        raise ManualError(f"pattern already promoted to {pattern['promoted_deliver_id']}")
    if int(pattern["reuse_count"]) < int(pattern["promotion_threshold"]):
        raise ManualError(f"pattern needs {pattern['promotion_threshold']} uses; it has {pattern['reuse_count']}")
    if db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (deliver_id,)):
        raise ManualError(f"Deliver {deliver_id} already exists")
    spec = json.loads(pattern["spec_json"])
    now = iso(utcnow())
    evidence = [dict(row) for row in db.q(
        "SELECT parent_task_id,child_task_id,source,created_at FROM subtask_occurrences "
        "WHERE pattern_hash=? ORDER BY created_at", (pattern_hash,))]
    with db.tx():
        db.conn.execute(
            "INSERT INTO deliver_catalog(deliver_id,owner,domain,description,source_kind,source_ref,execution_kind,"
            "definition_hash,enabled,availability,updated_at,preferred_model_key) "
            "VALUES(?,?,?,?,? ,?,'worker',?,1,'available',?,?)",
            (deliver_id, owner or spec.get("owner"), domain or None,
             description or spec.get("title") or "Promoted reusable subtask",
             "subtask_promotion", "subtask-pattern:" + pattern_hash, pattern_hash, now, spec.get("model_key")))
        db.conn.execute(
            "INSERT INTO deliver_templates(deliver_id,pattern_hash,instructions,model_key,context_files_json,"
            "mcp_servers_json,tool_names_json,write_scope_json,acceptance_commands_json,promotion_evidence_json,created_at,"
            "allow_web) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (deliver_id, pattern_hash, spec.get("instructions") or "", spec.get("model_key"),
             json.dumps(spec.get("context_files") or [], ensure_ascii=False),
             json.dumps(spec.get("mcp_servers") or [], ensure_ascii=False),
             json.dumps(spec.get("tool_names") or [], ensure_ascii=False),
             json.dumps(spec.get("write_scope") or [], ensure_ascii=False),
             json.dumps(spec.get("acceptance_commands") or [], ensure_ascii=False),
             json.dumps(evidence, ensure_ascii=False), now, 1 if spec.get("allow_web") else 0))
        db.conn.execute("UPDATE subtask_patterns SET promotion_status='promoted',promoted_deliver_id=?,last_seen_at=? "
                        "WHERE pattern_hash=?", (deliver_id, now, pattern_hash))
    db.event("SUBTASK_PATTERN_PROMOTED", task_id=deliver_id, pattern_hash=pattern_hash,
             reuse_count=pattern["reuse_count"], evidence_count=len(evidence), allow_web=bool(spec.get("allow_web")))
    return deliver_id


def set_template_allow_web(db: DB, deliver_id: str, allow_web: bool) -> None:
    """Opt a Deliver template in to (or out of) web research access for the tasks created from it."""
    if not db.one("SELECT 1 FROM deliver_templates WHERE deliver_id=?", (deliver_id,)):
        raise ManualError(f"Deliver {deliver_id} has no template")
    db.x("UPDATE deliver_templates SET allow_web=? WHERE deliver_id=?", (1 if allow_web else 0, deliver_id))
    db.event("DELIVER_TEMPLATE_WEB_ACCESS", task_id=deliver_id, allow_web=bool(allow_web))


def template_task_spec(db: DB, deliver_id: str) -> dict:
    """A create_tasks() spec from a promoted Deliver template, including its allow_web opt-in."""
    row = db.one("SELECT t.*,c.owner FROM deliver_templates t JOIN deliver_catalog c ON c.deliver_id=t.deliver_id "
                 "WHERE t.deliver_id=?", (deliver_id,))
    if not row:
        raise ManualError(f"Deliver {deliver_id} has no template")
    pattern = db.one("SELECT spec_json FROM subtask_patterns WHERE pattern_hash=?", (row["pattern_hash"],))
    base_spec = json.loads(pattern["spec_json"]) if pattern else {}
    return {**base_spec, "key": deliver_id.replace("/", "-"), "title": base_spec.get("title") or deliver_id,
            "instructions": row["instructions"] or "", "owner": row["owner"] or base_spec.get("owner") or "",
            "model_key": row["model_key"] or "",
            "context_files": json.loads(row["context_files_json"] or "[]"),
            "mcp_servers": json.loads(row["mcp_servers_json"] or "[]"),
            "tool_names": json.loads(row["tool_names_json"] or "[]"),
            "write_scope": json.loads(row["write_scope_json"] or "[]"),
            "acceptance_commands": json.loads(row["acceptance_commands_json"] or "[]"),
            "allow_web": bool(row["allow_web"])}


# ------------------------------------------------------------------------------- planner
def create_plan(db: DB, cfg: Config, prompt: str, model_key: str | None = None,
                mode: str = "plan_build", mcp_servers: list[str] | None = None) -> str:
    require_current_daemon(db, cfg)
    if not prompt.strip():
        raise ManualError("the prompt is empty")
    if model_key and model_key not in cfg.data["models"]:
        raise ManualError(f"unknown model '{model_key}'")
    selected_model_key = model_key or None      # None = automatic: routed by best fit for PLAN
    if not model_key and not cfg.chain("PLAN"):
        raise ManualError("PLAN routing has no configured model")
    if mode not in {"plan_build", "advise_next", "graph_query"}:
        raise ManualError("unknown prompt mode")
    mcp_servers = [str(name).strip() for name in (mcp_servers or []) if str(name).strip()]
    n = db.one("SELECT COUNT(*) n FROM tasks WHERE kind='plan'")["n"] + 1
    tid = f"PLAN/{n}"
    now = iso(utcnow())
    top = int(db.one("SELECT COALESCE(MAX(dispatch_priority),0) top FROM tasks")["top"])
    db.x("INSERT INTO tasks(task_id, packet, owner, domain, mode, model_profile, lego_ids, write_scope, context_entry, "
         "brief_path, note, acceptance, extra, definition_hash, wave, state, state_reason, created_at, updated_at, kind, "
         "source, title, preferred_model_key,dispatch_priority) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (tid, "PLAN", "planner", None, "read_only_plan", "PLAN", "[]", "[]", None, None, prompt[:500], "[]",
          json.dumps({"prompt": prompt, "prompt_mode": mode, "requested_mcp": mcp_servers}, ensure_ascii=False), "plan-1", 0, TaskState.PENDING.value,
          "waiting for the planner model", now, now, "plan", "planner", prompt.strip().splitlines()[0][:120], selected_model_key,
          top + 1))
    if model_key:
        db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at, decided_at) VALUES(?,?,?,?,?,?,?)",
             (tid, "model", model_key, "approved", "chosen for the planner", now, now))
    db.event("PLAN_REQUESTED", task_id=tid, model_key=selected_model_key,
             model_selection="manual" if model_key else "default", chars=len(prompt), mode=mode,
             mcp_servers=mcp_servers, auto_prioritized=True, dispatch_priority=top + 1)
    return tid


def create_context_plan(db: DB, cfg: Config, spec: dict, context_request: str,
                        model_key: str | None = None, mcp_available: dict | None = None) -> str:
    """Queue a one-task plan that may choose only Jev-admitted graph and Markdown context.

    The worker contract is validated and locked before the planner runs. The planner may
    select context, but it cannot silently change the user's model, scope or dependencies.
    """
    request = str(context_request or "").strip()[:6000]
    if not request:
        raise ManualError("the context request is empty")
    normalized, msgs = validate(db, cfg, [dict(spec, context_request=request)], mcp_available)
    errors = [m for m in msgs if m["level"] == "error"]
    if errors:
        raise ManualError("; ".join(f"[{m['key']}] {m['message']}" for m in errors))
    target = dict(normalized[0])
    target.pop("task_id", None)
    search_prompt = "\n".join([
        request,
        "",
        "פרטי המשימה שעבורה נדרש הקונטקסט:",
        str(target.get("title") or ""),
        str(target.get("instructions") or ""),
    ]).strip()
    tid = create_plan(db, cfg, search_prompt, model_key, "graph_query", target.get("mcp_servers") or [])
    row = db.task(tid)
    extra = json.loads(row["extra"] or "{}")
    extra.update(context_request=request, context_target_spec=target, context_plan=True)
    db.x("UPDATE tasks SET extra=?,title=?,note=? WHERE task_id=?",
         (json.dumps(extra, ensure_ascii=False), f"בחירת קונטקסט: {target.get('title') or target.get('key')}",
          request[:500], tid))
    db.event("CONTEXT_PLAN_REQUESTED", task_id=tid, chars=len(request),
             target_title=target.get("title"), worker_model=target.get("model_key"))
    return tid


def _context_markdown_paths(cfg: Config) -> list[Path]:
    paths: list[Path] = []
    for root in ("context/game", "docs/game", "context/systems"):
        base = cfg.repo / root
        if base.is_dir():
            paths.extend(p for p in base.rglob("*.md") if p.is_file())
    return sorted(set(paths), key=lambda p: str(p.relative_to(cfg.repo)))


def plan_prompt(cfg: Config, db: DB, registry: dict, plan_row, mcp_available: dict,
                graph_context: list[dict] | None = None) -> str:
    extra = json.loads(plan_row["extra"] or "{}")
    tasks = db.q("SELECT task_id, owner, state, model_profile, write_scope FROM tasks WHERE kind='task' "
                 "ORDER BY wave, task_id")
    rows = "\n".join(f"- {t['task_id']} | owner {t['owner']} | {t['state']} | {t['model_profile']} | "
                     f"scope {', '.join(json.loads(t['write_scope'])[:3])}" for t in tasks)
    owners = "\n".join(f"- {o} ({v.get('domain')})" for o, v in sorted((registry.get("owner_roles") or {}).items()))
    models = "\n".join(f"- {k}: {m.provider}/{m.model} ({m.tier})" for k, m in cfg.models().items())
    ctx_files = [str(p.relative_to(cfg.repo)) for p in _context_markdown_paths(cfg)][:300]
    mcps = "\n".join(f"- {prov}: {', '.join(sorted(names)) or 'none'}" for prov, names in mcp_available.items())
    maxn = int(cfg.section("planner").get("max_tasks", 20))
    mode = extra.get("prompt_mode", "plan_build")
    graph_console_only = bool(extra.get("graph_console_only"))
    context_target = extra.get("context_target_spec") if isinstance(extra.get("context_target_spec"), dict) else None
    mode_rule = {
        "plan_build": "Turn the request into a complete build plan. Infer and include missing enabling work.",
        "advise_next": "Explain what should be done next, identify gaps, and propose the smallest useful task set.",
        "graph_query": "Answer from the selected graph evidence, state unknowns, and propose tasks needed to resolve them.",
    }.get(mode, "Turn the request into a complete build plan.")
    if graph_console_only:
        mode_rule = ("Answer the graph question directly in summary using only the selected evidence. "
                     "State source limits and unknowns. Return questions only when the graph cannot disambiguate. "
                     "Return tasks=[] because this console request must never create build work.")
    evidence = "\n\n".join(
        f"SOURCE_ID {item['id']} · {item['source_key']} ({item.get('origin_ref') or item.get('origin_kind')}):\n{item['excerpt']}"
        for item in (graph_context or [])) or "(no graph evidence selected by Jev)"
    context_rules = []
    if context_target:
        context_rules = [
            "", "## LOCKED ONE-TASK CONTEXT PLAN",
            "Return exactly one task. Preserve the locked task contract below. Your only design decision is which",
            "Markdown paths and SOURCE_ID values provide the smallest sufficient context for that worker.",
            "Use context_files only for Markdown paths from the CONTEXT INDEX. Use context_source_ids only for",
            "SOURCE_ID values present in JEV-SELECTED CONTEXT. Do not add facts or sources that are not listed.",
            "LOCKED TASK: " + json.dumps(context_target, ensure_ascii=False, sort_keys=True),
        ]
    return "\n".join([
        f"TASK_ID: {plan_row['task_id']}",
        "You are a task PLANNER for a deterministic build farm. Do not implement anything and do not edit files.",
        mode_rule,
        "", "## RULES",
        f"- At most {maxn} tasks. Each task has one owner, a narrow write_scope (relative paths; directories end with /),",
        "  and instructions a worker can follow without this conversation.",
        "- depends_on may name other tasks in your list (by key) or EXISTING task ids below. Never invent other ids.",
        "- Prefer cheap models (sol, luna, sonnet). Use opus/astra only if the request explicitly needs deep reasoning.",
        "- context_files: only files from the CONTEXT INDEX that the worker truly needs. mcp_servers: only listed names.",
        "- acceptance_commands: real shell commands that deterministically prove the task (tests, schema checks). "
        "Never list a built-in check name such as game-contract-tests: built-in checks always run anyway.",
        "- task_target='task_manager' only for repairs or features of this Task Manager/dashboard/scheduler/MCP. "
        "Those tasks use the protected tools/build_manager/ scope, full tests and staged activation. Use "
        "task_target='project' for game, research and content work.",
        "- read_only=true for research/report tasks (no files changed). Ask in `questions` when the request is ambiguous.",
        "- allow_web=false by default. Set allow_web=true only for a research task that truly needs live web sources; "
        "never for task_target='task_manager'.",
        "- Historical facts must come from evidence tasks, never be invented.",
        "- Detect missing contracts, context, dependencies, listeners, tests and review work implied by the request.",
        "- The tasks you propose are saved subtasks/work items, not Deliver definitions. Never create a Deliver merely "
        "because you decomposed the request. Reuse is measured later and promotion is a separate explicit action.",
        "- tool_names lists only the local tools the worker needs; keep it narrow. MCP access stays in mcp_servers.",
        "- Context evidence below was admitted by Jev. Put chosen SOURCE_ID values in context_source_ids.",
        "  Do not claim facts absent from it; create a research task for unknowns.",
        "- Uploaded files appear only after Jev selected them. Images are attached natively when the chosen provider "
        "supports it; other selected files are available at their origin_ref. Use only those selected uploads.",
        f"- MCP tools requested for downstream tasks: {', '.join(extra.get('requested_mcp') or []) or '(none)' }.",
        *context_rules,
        "", "## USER REQUEST", extra.get("prompt", ""),
        "", "## JEV-SELECTED CONTEXT", evidence,
        "", "## EXISTING TASKS", rows or "(none)",
        "", "## OWNERS (registry roles; or a new 'manual:<name>' owner)", owners or "(none)",
        "", "## MODELS", models,
        "", "## MCP SERVERS", mcps or "(none)",
        "", "## CONTEXT INDEX", "\n".join(ctx_files),
        "", "## RETURN FORMAT",
        "Write a clear Hebrew description_he for every proposed task, explaining what it does. "
        "One JSON object: {summary, questions[], tasks[{key, title, instructions, description_he, task_target, owner, model_key, fallback, depends_on[], "
        "write_scope[], read_only, context_files[], context_source_ids[], context_request, reference_files[], "
        "mcp_servers[], tool_names[], acceptance_commands[], auto_approve, allow_web}] }.",
    ]) + "\n"


def planner_graph_candidates(db: DB, prompt: str, limit: int = 16) -> list[dict]:
    """Deterministic graph search. Jev decides which results may enter the prompt."""
    tokens = {t.casefold() for t in re.findall(r"[\w.-]{3,}", prompt, flags=re.UNICODE)}
    rows = [dict(r) for r in db.q(
        "SELECT source_key,origin_kind,origin_ref,graph_entity_id,title,excerpt,content_sha256 "
        "FROM context_sources WHERE active=1 ORDER BY updated_at DESC LIMIT 500")]
    scored = []
    for row in rows:
        title = (row.get("title") or "").casefold()
        body = (row.get("excerpt") or "").casefold()
        origin = (row.get("origin_ref") or "").casefold()
        score = sum(5 for token in tokens if token in title) + sum(2 for token in tokens if token in origin) + \
                sum(1 for token in tokens if token in body)
        if score:
            scored.append((score, row))
    out = []
    for score, row in sorted(scored, key=lambda item: (-item[0], item[1]["source_key"]))[:max(0, limit)]:
        cid = "graph-context:" + row["content_sha256"][:16]
        out.append({"id": cid, "source_key": row["source_key"], "description":
                    f"{row['title']} · {row['origin_kind']} · {row['origin_ref']} · relevance {score}",
                    "execution_kind": "graph_context", "excerpt": row["excerpt"],
                    "origin_kind": row["origin_kind"], "origin_ref": row["origin_ref"],
                    "graph_entity_id": row.get("graph_entity_id"),
                    "content_sha256": row["content_sha256"], "title": row["title"]})
    return out


def planner_markdown_candidates(cfg: Config, prompt: str, limit: int = 12) -> list[dict]:
    """Search allowed Markdown context by path and content before Jev admission."""
    tokens = {t.casefold() for t in re.findall(r"[\w.-]{3,}", prompt, flags=re.UNICODE)}
    scored: list[tuple[int, str, str, str]] = []
    for path in _context_markdown_paths(cfg):
        rel = str(path.relative_to(cfg.repo))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:240000]
        except OSError:
            continue
        rel_fold, text_fold = rel.casefold(), text.casefold()
        matches = [(text_fold.find(token), token) for token in tokens if token in text_fold]
        score = sum(5 for token in tokens if token in rel_fold) + len(matches)
        if not score:
            continue
        first = min((pos for pos, _ in matches if pos >= 0), default=0)
        start = max(0, first - 350)
        excerpt = re.sub(r"\n{3,}", "\n\n", text[start:start + 1800]).strip()
        scored.append((score, rel, excerpt, hashlib.sha256(text.encode()).hexdigest()))
    out = []
    for score, rel, excerpt, digest in sorted(scored, key=lambda item: (-item[0], item[1]))[:max(0, limit)]:
        out.append({"id": "md-context:" + hashlib.sha256(rel.encode()).hexdigest()[:16],
                    "source_key": rel, "description": f"Markdown · {rel} · relevance {score}",
                    "execution_kind": "markdown_context", "excerpt": excerpt,
                    "origin_kind": "markdown", "origin_ref": rel, "graph_entity_id": None,
                    "content_sha256": digest, "title": Path(rel).name})
    return out


def store_proposal(db: DB, cfg: Config, plan_row, proposal: dict | None, raw: str | None,
                   mcp_available: dict) -> tuple[int, list[dict]]:
    extra = json.loads(plan_row["extra"] or "{}")
    pre_msgs: list[dict] = []
    if not isinstance(proposal, dict) or not isinstance(proposal.get("tasks"), list):
        msgs = [{"level": "error", "key": "*", "message": "planner did not return a valid JSON proposal"}]
        proposal = {"summary": "", "questions": [], "tasks": [], "raw": (raw or "")[-4000:]}
    else:
        target = extra.get("context_target_spec") if isinstance(extra.get("context_target_spec"), dict) else None
        proposed_tasks = proposal["tasks"]
        if target:
            if len(proposed_tasks) != 1:
                pre_msgs.append({"level": "error", "key": "*",
                                 "message": "a context plan must return exactly one task"})
            else:
                suggestion = proposed_tasks[0]
                allowed_md = {str(p.relative_to(cfg.repo)) for p in _context_markdown_paths(cfg)}
                chosen_md = [p for p in suggestion.get("context_files") or [] if p in allowed_md]
                chosen_ids = [str(x) for x in suggestion.get("context_source_ids") or []]
                merged = dict(target)
                merged["context_files"] = list(dict.fromkeys([*(target.get("context_files") or []), *chosen_md]))
                merged["context_source_ids"] = list(dict.fromkeys(chosen_ids))
                merged["context_request"] = extra.get("context_request") or ""
                proposal["tasks"] = [merged]
                proposal["source"] = "context-planner"
        admitted = {str(item.get("id")): item for item in (extra.get("jev_selected_context") or [])
                    if isinstance(item, dict) and item.get("id")}
        for task in proposal["tasks"]:
            ids = [str(x) for x in task.get("context_source_ids") or [] if str(x) in admitted]
            task["context_source_ids"] = ids
            task["planned_graph_context"] = [admitted[item_id] for item_id in ids]
            for item in task["planned_graph_context"]:
                if item.get("origin_kind") == "markdown" and item.get("origin_ref"):
                    task.setdefault("context_files", []).append(str(item["origin_ref"]))
            task["context_files"] = list(dict.fromkeys(task.get("context_files") or []))
        maxn = int(cfg.section("planner").get("max_tasks", 20))
        if len(proposal["tasks"]) > maxn:
            proposal["tasks"] = proposal["tasks"][:maxn]
        _, msgs = validate(db, cfg, proposal["tasks"], mcp_available, id_prefix=_plan_prefix(plan_row["task_id"]))
        msgs = pre_msgs + msgs
        if not proposal["tasks"] and not extra.get("graph_console_only"):
            msgs.append({"level": "error", "key": "*", "message": "the proposal contains no tasks"})
    status = "invalid" if any(m["level"] == "error" for m in msgs) else "pending"
    pid = db.x("INSERT INTO plan_proposals(plan_task_id, created_at, status, request, proposal, validation) "
               "VALUES(?,?,?,?,?,?)", (plan_row["task_id"], iso(utcnow()), status, extra.get("prompt", ""),
                                       json.dumps(proposal, ensure_ascii=False), json.dumps(msgs, ensure_ascii=False)))
    db.event("PLAN_PROPOSAL", task_id=plan_row["task_id"], proposal_id=pid, status=status,
             tasks=len(proposal.get("tasks") or []), errors=sum(m["level"] == "error" for m in msgs))
    return pid, msgs


def _plan_prefix(plan_task_id: str) -> str:
    return f"MANUAL/plan{plan_task_id.split('/')[-1]}-"


def apply_proposal(db: DB, cfg: Config, proposal_id: int, mcp_available: dict | None = None) -> list[str]:
    p = db.one("SELECT * FROM plan_proposals WHERE id=?", (proposal_id,))
    if not p:
        raise ManualError(f"no proposal #{proposal_id}")
    if p["status"] != "pending":
        raise ManualError(f"proposal #{proposal_id} is {p['status']}")
    prop = json.loads(p["proposal"])
    ids = create_tasks(db, cfg, prop["tasks"], source=prop.get("source", "planner"), mcp_available=mcp_available,
                       id_prefix=prop.get("id_prefix") or _plan_prefix(p["plan_task_id"]))
    if prop.get("followup_of"):
        depth = int(json.loads(db.task(prop["followup_of"])["extra"] or "{}").get("followup_depth", 0)) + 1
        for tid in ids:
            ex = json.loads(db.task(tid)["extra"])
            ex.update(followup_of=prop["followup_of"], followup_depth=depth)
            db.x("UPDATE tasks SET extra=? WHERE task_id=?", (json.dumps(ex, ensure_ascii=False), tid))
        record_subtask_usage(db, cfg, prop["followup_of"], ids, "followup")
    else:
        # A planner decomposition is persisted as ordinary tasks. Repeated task
        # contracts are learned here, but never become Delivers automatically.
        record_subtask_usage(db, cfg, p["plan_task_id"], ids, prop.get("source", "planner"))
    db.x("UPDATE plan_proposals SET status='approved', decided_at=?, created_task_ids=? WHERE id=?",
         (iso(utcnow()), json.dumps(ids), proposal_id))
    return ids


# ------------------------------------------------------------------------------- follow-ups
def _within(path: str, scope: list[str]) -> bool:
    p = path if path.endswith("/") else path + "/"
    return any(p.startswith(s if s.endswith("/") else s + "/") for s in scope)


def followup_prefix(parent_id: str) -> str:
    return f"MANUAL/fu-{slugify(parent_id.replace('/', '-'))}-"


def propose_followups(db: DB, cfg: Config, parent_id: str, items: list, mcp_available: dict | None = None) -> dict:
    """A worker asked for follow-up tasks. Called once, when the parent passes.
    Safe ones (cheap model, inside the parent's write scope, valid) are created; the rest wait for approval."""
    fc = cfg.section("followups")
    if not fc.get("enabled", True) or not items:
        return {"created": [], "proposal": None, "rejected": []}
    parent = db.task(parent_id)
    pextra = json.loads(parent["extra"] or "{}")
    depth = int(pextra.get("followup_depth", 0)) + 1
    rejected = []
    if depth > int(fc.get("max_depth", 2)):
        db.event("FOLLOWUP_REJECTED", task_id=parent_id, reason=f"depth {depth} > followups.max_depth", count=len(items))
        return {"created": [], "proposal": None, "rejected": [str(i.get("key")) for i in items]}
    items = [i for i in items if isinstance(i, dict)][: int(fc.get("max_per_task", 5))]
    prefix = followup_prefix(parent_id)
    existing = {r["task_id"] for r in db.q("SELECT task_id FROM tasks WHERE task_id LIKE ?", (prefix + "%",))}
    specs = []
    for it in items:
        sp = dict(it)
        sp.setdefault("title", sp.get("key"))
        if prefix + slugify(str(sp.get("key") or sp.get("title") or "")) in existing:
            continue                                   # never duplicate a follow-up
        sp["owner"] = sp.get("owner") or parent["owner"]
        sp["model_key"] = sp.get("model_key") or ""
        sp["depends_on"] = list(dict.fromkeys([parent_id, *(sp.get("depends_on") or [])]))
        sp["fallback"] = True
        sp["_depth"] = depth
        if sp.get("reason"):
            sp["instructions"] = (sp.get("instructions") or "") + f"\n\n(Requested by {parent_id}: {sp['reason']})"
        specs.append(sp)
    if not specs:
        return {"created": [], "proposal": None, "rejected": rejected}
    norm, msgs = validate(db, cfg, specs, mcp_available, id_prefix=prefix)
    errors = {m["key"] for m in msgs if m["level"] == "error"}
    pscope = json.loads(parent["write_scope"])
    mode = fc.get("auto_create", "safe")               # safe | always | never

    def safe(sp) -> bool:
        m = cfg.data["models"].get(sp["model_key"], {})
        return (sp["key"] not in errors and m.get("tier") != "premium" and not sp.get("mcp_servers")
                and (sp.get("read_only") or all(_within(p, pscope) for p in sp["write_scope"])))
    auto = [sp for sp in norm if mode == "always" and sp["key"] not in errors or mode == "safe" and safe(sp)]
    ask = [sp for sp in norm if sp not in auto]
    created = []
    if auto:
        created = create_tasks(db, cfg, auto, source="followup", mcp_available=mcp_available, id_prefix=prefix)
        for tid in created:
            ex = json.loads(db.task(tid)["extra"])
            ex.update(followup_of=parent_id, followup_depth=depth)
            db.x("UPDATE tasks SET extra=? WHERE task_id=?", (json.dumps(ex, ensure_ascii=False), tid))
        record_subtask_usage(db, cfg, parent_id, created, "followup")
    pid = None
    if ask:
        prop = {"summary": f"{len(ask)} follow-up task(s) requested by {parent_id}", "questions": [],
                "tasks": [{k: v for k, v in sp.items() if k not in ("task_id", "_depth")} for sp in ask],
                "source": "followup", "id_prefix": prefix, "followup_of": parent_id}
        ask_msgs = [m for m in msgs if m["key"] in {sp["key"] for sp in ask}]
        status = "invalid" if any(m["level"] == "error" for m in ask_msgs) else "pending"
        pid = db.x("INSERT INTO plan_proposals(plan_task_id, created_at, status, request, proposal, validation) "
                   "VALUES(?,?,?,?,?,?)", (parent_id, iso(utcnow()), status, f"follow-ups requested by {parent_id}",
                                           json.dumps(prop, ensure_ascii=False), json.dumps(ask_msgs, ensure_ascii=False)))
        if status == "pending":
            db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
                 (parent_id, "plan_proposal", str(pid), "pending",
                  f"{len(ask)} follow-up task(s) requested by the worker need your approval "
                  "(premium model, MCP, or write scope outside this task)", iso(utcnow())))
    db.event("FOLLOWUPS", task_id=parent_id, created=created, proposal_id=pid, depth=depth,
             asked=[sp["key"] for sp in ask])
    return {"created": created, "proposal": pid, "rejected": rejected}
