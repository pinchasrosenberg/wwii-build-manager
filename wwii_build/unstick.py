"""Why is the run stuck? Continue it. One deterministic diagnose-and-resume pass (dashboard button, CLI, MCP).

Every finding is explained in Hebrew and every action is recorded. Actions only use the manager's own control
paths (resume, approvals, retry, recheck, repair, provider refresh). Retries that would only repeat the same
failure are bounded per task, so pressing the button repeatedly cannot loop forever.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import control
from .config import MANAGER_DIR, Config
from .db import DB
from .models import ProviderStatus, TaskState, iso, parse_iso, utcnow

MAX_UNSTICK_RETRIES = 2          # per task, over its lifetime
CODE_READY_STALE_MINUTES = 10


def _retries(db: DB, task_id: str) -> int:
    return db.one("SELECT COUNT(*) n FROM event_log WHERE event='UNSTICK_RETRY' AND task_id=?", (task_id,))["n"]


def _root_blockers(db: DB) -> dict[str, set[str]]:
    """Unfinished prerequisites at the bottom of every WAITING_DEPENDENCY chain -> the tasks they hold up."""
    waiting = {r["task_id"] for r in db.q("SELECT task_id FROM tasks WHERE state='WAITING_DEPENDENCY'")}
    roots: dict[str, set[str]] = {}

    def walk(tid: str, origin: str, seen: set[str]) -> None:
        for dep in db.deps(tid):
            if dep in seen:
                continue
            seen.add(dep)
            row = db.task(dep)
            if row is None or row["state"] == TaskState.PASSED.value:
                continue
            if row["state"] == TaskState.WAITING_DEPENDENCY.value:
                walk(dep, origin, seen)
            else:
                roots.setdefault(dep, set()).add(origin)
    for tid in waiting:
        walk(tid, tid, set())
    return roots


def _alternate_model(cfg: Config, row) -> str | None:
    """Best-fit model for the task's profile other than the one that kept failing (fit order, any provider)."""
    from .routing import fit_chain
    chain = fit_chain(cfg, None, row["model_profile"] or "MANUAL")
    last = row["last_model_key"] or row["preferred_model_key"]
    for key in chain:
        if key != last and cfg.model(key).automatic:
            return key
    return None


def _resolve_merge_conflict(cfg: Config, db: DB, row) -> str:
    """Merge the integration branch into the task worktree, commit the conflict markers, and open a repair that
    resolves them. The repair runs in the same worktree; integration then merges cleanly."""
    from . import repair as rp
    from .worktrees import IDENT, WorktreeManager
    wt = WorktreeManager(cfg)
    path = Path(row["worktree"] or "")
    if not path.is_dir():
        raise control.ControlError("task worktree is missing")
    r = wt.git(*IDENT, "merge", "--no-ff", "--no-commit", wt.branch, cwd=path, check=False)
    if r.rc == 0:
        wt.git(*IDENT, "commit", "--no-edit", "-m", "wwii-build: merge integration", cwd=path, check=False)
        control.recheck(db, row["task_id"], "unstick")
        return "integration merged cleanly; acceptance re-runs"
    conflicted = [x for x in wt.git("diff", "--name-only", "--diff-filter=U", cwd=path, check=False).out.splitlines()
                  if x.strip()]
    wt.git("add", "-A", cwd=path, check=False)
    wt.git(*IDENT, "commit", "--no-verify", "-m", "wwii-build: merge integration (conflict markers to resolve)",
           cwd=path, check=False)
    c = rp.Classification(rp.REPAIRABLE_CODE,
                          "merge conflict with the integration branch: remove every conflict marker (<<<<<<<, "
                          "=======, >>>>>>>) in " + ", ".join(conflicted[:12]) + " keeping both sides' intent, so the "
                          "task's checks pass on top of the latest integrated work", failing=["merge-conflict"])
    rid = rp.create_repair(db, cfg, row["task_id"], None, c, wt.head(path))
    return f"conflict markers committed in {len(conflicted)} file(s); {rid} resolves them"


def _start_daemon(cfg: Config) -> None:
    log = open(cfg.state_dir / "daemon.log", "ab")
    subprocess.Popen([str(MANAGER_DIR / "bin" / "wwii-build"), "start", "--no-dashboard"], cwd=str(cfg.repo),
                     stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                     env={**os.environ, "WWII_BUILD_REPO": str(cfg.repo)})


