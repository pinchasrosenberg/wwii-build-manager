"""Control operations shared by the CLI and the dashboard.

State-only operations (approve/reject/retry/skip/set provider/pause flag/resume) are
applied directly to SQLite; the daemon re-reads state every cycle. Operations that
touch processes (stop, kill, pause --interrupt-running, skip of a running task,
provider refresh) are queued in ``control_requests`` and the daemon is woken with
SIGUSR1. With no daemon alive, ``kill`` acts directly on recorded PIDs (verified by
process start time, so a reused PID is never signalled).
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
from pathlib import Path

from .config import Config
from .db import DB
from .models import AttemptStatus, TaskState, iso, parse_iso, utcnow
from .supervisor import is_same_process, signal_group

PROCESS_COMMANDS = {"stop", "kill", "pause_interrupt", "skip_running", "refresh", "interrupt_task"}


class ControlError(Exception):
    pass


# --- daemon liveness --------------------------------------------------------
def lock_path(cfg: Config) -> Path:
    return cfg.state_dir / "daemon.lock"


def daemon_pid(cfg: Config) -> int | None:
    """PID of the live daemon holding the lock, else None."""
    p = lock_path(cfg)
    if not p.exists():
        return None
    try:
        fd = os.open(p, os.O_RDWR)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            return int(Path(p).read_text().strip() or 0) or None
        except (ValueError, OSError):
            return None
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def acquire_daemon_lock(cfg: Config) -> int:
    p = lock_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ControlError(f"another wwii-build daemon is running (pid {daemon_pid(cfg)})")
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd


# --- queued process commands -------------------------------------------------
def enqueue(db: DB, cfg: Config, command: str, args: dict | None = None, source: str = "cli") -> int:
    rid = db.x("INSERT INTO control_requests(at, command, args, source) VALUES(?,?,?,?)",
               (iso(utcnow()), command, json.dumps(args or {}), source))
    db.event("CONTROL_REQUESTED", command=command, args=args or {}, source=source)
    pid = daemon_pid(cfg)
    if pid and pid != os.getpid():
        try:
            os.kill(pid, signal.SIGUSR1)
        except ProcessLookupError:
            pass
    return rid


# --- state-only operations ---------------------------------------------------
def pause(db: DB, cfg: Config, interrupt_running: bool = False, source: str = "cli") -> str:
    db.set_flag("paused", "1")
    db.event("PAUSE_REQUESTED", interrupt_running=interrupt_running, source=source)
    if interrupt_running:
        enqueue(db, cfg, "pause_interrupt", {}, source)
        return "paused; running tasks will be interrupted (work kept in worktrees)"
    return "paused; no new tasks will start; running tasks finish"


def resume(db: DB, cfg: Config, clear_emergency: bool = False, source: str = "cli") -> str:
    msgs = []
    if db.get_flag("emergency_stop"):
        if not clear_emergency:
            raise ControlError("emergency-stop marker is set; use `wwii-build resume --clear-emergency`")
        db.set_flag("emergency_stop", None)
        msgs.append("emergency marker cleared")
    db.set_flag("paused", None)
    db.set_flag("stop_requested", None)
    n = db.x("UPDATE tasks SET state=?, state_reason=?, updated_at=? WHERE state=?",
             (TaskState.PENDING.value, "resumed", iso(utcnow()), TaskState.PAUSED.value))
    db.event("RESUME_REQUESTED", source=source, clear_emergency=clear_emergency)
    msgs.append("resumed")
    return "; ".join(msgs)


def _task_or_raise(db: DB, task_id: str):
    t = db.task(task_id)
    if not t:
        raise ControlError(f"unknown task {task_id}")
    return t


def retry(db: DB, task_id: str, source: str = "cli") -> str:
    t = _task_or_raise(db, task_id)
    if t["state"] in (TaskState.RUNNING.value, TaskState.REVIEWING.value, TaskState.PAUSING.value):
        raise ControlError(f"{task_id} is {t['state']}")
    if t["state"] == TaskState.PASSED.value:
        raise ControlError(f"{task_id} already PASSED; not re-running finished work")
    if t["kind"] == "repair":
        p = db.task(t["parent_task_id"])
        if p["active_repair_id"] != task_id or p["state"] != TaskState.WAITING_REPAIR.value:
            raise ControlError(f"{task_id} is not the parent's active repair")
    else:
        _cancel_active_repair(db, task_id, "superseded by a full retry of the parent")
    db.set_task_state(task_id, TaskState.PENDING.value, "manual retry", failed_attempts=0, not_before=None)
    db.x("UPDATE approvals SET status='rejected', decided_at=?, note='superseded by retry' "
         "WHERE task_id=? AND status='pending' AND kind IN ('escalation','review')", (iso(utcnow()), task_id))
    db.event("TASK_RETRY_REQUESTED", task_id=task_id, source=source)
    return f"{task_id} -> PENDING"


def release_jev_backoff(db: DB, source: str = "dashboard") -> int:
    """Retry only tasks delayed by the fail-closed Jev context gate."""
    reason = "Jev did not approve required LLM context; retry is delayed"
    rows = []
    for row in db.q("SELECT task_id,state_reason,updated_at FROM tasks WHERE state='PENDING' AND not_before IS NOT NULL"):
        if row["state_reason"] == reason:
            rows.append(row)
            continue
        # The scheduler replaces the gate reason with a generic retry countdown.
        # The most recent gate event must still be adjacent to that update, so an
        # unrelated technical/quota backoff is never cleared accidentally.
        if not (row["state_reason"] or "").startswith("retry backoff until "):
            continue
        gate = db.one("SELECT at FROM event_log WHERE task_id=? AND event='JEV_CONTEXT_GATE_BLOCKED' "
                      "ORDER BY id DESC LIMIT 1", (row["task_id"],))
        if gate:
            elapsed = (parse_iso(row["updated_at"]) - parse_iso(gate["at"])).total_seconds()
            if 0 <= elapsed <= 10:
                rows.append(row)
    if not rows:
        return 0
    now = iso(utcnow())
    with db.tx():
        for row in rows:
            db.conn.execute(
                "UPDATE tasks SET state_reason=?,not_before=NULL,updated_at=? WHERE task_id=?",
                ("Jev READY; context routing retry requested", now, row["task_id"]))
        db.event("JEV_BACKOFF_RELEASED", provider="jev", source=source,
                 task_count=len(rows), task_ids=[row["task_id"] for row in rows])
    return len(rows)


def expedite(db: DB, task_id: str, source: str = "cli") -> str:
    """Move an already eligible task to the front of the next dispatch decision.

    The boost is deliberately one-shot: the scheduler clears it when the task
    starts. Dependencies, provider/quota checks, capacity and writer locks still
    apply, so this never turns an ineligible task into executable work.
    """
    task = _task_or_raise(db, task_id)
    if task["state"] != TaskState.READY.value:
        raise ControlError(f"{task_id} is {task['state']}; only READY tasks can be expedited")
    row = db.one("SELECT COALESCE(MAX(dispatch_priority),0) top FROM tasks")
    priority = max(1, int(row["top"] if row else 0) + 1)
    now = iso(utcnow())
    db.x("UPDATE tasks SET dispatch_priority=?,updated_at=? WHERE task_id=?",
         (priority, now, task_id))
    db.event("TASK_EXPEDITED", task_id=task_id, source=source, dispatch_priority=priority,
             eligibility="unchanged")
    return f"{task_id} expedited; it will start at the next eligible dispatch opportunity"


def skip(db: DB, cfg: Config, task_id: str, satisfy: bool = False, source: str = "cli") -> str:
    t = _task_or_raise(db, task_id)
    if t["state"] in (TaskState.RUNNING.value, TaskState.REVIEWING.value, TaskState.PAUSING.value):
        enqueue(db, cfg, "skip_running", {"task_id": task_id, "satisfy": satisfy}, source)
        return f"{task_id} is running; queued interrupt + skip"
    if t["kind"] == "repair":
        db.set_task_state(task_id, TaskState.CANCELLED.value, "repair skipped by user")
        p = db.task(t["parent_task_id"])
        if p["active_repair_id"] == task_id:
            db.x("UPDATE tasks SET active_repair_id=NULL WHERE task_id=?", (p["task_id"],))
            db.set_task_state(p["task_id"], TaskState.BLOCKED.value, f"repair {task_id} skipped by user")
        db.event("TASK_SKIPPED", task_id=task_id, satisfy=False, source=source)
        return f"{task_id} -> CANCELLED; parent {t['parent_task_id']} -> BLOCKED"
    _cancel_active_repair(db, task_id, "parent skipped")
    if satisfy:
        db.set_task_state(task_id, TaskState.PASSED.value, "manually marked satisfied (skip --as-satisfied)")
        db.x("INSERT INTO reviews(task_id, reviewer, verdict, findings, created_at) VALUES(?,?,?,?,?)",
             (task_id, "human", "approve", json.dumps(["skipped as satisfied; no work verified"]), iso(utcnow())))
    else:
        db.set_task_state(task_id, TaskState.CANCELLED.value, "skipped by user")
    db.event("TASK_SKIPPED", task_id=task_id, satisfy=satisfy, source=source)
    return f"{task_id} -> {'PASSED (manual)' if satisfy else 'CANCELLED'}"


def set_provider(db: DB, cfg: Config, task_id: str, model_key: str, source: str = "cli") -> str:
    _task_or_raise(db, task_id)
    if model_key not in cfg.data["models"]:
        raise ControlError(f"unknown model profile {model_key!r}; known: {', '.join(cfg.data['models'])}")
    t = db.task(task_id)
    if t["state"] in (TaskState.RUNNING.value, TaskState.REVIEWING.value):
        raise ControlError("provider affinity: cannot switch a running task; it applies to the next attempt "
                           "after it finishes or is stopped")
    now = iso(utcnow())
    db.x("UPDATE tasks SET preferred_model_key=?, updated_at=? WHERE task_id=?", (model_key, now, task_id))
    # An explicit user choice counts as approval for that premium model on this task.
    db.x("UPDATE approvals SET status='approved', decided_at=?, note='chosen via change-provider' "
         "WHERE task_id=? AND kind='model' AND subject=? AND status='pending'", (now, task_id, model_key))
    db.x("UPDATE approvals SET status='rejected', decided_at=?, note=? "
         "WHERE task_id=? AND kind='model' AND subject!=? AND status='pending'",
         (now, f"superseded: user chose {model_key}", task_id, model_key))
    if not db.one("SELECT 1 FROM approvals WHERE task_id=? AND kind='model' AND subject=? AND status='approved'",
                  (task_id, model_key)):
        db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, note, created_at, decided_at) "
             "VALUES(?,?,?,?,?,?,?,?)", (task_id, "model", model_key, "approved", "user selected provider",
                                         "chosen via change-provider", now, now))
    if t["state"] in (TaskState.WAITING_APPROVAL.value, TaskState.WAITING_PROVIDER.value,
                      TaskState.WAITING_QUOTA.value, TaskState.BLOCKED.value, TaskState.FAILED.value):
        db.set_task_state(task_id, TaskState.PENDING.value, f"provider set to {model_key}", failed_attempts=0)
    db.event("PROVIDER_CHANGED", task_id=task_id, model_key=model_key, source=source)
    return f"{task_id}: next attempt uses {model_key}"


def decide(db: DB, cfg: Config, approval_id: int, approve: bool, note: str | None = None,
           model_key: str | None = None, source: str = "cli") -> str:
    a = db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
    if not a:
        raise ControlError(f"no approval #{approval_id}")
    if a["status"] != "pending":
        raise ControlError(f"approval #{approval_id} already {a['status']}")
    now = iso(utcnow())
    db.x("UPDATE approvals SET status=?, decided_at=?, note=? WHERE id=?",
         ("approved" if approve else "rejected", now, note, approval_id))
    tid, kind = a["task_id"], a["kind"]
    db.event("APPROVAL_DECIDED", task_id=tid, approval_id=approval_id, kind=kind, subject=a["subject"],
             approved=approve, source=source)
    if kind == "model":
        if tid:
            db.set_task_state(tid, TaskState.PENDING.value,
                              f"{a['subject']} {'approved' if approve else 'rejected'}")
        return f"#{approval_id} {'approved' if approve else 'rejected'}"
    if kind == "review":
        db.x("INSERT INTO reviews(task_id, reviewer, verdict, findings, created_at) VALUES(?,?,?,?,?)",
             (tid, "human", "approve" if approve else "changes_requested", json.dumps([note] if note else []), now))
        if approve:
            db.set_task_state(tid, TaskState.CODE_READY.value, "review approved; integrating", )
            db.set_flag(f"review_approved:{tid}", "1")
        else:
            t = db.task(tid)
            db.set_task_state(tid, TaskState.PENDING.value, "review rejected: " + (note or ""),
                              failed_attempts=(t["failed_attempts"] or 0) + 1)
        return f"review #{approval_id} {'approved' if approve else 'rejected'}"
    if kind in ("escalation", "astra_recommended"):
        if approve:
            key = model_key or a["subject"]
            if key:
                set_provider(db, cfg, tid, key, source)
            db.set_task_state(tid, TaskState.PENDING.value, f"escalation approved ({key or 'same route'})",
                              failed_attempts=0)
        else:
            if kind == "escalation":
                db.set_task_state(tid, TaskState.FAILED.value, "escalation rejected by user")
        return f"#{approval_id} {'approved' if approve else 'rejected'}"
    if kind in ("repair_limit", "architecture_review"):
        if not approve:
            db.set_task_state(tid, TaskState.FAILED.value, f"{kind} rejected by user")
            return f"#{approval_id} rejected; {tid} -> FAILED"
        from . import repair as rp
        parent = db.task(tid)                      # the parent carries its latest failure context
        ctx = json.loads(parent["repair_context"]) if parent["repair_context"] else {}
        c = rp.Classification(ctx.get("class", rp.REPAIRABLE_CODE), ctx.get("summary", a["reason"] or ""),
                              ctx.get("failing_checks", []), ctx.get("violating_paths", []), ctx.get("foreign_owned", {}),
                              ctx.get("shared_contracts", []), outputs=ctx.get("check_outputs", []))
        if kind == "architecture_review":
            c.cls = rp.ARCHITECTURAL_CONFLICT
        db.x("UPDATE tasks SET repair_budget_extra=repair_budget_extra+1 WHERE task_id=?", (tid,))
        profile = "REPAIR_ARCHITECTURE" if kind == "architecture_review" else None
        rid = rp.create_repair(db, cfg, tid, parent["failed_attempt_id"], c, ctx.get("head"),
                               preferred_model=model_key, profile=profile)
        if model_key:   # the user's explicit model choice is the approval for that premium model
            db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, note, created_at, decided_at) "
                 "VALUES(?,?,?,?,?,?,?,?)", (rid, "model", model_key, "approved", f"chosen in {kind} approval",
                                             note, now, now))
        return f"#{approval_id} approved; created {rid}" + (f" on {model_key}" if model_key else "")
    if kind == "dependency_missing":
        if approve:
            db.set_task_state(tid, TaskState.CODE_READY.value, "dependency reported available; acceptance re-runs")
            return f"#{approval_id} approved; {tid} acceptance re-runs"
        db.set_task_state(tid, TaskState.FAILED.value, "dependency_missing rejected by user")
        return f"#{approval_id} rejected; {tid} -> FAILED"
    if kind == "plan_proposal":
        from . import manual as mn
        pid = int(a["subject"])
        if not approve:
            db.x("UPDATE plan_proposals SET status='rejected', decided_at=? WHERE id=?", (now, pid))
            return f"proposal #{pid} rejected; nothing created"
        try:
            from .mcp import available
            ids = mn.apply_proposal(db, cfg, pid, available(cfg))
        except mn.ManualError as e:
            db.x("UPDATE approvals SET status='pending', decided_at=NULL WHERE id=?", (approval_id,))
            raise ControlError(str(e))
        return f"proposal #{pid} approved; created {len(ids)} tasks: {', '.join(ids)}"
    if kind == "dependency_change":
        return f"#{approval_id} recorded"
    return f"#{approval_id} {'approved' if approve else 'rejected'}"


# Approvals that spend another repair/retry cycle: auto-approved at most this many times per task, so a task that
# can never pass does not loop forever on the subscription quota (the rest then waits for you).
LOOPING_APPROVALS = ("escalation", "repair_limit", "architecture_review", "astra_recommended")


def auto_approve_pending(db: DB, cfg: Config, source: str = "auto", force: bool = False) -> list[str]:
    """Full automatic mode (flag ``review_auto_approve_all``): approve every pending approval.
    ``force`` applies the same rules once even when the mode is off (the user pressed "continue")."""
    if not force and db.get_flag("review_auto_approve_all") != "1":
        return []
    cap = int(cfg.section("approvals").get("auto_max_per_task", 3))
    after_cap = str(cfg.section("approvals").get("auto_after_cap", "reject"))   # reject | ask
    done = []
    for a in db.q("SELECT * FROM approvals WHERE status='pending' ORDER BY id"):
        if a["kind"] in LOOPING_APPROVALS and a["task_id"]:
            used = db.one("SELECT COUNT(*) n FROM approvals WHERE task_id=? AND kind=? AND status='approved' "
                          "AND note LIKE 'auto:%'", (a["task_id"], a["kind"]))["n"]
            if used >= cap:
                if after_cap != "reject":
                    continue          # leave it for the user
                # Nothing waits for a human in full automatic mode: one more loop would only repeat a failure
                # that already survived `cap` automatic rounds, so the task is closed as FAILED.
                try:
                    decide(db, cfg, int(a["id"]), False,
                           f"auto: rejected after {cap} automatic {a['kind']} approvals ({source})", source=source)
                    done.append(f"#{a['id']} {a['kind']} {a['task_id']} (rejected: cap)")
                except ControlError as e:
                    db.event("AUTO_APPROVAL_FAILED", task_id=a["task_id"], approval_id=a["id"], kind=a["kind"],
                             error=str(e)[:300])
                continue
        try:
            decide(db, cfg, int(a["id"]), True, f"auto: approved by full automatic mode ({source})", source=source)
            done.append(f"#{a['id']} {a['kind']} {a['task_id'] or ''}")
        except ControlError as e:
            # e.g. an invalid planner proposal: approving can never succeed, so close it instead of retrying forever.
            db.event("AUTO_APPROVAL_FAILED", task_id=a["task_id"], approval_id=a["id"], kind=a["kind"], error=str(e)[:300])
            try:
                decide(db, cfg, int(a["id"]), False, f"auto: rejected, approval failed: {str(e)[:200]}", source=source)
                done.append(f"#{a['id']} {a['kind']} {a['task_id'] or ''} (rejected: {str(e)[:80]})")
            except ControlError:
                pass
    if done:
        db.event("AUTO_APPROVED", source=source, approvals=done)
    return done


def recheck(db: DB, task_id: str, source: str = "cli") -> str:
    """Re-run deterministic acceptance (and integration) without re-running the worker."""
    t = _task_or_raise(db, task_id)
    if t["kind"] == "repair":
        raise ControlError("recheck the parent task, not the repair")
    if t["state"] in (TaskState.RUNNING.value, TaskState.PAUSING.value, TaskState.REVIEWING.value, TaskState.PASSED.value):
        raise ControlError(f"{task_id} is {t['state']}")
    if not t["worktree"] or not db.one("SELECT 1 FROM task_attempts WHERE task_id=? AND kind='execute' AND ended_at "
                                       "IS NOT NULL", (task_id,)):
        raise ControlError(f"{task_id} has no finished attempt/worktree to check")
    _cancel_active_repair(db, task_id, "superseded by manual recheck")
    db.set_task_state(task_id, TaskState.CODE_READY.value, "manual recheck: acceptance re-runs")
    db.event("TASK_RECHECK_REQUESTED", task_id=task_id, source=source)
    return f"{task_id} -> CODE_READY (acceptance re-runs; worker not re-run)"


def _cancel_active_repair(db: DB, parent_id: str, reason: str) -> None:
    p = db.task(parent_id)
    rid = p["active_repair_id"] if p and "active_repair_id" in p.keys() else None
    if not rid:
        return
    r = db.task(rid)
    if r and r["state"] in (TaskState.RUNNING.value, TaskState.PAUSING.value):
        raise ControlError(f"{rid} is running; stop or pause it first")
    if r and r["state"] not in (TaskState.PASSED.value, TaskState.FAILED.value, TaskState.CANCELLED.value):
        db.set_task_state(rid, TaskState.CANCELLED.value, reason)
    db.x("UPDATE tasks SET active_repair_id=NULL WHERE task_id=?", (parent_id,))


def provider_reset_done(db: DB, cfg: Config, provider: str, source: str = "cli") -> str:
    """User says: 'I used a usage reset in the Claude/Codex app'. Clear blocks and let the scheduler continue.
    For Codex the daemon re-reads the real rate limits right away (a stale reset shows up again)."""
    if provider not in cfg.data["providers"]:
        raise ControlError(f"unknown provider {provider}")
    from .quota import QuotaManager
    cleared = QuotaManager(db, cfg.section("quota")).user_reset(provider)
    db.x("UPDATE tasks SET state=?, state_reason=?, updated_at=? WHERE state=?",
         (TaskState.PENDING.value, f"{provider} reset reported by user", iso(utcnow()), TaskState.WAITING_QUOTA.value))
    enqueue(db, cfg, "refresh", {"provider": provider}, source)
    return (f"{provider}: reset recorded ({', '.join(cleared) or 'no active block'}); waiting tasks re-evaluated"
            + ("" if daemon_pid(cfg) else "; daemon not running — re-checked on next start"))


def stop_recorded_workers(db: DB, graceful: float = 20.0) -> list[str]:
    """No daemon alive but workers recorded (crash leftovers): SIGINT guard, then KILL group."""
    import time
    out = []
    for w in db.q("SELECT * FROM workers"):
        if is_same_process(w["pid"], w["process_started"]):
            os.kill(w["pid"], signal.SIGINT)
            deadline = time.time() + graceful
            while time.time() < deadline and is_same_process(w["pid"], w["process_started"]):
                time.sleep(0.2)
            if is_same_process(w["pid"], w["process_started"]):
                signal_group(w["pgid"], signal.SIGKILL)
            out.append(f"{w['task_id']} pid {w['pid']} stopped")
    return out


def pending_approval_for_task(db: DB, task_id: str) -> int | None:
    r = db.one("SELECT id FROM approvals WHERE task_id=? AND status='pending' ORDER BY id DESC", (task_id,))
    return r["id"] if r else None


# --- offline emergency kill -----------------------------------------------------
def kill_recorded_workers(db: DB, reason: str) -> list[str]:
    killed = []
    for w in db.q("SELECT * FROM workers"):
        if is_same_process(w["pid"], w["process_started"]):
            signal_group(w["pgid"], signal.SIGKILL)
            killed.append(f"{w['task_id']} pid {w['pid']}")
        db.update_attempt(w["attempt_id"], status=AttemptStatus.INTERRUPTED.value, ended_at=iso(utcnow()),
                          failure_class="emergency_kill")
        db.set_task_state(w["task_id"], TaskState.PENDING.value, f"emergency kill: {reason}; work kept in worktree")
        db.x("DELETE FROM workers WHERE attempt_id=?", (w["attempt_id"],))
    return killed
