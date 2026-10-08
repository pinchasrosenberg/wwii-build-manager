"""Import the existing dispatch graph from the Lego ownership registry.

Source of truth: ``docs/game/LEGO_OWNERSHIP_REGISTRY.json`` -> ``dispatch_tasks``.
Nothing is invented: owners, dependencies, profiles, context entries and lego ids come
from the registry; write scopes are the registry items' ``output_path`` values.
The optional overlay (``plan_overlay.toml``) only *adds* what the registry does not
carry yet: executable acceptance commands, evidence files, scope additions.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from .config import Config
from .db import DB
from .models import TaskRequest, TaskState, iso, utcnow


class PlanError(Exception):
    pass


def load_registry(cfg: Config) -> dict:
    p = cfg.repo / cfg.data["plan"]["registry"]
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_overlay(cfg: Config) -> dict:
    p = cfg.overlay_path
    if not p.is_file():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def _domain_of(entry: str | None, owner_roles: dict, owner: str) -> str | None:
    if owner in owner_roles and owner_roles[owner].get("domain"):
        return owner_roles[owner]["domain"]
    if entry and "/domains/" in entry:
        return entry.split("/domains/")[1].split("/")[0]
    return None


def build_requests(cfg: Config, registry: dict | None = None, overlay: dict | None = None) -> list[TaskRequest]:
    registry = registry if registry is not None else load_registry(cfg)
    overlay = overlay if overlay is not None else load_overlay(cfg)
    tasks = registry.get("dispatch_tasks")
    if not tasks:
        raise PlanError("registry has no dispatch_tasks")
    items = {i["lego_id"]: i for i in registry.get("items", [])}
    packets = {p["id"]: p for p in registry.get("build_packets", [])}
    owner_roles = registry.get("owner_roles", {})
    ov_tasks = overlay.get("tasks", {})
    out: list[TaskRequest] = []
    for t in tasks:
        tid = t["task_id"]
        ov = ov_tasks.get(tid, {})
        missing = [lid for lid in t.get("lego_ids", []) if lid not in items]
        if missing:
            raise PlanError(f"{tid}: unknown lego ids {missing}")
        scope = sorted({items[lid]["output_path"] for lid in t.get("lego_ids", []) if items[lid].get("output_path")})
        if "write_scope" in ov:
            scope = list(ov["write_scope"])
        scope = sorted(set(scope) | set(ov.get("extra_write_scope", [])))
        packet = packets.get(t["packet"], {})
        out.append(TaskRequest(
            task_id=tid, packet=t["packet"], owner=t["owner"],
            domain=_domain_of(t.get("context_entry"), owner_roles, t["owner"]),
            mode=t.get("mode", "build"),
            model_profile=ov.get("model_profile", t.get("model_profile") or packet.get("model_profile") or "IMPLEMENT"),
            lego_ids=list(t.get("lego_ids", [])), write_scope=scope,
            depends_on=list(t.get("depends_on", [])),
            context_entry=t.get("context_entry"), brief_path=packet.get("brief_path"),
            note=t.get("note_he") or None,
            acceptance=list(overlay.get("defaults", {}).get("acceptance", [])) + list(ov.get("acceptance", [])),
            extra={k: v for k, v in ov.items()
                   if k in ("evidence", "required_paths", "reference_extra", "notes", "review", "full_checkout")},
        ))
    _validate(out)
    return out


def _validate(reqs: list[TaskRequest]) -> None:
    ids = {r.task_id for r in reqs}
    if len(ids) != len(reqs):
        raise PlanError("duplicate task ids")
    for r in reqs:
        for d in r.depends_on:
            if d not in ids:
                raise PlanError(f"{r.task_id} depends on unknown task {d}")
        if not r.write_scope and not r.read_only:
            raise PlanError(f"{r.task_id}: build task without write scope")
    compute_waves(reqs)   # raises on cycles


def compute_waves(reqs: list[TaskRequest]) -> dict[str, int]:
    by_id = {r.task_id: r for r in reqs}
    wave: dict[str, int] = {}
    visiting: set[str] = set()

    def visit(tid: str) -> int:
        if tid in wave:
            return wave[tid]
        if tid in visiting:
            raise PlanError(f"dependency cycle through {tid}")
        visiting.add(tid)
        deps = by_id[tid].depends_on
        wave[tid] = 0 if not deps else 1 + max(visit(d) for d in deps)
        visiting.discard(tid)
        return wave[tid]

    for r in reqs:
        visit(r.task_id)
    return wave


def definition_hash(r: TaskRequest) -> str:
    blob = json.dumps({k: getattr(r, k) for k in (
        "packet", "owner", "mode", "model_profile", "lego_ids", "write_scope", "depends_on",
        "context_entry", "brief_path", "acceptance", "extra")}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_deliver_listener_catalog(cfg: Config) -> dict:
    """Load the additive Deliver/listener catalogue owned by the game design.

    The enclosing Deliver is the owner of every proposed listener.  Importing a
    proposal does not activate it; the listener runtime always requires a Jev
    decision for ``edge_type=listener`` and ``jev_gate=1``.
    """
    path = cfg.repo / "docs/game/DELIVER_LISTENER_CATALOG.json"
    if not path.is_file():
        return {"delivers": []}
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlanError(f"invalid Deliver listener catalog: {exc}") from exc
    delivers = catalog.get("delivers")
    if not isinstance(delivers, list):
        raise PlanError("Deliver listener catalog must contain a delivers list")
    ids = [d.get("deliver_id") for d in delivers if isinstance(d, dict)]
    if len(ids) != len(delivers) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise PlanError("Deliver listener catalog has missing or duplicate deliver_id")
    known = set(ids)
    listener_ids: set[str] = set()
    for deliver in delivers:
        proposals = deliver.get("proposed_listeners", [])
        if not isinstance(proposals, list):
            raise PlanError(f"{deliver['deliver_id']}: proposed_listeners must be a list")
        for listener in proposals:
            if not isinstance(listener, dict) or not listener.get("listener_id"):
                raise PlanError(f"{deliver['deliver_id']}: listener_id is required")
            if listener["listener_id"] in listener_ids:
                raise PlanError(f"duplicate listener_id {listener['listener_id']}")
            listener_ids.add(listener["listener_id"])
            if listener.get("target_deliver_id") not in known:
                raise PlanError(f"{listener['listener_id']}: unknown target Deliver {listener.get('target_deliver_id')}")
            if not listener.get("event_type"):
                raise PlanError(f"{listener['listener_id']}: event_type is required")
    return catalog


def _import_deliver_listener_catalog(cfg: Config, db: DB, catalog: dict, now: str) -> tuple[int, int]:
    delivers = catalog.get("delivers", [])
    for deliver in delivers:
        canonical = json.dumps(deliver, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        db.conn.execute(
            "INSERT INTO deliver_catalog(deliver_id,owner,domain,description,source_kind,source_ref,execution_kind,implementation_ref,definition_hash,enabled,availability,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT(deliver_id) DO UPDATE SET owner=excluded.owner,domain=excluded.domain,description=excluded.description,source_kind=excluded.source_kind,source_ref=excluded.source_ref,execution_kind=excluded.execution_kind,implementation_ref=excluded.implementation_ref,definition_hash=excluded.definition_hash,enabled=1,availability=excluded.availability,updated_at=excluded.updated_at",
            (deliver["deliver_id"], deliver.get("owner"), deliver.get("domain"), deliver.get("description"),
             "deliver_listener_catalog", "docs/game/DELIVER_LISTENER_CATALOG.json", deliver.get("execution_kind", "worker"),
             deliver.get("implementation_ref"), hashlib.sha256(canonical.encode()).hexdigest()[:16],
             deliver.get("availability", "planned"), now))
    count = 0
    for deliver in delivers:
        for listener in deliver.get("proposed_listeners", []):
            db.conn.execute(
                "INSERT INTO deliver_listener_edges(listener_id,source_deliver_id,target_deliver_id,event_type,context_selector,source_kind,edge_type,jev_gate,enabled,proposal_reason,updated_at) "
                "VALUES(?,?,?,?,?,'deliver_listener_catalog','listener',1,1,?,?) ON CONFLICT(listener_id) DO UPDATE SET source_deliver_id=excluded.source_deliver_id,target_deliver_id=excluded.target_deliver_id,event_type=excluded.event_type,context_selector=excluded.context_selector,source_kind=excluded.source_kind,edge_type='listener',jev_gate=1,enabled=1,proposal_reason=excluded.proposal_reason,updated_at=excluded.updated_at",
                (listener["listener_id"], deliver["deliver_id"], listener["target_deliver_id"],
                 listener["event_type"], json.dumps(listener.get("when", {}), ensure_ascii=False, sort_keys=True),
                 listener.get("reason"), now))
            count += 1
    return len(delivers), count


def import_plan(cfg: Config, db: DB) -> dict:
    reqs = build_requests(cfg)
    listener_catalog = load_deliver_listener_catalog(cfg)
    waves = compute_waves(reqs)
    now = iso(utcnow())
    added, updated, unchanged, protected = [], [], [], []
    with db.tx():
        for r in reqs:
            h = definition_hash(r)
            row = db.one("SELECT state, definition_hash FROM tasks WHERE task_id=?", (r.task_id,))
            cols = dict(packet=r.packet, owner=r.owner, domain=r.domain, mode=r.mode, model_profile=r.model_profile,
                        lego_ids=json.dumps(r.lego_ids), write_scope=json.dumps(r.write_scope),
                        context_entry=r.context_entry, brief_path=r.brief_path, note=r.note,
                        acceptance=json.dumps(r.acceptance, ensure_ascii=False),
                        extra=json.dumps(r.extra, ensure_ascii=False), definition_hash=h, wave=waves[r.task_id])
            if row is None:
                cols.update(task_id=r.task_id, state=TaskState.PENDING.value, created_at=now, updated_at=now)
                db.conn.execute(f"INSERT INTO tasks({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                tuple(cols.values()))
                added.append(r.task_id)
            elif row["definition_hash"] == h:
                unchanged.append(r.task_id)
            elif row["state"] in (TaskState.PASSED.value, TaskState.RUNNING.value, TaskState.REVIEWING.value,
                                  TaskState.WAITING_REPAIR.value, TaskState.CODE_READY.value):
                protected.append(r.task_id)
            else:
                cols["updated_at"] = now
                db.conn.execute(f"UPDATE tasks SET {', '.join(k + '=?' for k in cols)} WHERE task_id=?",
                                (*cols.values(), r.task_id))
                updated.append(r.task_id)
        for r in reqs:   # second pass: every task row exists before dependency rows reference it
            db.conn.execute("DELETE FROM task_dependencies WHERE task_id=?", (r.task_id,))
            for d in r.depends_on:
                db.conn.execute("INSERT INTO task_dependencies(task_id, depends_on) VALUES(?,?)", (r.task_id, d))
        # TaskSlices are the first Deliver catalogue. This is a projection for the
        # manager/dashboard; execution remains owned by the scheduler/provider.
        for r in reqs:
            description = r.note or f"{r.owner} / {r.packet}"
            db.conn.execute(
                "INSERT INTO deliver_catalog(deliver_id,packet,owner,domain,description,source_kind,source_ref,execution_kind,implementation_ref,definition_hash,enabled,availability,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,1,'available',?) ON CONFLICT(deliver_id) DO UPDATE SET packet=excluded.packet,owner=excluded.owner,domain=excluded.domain,description=excluded.description,source_ref=excluded.source_ref,execution_kind=excluded.execution_kind,implementation_ref=excluded.implementation_ref,definition_hash=excluded.definition_hash,enabled=1,availability='available',updated_at=excluded.updated_at",
                (r.task_id, r.packet, r.owner, r.domain, description, "task_graph",
                 f"{cfg.data['plan']['registry']}#dispatch_tasks/{r.task_id}", "worker",
                 r.context_entry, definition_hash(r), now))
            excerpt = json.dumps({"task_id": r.task_id, "owner": r.owner, "domain": r.domain,
                                  "packet": r.packet, "depends_on": r.depends_on,
                                  "lego_ids": r.lego_ids, "note": r.note}, ensure_ascii=False, sort_keys=True)
            source_key = "task-graph:" + r.task_id
            sha = hashlib.sha256(excerpt.encode()).hexdigest()
            db.conn.execute(
                "INSERT INTO context_sources(source_key,task_id,deliver_id,origin_kind,origin_ref,graph_entity_id,graph_revision,title,excerpt,content_sha256,tags_json,active,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?, ?,1,?,?) ON CONFLICT(source_key) DO UPDATE SET task_id=excluded.task_id,deliver_id=excluded.deliver_id,origin_ref=excluded.origin_ref,graph_entity_id=excluded.graph_entity_id,graph_revision=excluded.graph_revision,title=excluded.title,excerpt=excluded.excerpt,content_sha256=excluded.content_sha256,tags_json=excluded.tags_json,active=1,updated_at=excluded.updated_at",
                (source_key, r.task_id, r.task_id, "task_graph", f"{cfg.data['plan']['registry']}#dispatch_tasks/{r.task_id}",
                 r.task_id, definition_hash(r), f"Task graph node {r.task_id}", excerpt, sha,
                 json.dumps([r.packet, r.owner, r.domain], ensure_ascii=False), now, now))
        catalog_delivers, catalog_listeners = _import_deliver_listener_catalog(cfg, db, listener_catalog, now)
        # Dependencies are prerequisites. They are displayed in the graph but are
        # never mistaken for Jev-gated listener activations.
        for r in reqs:
            for dep in r.depends_on:
                lid = "prerequisite:" + hashlib.sha256(f"{dep}->{r.task_id}".encode()).hexdigest()[:24]
                db.conn.execute(
                    "INSERT INTO deliver_listener_edges(listener_id,source_deliver_id,target_deliver_id,event_type,context_selector,source_kind,edge_type,jev_gate,enabled,updated_at) "
                    "VALUES(?,?,?,?,?,?, 'prerequisite',0,1,?) ON CONFLICT(listener_id) DO UPDATE SET enabled=1,updated_at=excluded.updated_at",
                    (lid, dep, r.task_id, "PREREQUISITE_PASSED", None, "task_graph", now))
    db.event("PLAN_IMPORTED", added=len(added), updated=updated, protected=protected,
             registry=cfg.data["plan"]["registry"])
    for tid in protected:
        db.event("PLAN_CHANGED_AFTER_START", task_id=tid)
    return {"added": added, "updated": updated, "unchanged": unchanged, "protected": protected,
            "total": len(reqs), "delivers": len(reqs) + catalog_delivers,
            "listeners": catalog_listeners}


def request_from_row(row, deps: list[str]) -> TaskRequest:
    return TaskRequest(
        task_id=row["task_id"], packet=row["packet"], owner=row["owner"], domain=row["domain"],
        mode=row["mode"], model_profile=row["model_profile"], lego_ids=json.loads(row["lego_ids"]),
        write_scope=json.loads(row["write_scope"]), depends_on=deps, context_entry=row["context_entry"],
        brief_path=row["brief_path"], note=row["note"], acceptance=json.loads(row["acceptance"]),
        extra=json.loads(row["extra"]),
        kind=row["kind"] if "kind" in row.keys() else "task",
        parent_task_id=row["parent_task_id"] if "parent_task_id" in row.keys() else None,
    )


def registry_items_for(registry: dict, lego_ids: list[str]) -> list[dict]:
    items = {i["lego_id"]: i for i in registry.get("items", [])}
    return [items[i] for i in lego_ids if i in items]


def repo_path(cfg: Config, rel: str) -> Path:
    return cfg.repo / rel
