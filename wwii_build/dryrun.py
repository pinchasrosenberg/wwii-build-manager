"""Dry run: exactly what `start` would do next, without any LLM request.

Works on an in-memory copy of the state DB (nothing persisted), re-imports the plan,
optionally runs the non-inference provider checks (version/help/auth status, Codex
app-server rate-limit read), evaluates routing and the one-writer rule, and renders
the ContextPack each first task would receive into .wwii-build/dryrun/<ts>/.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from .config import Config
from .context_builder import ContextBuilder, materialize
from .db import DB
from .models import TaskState, utcnow
from .plan_importer import import_plan, request_from_row
from .scheduler import Scheduler, Services
from .worktrees import slug


def _memory_copy(cfg: Config) -> DB:
    mem = DB(":memory:")
    if cfg.db_path.exists():
        src = sqlite3.connect(str(cfg.db_path))
        src.backup(mem.conn)
        src.close()
    return mem


async def dry_run(cfg: Config, *, check_providers: bool = True, providers=None) -> dict:
    db = _memory_copy(cfg)
    svc = Services(cfg, db=db, providers=providers)
    imported = import_plan(cfg, db)
    sched = Scheduler(svc)
    provider_reports = {}
    if check_providers:
        for name, p in svc.providers.items():
            if not cfg.provider(name).get("enabled", True):
                provider_reports[name] = {"enabled": False}
                continue
            rep = await p.check_status(with_quota=True)
            sched.apply_status(rep)
            p._status_cache = (asyncio.get_running_loop().time(), rep)
            provider_reports[name] = {
                "installed": rep.installed, "binary": rep.binary, "version": rep.version, "auth_mode": rep.auth_mode,
                "auth_detail": rep.auth_detail, "billing_ok": rep.billing_ok, "status": rep.status.value,
                "missing_flags": rep.missing_flags, "notes": rep.notes,
            }
    decisions = sched.evaluate(write=True)
    picked = sched.pick_dispatch(decisions, running=[])
    paused = bool(db.get_flag("paused"))
    emergency = bool(db.get_flag("emergency_stop"))
    out_dir = cfg.state_dir / "dryrun" / utcnow().strftime("%Y%m%dT%H%M%SZ")
    builder = ContextBuilder(cfg, svc.registry)
    would_run = []
    for d, _ in picked:
        row = db.task(d.task_id)
        req = request_from_row(row, db.deps(d.task_id))
        m = cfg.model(d.route.model_key)
        if req.is_repair and cfg.section("repair").get("effort"):
            m.effort = cfg.section("repair")["effort"]          # same override the scheduler applies
        acc = list(cfg.section("acceptance").get("default_commands", [])) + req.acceptance
        if req.is_repair:   # a repair gets the minimal repair context, built from the parent's worktree
            parent = db.task(req.parent_task_id)
            pack = sched._repair_pack(row, parent, Path(parent["worktree"]), acc)
        else:
            pack = builder.build(req, sched._deps_handoffs(req), None, acc)
        materialize(pack, out_dir / slug(d.task_id))
        would_run.append({
            "task_id": d.task_id, "wave": row["wave"], "packet": row["packet"], "owner": row["owner"],
            "mode": row["mode"], "profile": row["model_profile"],
            "provider": m.provider, "model": m.model, "effort": m.effort, "model_key": m.key,
            "why": d.reason, "fallback_chain": d.route.chain,
            "dependencies": req.depends_on or [], "write_scope": req.write_scope,
            "worktree": row["worktree"] if req.is_repair else str(svc.wt.task_path(d.task_id)),
            "branch": row["branch"] if req.is_repair else svc.wt.task_branch(d.task_id),
            "repair_of": req.parent_task_id,
            "context": [vars(i) for i in pack.items], "prompt_bytes": pack.total_bytes,
            "prompt_path": pack.prompt_path, "acceptance_commands": [c["name"] for c in acc],
        })
    others = []
    for d in decisions:
        if any(d.task_id == p.task_id for p, _ in picked):
            continue
        entry = {"task_id": d.task_id, "state": d.state.value, "reason": d.reason, "wave": d.wave}
        if d.route:
            entry["fallback_chain"] = d.route.chain
        if d.state == TaskState.WAITING_APPROVAL and d.route:
            m = cfg.model(d.route.model_key)
            entry["would_use_after_approval"] = f"{m.provider}/{m.model} ({m.effort})"
            row = db.task(d.task_id)
            req = request_from_row(row, db.deps(d.task_id))
            acc = list(cfg.section("acceptance").get("default_commands", [])) + req.acceptance
            pack = builder.build(req, sched._deps_handoffs(req), None, acc)
            materialize(pack, out_dir / slug(d.task_id))
            entry["context"] = [vars(i) for i in pack.items]
            entry["prompt_bytes"] = pack.total_bytes
            entry["prompt_path"] = pack.prompt_path
            entry["worktree"] = str(svc.wt.task_path(d.task_id))
        others.append(entry)
    # Projection: what unlocks once the would-run tasks pass (assumes success; no promises).
    passed = {r["task_id"] for r in db.q("SELECT task_id FROM tasks WHERE state=?", (TaskState.PASSED.value,))}
    first = {w["task_id"] for w in would_run} | {o["task_id"] for o in others if o["state"] in (
        TaskState.WAITING_APPROVAL.value, TaskState.READY.value, TaskState.WAITING_PROVIDER.value,
        TaskState.WAITING_QUOTA.value)}
    unlock = []
    for r in db.q("SELECT task_id FROM tasks WHERE kind='task' ORDER BY wave, task_id"):
        deps = set(db.deps(r["task_id"]))
        if r["task_id"] not in first | passed and deps and deps <= (passed | first):
            unlock.append(r["task_id"])
    from .quota import QuotaManager
    quota = QuotaManager(db, cfg.section("quota")).accounts()
    report = {
        "generated_at": utcnow().isoformat(timespec="seconds"), "repo": str(cfg.repo),
        "config_file": str(cfg.path) if cfg.path else "(defaults)",
        "plan": imported, "paused": paused, "emergency_stop": emergency,
        "baseline_branch": svc.wt.branch, "baseline_exists": svc.wt.baseline_exists(),
        "max_parallel": sched.max_parallel, "providers": provider_reports, "quota": quota,
        "would_run": would_run, "not_starting": others, "unlocks_next_if_first_wave_passes": unlock,
        "prompts_dir": str(out_dir),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dryrun.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    db.close()
    return report


def _local(ts: str | None) -> str:
    from .models import parse_iso
    d = parse_iso(ts)
    return d.astimezone().strftime("%Y-%m-%d %H:%M %Z") if d else "unknown"


def render(report: dict) -> str:
    L = []
    L.append(f"DRY RUN — no LLM request sent. repo: {report['repo']}")
    L.append(f"config: {report['config_file']} | max_parallel={report['max_parallel']} | "
             f"paused={report['paused']} | emergency_stop={report['emergency_stop']}")
    L.append(f"plan: {report['plan']['total']} dispatch tasks imported from the registry "
             f"(new {len(report['plan']['added'])}, updated {len(report['plan']['updated'])})")
    if not report["baseline_exists"]:
        L.append(f"NOTE: integration branch '{report['baseline_branch']}' does not exist yet. `start` needs "
                 "`wwii-build baseline` first (snapshots the untracked game plan via a temporary index).")
    L.append("")
    L.append("PROVIDERS (non-inference checks)")
    for n, p in report["providers"].items():
        if not p.get("enabled", True):
            L.append(f"  {n}: disabled")
            continue
        L.append(f"  {n}: {p['status']} | auth={p['auth_mode']} ({p['auth_detail']}) | billing_ok={p['billing_ok']} | "
                 f"{p['version']}")
        for note in p["notes"]:
            L.append(f"      - {note}")
    L.append("QUOTA")
    for q in report["quota"]:
        f = lambda v: f"{v:.0f}%" if v is not None else "unknown"
        wk = q["weekly_used_percent"] if q["weekly_used_percent"] is not None else (
            q["used_percent"] if q["session_used_percent"] is None else None)
        L.append(f"  {q['provider']}: {q['status']}{''.join(f' [{n}]' for n in q['notes'])} | 5h {f(q['session_used_percent'])} "
                 f"(reset {_local(q['session_reset_at'])}) | weekly {f(wk)} (reset {_local(q['weekly_reset_at'])})"
                 f" | data {_local(q['data_at'])} | source {q['source'] or '-'}")
    L.append("")
    L.append(f"WOULD START NOW ({len(report['would_run'])})")
    for w in report["would_run"]:
        L.append(f"* {w['task_id']}  [wave {w['wave']}, owner {w['owner']}, mode {w['mode']}, profile {w['profile']}]")
        L.append(f"    provider/model: {w['provider']} / {w['model']} (effort {w['effort']})")
        L.append(f"    why: {w['why']}")
        L.append("    fallback chain: " + " -> ".join(f"{c['model_key']}[{c.get('verdict', '-')}]" for c in w["fallback_chain"]))
        L.append(f"    dependencies: {', '.join(w['dependencies']) or 'none (root)'}")
        L.append(f"    worktree: {w['worktree']}  (branch {w['branch']})")
        L.append(f"    write scope: {', '.join(w['write_scope'])}")
        L.append(f"    context ({w['prompt_bytes']} bytes prompt; {w['prompt_path']}):")
        for c in w["context"]:
            L.append(f"      [{c['mode']:9}] {c['layer']:10} {c['path']}  ({c['bytes']} B)")
        L.append(f"    acceptance: {', '.join(w['acceptance_commands'])} + built-in ownership/diff/secret checks")
    L.append("")
    L.append("NOT STARTING")
    for o in report["not_starting"]:
        extra = f" -> after approval: {o['would_use_after_approval']}" if o.get("would_use_after_approval") else ""
        L.append(f"  {o['task_id']:28} {o['state']:18} {o['reason'][:110]}{extra}")
        if o["state"] in ("WAITING_APPROVAL", "WAITING_PROVIDER", "WAITING_QUOTA") and o.get("fallback_chain"):
            L.append("  " + " " * 48 + "chain: " + " -> ".join(
                f"{c['model_key']}[{c.get('verdict', '-')}]" for c in o["fallback_chain"]))
    L.append("")
    L.append("Unlocks next if the first tasks pass: " + (", ".join(report["unlocks_next_if_first_wave_passes"]) or "-"))
    L.append(f"Prompts + manifests written to: {report['prompts_dir']}")
    return "\n".join(L)
