"""wwii-build command line."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import control
from .activation import activation_id, restart_decision
from .config import MANAGER_DIR, Config, find_repo_root, load_config
from .db import DB
from .models import TaskState
from .plan_importer import PlanError, import_plan


def _cfg(args) -> Config:
    repo = Path(args.repo).resolve() if args.repo else find_repo_root()
    return load_config(repo, Path(args.config) if args.config else None)


def _db(cfg: Config) -> DB:
    return DB(cfg.db_path)


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str) if not isinstance(obj, str) else obj)


def _original_exec_argv() -> list[str]:
    """The interpreter argv that launched this CLI, preserving -m and all global/subcommand flags."""
    original = list(getattr(sys, "orig_argv", ()) or ())
    if len(original) > 1:
        original[0] = sys.executable
        return original
    return [sys.executable, "-m", "wwii_build", *sys.argv[1:]]


def _reexec_current_process() -> None:
    os.execv(sys.executable, _original_exec_argv())


def cmd_doctor(args, cfg):
    from .doctor import doctor, render
    lines = asyncio.run(doctor(cfg, with_quota=not args.no_quota))
    print(render(lines) if not args.json else json.dumps(lines, indent=1))
    return 1 if any(x["status"] == "FAIL" for x in lines) else 0


def cmd_config(args, cfg):
    target = cfg.state_dir / "config.toml"
    if args.action == "path":
        print(cfg.path or f"(none; defaults) — create with `wwii-build config init` at {target}")
        return 0
    if args.action == "init":
        if target.exists():
            print(f"exists: {target}")
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(MANAGER_DIR / "config.example.toml", target)
        print(f"wrote {target}")
        return 0
    if args.action == "show":
        _print(cfg.data)
        return 0


def cmd_import(args, cfg):
    from .worktrees import WorktreeManager
    WorktreeManager(cfg).ensure_excludes()
    db = _db(cfg)
    try:
        r = import_plan(cfg, db)
    except PlanError as e:
        print(f"plan error: {e}", file=sys.stderr)
        return 1
    print(f"imported {r['total']} dispatch tasks from {cfg.data['plan']['registry']}: new {len(r['added'])}, "
          f"updated {len(r['updated'])}, unchanged {len(r['unchanged'])}, protected {len(r['protected'])}")
    for w in sorted({t['wave'] for t in db.q("SELECT wave FROM tasks WHERE kind='task'")}):
        ids = [t["task_id"] for t in db.q("SELECT task_id FROM tasks WHERE wave=? AND kind='task' ORDER BY task_id", (w,))]
        print(f"  wave {w}: {', '.join(ids)}")
    return 0


def cmd_baseline(args, cfg):
    from .worktrees import WorktreeManager
    wt = WorktreeManager(cfg)
    wt.ensure_excludes()
    before = wt.git("status", "--porcelain").out
    r = wt.create_baseline()
    after = wt.git("status", "--porcelain").out
    _print(r)
    if before != after:
        print("WARNING: working tree status changed during baseline — please inspect", file=sys.stderr)
        return 1
    print("your branch, index and working tree are unchanged")
    return 0


def cmd_dry_run(args, cfg):
    from .dryrun import dry_run, render
    rep = asyncio.run(dry_run(cfg, check_providers=not args.no_provider_checks))
    print(render(rep) if not args.json else json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    return 0


def cmd_start(args, cfg):
    if args.dry_run:
        return cmd_dry_run(args, cfg)
    from .dashboard import Dashboard
    from .scheduler import Scheduler, Services
    from .worktrees import WorktreeManager
    from .model_watch import ModelWatch
    wt = WorktreeManager(cfg)
    wt.ensure_excludes()
    if not wt.baseline_exists():
        print(f"integration branch {wt.branch} missing. Run `wwii-build baseline` first "
              "(snapshots the untracked game plan without touching your branch).", file=sys.stderr)
        return 2
    try:
        lock_fd = control.acquire_daemon_lock(cfg)
    except control.ControlError as e:
        print(str(e), file=sys.stderr)
        return 2
    svc = Services(cfg)
    r = import_plan(cfg, svc.db)
    print(f"plan: {r['total']} tasks ({len(r['added'])} new, {len(r['updated'])} updated)")
    sched = Scheduler(svc, exit_when_idle=args.exit_when_idle)
    dash = None
    hook = None
    if not args.no_dashboard:
        holder = {}
        dash = Dashboard(cfg, wake=lambda: holder.get("wake", lambda: None)())
        try:
            dash.serve_in_thread()
            print(f"dashboard: {dash.url}")
            hook = lambda w: holder.__setitem__("wake", w)
        except OSError as e:
            print(f"dashboard not started ({e}); continuing headless", file=sys.stderr)
            dash = None
    print("scheduler running. Ctrl-C = graceful stop (twice = kill). `wwii-build pause|stop|kill` from another shell.")
    watch_stop = None
    if cfg.section("model_watch").get("enabled", True):
        import threading
        watch_stop = threading.Event()

        def watch_loop():
            watcher = ModelWatch(cfg, DB(cfg.db_path))
            while not watch_stop.is_set():
                try:
                    if watcher.due():
                        watcher.check()
                except Exception as exc:
                    watcher.db.event("MODEL_WATCH_FAILED", error_type=type(exc).__name__)
                watch_stop.wait(1800)

        threading.Thread(target=watch_loop, name="model-watch", daemon=True).start()
    reason = "stopped"
    try:
        reason = asyncio.run(sched.run(dashboard_wake_hook=hook))
    finally:
        if watch_stop:
            watch_stop.set()
        if dash:
            dash.shutdown(service_restart=reason == "system-restart")
        os.close(lock_fd)
    print(f"daemon exited: {reason}")
    if reason == "system-restart":
        print("validated Task Manager repair activated; restarting the daemon on the new code")
        _reexec_current_process()
    return 0


def _wait_daemon_exit(cfg, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not control.daemon_pid(cfg):
            return True
        time.sleep(0.5)
    return False


def cmd_pause(args, cfg):
    print(control.pause(_db(cfg), cfg, args.interrupt_running))
    return 0


def cmd_resume(args, cfg):
    try:
        print(control.resume(_db(cfg), cfg, args.clear_emergency))
    except control.ControlError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not control.daemon_pid(cfg):
        print("daemon not running: `wwii-build start` continues (finished tasks are never re-run)")
    return 0


def cmd_stop(args, cfg):
    db = _db(cfg)
    if control.daemon_pid(cfg):
        control.enqueue(db, cfg, "stop")
        grace = float(cfg.section("stop").get("graceful_timeout_seconds", 20))
        print("stop requested; waiting for workers to exit gracefully...")
        ok = _wait_daemon_exit(cfg, grace + 60)
        print("daemon stopped; state saved; worktrees kept" if ok else "daemon still running; try `wwii-build kill`")
        return 0 if ok else 1
    left = control.stop_recorded_workers(db, float(cfg.section("stop").get("graceful_timeout_seconds", 20)))
    print("daemon not running" + (f"; stopped leftover workers: {left}" if left else ""))
    return 0


def cmd_kill(args, cfg):
    db = _db(cfg)
    if control.daemon_pid(cfg):
        control.enqueue(db, cfg, "kill")
        ok = _wait_daemon_exit(cfg, 30)
        print("workers killed; scheduler disabled (emergency marker). `wwii-build resume --clear-emergency` to re-enable"
              if ok else "daemon did not exit; check `ps`")
        return 0 if ok else 1
    from .models import iso, utcnow
    db.set_flag("emergency_stop", iso(utcnow()))
    killed = control.kill_recorded_workers(db, "cli emergency kill")
    db.event("EMERGENCY_KILL", offline=True, killed=killed)
    print(f"emergency marker set; killed: {killed or 'none running'}")
    return 0


def cmd_status(args, cfg):
    db = _db(cfg)
    pid = control.daemon_pid(cfg)
    counts = {r["state"]: r["n"] for r in db.q("SELECT state, COUNT(*) n FROM tasks GROUP BY state")}
    if not counts:
        print("no plan imported yet: `wwii-build import-plan`")
        return 0
    print(f"daemon: {'running pid ' + str(pid) if pid else 'not running'} | paused: {bool(db.get_flag('paused'))} | "
          f"emergency: {db.get_flag('emergency_stop') or 'no'}")
    if db.get_flag("idle_reason"):
        print(f"idle: {db.get_flag('idle_reason')}")
    if db.get_flag("next_wakeup_at"):
        print(f"next wakeup: {db.get_flag('next_wakeup_at')} ({db.get_flag('next_wakeup_reason')})")
    open_waves = [r["wave"] for r in db.q("SELECT wave FROM tasks WHERE state NOT IN ('PASSED','CANCELLED')")]
    print(f"current wave: {min(open_waves) if open_waves else 'done'} | " +
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for w in db.q("SELECT * FROM workers"):
        print(f"  running: {w['task_id']} {w['provider']}/{w['model']} pid {w['pid']} since {w['started_at']}")
    for a in db.q("SELECT * FROM approvals WHERE status='pending' ORDER BY id"):
        print(f"  approval #{a['id']}: {a['task_id']} {a['kind']} {a['subject'] or ''} — {a['reason']}")
    from .quota import QuotaManager
    f = lambda v: f"{v:.0f}%" if v is not None else "unknown"
    for q in QuotaManager(db, cfg.section("quota")).accounts():
        print(f"  quota {q['provider']}: {q['status']} 5h={f(q['session_used_percent'])} weekly={f(q['weekly_used_percent'])} "
              f"blocked_until={q['blocked_until'] or '-'}" + "".join(f" [{n}]" for n in q["notes"]))
    return 0


def cmd_tasks(args, cfg):
    db = _db(cfg)
    for t in db.q("SELECT * FROM tasks WHERE kind='task' ORDER BY wave, task_id"):
        reps = db.q("SELECT * FROM tasks WHERE parent_task_id=? AND kind='repair' ORDER BY repair_no", (t["task_id"],))
        if args.state and t["state"] != args.state and not any(r["state"] == args.state for r in reps):
            continue
        print(f"{t['wave']:>2} {t['task_id']:28} {t['state']:28} {t['last_model_key'] or '':7} "
              f"{(t['state_reason'] or '')[:90]}")
        for r in reps:
            print(f"   └─ Repair #{r['repair_no']:<3} {r['failure_class'] or '':24} {r['state']:28} "
                  f"{r['last_model_key'] or '':7} {(r['state_reason'] or '')[:70]}")
    return 0


def cmd_task(args, cfg):
    db = _db(cfg)
    t = db.task(args.task_id)
    if not t:
        print(f"unknown task {args.task_id}", file=sys.stderr)
        return 1
    d = dict(t)
    d["depends_on"] = db.deps(args.task_id)
    d["attempts"] = [dict(a) for a in db.q("SELECT id, kind, attempt_no, provider, model, status, failure_class, "
                                          "started_at, ended_at, exit_code, input_tokens, output_tokens, "
                                          "reported_cost_usd, handoff_status FROM task_attempts WHERE task_id=? "
                                          "ORDER BY id", (args.task_id,))]
    d["tests"] = [dict(r) for r in db.q("SELECT name, passed, exit_code FROM test_results WHERE task_id=? "
                                        "ORDER BY id DESC LIMIT 20", (args.task_id,))]
    d["approvals"] = [dict(r) for r in db.q("SELECT * FROM approvals WHERE task_id=? ORDER BY id", (args.task_id,))]
    d["repairs"] = [{k: r[k] for k in ("task_id", "repair_no", "state", "state_reason", "failure_class",
                                       "failure_summary", "model_profile", "last_model_key")}
                    for r in db.q("SELECT * FROM tasks WHERE parent_task_id=? AND kind='repair' ORDER BY repair_no",
                                  (args.task_id,))]
    _print(d)
    return 0


def _simple(fn):
    def run(args, cfg):
        try:
            print(fn(args, cfg))
            return 0
        except control.ControlError as e:
            print(str(e), file=sys.stderr)
            return 1
    return run


def _approval_id(db, ident: str) -> int:
    if ident.isdigit():
        return int(ident)
    a = control.pending_approval_for_task(db, ident)
    if a is None:
        raise control.ControlError(f"no pending approval for {ident}")
    return a


cmd_retry = _simple(lambda a, c: control.retry(_db(c), a.task_id))
cmd_skip = _simple(lambda a, c: control.skip(_db(c), c, a.task_id, a.as_satisfied))
def cmd_recheck(args, cfg):
    db = _db(cfg)
    try:
        print(control.recheck(db, args.task_id))
    except control.ControlError as e:
        print(str(e), file=sys.stderr)
        return 1
    if not args.run:
        return 0
    if control.daemon_pid(cfg):
        print("daemon is running; it will re-run acceptance itself")
        return 0
    from .scheduler import Scheduler, Services

    async def go():
        sched = Scheduler(Services(cfg, db=db))
        sched.prepare()
        await sched.finalize(args.task_id)      # deterministic acceptance only; never starts a worker
    asyncio.run(go())
    t = db.task(args.task_id)
    print(f"{args.task_id}: {t['state']} — {t['state_reason']}")
    last = db.one("SELECT created_at FROM test_results WHERE task_id=? ORDER BY id DESC LIMIT 1", (args.task_id,))
    if last:   # only the run that just happened
        for r in db.q("SELECT name, passed FROM test_results WHERE task_id=? AND created_at=? ORDER BY id",
                      (args.task_id, last["created_at"])):
            print(f"  {'pass' if r['passed'] else 'FAIL'}  {r['name']}")
    return 0
cmd_set_provider = _simple(lambda a, c: control.set_provider(_db(c), c, a.task_id, a.model_key))


def cmd_approve(args, cfg):
    db = _db(cfg)
    try:
        print(control.decide(db, cfg, _approval_id(db, args.ident), True, args.note, args.model))
        return 0
    except control.ControlError as e:
        print(str(e), file=sys.stderr)
        return 1


def cmd_reject(args, cfg):
    db = _db(cfg)
    try:
        print(control.decide(db, cfg, _approval_id(db, args.ident), False, args.note))
        return 0
    except control.ControlError as e:
        print(str(e), file=sys.stderr)
        return 1


def cmd_approvals(args, cfg):
    for a in _db(cfg).q("SELECT * FROM approvals WHERE status='pending' ORDER BY id"):
        print(f"#{a['id']:<4} {a['task_id'] or '-':28} {a['kind']:18} {a['subject'] or '':10} {a['reason'] or ''}")
    return 0


def cmd_providers(args, cfg):
    db = _db(cfg)
    for name in cfg.data["providers"]:
        pc = cfg.provider(name)
        print(f"{name}: {'enabled' if pc.get('enabled', True) else 'DISABLED'}")
        from .quota import QuotaManager
        for q in [a for a in QuotaManager(db, cfg.section("quota")).accounts() if a["provider"] == name]:
            f = lambda v: f"{v:.0f}%" if v is not None else "unknown"
            for note in q["notes"]:
                print(f"  restriction: {note}")
            print(f"  {'account':>14}: {q['status']:16} 5h={f(q['session_used_percent']):7} "
                  f"(reset {q['session_reset_at'] or 'unknown'}) weekly={f(q['weekly_used_percent']):7} "
                  f"(reset {q['weekly_reset_at'] or 'unknown'}) blocked_until={q['blocked_until'] or '-'} "
                  f"data_at={q['data_at'] or q['last_checked_at'] or '-'} source={q['source'] or '-'}")
    for k, m in cfg.models().items():
        print(f"  model {k:7} -> {m.provider}/{m.model} effort={m.effort} tier={m.tier} automatic={m.automatic}")
    return 0


def cmd_provider(args, cfg):
    db = _db(cfg)
    if args.action == "reset-done":
        try:
            print(control.provider_reset_done(db, cfg, args.name))
        except control.ControlError as e:
            print(str(e), file=sys.stderr)
            return 1
        if control.daemon_pid(cfg):
            return 0
        args.action = "refresh"          # no daemon: re-check the provider right now
    if args.action != "refresh":
        return 1
    if control.daemon_pid(cfg):
        rid = control.enqueue(db, cfg, "refresh", {"provider": args.name})
        for _ in range(120):
            r = db.one("SELECT handled_at, result FROM control_requests WHERE id=?", (rid,))
            if r["handled_at"]:
                print(f"{args.name}: {r['result']}")
                return 0
            time.sleep(0.5)
        print("daemon did not answer in time")
        return 1
    from .scheduler import Scheduler, Services

    async def go():
        svc = Services(cfg, db=db)
        return await Scheduler(svc).refresh_provider(args.name, manual=True)
    rep = asyncio.run(go())
    if not rep:
        print(f"{args.name}: not enabled")
        return 1
    print(f"{args.name}: {rep.status.value} auth={rep.auth_mode} ({rep.auth_detail}) {rep.version or ''}")
    for n in rep.notes:
        print(f"  - {n}")
    return 0


def cmd_dashboard(args, cfg):
    from .dashboard import Dashboard
    from .model_watch import ModelWatch
    if args.persistent:
        print("persistent dashboard: waiting for port; Ctrl-C to exit")
        marker_db = _db(cfg)
        seen_activation = activation_id(marker_db)
        try:
            while True:
                if restart_decision(seen_activation, activation_id(marker_db)) == "restart":
                    print("Task Manager activation detected; restarting the persistent dashboard on the new code")
                    _reexec_current_process()
                try:
                    current = load_config(cfg.repo, cfg.path)
                    d = Dashboard(current)
                    thread = d.serve_in_thread()
                except OSError:
                    time.sleep(5)
                    continue
                print(f"dashboard: {d.url}")
                service_restart = False
                try:
                    while thread.is_alive():
                        if restart_decision(seen_activation, activation_id(marker_db)) == "restart":
                            service_restart = True
                            break
                        if not control.daemon_pid(current) and current.section("model_watch").get("enabled", True):
                            watcher = ModelWatch(current, d.db)
                            try:
                                if watcher.due():
                                    watcher.check()
                            except Exception as exc:
                                d.db.event("MODEL_WATCH_FAILED", error_type=type(exc).__name__)
                        try:   # full automatic mode keeps working even while the daemon runs older code
                            control.auto_approve_pending(d.db, current, "dashboard")
                        except Exception as exc:
                            d.db.event("AUTO_APPROVAL_FAILED", error_type=type(exc).__name__, error=str(exc)[:300])
                        time.sleep(5)
                finally:
                    d.shutdown(service_restart=service_restart)
                if service_restart:
                    print("Task Manager activation detected; restarting the persistent dashboard on the new code")
                    _reexec_current_process()
        except KeyboardInterrupt:
            return 0
    if control.daemon_pid(cfg):
        print(f"daemon is running and serves the dashboard at http://{cfg.section('dashboard').get('host')}:"
              f"{cfg.section('dashboard').get('port')}/")
        return 0
    d = Dashboard(cfg)
    d.serve_in_thread()
    print(f"dashboard (read/write, no scheduler): {d.url}  Ctrl-C to exit")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        d.shutdown()
    return 0


def cmd_add_task(args, cfg):
    from . import manual as mn
    from .mcp import available
    spec = {"key": args.name or args.title, "title": args.title, "instructions": args.instructions or "",
            "model_key": args.model, "fallback": not args.no_fallback, "owner": args.owner or "",
            "depends_on": args.dep or [], "write_scope": args.scope or [], "read_only": args.read_only,
            "context_files": args.context or [], "reference_files": args.reference or [],
            "mcp_servers": args.mcp or [], "acceptance_commands": args.check or [],
            "auto_approve": args.auto_approve, "allow_web": args.allow_web}
    db = _db(cfg)
    try:
        ids = mn.create_tasks(db, cfg, [spec], "manual", available(cfg) if args.mcp else None)
    except mn.ManualError as e:
        print(f"not created: {e}", file=sys.stderr)
        return 1
    print(f"created {ids[0]}")
    return 0


def cmd_battle_request(args, cfg):
    from . import battle_request as br
    from . import manual as mn
    try:
        result = br.request_battle(
            _db(cfg), cfg, title=args.title, battle_key=args.key or "", date=args.date or "", date_end=args.date_end or "",
            bbox=args.bbox, place=args.place or "", notes=args.notes or "", dry_run=args.dry_run)
    except mn.ManualError as e:
        print(f"not created: {e}", file=sys.stderr)
        return 1
    print(("would create" if args.dry_run else "created") + f" the chain for {result['battle_key']} ({result['date']}):")
    for stage in result["stages"]:
        deps = ", ".join(stage["depends_on"]) or "-"
        print(f"  {stage['task_id']}  model={stage['model_key']}  web={'yes' if stage['allow_web'] else 'no'}  "
              f"scope={stage['write_scope'][0]}  after: {deps}")
    return 0


def cmd_unstick(args, cfg):
    from . import unstick as us
    rep = us.unstick(cfg, _db(cfg), "cli")
    for title, key in (("מה מצאתי", "findings"), ("מה עשיתי", "actions"), ("דורש החלטה שלך", "needs_you")):
        if rep[key]:
            print(title + ":")
            for x in rep[key]:
                print("  - " + x)
    print(us.summary_he(rep))
    return 0


def cmd_onboard(args, cfg):
    from . import onboarding as ob
    db = _db(cfg)
    if args.list or not args.manifest:
        for s in ob.systems(db):
            print(f"{s['system_id']}: {s['components']} components, {s['capabilities']} capabilities, "
                  f"graph current {s['graph_current'] or 0}, "
                  f"manifest {s['manifest_ref']}, updated {s['updated_at']}")
        print("manifests:", ", ".join(p.name for p in sorted(ob.SYSTEMS_DIR.glob("*.toml"))
                                     if not p.name.startswith("_") and not p.name.endswith("_templates.toml")) or "none")
        return 0
    try:
        if args.graph_only:
            m = ob.load_manifest(Path(args.manifest))
            rep = {"system": m.system_id, "graph": ob.push_structured_graph(cfg, db, m, force=args.force,
                                                                            progress=print)}
            if args.text:
                rep["text"] = ob.ingest_to_graph(cfg, db, m.system_id, force=args.force, progress=print)
        else:
            rep = ob.onboard(cfg, db, Path(args.manifest), graph=False if args.no_graph else None,
                             dry_run=args.dry_run, progress=print)
    except ob.OnboardingError as e:
        print(f"onboard: {e}", file=sys.stderr)
        return 1
    _print(rep)
    return 0


def cmd_plan(args, cfg):
    from . import manual as mn
    text = args.prompt if args.prompt != "-" else sys.stdin.read()
    try:
        tid = mn.create_plan(_db(cfg), cfg, text, args.model)
    except mn.ManualError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"{tid} queued; the scheduler runs the planner model, then `wwii-build proposals` / the dashboard shows the "
          "proposed tasks for approval")
    return 0


def cmd_proposals(args, cfg):
    db = _db(cfg)
    for p in db.q("SELECT * FROM plan_proposals ORDER BY id DESC LIMIT 20"):
        prop = json.loads(p["proposal"])
        print(f"#{p['id']} {p['plan_task_id']} {p['status']}: {prop.get('summary', '')}")
        for t in prop.get("tasks", []):
            print(f"   - {t.get('key')}: model={t.get('model_key')} deps={t.get('depends_on')} scope={t.get('write_scope')}")
        for m in json.loads(p["validation"]):
            print(f"   [{m['level']}] {m['key']}: {m['message']}")
    return 0


def cmd_events(args, cfg):
    for e in reversed(_db(cfg).events(limit=args.n)):
        print(f"{e['at']} {e['event']:24} {e['task_id'] or '':26} {e['provider'] or '':7} {(e['detail'] or '')[:140]}")
    return 0


def cmd_listener(args, cfg):
    from .jev import JevService
    from .listeners import ListenerEngine
    db = _db(cfg)
    if args.action == "status":
        _print({"jev": JevService(cfg, db).status(),
                "episodes": [dict(r) for r in db.q("SELECT episode_id,version,objective,phase,updated_by_deliver_id,updated_at FROM episode_build_states ORDER BY updated_at DESC")],
                "pending_activations": [dict(r) for r in db.q("SELECT * FROM listener_activations WHERE status='SELECTED' ORDER BY created_at")]})
        return 0
    if args.action == "emit":
        if not args.episode or not args.source_deliver or not args.event_type:
            print("listener emit requires --episode, --source-deliver and --event-type", file=sys.stderr)
            return 2
        try:
            payload = json.loads(Path(args.state).read_text(encoding="utf-8")) if args.state else {}
            if not isinstance(payload, dict):
                raise ValueError("state file must contain an object")
            routed = ListenerEngine(cfg, db).emit(
                episode_id=args.episode, source_deliver_id=args.source_deliver,
                event_type=args.event_type, episode_patch=payload.get("episode"),
                build_patch=payload.get("build"), result=payload.get("result"),
                context_refs=payload.get("context_refs"), objective=payload.get("objective"),
                phase=payload.get("phase"))
        except (OSError, ValueError) as exc:
            print(f"listener event rejected: {exc}", file=sys.stderr)
            return 1
        _print(routed.__dict__)
        return 0
    return 1


def cmd_jev(args, cfg):
    from .jev import JevService
    db = _db(cfg)
    service = JevService(cfg, db)
    if args.action == "status":
        result = service.health_check()
        if result["status"] == "READY":
            result["released_tasks"] = control.release_jev_backoff(db, "cli:jev-status")
            if result["released_tasks"]:
                import signal
                pid = control.daemon_pid(cfg)
                if pid and pid != os.getpid():
                    try:
                        os.kill(pid, signal.SIGUSR1)
                    except (ProcessLookupError, PermissionError):
                        pass
        _print(result)
        return 0
    if args.action == "docs-refresh":
        _print(service.knowledge.refresh(force=args.force))
        return 0
    return 1


def cmd_worktree(args, cfg):
    from .worktrees import WorktreeManager
    db, wt = _db(cfg), WorktreeManager(cfg)
    if args.action == "list":
        for p in wt.worktree_list():
            print(p)
        return 0
    if args.action == "prune":
        for t in db.q("SELECT task_id FROM tasks WHERE state=?", (TaskState.PASSED.value,)):
            ok, msg = wt.remove_clean_worktree(t["task_id"])
            if ok or msg != "no worktree":
                print(f"{t['task_id']}: {'removed (branch kept)' if ok else msg}")
        return 0
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wwii-build", description="WWII Build Manager — deterministic local build farm")
    ap.add_argument("--repo", help="repo root (default: auto-detect)")
    ap.add_argument("--config", help="config TOML (default: <repo>/.wwii-build/config.toml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("doctor", help="check installation/auth/flags (no inference)")
    p.add_argument("--no-quota", action="store_true", help="skip the Codex app-server quota read")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("config", help="config init|path|show")
    p.add_argument("action", choices=["init", "path", "show"])
    p.set_defaults(fn=cmd_config)
    sub.add_parser("import-plan", help="import dispatch_tasks from the registry").set_defaults(fn=cmd_import)
    sub.add_parser("baseline", help="create the integration branch from the current plan files").set_defaults(fn=cmd_baseline)
    for name in ("dry-run",):
        p = sub.add_parser(name, help="show what would run; no LLM request")
        p.add_argument("--no-provider-checks", action="store_true")
        p.add_argument("--json", action="store_true")
        p.set_defaults(fn=cmd_dry_run)
    p = sub.add_parser("start", help="run the scheduler (foreground) + dashboard")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-provider-checks", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-dashboard", action="store_true")
    p.add_argument("--exit-when-idle", action="store_true")
    p.set_defaults(fn=cmd_start)
    p = sub.add_parser("pause", help="stop starting new tasks")
    p.add_argument("--interrupt-running", action="store_true")
    p.set_defaults(fn=cmd_pause)
    p = sub.add_parser("resume")
    p.add_argument("--clear-emergency", action="store_true")
    p.set_defaults(fn=cmd_resume)
    sub.add_parser("stop", help="graceful stop: SIGINT workers, timeout, then kill; save state").set_defaults(fn=cmd_stop)
    sub.add_parser("kill", help="EMERGENCY: kill workers now, disable scheduler").set_defaults(fn=cmd_kill)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("tasks")
    p.add_argument("--state")
    p.set_defaults(fn=cmd_tasks)
    for name, fn in (("task", cmd_task), ("retry", cmd_retry)):
        p = sub.add_parser(name)
        p.add_argument("task_id")
        p.set_defaults(fn=fn)
    p = sub.add_parser("recheck", help="re-run deterministic acceptance on the existing worktree (no LLM)")
    p.add_argument("task_id")
    p.add_argument("--run", action="store_true", help="run it now in this process (daemon must not be running)")
    p.set_defaults(fn=cmd_recheck)
    p = sub.add_parser("skip")
    p.add_argument("task_id")
    p.add_argument("--as-satisfied", action="store_true", help="mark PASSED manually so dependents unlock")
    p.set_defaults(fn=cmd_skip)
    p = sub.add_parser("set-provider", help="change provider/model for the next attempt of a task")
    p.add_argument("task_id")
    p.add_argument("model_key")
    p.set_defaults(fn=cmd_set_provider)
    sub.add_parser("approvals").set_defaults(fn=cmd_approvals)
    p = sub.add_parser("approve")
    p.add_argument("ident", help="approval id or task id")
    p.add_argument("--model", help="for escalations: model key to use next")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("reject")
    p.add_argument("ident")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_reject)
    sub.add_parser("providers").set_defaults(fn=cmd_providers)
    p = sub.add_parser("provider")
    p.add_argument("action", choices=["refresh", "reset-done"],
                   help="reset-done: you used a usage reset in the Claude/Codex app; clear the block and re-check")
    p.add_argument("name")
    p.set_defaults(fn=cmd_provider)
    p = sub.add_parser("dashboard", help="serve the dashboard without the scheduler")
    p.add_argument("--persistent", action="store_true", help="wait for the port and keep the dashboard available")
    p.set_defaults(fn=cmd_dashboard)
    p = sub.add_parser("add-task", help="create a manual task (model, MCP, context, dependencies)")
    p.add_argument("title")
    p.add_argument("--name", help="short id (MANUAL/<name>)")
    p.add_argument("--instructions", "-i")
    p.add_argument("--model", default="", help="model key (default: automatic, best fit)")
    p.add_argument("--no-fallback", action="store_true")
    p.add_argument("--owner")
    p.add_argument("--dep", action="append", help="dependency task id (repeatable)")
    p.add_argument("--scope", action="append", help="write scope path (repeatable)")
    p.add_argument("--read-only", action="store_true")
    p.add_argument("--context", action="append", help="context file inlined in the prompt (repeatable)")
    p.add_argument("--reference", action="append", help="reference-only path (repeatable)")
    p.add_argument("--mcp", action="append", help="MCP server name (repeatable)")
    p.add_argument("--check", action="append", help="acceptance shell command (repeatable)")
    p.add_argument("--auto-approve", action="store_true",
                   help="integrate automatically after built-in/default acceptance checks pass")
    p.add_argument("--allow-web", action="store_true",
                   help="research task with live web access (web search/fetch); not allowed for Task Manager repairs")
    p.set_defaults(fn=cmd_add_task)
    p = sub.add_parser("battle-request", help="request a battle: one action creates the whole battle-builder task chain "
                                              "(evidence -> maps -> web research -> reconstruction -> package)")
    p.add_argument("title", help="battle title, e.g. 'Brécourt Manor assault'")
    p.add_argument("--key", help="battle_key slug (default: generated from the title)")
    p.add_argument("--date", required=True, help="YYYY-MM-DD or a range YYYY-MM-DD..YYYY-MM-DD")
    p.add_argument("--date-end", help="end of the range, when --date is the start only")
    p.add_argument("--bbox", help="west,south,east,north in degrees; write it as --bbox=-1.3,49.3,-1.1,49.5")
    p.add_argument("--place", help="place name (optional)")
    p.add_argument("--notes", help="free notes for the researchers (optional)")
    p.add_argument("--dry-run", action="store_true", help="show the chain without creating tasks")
    p.set_defaults(fn=cmd_battle_request)
    p = sub.add_parser("unstick", help="diagnose why the run is stuck and continue it (same as the dashboard button)")
    p.set_defaults(fn=cmd_unstick)
    p = sub.add_parser("onboard", help="bring a system into the manager from a manifest: RAG context files, "
                                       "Delivers, context sources and graph RAG ingest (idempotent)")
    p.add_argument("manifest", nargs="?", help="path or name in tools/build_manager/systems/ (e.g. ww2_atlas)")
    p.add_argument("--list", action="store_true", help="list onboarded systems and available manifests")
    p.add_argument("--dry-run", action="store_true", help="render only; write nothing")
    p.add_argument("--no-graph", action="store_true", help="skip the graph RAG ingest")
    p.add_argument("--graph-only", action="store_true", help="only (re)send changed context files to the graph")
    p.add_argument("--force", action="store_true", help="with --graph-only: re-send even when unchanged")
    p.add_argument("--text", action="store_true", help="with --graph-only: also send the context text through the "
                                                         "graph service's LLM extraction (slow)")
    p.set_defaults(fn=cmd_onboard)
    p = sub.add_parser("plan", help="free-text prompt -> capable planner model -> proposed tasks for approval")
    p.add_argument("prompt", help="text, or - to read stdin")
    p.add_argument("--model", help="planner model key (default: automatic, best fit for PLAN)")
    p.set_defaults(fn=cmd_plan)
    sub.add_parser("proposals").set_defaults(fn=cmd_proposals)
    p = sub.add_parser("events")
    p.add_argument("-n", type=int, default=50)
    p.set_defaults(fn=cmd_events)
    p = sub.add_parser("listener", help="inspect state or emit a Deliver event for Jev-gated listener routing")
    p.add_argument("action", choices=["status", "emit"])
    p.add_argument("--episode")
    p.add_argument("--source-deliver")
    p.add_argument("--event-type")
    p.add_argument("--state", help="JSON file with episode/build/result/context_refs patches")
    p.set_defaults(fn=cmd_listener)
    p = sub.add_parser("jev", help="Jev status or live-documentation cache")
    p.add_argument("action", choices=["status", "docs-refresh"])
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_jev)
    p = sub.add_parser("worktree")
    p.add_argument("action", choices=["list", "prune"])
    p.set_defaults(fn=cmd_worktree)
    args = ap.parse_args(argv)
    cfg = _cfg(args)
    return args.fn(args, cfg) or 0


if __name__ == "__main__":
    sys.exit(main())