class _Stream(list):
    """A list that tells ``progress`` about every appended line (the findings/actions as they happen)."""

    def __init__(self, progress, prefix: str):
        super().__init__()
        self._progress, self._prefix = progress, prefix

    def append(self, item) -> None:
        super().append(item)
        if self._progress:
            try:
                self._progress(f"{self._prefix}{item}")
            except Exception:                # a dead listener (closed socket) must not stop the repair pass
                self._progress = None


def unstick(cfg: Config, db: DB, source: str = "dashboard", progress=None) -> dict:
    """One diagnose-and-resume pass. ``progress(line)`` (optional) hears each finding/action as it is recorded."""
    findings = _Stream(progress, "ממצא: ")
    actions = _Stream(progress, "פעולה: ")
    problems = _Stream(progress, "דורש אותך: ")
    now = utcnow()

    # 1. scheduler process and switches
    pid = control.daemon_pid(cfg)
    if not pid:
        findings.append("המתזמן לא רץ, ולכן שום משימה לא מתחילה.")
        _start_daemon(cfg)
        actions.append("הפעלתי את המתזמן ברקע (wwii-build start --no-dashboard).")
    if db.get_flag("emergency_stop"):
        findings.append("סימון עצירת חירום היה פעיל.")
        control.resume(db, cfg, clear_emergency=True, source=source)
        actions.append("ניקיתי את עצירת החירום והמשכתי.")
    elif db.get_flag("paused"):
        findings.append("המתזמן היה מושהה.")
        control.resume(db, cfg, source=source)
        actions.append("המשכתי (RESUME).")

    # 2. workers recorded as running whose process is gone
    from .supervisor import pid_alive
    dead = [w["task_id"] for w in db.q("SELECT task_id, pid FROM workers") if w["pid"] and not pid_alive(int(w["pid"]))]
    if dead:
        findings.append(f"{len(dead)} עובדים רשומים כרצים אבל התהליך שלהם מת: {', '.join(dead[:5])}.")
        problems.append("עובדים יתומים חוזרים לתור רק בהפעלה מחדש של המתזמן (reconcile): "
                        "wwii-build stop ואז wwii-build start.")

    # 3. approvals: nothing should wait for a human when the user asked to continue
    pending = db.one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"]
    if pending:
        findings.append(f"{pending} אישורים חיכו לך.")
        done = control.auto_approve_pending(db, cfg, source, force=True)
        actions.append(f"טיפלתי ב־{len(done)} אישורים: " + "; ".join(done[:6]))

    # 4. retry backoff / Jev backoff
    released = control.release_jev_backoff(db, source)
    if released:
        actions.append(f"שחררתי {released} משימות שהמתינו לשער ה־Jev.")
    waiting = [r["task_id"] for r in db.q("SELECT task_id, not_before FROM tasks WHERE state='PENDING' AND not_before IS NOT NULL")
               if (parse_iso(r["not_before"]) or now) > now]
    if waiting:
        db.x("UPDATE tasks SET not_before=NULL, updated_at=? WHERE state='PENDING' AND not_before IS NOT NULL", (iso(now),))
        findings.append(f"{len(waiting)} משימות חיכו להמתנה בין ניסיונות (backoff).")
        actions.append("ביטלתי את ההמתנה כדי שירוצו עכשיו.")

    # 5. providers: quota blocks with an unknown/low-confidence reset get re-probed
    for r in db.q("SELECT * FROM provider_state WHERE family='*'"):
        if r["status"] in (ProviderStatus.BLOCKED_UNKNOWN.value, ProviderStatus.UNKNOWN.value, ProviderStatus.AUTH_ERROR.value) \
                or (r["status"] in (ProviderStatus.BLOCKED_SESSION.value, ProviderStatus.BLOCKED_WEEKLY.value)
                    and r["confidence"] == "low"):
            control.enqueue(db, cfg, "refresh", {"provider": r["provider"]}, source)
            actions.append(f"ביקשתי בדיקה מחדש של הספק {r['provider']} ({r['status']}).")
        elif r["status"] in (ProviderStatus.BLOCKED_SESSION.value, ProviderStatus.BLOCKED_WEEKLY.value):
            findings.append(f"המכסה של {r['provider']} חסומה עד {r['blocked_until']} (מידע ודאי); משימות שלו ממתינות או עוברות לספק אחר.")

    # 6. the actual blockers: unfinished prerequisites at the root of dependency chains, plus stuck tasks
    roots = _root_blockers(db)
    stuck = {r["task_id"] for r in db.q("SELECT task_id FROM tasks WHERE state IN ('BLOCKED','FAILED') AND kind='task' "
                                        "AND task_id IN (SELECT depends_on FROM task_dependencies) ")}
    stuck |= {r["task_id"] for r in db.q("SELECT task_id FROM tasks WHERE state='BLOCKED' AND kind='task'")}
    targets = sorted(set(roots) | stuck, key=lambda t: -len(roots.get(t, ())))
    for tid in targets:
        row = db.task(tid)
        if row is None or row["state"] in (TaskState.PASSED.value, TaskState.RUNNING.value):
            continue
        held = roots.get(tid, set())
        reason = row["state_reason"] or ""
        head = f"{tid} [{row['state']}]" + (f" מעכב {len(held)} משימות" if held else "") + f": {reason[:160]}"
        if row["state"] not in (TaskState.FAILED.value, TaskState.BLOCKED.value):
            if row["state"] not in (TaskState.PENDING.value, TaskState.READY.value, TaskState.WAITING_REPAIR.value,
                                    TaskState.CODE_READY.value, TaskState.REVIEWING.value):
                findings.append(head)
            continue
        findings.append(head)
        if _retries(db, tid) >= MAX_UNSTICK_RETRIES:
            problems.append(f"{tid}: כבר נוסה {MAX_UNSTICK_RETRIES} פעמים מהכפתור הזה ועדיין נכשל — צריך החלטה שלך "
                            f"(לשנות את המשימה, לדלג עליה או לבטל אותה).")
            continue
        try:
            if "merge conflict" in reason:
                result = _resolve_merge_conflict(cfg, db, row)
            elif "active manager changed" in reason:
                result = control.retry(db, tid, "unstick") + " (תמונת מצב חדשה של מנהל המשימות)"
            else:
                alt = _alternate_model(cfg, row)
                result = control.retry(db, tid, "unstick")
                if alt:
                    db.x("UPDATE tasks SET preferred_model_key=? WHERE task_id=?", (alt, tid))
                    result += f" על {alt} (המודל הקודם נכשל שוב ושוב)"
            db.event("UNSTICK_RETRY", task_id=tid, source=source, result=result[:300])
            actions.append(f"{tid}: {result}")
        except Exception as exc:          # one bad task must not stop the rest of the pass
            problems.append(f"{tid}: לא הצלחתי להמשיך אוטומטית ({type(exc).__name__}: {str(exc)[:160]})")

    # 7. finished work that nobody is accepting
    for r in db.q("SELECT task_id, updated_at FROM tasks WHERE state='CODE_READY'"):
        t = parse_iso(r["updated_at"])
        if t and (now - t).total_seconds() > CODE_READY_STALE_MINUTES * 60 and \
                not db.one("SELECT 1 FROM workers WHERE task_id=?", (r["task_id"],)):
            try:
                control.recheck(db, r["task_id"], "unstick")
                actions.append(f"{r['task_id']}: בדיקת הקבלה נתקעה — הרצתי אותה מחדש.")
            except control.ControlError as exc:
                problems.append(f"{r['task_id']}: {exc}")

    # 8. wake the scheduler so it re-evaluates right away
    if control.daemon_pid(cfg):
        control.enqueue(db, cfg, "refresh", {"provider": "codex"}, source)
    counts = {r["state"]: r["n"] for r in db.q("SELECT state, COUNT(*) n FROM tasks GROUP BY state")}
    if not findings and not actions:
        findings.append("לא מצאתי סיבה לתקיעה: " + (db.get_flag("idle_reason") or "המתזמן פעיל ויש עבודה בתור."))
    report = {"at": iso(now), "source": source, "findings": list(findings), "actions": list(actions),
              "needs_you": list(problems), "counts": counts}
    db.set_flag("unstick_last_report", json.dumps(report, ensure_ascii=False))
    db.event("UNSTICK", source=source, findings=len(findings), actions=len(actions), needs_you=len(problems))
    return report


def summary_he(report: dict) -> str:
    parts = []
    if report["actions"]:
        parts.append(f"בוצעו {len(report['actions'])} פעולות להמשך הריצה")
    if report["needs_you"]:
        parts.append(f"{len(report['needs_you'])} דורשים החלטה שלך")
    return (" · ".join(parts) or "לא נמצאה תקיעה") + " — הפירוט בכרטיס 'למה הריצה תקועה'"
