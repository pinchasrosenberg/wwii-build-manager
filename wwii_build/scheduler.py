"""Deterministic scheduler / daemon loop.

  read READY tasks -> select worker/model (routing, no LLM) -> build ContextPack ->
  run CLI in its own worktree -> capture structured output -> run acceptance ->
  record artifacts/diff/results -> integrate -> unlock dependents -> repeat

The loop sleeps until the earliest of: a worker finishing, a control request
(SIGUSR1 / 2s DB poll), a retry backoff expiring, or a quota reset (+margin).
Providers are never polled on a timer; they are checked at start, after runs, when a
known reset passes, and on `provider refresh`.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import shutil
import signal
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import control
from . import manual as mn
from . import mcp as mcpmod
from . import planner_uploads
from . import repair as rp
from .acceptance import AcceptanceReport, kill_running_commands, run_acceptance, save_receipt
from .activation import activation_id, record_activation, restart_decision
from .config import Config
from .context_builder import ContextBuilder, DependencyHandoff, RetryInfo, materialize
from .db import DB
from .models import (ACTIVE, HARD_UNAVAILABLE, SCHEDULABLE, AttemptStatus, ProviderStatus, RunSpec, TaskRequest,
                     TaskState, iso, parse_iso, utcnow)
from .notify import Notifier
from .plan_importer import load_registry, request_from_row
from .prompts import RESULT_SCHEMA, REVIEW_SCHEMA, review_prompt, web_allowed
from .providers.base import StatusReport, WorkerProvider
from .quota import QuotaManager
from .result_parser import VALID, parse_result
from .routing import RUN, WAIT_APPROVAL, WAIT_PROVIDER, WAIT_QUOTA, RouteDecision, select_route
from .jev import JevService
from .graph_rag import GraphRagService
from .listeners import register_listener_manifest, validate_listener_manifest
from .sanitize import redact
from .supervisor import Supervisor, is_same_process, signal_pid
from .worktrees import WorktreeManager, slug
from .system_repair import SystemRepairError, activate_release, stage_release

ART_KINDS = {".png": "screenshot", ".jpg": "screenshot", ".jpeg": "screenshot", ".webp": "screenshot",
             ".gif": "screenshot", ".mp4": "video", ".webm": "video", ".mov": "video", ".glb": "preview_3d",
             ".gltf": "preview_3d", ".tscn": "test_scene", ".md": "report", ".html": "report", ".json": "data"}


@dataclass
class Decision:
    task_id: str
    state: TaskState
    reason: str
    route: RouteDecision | None = None
    wave: int = 0


@dataclass
class Running:
    attempt_id: int
    task_id: str
    owner: str
    scope: list[str]
    provider: str
    model_key: str
    kind: str
    future: asyncio.Task | None = None
    started: float = field(default_factory=time.time)


def scopes_overlap(a: list[str], b: list[str]) -> bool:
    for x in a:
        for y in b:
            xd, yd = x if x.endswith("/") else x + "/", y if y.endswith("/") else y + "/"
            if xd.startswith(yd) or yd.startswith(xd):
                return True
    return False


class Services:
    """Everything the scheduler needs, constructed once."""

    def __init__(self, cfg: Config, db: DB | None = None, providers: dict[str, WorkerProvider] | None = None,
                 wt: WorktreeManager | None = None):
        from .providers import build_providers
        self.cfg = cfg
        self.db = db or DB(cfg.db_path)
        self.quota = QuotaManager(self.db, cfg.section("quota"))
        self.providers = providers if providers is not None else build_providers(cfg)
        self.wt = wt or WorktreeManager(cfg)
        self.registry = load_registry(cfg)
        self.notifier = Notifier(cfg.section("notifications"), self.db)
        self.jev = JevService(cfg, self.db, self.notifier)
        self.graph_rag = GraphRagService(cfg, self.db)
        self.sup = Supervisor()


class Scheduler:
    def __init__(self, svc: Services, *, exit_when_idle: bool = False, clock=utcnow):
        self.svc = svc
        self.cfg, self.db, self.quota, self.wt = svc.cfg, svc.db, svc.quota, svc.wt
        self.clock = clock
        self.exit_when_idle = exit_when_idle
        self.running: dict[int, Running] = {}
        self.post: dict[str, asyncio.Task] = {}
        self.intent: dict[int, str] = {}          # attempt_id -> stop | pause | kill | skip | skip_satisfy
        self.stopping: str | None = None          # None | "stop" | "kill"
        self.wake = asyncio.Event()
        self.state_dir = self.cfg.state_dir
        self.schema_path = self.state_dir / "schemas" / "task_result.schema.json"
        self.review_schema_path = self.state_dir / "schemas" / "review.schema.json"
        self.repair_schema_path = self.state_dir / "schemas" / "repair.schema.json"
        self.plan_schema_path = self.state_dir / "schemas" / "plan.schema.json"
        sc = self.cfg.section("scheduler")
        self.max_parallel = int(sc.get("max_parallel", 3))
        self.poll = float(sc.get("control_poll_seconds", 2.0))
        self.escalation = int(sc.get("escalation_threshold", 3))
        self.tech_limit = int(sc.get("technical_retry_limit", 2))
        self.backoffs = [int(x) for x in sc.get("retry_backoff_seconds", [60, 300, 900])]
        self.timeout = float(sc.get("task_timeout_minutes", 90)) * 60
        self.graceful = float(self.cfg.section("stop").get("graceful_timeout_seconds", 20))
        self.term_grace = float(self.cfg.section("stop").get("kill_after_term_seconds", 5))
        self.max_attempts = int(self.cfg.data.get("budget", {}).get("max_attempts_per_task", 8))
        self._last_wall = time.time()
        self._last_mono = time.monotonic()
        self._idle_reason = ""
        self._last_refresh: dict[str, float] = {}
        self._signals_done: dict[int, int] = {}
        self._quota_poll_task: asyncio.Task | None = None
        self._last_quota_poll = 0.0
        self.quota_poll = float(self.cfg.provider("codex").get("quota_poll_seconds", 120))
        self.activation_id = activation_id(self.db)

    # ======================================================================
    # evaluation (pure w.r.t. processes; used by dry-run too)
    # ======================================================================
    def approval_map(self, task_id: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in self.db.q("SELECT subject, status FROM approvals WHERE task_id=? AND kind='model' ORDER BY id",
                           (task_id,)):
            out[r["subject"]] = r["status"]
        return out

    def _evaluate_repair(self, row, now: dt.datetime) -> Decision:
        """Repair and planner tasks: no dependencies, own budget, routed by their profile."""
        tid = row["task_id"]
        if self.cfg.section("jev").get("require_for_all_llm_context", True) and not self.svc.jev.enabled:
            return Decision(tid, TaskState.WAITING_PROVIDER,
                            "Jev context gate is disabled; no LLM context may bypass it", wave=row["wave"])
        if row["kind"] == "repair":
            p = self.db.task(row["parent_task_id"])
            if not p or p["state"] != TaskState.WAITING_REPAIR.value or p["active_repair_id"] != tid:
                return Decision(tid, TaskState.CANCELLED, "parent is no longer waiting for this repair", wave=row["wave"])
        real = self.db.one("SELECT COUNT(*) n FROM task_attempts WHERE task_id=? AND status NOT IN "
                           "('QUOTA_LIMITED','AUTH_ERROR','BILLING_BLOCKED','MODEL_UNAVAILABLE','INTERRUPTED','ORPHANED')",
                           (tid,))["n"]
        if real > self.tech_limit + 1:
            return Decision(tid, TaskState.BLOCKED, f"budget: {real} runs for one repair", wave=row["wave"])
        nb = parse_iso(row["not_before"])
        if nb and nb > now:
            return Decision(tid, TaskState.PENDING, f"retry backoff until {iso(nb)}", wave=row["wave"])
        last = self.db.one("SELECT failure_class FROM task_attempts WHERE task_id=? ORDER BY id DESC LIMIT 1", (tid,))
        affinity = bool(row["failed_attempts"]) and bool(last) and last["failure_class"] in ("cli_error", "timeout",
                                                                                             "manager_error")
        route = select_route(self.cfg, self.quota, request_from_row(row, []), approvals=self.approval_map(tid),
                             last_model_key=row["last_model_key"], preferred=row["preferred_model_key"],
                             retry_affinity=affinity, now=now)
        state = {RUN: TaskState.READY, WAIT_APPROVAL: TaskState.WAITING_APPROVAL, WAIT_QUOTA: TaskState.WAITING_QUOTA,
                 WAIT_PROVIDER: TaskState.WAITING_PROVIDER}[route.kind]
        return Decision(tid, state, route.reason, route, wave=row["wave"])

    def evaluate_task(self, row, states: dict[str, str], now: dt.datetime) -> Decision:
        tid = row["task_id"]
        if row["kind"] in ("repair", "plan"):
            return self._evaluate_repair(row, now)
        if self.cfg.section("jev").get("require_for_all_llm_context", True) and not self.svc.jev.enabled:
            return Decision(tid, TaskState.WAITING_PROVIDER,
                            "Jev context gate is disabled; no LLM context may bypass it", wave=row["wave"])
        deps = self.db.deps(tid)
        pending = [d for d in deps if states.get(d) != TaskState.PASSED.value]
        if pending:
            return Decision(tid, TaskState.WAITING_DEPENDENCY, "waiting for " + ", ".join(pending), wave=row["wave"])
        req = request_from_row(row, deps)
        for p in req.extra.get("required_paths", []):
            if self.wt.baseline_exists() and not self.wt.git("cat-file", "-e", f"{self.wt.branch}:{p}", check=False).rc == 0:
                return Decision(tid, TaskState.WAITING_DEPENDENCY, f"required contract path missing: {p}", wave=row["wave"])
        real = self.db.one("SELECT COUNT(*) n FROM task_attempts WHERE task_id=? AND kind='execute' AND status NOT IN "
                           "('QUOTA_LIMITED','AUTH_ERROR','BILLING_BLOCKED','MODEL_UNAVAILABLE','INTERRUPTED','ORPHANED')",
                           (tid,))["n"]
        if real >= self.max_attempts:
            return Decision(tid, TaskState.BLOCKED, f"budget: {real} real attempts (budget.max_attempts_per_task)",
                            wave=row["wave"])
        nb = parse_iso(row["not_before"])
        if nb and nb > now:
            return Decision(tid, TaskState.PENDING, f"retry backoff until {iso(nb)}", wave=row["wave"])
        last = self.db.one("SELECT failure_class FROM task_attempts WHERE task_id=? AND kind='execute' "
                           "ORDER BY id DESC LIMIT 1", (tid,))
        affinity = bool(row["failed_attempts"]) and bool(last) and last["failure_class"] in (
            "test_failure", "cli_error", "timeout", "scope_violation", "no_output", "review_rejected", "manager_error")
        route = select_route(self.cfg, self.quota, req, approvals=self.approval_map(tid),
                             last_model_key=row["last_model_key"], preferred=row["preferred_model_key"],
                             retry_affinity=affinity, now=now)
        state = {RUN: TaskState.READY, WAIT_APPROVAL: TaskState.WAITING_APPROVAL, WAIT_QUOTA: TaskState.WAITING_QUOTA,
                 WAIT_PROVIDER: TaskState.WAITING_PROVIDER}[route.kind]
        return Decision(tid, state, route.reason, route, wave=row["wave"])

    def evaluate(self, now: dt.datetime | None = None, write: bool = True) -> list[Decision]:
        now = now or self.clock()
        rows = self.db.q("SELECT * FROM tasks ORDER BY wave, task_id")
        states = {r["task_id"]: r["state"] for r in rows}
        out = []
        for r in rows:
            if TaskState(r["state"]) not in SCHEDULABLE:
                continue
            d = self.evaluate_task(r, states, now)
            out.append(d)
            if write:
                self._apply_decision(r, d)
        return out

    def _apply_decision(self, row, d: Decision) -> None:
        if row["state"] == d.state.value and row["state_reason"] == d.reason:
            return
        self.db.set_task_state(d.task_id, d.state.value, d.reason)
        if row["state"] == d.state.value:
            return
        if d.state == TaskState.READY:
            self.db.event("TASK_READY", task_id=d.task_id, route=d.reason)
        elif d.state == TaskState.WAITING_APPROVAL and d.route:
            key = d.route.model_key
            if not self.db.one("SELECT 1 FROM approvals WHERE task_id=? AND kind='model' AND subject=? AND status='pending'",
                               (d.task_id, key)):
                self.db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
                          (d.task_id, "model", key, "pending", d.route.quote.approval_reason if d.route.quote else d.reason,
                           iso(utcnow())))
            self.db.event("APPROVAL_REQUIRED", task_id=d.task_id, model_key=key, reason=d.reason)
            self.svc.notifier.notify(f"approval:{d.task_id}", "approval needed", f"{d.task_id}: {d.reason}")
        elif d.state == TaskState.WAITING_QUOTA:
            self.db.event("TASK_WAITING_QUOTA", task_id=d.task_id, reason=d.reason)
        elif d.state == TaskState.WAITING_PROVIDER:
            self.db.event("TASK_WAITING_PROVIDER", task_id=d.task_id, reason=d.reason)
        elif d.state == TaskState.BLOCKED:
            self.db.event("TASK_BLOCKED", task_id=d.task_id, reason=d.reason)

    def pick_dispatch(self, decisions: list[Decision], running: list[Running] | None = None) -> list[tuple[Decision, str]]:
        """Capacity + one-writer rule (owner and overlapping write scopes). Returns (decision, lock-note)."""
        running = list(self.running.values()) if running is None else running
        # (task, owner, scope, active). Active = a worker is (about to be) writing: blocks by owner AND scope.
        held = [(r.task_id, r.owner, r.scope, True) for r in running]
        # A parent waiting for repair (or acceptance/review) keeps its write-scope lock so nothing else edits its
        # files. It is parked (no worker), so it does not hold its owner lock: otherwise two parents of one owner
        # that both wait for a repair would block each other's repairs forever.
        for r in self.db.q("SELECT task_id, owner, write_scope FROM tasks WHERE state IN (?,?,?)",
                           (TaskState.CODE_READY.value, TaskState.REVIEWING.value, TaskState.WAITING_REPAIR.value)):
            held.append((r["task_id"], r["owner"], json.loads(r["write_scope"]), False))
        cap = self.max_parallel - len(running)
        out = []
        priority = {row["task_id"]: int(row["dispatch_priority"] or 0)
                    for row in self.db.q("SELECT task_id,dispatch_priority FROM tasks")}
        for d in sorted((d for d in decisions if d.state == TaskState.READY),
                        key=lambda d: (-priority.get(d.task_id, 0), d.wave,
                                       not d.task_id.startswith("REPAIR/"), d.task_id)):
            if cap <= 0:
                break
            t = self.db.task(d.task_id)
            scope, owner = json.loads(t["write_scope"]), t["owner"]
            exempt = t["parent_task_id"] if t["kind"] == "repair" else None
            hs = [(o, sc, active) for tid_, o, sc, active in held if tid_ != exempt]
            if any(o == owner for o, _, active in hs if active):
                continue
            if any(scopes_overlap(scope, sc) for _, sc, _ in hs):
                continue
            out.append((d, ""))
            held.append((d.task_id, owner, scope, True))
            cap -= 1
        return out

    def blocked_by_lock(self, decisions: list[Decision], picked: list[tuple[Decision, str]]) -> dict[str, str]:
        chosen = {d.task_id for d, _ in picked}
        out = {}
        for d in decisions:
            if d.state == TaskState.READY and d.task_id not in chosen:
                out[d.task_id] = "capacity or write-scope/owner lock"
        return out

    # ======================================================================
    # provider status
    # ======================================================================
    def apply_status(self, rep: StatusReport) -> None:
        cur = ProviderStatus(self.quota.row(rep.provider)["status"])
        if rep.status in (ProviderStatus.MISSING, ProviderStatus.AUTH_ERROR, ProviderStatus.BILLING_BLOCKED):
            self.quota.set_status(rep.provider, rep.status, "; ".join([rep.auth_detail, *rep.notes])[:500],
                                  source="check_status")
        elif cur in HARD_UNAVAILABLE:
            self.quota.set_status(rep.provider, ProviderStatus.UNKNOWN, "status check passed", source="check_status",
                                  confidence="none")
        if rep.quota and rep.provider == "codex":
            pc = self.cfg.provider("codex")
            self.quota.record_codex_snapshot(rep.quota, float(pc.get("near_limit_percent", 90)),
                                             float(pc.get("stop_dispatch_at_percent", 100)))

    async def refresh_provider(self, name: str, *, manual: bool = False) -> StatusReport | None:
        p = self.svc.providers.get(name)
        if not p or not self.cfg.provider(name).get("enabled", True):
            return None
        p.invalidate()
        try:
            rep = await p.check_status(with_quota=True)
        except Exception as e:
            self.db.event("PROVIDER_CHECK_FAILED", provider=name, error=str(e)[:300])
            return None
        self.apply_status(rep)
        if manual:
            row = self.quota.row(name)
            # A manual refresh lets a provider with an *unknown* reset be probed again.
            if row["status"] == ProviderStatus.BLOCKED_UNKNOWN.value or (
                    row["status"] in (ProviderStatus.BLOCKED_SESSION.value, ProviderStatus.BLOCKED_WEEKLY.value)
                    and row["confidence"] == "low"):
                self.quota.set_status(name, ProviderStatus.UNKNOWN, "manual refresh", source="manual",
                                      confidence="none")
        self.db.event("PROVIDER_REFRESHED", provider=name, status=rep.status.value, auth=rep.auth_mode,
                      manual=manual)
        return rep

    async def refresh_all(self) -> None:
        await asyncio.gather(*(self.refresh_provider(n) for n in self.svc.providers))

    # ======================================================================
    # attempt lifecycle
    # ======================================================================
    def _run_dir(self, tid: str, attempt_id: int) -> Path:
        return self.state_dir / "runs" / slug(tid) / f"a{attempt_id}"

    def _deps_handoffs(self, req: TaskRequest) -> list[DependencyHandoff]:
        out = []
        for d in req.depends_on:
            t = self.db.task(d)
            a = self.db.one("SELECT * FROM task_attempts WHERE task_id=? AND kind='execute' AND handoff IS NOT NULL "
                            "ORDER BY id DESC LIMIT 1", (d,))
            h = json.loads(a["handoff"]) if a and a["handoff"] else {}
            arts = [dict(kind=r["kind"], path=r["source_path"] or r["path"], description=r["description"])
                    for r in self.db.q("SELECT * FROM artifacts WHERE task_id=? ORDER BY id DESC LIMIT 20", (d,))]
            out.append(DependencyHandoff(d, t["state"], h.get("summary", ""), arts, h.get("changed_files", []),
                                         h.get("contracts_used", []), t["passed_commit"]))
        return out

    def _retry_info(self, tid: str, attempt_no: int, worktree: Path, base: str) -> RetryInfo | None:
        last = self.db.one("SELECT * FROM task_attempts WHERE task_id=? AND kind='execute' AND status IN (?,?) "
                           "ORDER BY id DESC LIMIT 1", (tid, AttemptStatus.FAILED_ATTEMPT.value, AttemptStatus.CRASHED.value))
        t = self.db.task(tid)
        if not last or not t["failed_attempts"]:
            return None
        tests = [dict(r) for r in self.db.q("SELECT name, exit_code, output_tail FROM test_results WHERE attempt_id=? "
                                            "AND passed=0", (last["id"],))]
        note = self.db.one("SELECT note FROM approvals WHERE task_id=? AND kind='review' AND status='rejected' "
                           "ORDER BY id DESC LIMIT 1", (tid,))
        try:
            diff = self.wt.diff(worktree, base, int(self.cfg.section("context").get("max_retry_diff_bytes", 20000)))
        except Exception:
            diff = ""
        return RetryInfo(attempt_no, diff, tests, json.loads(last["handoff"]) if last["handoff"] else None,
                         note["note"] if note else None, last["failure_class"])

    async def start_attempt(self, d: Decision, kind: str = "execute") -> int | None:
        tid = d.task_id
        row = self.db.task(tid)
        req = request_from_row(row, self.db.deps(tid))
        key = d.route.model_key
        model = self.cfg.model(key)
        if req.is_repair and self.cfg.section("repair").get("effort"):
            model.effort = self.cfg.section("repair")["effort"]      # repairs run cheaper than the original
        provider = self.svc.providers[model.provider]
        # Billing / auth gate right before spending anything.
        st = await provider.cached_status()
        if st.status in (ProviderStatus.MISSING, ProviderStatus.AUTH_ERROR, ProviderStatus.BILLING_BLOCKED) \
                or not st.billing_ok:
            self.apply_status(st)
            self.db.event("DISPATCH_REFUSED", task_id=tid, provider=model.provider, status=st.status.value,
                          detail=st.auth_detail)
            self.db.set_task_state(tid, TaskState.PENDING.value, f"{model.provider}: {st.status.value}; rerouting")
            return None
        parent_row = self.db.task(req.parent_task_id) if req.is_repair else None
        try:
            if req.kind == "plan":
                wtpath = await asyncio.to_thread(self.wt.ensure_integration)   # read-only look at the repo
                branch, base, integ = self.wt.branch, None, None
            elif req.is_repair:
                # A repair fixes the parent's candidate in place: same worktree, same branch, no integration merge.
                wtpath, branch, _ = await asyncio.to_thread(self.wt.ensure_task, req.parent_task_id)
                base = self.wt.head(wtpath)      # repair diff = base..head of this attempt
                integ = None
            elif req.extra.get("system_task"):
                saved_base = req.extra.get("system_base_commit")
                saved_manifest = req.extra.get("system_source_manifest")
                if saved_base and isinstance(saved_manifest, dict):
                    wtpath, branch, _ = await asyncio.to_thread(self.wt.ensure_task, tid, True)
                    base, integ = saved_base, None
                else:
                    wtpath, branch, base, manifest = await asyncio.to_thread(self.wt.ensure_system_task, tid)
                    req.extra["system_base_commit"] = base
                    req.extra["system_source_manifest"] = manifest
                    self.db.x("UPDATE tasks SET extra=?,updated_at=? WHERE task_id=?",
                              (json.dumps(req.extra, ensure_ascii=False), iso(utcnow()), tid))
                    integ = None
                    self.db.event("SYSTEM_REPAIR_SNAPSHOT", task_id=tid, base_commit=base,
                                  files=len(manifest))
            else:
                wtpath, branch, base = await asyncio.to_thread(self.wt.ensure_task, tid,
                                                               bool(req.extra.get("full_checkout")))
                integ = self.wt.rev(f"refs/heads/{self.wt.branch}")
            if integ and base != integ:
                ok, msg = await asyncio.to_thread(self.wt.update_from_integration, wtpath)
                if ok:
                    base = integ
                else:
                    self.db.event("INTEGRATION_UPDATE_CONFLICT", task_id=tid, detail=msg[-500:])
        except Exception as e:
            self.db.event("WORKTREE_ERROR", task_id=tid, error=str(e)[:500])
            self.db.set_task_state(tid, TaskState.BLOCKED.value, f"worktree error: {str(e)[:200]}")
            return None
        attempt_no = (row["attempts_count"] or 0) + 1
        acc_cmds = list(self.cfg.section("acceptance").get("default_commands", [])) + req.acceptance
        retry = None
        if req.kind == "plan":
            pack = self._jev_gate_whole_pack(req, self._plan_pack(row), "planner task context")
        elif req.is_repair:
            pack = self._jev_gate_whole_pack(req, self._repair_pack(row, parent_row, wtpath, acc_cmds),
                                             "repair failure, diff and acceptance context")
        else:
            builder = ContextBuilder(self.cfg, self.svc.registry, source_root=wtpath)
            retry = self._retry_info(tid, attempt_no, wtpath, base)
            graph_context = self._graph_context(req)
            deps = self._deps_handoffs(req)
            inventory = builder.build(req, deps, retry, acc_cmds, graph_context)
            if not self.cfg.section("jev").get("require_for_all_llm_context", True):
                pack = inventory
            else:
                candidates, paths_by_bundle = self._context_bundles(inventory)
                selected = self.svc.jev.select_context_bundles(
                    tid, candidates, f"{req.task_id}: {req.note or req.owner}; model task profile {req.model_profile}")
                if "context:core" not in selected:
                    pack = None
                else:
                    selected_paths = {path for bundle_id in selected for path in paths_by_bundle.get(bundle_id, [])}
                    pack = builder.build(req, deps, retry, acc_cmds, graph_context, selected_paths=selected_paths)
                    pack.routing = {"gate": "jev", "policy": "fail_closed", "selected_bundles": selected,
                                    "candidate_bundles": [candidate["id"] for candidate in candidates]}
        if pack is None:
            delay = utcnow() + dt.timedelta(minutes=5)
            self.db.set_task_state(tid, TaskState.PENDING.value,
                                   "Jev did not approve required LLM context; retry is delayed",
                                   not_before=iso(delay))
            self.db.event("JEV_CONTEXT_GATE_BLOCKED", task_id=tid, provider="jev",
                          reason="required context not selected", retry_at=iso(delay))
            return None
        now = iso(utcnow())
        attempt_id = self.db.x(
            "INSERT INTO task_attempts(task_id, kind, attempt_no, provider, model_key, model, effort, status, started_at, "
            "cwd, base_commit, quota_before) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, kind, attempt_no, model.provider, key, model.model, model.effort, AttemptStatus.RUNNING.value, now,
             str(wtpath), base, self.quota.snapshot(model.provider)))
        run_dir = self._run_dir(tid, attempt_id)
        materialize(pack, self.state_dir / "context_packs" / slug(tid) / f"a{attempt_id}")
        pack_id = self.db.x("INSERT INTO context_packs(task_id, created_at, manifest, prompt_path, prompt_sha256, total_bytes) "
                            "VALUES(?,?,?,?,?,?)", (tid, now, json.dumps(pack.manifest(), ensure_ascii=False),
                                                    pack.prompt_path, pack.prompt_sha256, pack.total_bytes))
        self.db.update_attempt(attempt_id, context_pack_id=pack_id, stdout_path=str(run_dir / "stdout.jsonl"),
                               stderr_path=str(run_dir / "stderr.log"))
        expedited = int(row["dispatch_priority"] or 0)
        self.db.set_task_state(tid, TaskState.RUNNING.value, f"{model.provider}/{model.model}",
                               attempts_count=attempt_no, last_model_key=key, branch=branch, worktree=str(wtpath),
                               dispatch_priority=0)
        if expedited:
            self.db.event("TASK_EXPEDITE_CONSUMED", task_id=tid, attempt_id=attempt_id,
                          dispatch_priority=expedited)
        if req.kind == "plan" and req.extra.get("graph_console_query_id"):
            self.db.x("UPDATE graph_console_queries SET status='RUNNING',updated_at=? WHERE id=?",
                      (iso(utcnow()), int(req.extra["graph_console_query_id"])))
        chain = self.cfg.chain(req.model_profile)
        if chain and key != chain[0] and key != row["preferred_model_key"]:
            self.db.event("FALLBACK_SELECTED", task_id=tid, attempt_id=attempt_id, provider=model.provider,
                          model_key=key, primary=chain[0], chain=[c.get("verdict") for c in d.route.chain])
        spec = RunSpec(task=req, attempt_id=attempt_id, attempt_no=attempt_no, model=model, worktree=str(wtpath),
                       prompt_path=pack.prompt_path, run_dir=str(run_dir), result_schema_path=str(self.schema_path),
                       allow_web=req.kind == "task" and web_allowed(req))
        web_enabled = provider.web_enabled(spec)
        if web_enabled:
            self.db.update_attempt(attempt_id, web_enabled=1)
        elif spec.allow_web:
            self.db.event("WEB_ACCESS_UNAVAILABLE", task_id=tid, attempt_id=attempt_id, provider=model.provider,
                          reason="the provider CLI cannot enable web search; the run stays web-closed")
        self.db.event("REPAIR_STARTED" if req.is_repair else "TASK_STARTED", task_id=tid, attempt_id=attempt_id,
                      provider=model.provider, model=model.model, effort=model.effort, attempt_no=attempt_no,
                      context_bytes=pack.total_bytes, retry=bool(retry), parent=req.parent_task_id,
                      web_enabled=web_enabled)
        if req.kind == "plan":
            spec.kind, spec.schema, spec.result_schema_path = "plan", mn.PLAN_SCHEMA, str(self.plan_schema_path)
            selected_uploads = list(pack.routing.get("selected_attachments") or [])
            spec.attachment_paths = [str(item["origin_ref"]) for item in selected_uploads]
            spec.image_paths = [str(item["origin_ref"]) for item in selected_uploads
                                if item.get("attachment_kind") == "image"]
        elif req.is_repair and not req.read_only:
            spec.kind, spec.schema, spec.result_schema_path = "repair", rp.REPAIR_SCHEMA, str(self.repair_schema_path)
        elif req.is_repair:
            spec.kind = "repair"
        self._attach_mcp(spec, req, model, run_dir)
        r = Running(attempt_id, tid, req.owner, req.write_scope, model.provider, key, kind)
        self.running[attempt_id] = r
        self.db.x("INSERT INTO workers(attempt_id, task_id, provider, model, worktree, started_at, context_bytes, daemon_pid) "
                  "VALUES(?,?,?,?,?,?,?,?)", (attempt_id, tid, model.provider, model.model, str(wtpath), now,
                                             pack.total_bytes, os.getpid()))
        r.future = asyncio.create_task(self._run_attempt(spec, provider, base))
        return attempt_id

    def _latest_exec(self, tid: str):
        return self.db.one("SELECT * FROM task_attempts WHERE task_id=? AND kind='execute' ORDER BY id DESC LIMIT 1",
                           (tid,))

    def _repair_history(self, parent_id: str, before_no: int, wtpath: Path) -> list[dict]:
        out = []
        for r in self.db.q("SELECT * FROM tasks WHERE parent_task_id=? AND kind='repair' AND repair_no<? "
                           "ORDER BY repair_no", (parent_id, before_no)):
            a = self._latest_exec(r["task_id"])
            d = ""
            if a and a["base_commit"] and a["head_commit"] and a["base_commit"] != a["head_commit"]:
                d = self.wt.git("diff", f"{a['base_commit']}..{a['head_commit']}", cwd=wtpath, check=False).out[-6000:]
            out.append({"repair_task_id": r["task_id"], "state": r["state"], "failure_class": r["failure_class"],
                        "failure_summary": r["failure_summary"], "outcome": r["state_reason"],
                        "model": a["model"] if a else None,
                        "result": json.loads(a["handoff"]) if a and a["handoff"] else None, "repair_diff": d})
        return out

    def _repair_pack(self, row, parent_row, wtpath: Path, acc_cmds: list[dict]):
        parent = request_from_row(parent_row, self.db.deps(parent_row["task_id"]))
        pa = self._latest_exec(parent_row["task_id"])
        diff = self.wt.diff(wtpath, pa["base_commit"]) if pa and pa["base_commit"] else ""
        cap = int(self.cfg.section("repair").get("max_diff_bytes", 30000))
        if len(diff.encode()) > cap and pa and pa["base_commit"]:
            # Large candidate: full file list + patch only for files tied to the failure (the rest is in the worktree).
            ctx = json.loads(row["repair_context"] or "{}")
            c = rp.Classification(ctx.get("class", ""), "", ctx.get("failing_checks", []), ctx.get("violating_paths", []),
                                  outputs=ctx.get("check_outputs", []))
            focus = sorted(set(rp.related_files(c, wtpath, parent.write_scope, limit=8, max_bytes=10 ** 7))
                           | set(c.violating))
            stat = self.wt.git("diff", "--stat=200", f"{pa['base_commit']}..HEAD", cwd=wtpath).out
            patch = self.wt.git("diff", f"{pa['base_commit']}..HEAD", "--", *focus, cwd=wtpath).out if focus else ""
            diff = ("[large diff: full file list below; patch shown only for files named in the failure. "
                    "Read other files in the worktree if needed.]\n" + stat + "\n" + patch)
        pack = rp.build_repair_pack(self.cfg, wtpath, parent, row, diff,
                                    json.loads(pa["handoff"]) if pa and pa["handoff"] else None,
                                    self._repair_history(parent_row["task_id"], row["repair_no"], wtpath),
                                    acc_cmds, rp.budget(self.cfg, parent_row))
        return pack

    def _plan_pack(self, row):
        from .models import ContextPack
        from .context_builder import sha256_bytes
        extra = json.loads(row["extra"] or "{}")
        candidate_limit = int(self.cfg.section("jev").get("max_context_candidates", 24))
        prompt = extra.get("prompt", "")
        if self.cfg.section("jev").get("enabled", True):
            # User-supplied files are a small, explicit pool (at most eight). Keep
            # every one in the Jev decision set so graph results cannot crowd an
            # attachment out before Jev has had a chance to inspect its metadata.
            candidates = planner_uploads.candidates(self.db, row["task_id"])
            pools = [
                mn.planner_graph_candidates(self.db, prompt, candidate_limit),
                mn.planner_markdown_candidates(self.cfg, prompt, candidate_limit),
                self.svc.graph_rag.retrieve_candidates(row["task_id"], prompt, planner=True),
            ]
        else:
            candidates, pools = [], []
        # Fill the remaining budget round-robin so one large graph source cannot
        # crowd Neo4j, Markdown, or Graph RAG out of the choice set.
        seen = {item["id"] for item in candidates}
        for index in range(max((len(pool) for pool in pools), default=0)):
            for pool in pools:
                if index >= len(pool) or pool[index]["id"] in seen:
                    continue
                seen.add(pool[index]["id"])
                candidates.append(pool[index])
                if len(candidates) >= candidate_limit:
                    break
            if len(candidates) >= candidate_limit:
                break
        selected_ids = self.svc.jev.select_context_bundles(
            row["task_id"], candidates,
            f"{row['task_id']}: select graph evidence needed to answer the user's Task Manager prompt") \
            if candidates else []
        by_id = {item["id"]: item for item in candidates}
        graph_context = [by_id[item_id] for item_id in selected_ids if item_id in by_id]
        selected_attachments = [item for item in graph_context if item.get("origin_kind") == "planner_upload"]
        planner_uploads.mark_selected(self.db, selected_attachments)
        fresh = self.db.task(row["task_id"])
        saved_extra = json.loads(fresh["extra"] or "{}")
        saved_extra["jev_selected_context"] = graph_context
        self.db.x("UPDATE tasks SET extra=? WHERE task_id=?",
                  (json.dumps(saved_extra, ensure_ascii=False), row["task_id"]))
        prompt = mn.plan_prompt(self.cfg, self.db, self.svc.registry, row, self._mcp_names(), graph_context)
        b = prompt.encode()
        pack = ContextPack(task_id=row["task_id"], items=[], prompt=prompt, prompt_sha256=sha256_bytes(b),
                           total_bytes=len(b))
        pack.routing = {"graph_gate": "jev", "selected_graph_context": selected_ids,
                        "candidate_graph_context": [item["id"] for item in candidates],
                        "selected_attachments": selected_attachments}
        return pack

    def _mcp_names(self) -> dict:
        try:
            return {k: sorted(v) for k, v in mcpmod.available(self.cfg).items()}
        except Exception:
            return {}

    def _attach_mcp(self, spec: RunSpec, req: TaskRequest, model, run_dir: Path) -> None:
        names = list(req.extra.get("mcp") or [])
        if not names:
            return
        if model.provider == "claude":
            defs = mcpmod.claude_definitions(self.cfg)
            chosen = {n: defs[n] for n in names if n in defs}
            if chosen:
                run_dir.mkdir(parents=True, exist_ok=True)
                f = run_dir / "mcp.json"
                f.write_text(json.dumps({"mcpServers": chosen}))
                os.chmod(f, 0o600)
                spec.mcp_selected, spec.mcp_config_path = list(chosen), str(f)
        elif model.provider == "codex":
            allv = mcpmod.codex_servers(self.cfg)
            spec.mcp_selected = [n for n in names if n in allv]
            spec.mcp_all = sorted(allv)
        missing = [n for n in names if n not in spec.mcp_selected]
        if missing:
            self.db.event("MCP_UNAVAILABLE", task_id=req.task_id, provider=model.provider, servers=missing)

    def _on_started(self, attempt_id: int, h) -> None:
        self.db.update_attempt(attempt_id, pid=h.pid, pgid=h.pgid, process_started=h.started,
                               command=redact(Path(self._run_dir(self.running[attempt_id].task_id, attempt_id)
                                                   / "command.json").read_text()[:4000]))
        self.db.x("UPDATE workers SET pid=?, pgid=?, process_started=? WHERE attempt_id=?",
                  (h.pid, h.pgid, h.started, attempt_id))
        # A stop/kill/pause that arrived between dispatch and spawn applies now.
        intent = self.intent.get(attempt_id)
        if self.stopping == "kill" or intent == "kill":
            self.svc.sup.kill(attempt_id)
        elif self.stopping or intent:
            asyncio.get_running_loop().create_task(self.svc.sup.shutdown(attempt_id, self.graceful, self.term_grace))

    async def _run_attempt(self, spec: RunSpec, provider: WorkerProvider, base: str) -> None:
        tid, aid = spec.task.task_id, spec.attempt_id
        try:
            run = await provider.run_task(spec, self.svc.sup, timeout=self.timeout,
                                          on_started=lambda h: self._on_started(aid, h),
                                          on_event=lambda col: self._live_signals(aid, col))
            await self._after_run(spec, provider, base, run)
        except Exception as e:
            tb = traceback.format_exc()
            self.db.event("MANAGER_ERROR", task_id=tid, attempt_id=aid, error=str(e)[:500], trace=tb[-1500:])
            self.db.update_attempt(aid, status=AttemptStatus.CRASHED.value, failure_class="manager_error",
                                   ended_at=iso(utcnow()), diagnosis=str(e)[:500])
            # Counts as a failure (backoff + escalation / repair budget) so a manager bug can never loop.
            try:
                self._record_failure(tid, aid, "manager_error", f"manager error: {e}")
            except Exception as e2:
                self.db.set_task_state(tid, TaskState.BLOCKED.value, f"manager error: {str(e)[:150]} / {str(e2)[:100]}")
        finally:
            self.running.pop(aid, None)
            self.intent.pop(aid, None)
            self.db.x("DELETE FROM workers WHERE attempt_id=?", (aid,))
            self.wake.set()

    def _live_signals(self, aid: int, col) -> None:
        """Record rate-limit data the moment the CLI reports it (not only when the run ends)."""
        done = self._signals_done.get(aid, 0)
        for sig in col.signals[done:]:
            self.quota.record_signal(sig, aid)
        self._signals_done[aid] = len(col.signals)

    async def _after_run(self, spec: RunSpec, provider: WorkerProvider, base: str, run) -> None:
        tid, aid, model = spec.task.task_id, spec.attempt_id, spec.model
        for sig in run.quota_signals[self._signals_done.pop(aid, 0):]:
            self.quota.record_signal(sig, aid)
        quota_after = None
        if provider.name == "codex" and self.cfg.provider("codex").get("quota_source") == "app-server":
            try:
                res = await provider.read_rate_limits()   # non-inference
                if res:
                    pc = self.cfg.provider("codex")
                    self.quota.record_codex_snapshot(res, float(pc.get("near_limit_percent", 90)),
                                                     float(pc.get("stop_dispatch_at_percent", 100)))
            except Exception as e:
                self.db.event("QUOTA_READ_FAILED", provider="codex", error=str(e)[:200])
        quota_after = self.quota.snapshot(provider.name)
        if spec.mcp_config_path:
            Path(spec.mcp_config_path).unlink(missing_ok=True)       # never keep copied MCP definitions around
        if spec.kind == "plan":
            await self._after_plan(spec, provider, run)
            return
        if spec.kind == "repair" and not spec.task.read_only:
            handoff, hstatus = rp.parse_repair_result(tid, spec.task.parent_task_id, run.structured, run.final_text)
            problems = [] if hstatus == VALID else ["repair result not valid JSON"]
        else:
            handoff, hstatus, problems = parse_result(spec.task.parent_task_id or tid, run.structured, run.final_text)
            if handoff and not spec.task.is_repair:
                listener_problems = validate_listener_manifest(handoff.get("listener_manifest"), spec.task.lego_ids)
                if listener_problems:
                    problems.extend(listener_problems)
                    hstatus = "MALFORMED"
        wtpath = Path(spec.worktree)
        # Preserve whatever the worker produced, whatever happened.
        head = None
        try:
            if spec.task.read_only and handoff and handoff.get("report_markdown"):
                report_p = wtpath / spec.task.write_scope[0] / "REPORT.md"
                report_p.parent.mkdir(parents=True, exist_ok=True)
                report_p.write_text(handoff["report_markdown"], encoding="utf-8")
                (report_p.parent / "handoff.json").write_text(json.dumps(handoff, ensure_ascii=False, indent=1))
            head = await asyncio.to_thread(self.wt.commit_all, wtpath,
                                           f"wwii-build: {tid} attempt {spec.attempt_no} ({model.provider}/{model.model}, "
                                           f"{run.status.value})")
            head = head or self.wt.head(wtpath)
        except Exception as e:
            self.db.event("COMMIT_ERROR", task_id=tid, attempt_id=aid, error=str(e)[:300])
        self.db.update_attempt(
            aid, status=run.status.value, failure_class=run.failure_class, ended_at=iso(utcnow()),
            exit_code=run.exit_code, session_id=run.session_id, input_tokens=run.input_tokens,
            cached_input_tokens=run.cached_input_tokens, output_tokens=run.output_tokens,
            reported_cost_usd=run.reported_cost_usd, quota_after=quota_after, head_commit=head,
            last_message_path=run.last_message_path,
            handoff=json.dumps(handoff, ensure_ascii=False) if handoff else None, handoff_status=hstatus,
            diagnosis=redact((run.error or "")[-1000:]) or None)
        intent = self.intent.get(aid)
        st = run.status
        if st == AttemptStatus.QUOTA_LIMITED:
            self.db.set_task_state(tid, TaskState.PENDING.value, f"{model.provider} quota limit; rerouting (not a failure)")
            self.db.event("TASK_QUOTA_LIMITED", task_id=tid, attempt_id=aid, provider=model.provider)
            self._maybe_all_blocked()
            return
        if st == AttemptStatus.AUTH_ERROR:
            self.quota.set_status(model.provider, ProviderStatus.AUTH_ERROR, (run.error or "")[-300:], source="run")
            provider.invalidate()
            self.db.set_task_state(tid, TaskState.PENDING.value, f"{model.provider} auth error; rerouting")
            self.svc.notifier.notify(f"auth:{model.provider}", "auth error", f"{model.provider}: login required")
            return
        if st == AttemptStatus.BILLING_BLOCKED:
            self.db.event("BILLING_BLOCKED", task_id=tid, attempt_id=aid, provider=model.provider, detail=run.failure_class)
            self.db.set_task_state(tid, TaskState.PENDING.value, f"{model.provider}: paid usage refused; rerouting")
            self.svc.notifier.notify(f"billing:{model.provider}", "paid usage refused",
                                     f"{model.provider} tried to use paid extra usage; run stopped")
            return
        if st == AttemptStatus.MODEL_UNAVAILABLE:
            from .model_watch import ModelWatch
            if ModelWatch(self.cfg, self.db).rollback_on_model_error(model.key, model.model):
                self.db.set_task_state(tid, TaskState.PENDING.value,
                                       "automatic model update rejected; previous model restored",
                                       not_before=None)
                return
            self.quota.set_status(model.provider, ProviderStatus.MODEL_UNAVAILABLE, (run.error or "")[-300:],
                                  source="run", family=f"model:{model.model}")
            self.db.set_task_state(tid, TaskState.PENDING.value, f"{model.model} unavailable; rerouting")
            return
        if st == AttemptStatus.INTERRUPTED or intent in ("skip", "skip_satisfy"):
            self._handle_interrupted(tid, intent)
            return
        if st in (AttemptStatus.CRASHED, AttemptStatus.TIMED_OUT):
            if run.failure_class == "provider_missing":
                self.quota.set_status(model.provider, ProviderStatus.MISSING, "binary not executable", source="run")
                self.db.set_task_state(tid, TaskState.PENDING.value, f"{model.provider} missing; rerouting")
                return
            self._record_failure(tid, aid, run.failure_class or "cli_error",
                                 f"{st.value}: exit {run.exit_code}; {(run.error or '')[-300:]}")
            return
        # SUCCEEDED
        self.quota.record_success(model.provider, model.family)
        if spec.task.is_repair:
            self.db.set_task_state(tid, TaskState.CODE_READY.value, f"repair worker finished ({hstatus}); "
                                   "manager re-runs the parent's acceptance")
            self.db.event("REPAIR_COMPLETED", task_id=tid, attempt_id=aid, handoff=hstatus, parent=spec.task.parent_task_id,
                          tokens_out=run.output_tokens)
            await self.finalize_repair(tid)
            return
        if handoff and hstatus == VALID:
            register_listener_manifest(self.db, tid, handoff.get("listener_manifest") or [],
                                       source_ref=f"task_attempt:{aid}")
        self._record_handoff_extras(tid, aid, handoff, wtpath, spec)
        if problems:
            self.db.event("HANDOFF_" + hstatus, task_id=tid, attempt_id=aid, problems=problems[:10])
        self.db.set_task_state(tid, TaskState.CODE_READY.value, f"worker finished ({hstatus} handoff); acceptance next")
        self.db.event("TASK_COMPLETED", task_id=tid, attempt_id=aid, handoff=hstatus,
                      tokens_out=run.output_tokens, cost_reported=run.reported_cost_usd)
        await self.finalize(tid)

    async def _after_plan(self, spec: RunSpec, provider: WorkerProvider, run) -> None:
        """Planner runs never commit anything; their output is a proposal for the user."""
        tid, aid, model = spec.task.task_id, spec.attempt_id, spec.model
        for sig in run.quota_signals:
            self.quota.record_signal(sig, aid)
        obj = run.structured if isinstance(run.structured, dict) else None
        if obj is None and run.final_text:
            from .result_parser import _candidates
            for cand in _candidates(run.final_text):
                try:
                    c = json.loads(cand)
                except ValueError:
                    continue
                if isinstance(c, dict) and "tasks" in c:
                    obj = c
                    break
        self.db.update_attempt(aid, status=run.status.value, failure_class=run.failure_class, ended_at=iso(utcnow()),
                               exit_code=run.exit_code, input_tokens=run.input_tokens, output_tokens=run.output_tokens,
                               cached_input_tokens=run.cached_input_tokens, reported_cost_usd=run.reported_cost_usd,
                               handoff=json.dumps(obj, ensure_ascii=False) if obj else None,
                               handoff_status=VALID if obj else "MALFORMED",
                               quota_after=self.quota.snapshot(provider.name))
        st = run.status
        if st in (AttemptStatus.QUOTA_LIMITED, AttemptStatus.AUTH_ERROR, AttemptStatus.MODEL_UNAVAILABLE,
                  AttemptStatus.BILLING_BLOCKED):
            if st == AttemptStatus.AUTH_ERROR:
                self.quota.set_status(model.provider, ProviderStatus.AUTH_ERROR, (run.error or "")[-300:], source="run")
            if st == AttemptStatus.MODEL_UNAVAILABLE:
                self.quota.set_status(model.provider, ProviderStatus.MODEL_UNAVAILABLE, "", source="run",
                                      family=f"model:{model.model}")
            self.db.set_task_state(tid, TaskState.PENDING.value, f"{st.value}; rerouting the planner")
            return
        if st == AttemptStatus.INTERRUPTED:
            self._handle_interrupted(tid, self.intent.get(aid))
            return
        if st != AttemptStatus.SUCCEEDED:
            self._record_failure(tid, aid, run.failure_class or "cli_error", run.error or st.value)
            return
        self.quota.record_success(model.provider, model.family)
        row = self.db.task(tid)
        mcps = self._mcp_names()
        pid, msgs = mn.store_proposal(self.db, self.cfg, row, obj, run.final_text, mcps)
        errors = [m for m in msgs if m["level"] == "error"]
        n = len((obj or {}).get("tasks") or [])
        if errors:
            console_id = json.loads(row["extra"] or "{}").get("graph_console_query_id")
            if console_id:
                self.db.x("UPDATE graph_console_queries SET status='FAILED',updated_at=?,result_json=?,error=? WHERE id=?",
                          (iso(utcnow()), json.dumps(obj or {}, ensure_ascii=False),
                           errors[0]["message"][:1000], int(console_id)))
            self.db.set_task_state(tid, TaskState.FAILED.value, f"proposal #{pid} invalid: {errors[0]['message']}"[:500])
            self.svc.notifier.notify(f"plan:{tid}", "planner proposal invalid", f"{tid}: {errors[0]['message']}")
            return
        extra = json.loads(row["extra"] or "{}")
        console_id = extra.get("graph_console_query_id")
        if console_id:
            self.db.x("UPDATE graph_console_queries SET status='READY',updated_at=?,result_json=? WHERE id=?",
                      (iso(utcnow()), json.dumps(obj or {}, ensure_ascii=False), int(console_id)))
            self.db.x("UPDATE plan_proposals SET status='approved',decided_at=? WHERE id=?",
                      (iso(utcnow()), pid))
            self.db.set_task_state(tid, TaskState.PASSED.value, f"graph console answer #{console_id} ready")
            self.db.event("GRAPH_CONSOLE_ANSWER_READY", task_id=tid, query_id=int(console_id),
                          model_key=row["last_model_key"])
            return
        if self.db.get_flag("review_auto_approve_all") == "1":
            ids = mn.apply_proposal(self.db, self.cfg, pid, mcps)
            self.db.set_task_state(tid, TaskState.PASSED.value,
                                   f"proposal #{pid}: created {len(ids)} tasks via global auto approval")
            self.db.event("PLAN_PROPOSAL_AUTO_APPROVED", task_id=tid, proposal_id=pid,
                          created_task_ids=ids, source="global auto approval")
            return
        self.db.set_task_state(tid, TaskState.PASSED.value, f"proposal #{pid} ready: {n} tasks await your approval")
        self._ask(tid, "plan_proposal", str(pid), f"{n} proposed tasks from your prompt; review and approve to create them")
        self.svc.notifier.notify(f"plan:{tid}", "task proposal ready", f"{tid}: {n} tasks")

    def _handle_interrupted(self, tid: str, intent: str | None) -> None:
        if intent == "pause":
            self.db.set_task_state(tid, TaskState.PAUSED.value, "interrupted by pause; work kept in worktree")
        elif intent == "skip":
            self.db.set_task_state(tid, TaskState.CANCELLED.value, "skipped by user while running")
        elif intent == "skip_satisfy":
            self.db.set_task_state(tid, TaskState.PASSED.value, "manually marked satisfied")
        elif intent == "kill":
            self.db.set_task_state(tid, TaskState.PENDING.value, "emergency kill; work kept in worktree")
        else:
            self.db.set_task_state(tid, TaskState.PENDING.value, "stopped; work kept in worktree; resumes on start")
        self.db.event("TASK_INTERRUPTED", task_id=tid, intent=intent or "stop")

    def _record_failure(self, tid: str, aid: int, failure_class: str, diagnosis: str) -> None:
        t = self.db.task(tid)
        n = (t["failed_attempts"] or 0) + 1
        if t["kind"] == "repair":          # technical failure of a repair run
            self.db.update_attempt(aid, failure_class=failure_class, diagnosis=diagnosis[:1000])
            if n <= self.tech_limit:
                back = self.backoffs[min(n - 1, len(self.backoffs) - 1)]
                self.db.set_task_state(tid, TaskState.PENDING.value, f"repair run failed technically ({failure_class}); "
                                       "retry same model", failed_attempts=n,
                                       not_before=iso(utcnow() + dt.timedelta(seconds=back)))
                return
            self.db.set_task_state(tid, TaskState.FAILED.value, f"{n} technical failures ({failure_class})",
                                   failed_attempts=n)
            ctx = json.loads(t["repair_context"] or "{}")
            c = rp.Classification(ctx.get("class", rp.REPAIRABLE_CODE), ctx.get("summary", ""),
                                  ctx.get("failing_checks", []), ctx.get("violating_paths", []),
                                  ctx.get("foreign_owned", {}), outputs=ctx.get("check_outputs", []))
            self._continue_repair_chain(t["parent_task_id"], aid, c, ctx.get("head"))
            return
        fields = dict(failure_class=failure_class, diagnosis=diagnosis[:1000])
        if failure_class in ("test_failure", "scope_violation", "no_output", "review_rejected"):
            fields["status"] = AttemptStatus.FAILED_ATTEMPT.value     # crashes keep CRASHED / TIMED_OUT
        self.db.update_attempt(aid, **fields)
        if n >= self.escalation:
            self.db.set_task_state(tid, TaskState.BLOCKED.value, f"ESCALATION_REQUIRED after {n} failed attempts "
                                   f"({failure_class})", failed_attempts=n)
            if not self.db.one("SELECT 1 FROM approvals WHERE task_id=? AND kind='escalation' AND status='pending'", (tid,)):
                self.db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
                          (tid, "escalation", None, "pending",
                           f"{n} failed attempts; last: {failure_class}. Approve to retry (optionally on another model, "
                           "e.g. astra/opus), reject to mark FAILED.", iso(utcnow())))
            self.db.event("ESCALATION_REQUIRED", task_id=tid, attempt_id=aid, failed_attempts=n, cls=failure_class)
            self.svc.notifier.notify(f"escalation:{tid}", "task repeatedly failed", f"{tid}: {n} failed attempts")
        else:
            back = self.backoffs[min(n - 1, len(self.backoffs) - 1)]
            self.db.set_task_state(tid, TaskState.PENDING.value, f"failed attempt {n} ({failure_class}); retry same model",
                                   failed_attempts=n, not_before=iso(utcnow() + dt.timedelta(seconds=back)))
            self.db.event("TASK_FAILED_ATTEMPT", task_id=tid, attempt_id=aid, n=n, cls=failure_class,
                          retry_in_s=back)

    def _record_handoff_extras(self, tid: str, aid: int, handoff: dict | None, wtpath: Path, spec: RunSpec) -> None:
        now = iso(utcnow())
        if not handoff:
            return
        for kind in ("capability_gaps", "cross_domain_requests", "uncertainties"):
            for text in handoff.get(kind) or []:
                if isinstance(text, str) and text.strip():
                    self.db.x("INSERT INTO capability_gaps(task_id, attempt_id, kind, text, created_at) VALUES(?,?,?,?,?)",
                              (tid, aid, kind.rstrip("s") if kind != "uncertainties" else "uncertainty", text[:2000], now))
        arts = list(handoff.get("artifacts") or [])
        if spec.task.read_only and handoff.get("report_markdown"):
            arts.append({"path": spec.task.write_scope[0] + "REPORT.md", "kind": "report",
                         "description": "read-only task report"})
        dest_root = self.state_dir / "artifacts" / slug(tid) / f"a{aid}"
        for a in arts:
            if not isinstance(a, dict) or not a.get("path"):
                continue
            rel = str(a["path"]).lstrip("/")
            src = (wtpath / rel).resolve()
            if not str(src).startswith(str(wtpath.resolve())) or not src.is_file():
                self.db.event("ARTIFACT_MISSING", task_id=tid, attempt_id=aid, path=rel)
                continue
            dest_root.mkdir(parents=True, exist_ok=True)
            dest = dest_root / src.name
            shutil.copy2(src, dest)
            import hashlib
            data = dest.read_bytes()
            kind = a.get("kind") or ART_KINDS.get(src.suffix.lower(), "other")
            self.db.x("INSERT INTO artifacts(task_id, attempt_id, kind, path, source_path, description, sha256, bytes, "
                      "created_at) VALUES(?,?,?,?,?,?,?,?,?)", (tid, aid, kind, str(dest), rel,
                                                                 str(a.get("description", ""))[:500],
                                                                 hashlib.sha256(data).hexdigest(), len(data), now))
        if handoff.get("status") == "blocked":
            if not self.db.one("SELECT 1 FROM approvals WHERE task_id=? AND kind='astra_recommended' AND status='pending'",
                               (tid,)):
                self.db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
                          (tid, "astra_recommended", "astra", "pending",
                           "worker reported status=blocked; a premium model may be warranted. Nothing runs "
                           "without your approval.", now))
                self.db.event("ASTRA_RECOMMENDED", task_id=tid, attempt_id=aid)

    # ======================================================================
    # acceptance, review, integration (idempotent; restart path too)
    # ======================================================================
    def _receipt_path(self, tid: str, head: str, handoff_status: str) -> Path:
        # Acceptance depends on the tree (HEAD), on the handoff's validity and on the check definitions: a fixed
        # acceptance command must re-run rather than replay a receipt of the old, broken command.
        t = self.db.task(tid)
        checks = json.dumps([t["acceptance"] if t else None, self.cfg.section("acceptance").get("default_commands")],
                            sort_keys=True, default=str)
        digest = hashlib.sha256(checks.encode()).hexdigest()[:12]
        return self.state_dir / "receipts" / slug(tid) / f"{head}-{handoff_status}-{digest}.json"

    async def _acceptance(self, tid: str, trigger_attempt_id: int, via: str | None = None):
        """Deterministic acceptance of task `tid` at its worktree HEAD (cached per HEAD).
        Generated artifacts already in the branch are untracked first (no LLM)."""
        t = self.db.task(tid)
        wtpath = Path(t["worktree"])
        a = self._latest_exec(tid)
        gen, commit = await asyncio.to_thread(self.wt.cleanup_generated, wtpath)
        if gen:
            self.db.event("GENERATED_ARTIFACTS_CLEANED", task_id=tid, count=len(gen), sample=gen[:8], commit=commit,
                          via=via)
        head = self.wt.head(wtpath)
        receipt_p = self._receipt_path(tid, head, a["handoff_status"] or "MISSING")
        if receipt_p.exists():
            return _report_from_receipt(json.loads(receipt_p.read_text())), a
        req = request_from_row(t, self.db.deps(tid))
        self.db.event("ACCEPTANCE_STARTED", task_id=tid, attempt_id=trigger_attempt_id, head=head[:12], via=via)
        rep = await asyncio.to_thread(run_acceptance, self.cfg, self.wt, req, wtpath, a["base_commit"],
                                      a["handoff_status"] or "MISSING",
                                      int(self.cfg.section("context").get("max_test_output_bytes", 6000)))
        if self.stopping:
            return None, a   # discarded; the task stays CODE_READY and re-runs after restart
        save_receipt(rep, receipt_p)
        now = iso(utcnow())
        for c in rep.checks:
            self.db.x("INSERT INTO test_results(task_id, attempt_id, name, kind, passed, exit_code, duration_s, "
                      "output_tail, commit_sha, created_at, via_task_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (tid, trigger_attempt_id, c.name, c.kind, int(c.passed), c.exit_code, c.duration_s,
                       redact(c.output_tail), head, now, via))
        run_dir = self._run_dir(via or tid, trigger_attempt_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "diff.patch").write_text(self.wt.diff(wtpath, a["base_commit"]))
        return rep, a

    def _repairs_on(self) -> bool:
        return bool(self.cfg.section("repair").get("enabled", True))

    def _handoff_needs_repair(self, rep: AcceptanceReport) -> bool:
        return (self._repairs_on() and self.cfg.section("repair").get("repair_malformed_handoff", True)
                and any(c.name == "handoff-valid" and not c.passed for c in rep.checks))

    async def finalize(self, tid: str) -> None:
        t = self.db.task(tid)
        if t["state"] != TaskState.CODE_READY.value or not t["worktree"]:
            return
        if t["kind"] == "repair":
            await self.finalize_repair(tid)
            return
        wtpath = Path(t["worktree"])
        req = request_from_row(t, self.db.deps(tid))
        a0 = self._latest_exec(tid)
        rep, a = await self._acceptance(tid, a0["id"])
        if rep is None:
            return
        head = rep.head_commit
        if not rep.passed or self._handoff_needs_repair(rep):
            self.db.event("TEST_FAILED", task_id=tid, attempt_id=a["id"], failed=[c.name for c in rep.failed()] or
                          ["handoff-valid"])
            await self.on_acceptance_failure(tid, a["id"], rep, None)
            return
        self.db.event("TESTS_PASSED", task_id=tid, attempt_id=a["id"], checks=len(rep.checks),
                      task_commands=rep.ran_task_commands)
        if self.db.get_flag(f"review_approved:{tid}"):
            await self.integrate(tid)
            return
        auto_approve = bool(req.extra.get("auto_approve")) or self.db.get_flag("review_auto_approve_all") == "1"
        if auto_approve:
            self.db.event("REVIEW_AUTO_APPROVED", task_id=tid, attempt_id=a["id"],
                          scope="task" if req.extra.get("auto_approve") else "global",
                          checks=len(rep.checks), task_commands=rep.ran_task_commands,
                          bypassed_review_reasons=list(rep.force_review))
            await self.integrate(tid)
            return
        if req.model_profile in self.cfg.section("review").get("llm_review_profiles", []) and not self.db.one(
                "SELECT 1 FROM reviews WHERE task_id=? AND attempt_id=? AND reviewer!='human'", (tid, a["id"])):
            verdict = await self.llm_review(tid, a, req, wtpath, rep)
            if verdict == "changes_requested":
                self._record_failure(tid, a["id"], "review_rejected", "LLM reviewer requested changes")
                return
        reasons = list(rep.force_review)
        if self.cfg.section("review").get("auto_pass_requires_task_commands", True) and not rep.ran_task_commands:
            reasons.append("no task-specific acceptance command defined (plan_overlay.toml); human review")
        if reasons:
            self.db.set_task_state(tid, TaskState.REVIEW_REQUIRED.value, "; ".join(reasons))
            if not self.db.one("SELECT 1 FROM approvals WHERE task_id=? AND kind='review' AND status='pending'", (tid,)):
                self.db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
                          (tid, "review", head, "pending", "; ".join(reasons), iso(utcnow())))
            self.db.event("REVIEW_REQUIRED", task_id=tid, attempt_id=a["id"], reasons=reasons)
            self.svc.notifier.notify(f"review:{tid}", "review needed", f"{tid}: tests green, awaiting your review")
            return
        await self.integrate(tid)

    # ======================================================================
    # failure classification -> repair tasks
    # ======================================================================
    def _other_tasks(self, tid: str) -> dict[str, tuple[list[str], str]]:
        return {r["task_id"]: (json.loads(r["write_scope"]), r["state"])
                for r in self.db.q("SELECT task_id, write_scope, state FROM tasks WHERE kind='task' AND task_id!=?", (tid,))}

    def _ask(self, tid: str, kind: str, subject: str | None, reason: str) -> None:
        if not self.db.one("SELECT 1 FROM approvals WHERE task_id=? AND kind=? AND status='pending'", (tid, kind)):
            self.db.x("INSERT INTO approvals(task_id, kind, subject, status, reason, created_at) VALUES(?,?,?,?,?,?)",
                      (tid, kind, subject, "pending", reason[:1000], iso(utcnow())))

    def _gaps(self, tid: str, aid: int | None, kind: str, texts) -> None:
        for text in texts:
            self.db.x("INSERT INTO capability_gaps(task_id, attempt_id, kind, text, created_at) VALUES(?,?,?,?,?)",
                      (tid, aid, kind, str(text)[:2000], iso(utcnow())))

    async def on_acceptance_failure(self, tid: str, attempt_id: int, rep: AcceptanceReport, repair_row) -> None:
        t = self.db.task(tid)
        req = request_from_row(t, self.db.deps(tid))
        c = rp.classify_failure(self.cfg, req, rep, self._other_tasks(tid))
        via = repair_row["task_id"] if repair_row else None
        self.db.event("FAILURE_CLASSIFIED", task_id=tid, attempt_id=attempt_id, failure_class=c.cls,
                      failing=c.failing, violating=c.violating[:20], via=via, summary=c.summary[:300])
        if repair_row:
            self.db.set_task_state(via, TaskState.FAILED.value, f"parent acceptance still failing: {c.summary}"[:500])
            self.db.update_attempt(attempt_id, status=AttemptStatus.FAILED_ATTEMPT.value, failure_class=c.cls)
            self.db.event("REPAIR_FAILED", task_id=via, parent=tid, failure_class=c.cls)
        else:
            self.db.update_attempt(attempt_id, status=AttemptStatus.FAILED_ATTEMPT.value, failure_class=c.cls,
                                   diagnosis=c.summary[:1000])
        if not self._repairs_on():
            legacy = {"SCOPE_ERROR": "scope_violation", "NO_OUTPUT": "no_output"}.get(c.cls, "test_failure")
            self._record_failure(tid, attempt_id, legacy, c.summary)
            return
        if c.cls == rp.NO_OUTPUT and not repair_row:
            self._record_failure(tid, attempt_id, "no_output", c.summary)     # nothing to repair: normal retry
            return
        self._continue_repair_chain(tid, attempt_id, c, rep.head_commit)

    def _continue_repair_chain(self, tid: str, attempt_id: int | None, c, head: str | None) -> None:
        # The latest failure is recorded on the parent, so an approval (limit / architecture) can resume from it.
        self.db.x("UPDATE tasks SET failure_class=?, failure_summary=?, repair_context=?, failed_attempt_id=? "
                  "WHERE task_id=?", (c.cls, c.summary[:1000], json.dumps(dict(c.context(), head=head),
                                                                          ensure_ascii=False), attempt_id, tid))
        t = self.db.task(tid)
        if c.cls == rp.DEPENDENCY_MISSING:
            self._gaps(tid, attempt_id, "cross_domain_request",
                       [f"needs {m} from {owner} (not produced yet)" for m, owner in c.missing_deps.items()])
            self.db.x("UPDATE tasks SET active_repair_id=NULL WHERE task_id=?", (tid,))
            self.db.set_task_state(tid, TaskState.BLOCKED.value, f"DEPENDENCY_MISSING: {c.summary}"[:500])
            self._ask(tid, "dependency_missing", ",".join(c.missing_deps.values()),
                      f"{c.summary}. No repair was created (a model must not invent another owner's module). "
                      "Approve once the dependency exists to re-run acceptance; reject to mark FAILED.")
            self.db.event("DEPENDENCY_MISSING", task_id=tid, missing=c.missing_deps)
            self.svc.notifier.notify(f"dep:{tid}", "dependency missing", f"{tid}: {c.summary}")
            return
        if c.cls == rp.ARCHITECTURAL_CONFLICT:
            self.db.x("UPDATE tasks SET active_repair_id=NULL WHERE task_id=?", (tid,))
            self.db.set_task_state(tid, TaskState.ARCHITECTURE_REVIEW_REQUIRED.value, c.summary[:500])
            self._ask(tid, "architecture_review", ",".join(c.shared),
                      f"{c.summary}. Approve (optionally choosing a model) to allow a manual repair; reject to mark FAILED.")
            self.db.event("ARCHITECTURE_REVIEW_REQUIRED", task_id=tid, shared=c.shared)
            self.svc.notifier.notify(f"arch:{tid}", "architecture review", f"{tid}: {c.summary}")
            return
        if c.cls == rp.SCOPE_ERROR and c.foreign:
            self._gaps(tid, attempt_id, "cross_domain_request",
                       [f"{p} belongs to {owner}; request the change there" for p, owner in c.foreign.items()])
        if int(t["repairs_count"] or 0) >= rp.budget(self.cfg, t):
            self.db.x("UPDATE tasks SET active_repair_id=NULL WHERE task_id=?", (tid,))
            self.db.set_task_state(tid, TaskState.BLOCKED.value,
                                   f"REPAIR_LIMIT_REACHED after {t['repairs_count']} repairs; last: {c.cls}")
            self._ask(tid, "repair_limit", None,
                      f"{t['repairs_count']} automatic repairs did not fix {tid} (last: {c.summary}). Approve to allow "
                      "one more repair (optionally on a stronger model); reject to mark FAILED.")
            self.db.event("REPAIR_LIMIT_REACHED", task_id=tid, repairs=t["repairs_count"], last=c.cls)
            self.svc.notifier.notify(f"repairlimit:{tid}", "repair limit reached", tid)
            return
        rid = rp.create_repair(self.db, self.cfg, tid, attempt_id, c, head)
        self.wake.set()
        return rid

    async def finalize_repair(self, rid: str) -> None:
        r = self.db.task(rid)
        if r["state"] != TaskState.CODE_READY.value:
            return
        parent_id = r["parent_task_id"]
        p = self.db.task(parent_id)
        if p["state"] != TaskState.WAITING_REPAIR.value or p["active_repair_id"] != rid:
            self.db.set_task_state(rid, TaskState.CANCELLED.value, "parent no longer waiting for this repair")
            return
        a = self._latest_exec(rid)
        h = json.loads(a["handoff"]) if a and a["handoff"] else None
        if r["mode"] == "read_only_handoff":
            if a["handoff_status"] == VALID and h:
                pa = self._latest_exec(parent_id)
                self.db.update_attempt(pa["id"], handoff=json.dumps(h, ensure_ascii=False), handoff_status=VALID)
                self.db.event("HANDOFF_REPAIRED", task_id=parent_id, via=rid)
        elif h:
            if h.get("cross_domain_requests"):
                self._gaps(parent_id, a["id"], "cross_domain_request", h["cross_domain_requests"])
            if h.get("requires_architecture_change"):
                self.db.set_task_state(rid, TaskState.FAILED.value, "repair reports an architecture change is required")
                c = rp.Classification(rp.ARCHITECTURAL_CONFLICT, "repair worker: fix requires an architecture change: "
                                      + "; ".join(h.get("remaining_failures") or [])[:300])
                self._continue_repair_chain(parent_id, a["id"], c, None)
                return
        rep, _ = await self._acceptance(parent_id, a["id"], via=rid)
        if rep is None:
            return
        if rep.passed and not self._handoff_needs_repair(rep):
            self.db.set_task_state(rid, TaskState.PASSED.value, f"parent acceptance passed at {rep.head_commit[:12]}")
            self.db.x("UPDATE tasks SET active_repair_id=NULL WHERE task_id=?", (parent_id,))
            self.db.set_task_state(parent_id, TaskState.CODE_READY.value, f"repaired by {rid}; acceptance passed")
            self.db.event("REPAIR_SUCCEEDED", task_id=rid, parent=parent_id, head=rep.head_commit)
            await self.finalize(parent_id)
            return
        await self.on_acceptance_failure(parent_id, a["id"], rep, r)

    async def llm_review(self, tid: str, attempt, req: TaskRequest, wtpath: Path, rep: AcceptanceReport) -> str | None:
        impl_provider = attempt["provider"]
        chain = self.cfg.chain("REVIEW")
        if self.cfg.section("review").get("cross_provider", True):
            chain = sorted(chain, key=lambda k: self.cfg.model(k).provider == impl_provider)
        for key in chain:
            m = self.cfg.model(key)
            av = self.quota.availability(m.provider, m.family, m.model)
            if not av.usable or (self.approval_map(tid).get(key) != "approved"
                                 and (not m.automatic or self.cfg.section("approvals").get(key) == "required")):
                continue
            provider = self.svc.providers[m.provider]
            if self.cfg.section("jev").get("require_for_all_llm_context", True):
                selected = self.svc.jev.select_context_bundles(tid, [{
                    "id": "context:review_pack", "description": "candidate diff, validated checks and task handoff",
                    "execution_kind": "context_bundle", "required_for_execution": True}],
                    f"{tid}: independent LLM review")
                if "context:review_pack" not in selected:
                    self.db.event("JEV_CONTEXT_GATE_BLOCKED", task_id=tid, provider="jev",
                                  reason="review context not selected")
                    return None
            aid = self.db.x("INSERT INTO task_attempts(task_id, kind, attempt_no, provider, model_key, model, effort, "
                            "status, started_at, cwd, base_commit) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (tid, "review", attempt["attempt_no"], m.provider, key, m.model, m.effort,
                             AttemptStatus.RUNNING.value, iso(utcnow()), str(wtpath), attempt["base_commit"]))
            run_dir = self._run_dir(tid, aid)
            run_dir.mkdir(parents=True, exist_ok=True)
            prompt = review_prompt(req, self.wt.diff(wtpath, attempt["base_commit"], 60000),
                                   json.loads(attempt["handoff"]) if attempt["handoff"] else None,
                                   [dict(name=c.name, passed=c.passed) for c in rep.checks])
            (run_dir / "prompt.md").write_text(prompt)
            spec = RunSpec(task=req, attempt_id=aid, attempt_no=attempt["attempt_no"], model=m, worktree=str(wtpath),
                           prompt_path=str(run_dir / "prompt.md"), run_dir=str(run_dir),
                           result_schema_path=str(self.review_schema_path), kind="review")
            self.db.set_task_state(tid, TaskState.REVIEWING.value, f"LLM review by {m.provider}/{m.model}")
            self.running[aid] = Running(aid, tid, req.owner, req.write_scope, m.provider, key, "review")
            try:
                run = await provider.run_task(spec, self.svc.sup, timeout=self.timeout)
            finally:
                self.running.pop(aid, None)
            for sig in run.quota_signals:
                self.quota.record_signal(sig, aid)
            obj = run.structured if isinstance(run.structured, dict) else None
            if obj is None and run.final_text:
                try:
                    obj = json.loads(run.final_text)
                except ValueError:
                    obj = None
            self.db.update_attempt(aid, status=run.status.value, ended_at=iso(utcnow()), exit_code=run.exit_code,
                                   handoff=json.dumps(obj) if obj else None)
            self.db.set_task_state(tid, TaskState.CODE_READY.value, "review finished")
            if run.status != AttemptStatus.SUCCEEDED or not obj or obj.get("verdict") not in ("approve", "changes_requested"):
                continue
            self.db.x("INSERT INTO reviews(task_id, attempt_id, reviewer, verdict, findings, created_at) VALUES(?,?,?,?,?,?)",
                      (tid, attempt["id"], f"{m.provider}:{m.model}", obj["verdict"],
                       json.dumps(obj.get("findings", []), ensure_ascii=False), iso(utcnow())))
            self.db.event("LLM_REVIEW", task_id=tid, reviewer=key, verdict=obj["verdict"])
            return obj["verdict"]
        return None

    async def integrate(self, tid: str) -> None:
        row = self.db.task(tid)
        extra = json.loads(row["extra"] or "{}")
        if extra.get("system_task"):
            await self._activate_system_repair(tid, row, extra)
            return
        ok, out, commit = await asyncio.to_thread(self.wt.merge_to_integration, tid)
        self.db.set_flag(f"review_approved:{tid}", None)
        if not ok:
            self.db.set_task_state(tid, TaskState.BLOCKED.value, "merge conflict with integration branch; resolve in "
                                   "the task worktree, then `wwii-build recheck <task>`")
            self.db.event("MERGE_CONFLICT", task_id=tid, detail=out[-800:])
            self.svc.notifier.notify(f"conflict:{tid}", "merge conflict", tid)
            return
        self.db.set_task_state(tid, TaskState.PASSED.value, "acceptance passed and integrated", passed_commit=commit)
        self.db.x("UPDATE deliver_listener_edges SET enabled=1,updated_at=? "
                  "WHERE source_deliver_id=? AND source_kind='model_listener_manifest'",
                  (iso(utcnow()), tid))
        self.db.event("TASK_PASSED", task_id=tid, integration_commit=commit)
        self._open_followups(tid)
        packet = self.db.task(tid)["packet"]
        rem = self.db.one("SELECT COUNT(*) n FROM tasks WHERE packet=? AND kind='task' AND state!=?",
                          (packet, TaskState.PASSED.value))
        if rem["n"] == 0:
            self.db.event("MILESTONE", packet=packet)
            self.svc.notifier.notify(f"milestone:{packet}", "milestone", f"packet {packet} fully passed")

    async def _activate_system_repair(self, tid: str, row, extra: dict) -> None:
        active_other = self.db.one(
            "SELECT COUNT(*) n FROM tasks WHERE task_id<>? AND state IN (?,?,?)",
            (tid, TaskState.RUNNING.value, TaskState.PAUSING.value, TaskState.REVIEWING.value))["n"]
        other_finalizers = [task_id for task_id in self.post if task_id != tid]
        if active_other or other_finalizers:
            reason = f"system repair passed; waiting for {active_other + len(other_finalizers)} active operations"
            if row["state_reason"] != reason:
                self.db.set_task_state(tid, TaskState.CODE_READY.value, reason)
                self.db.event("SYSTEM_REPAIR_WAITING_FOR_QUIET", task_id=tid,
                              active_workers=active_other, active_finalizers=other_finalizers)
            return

        attempt = self._latest_exec(tid)
        worktree = Path(row["worktree"])
        base = str(extra.get("system_base_commit") or (attempt["base_commit"] if attempt else ""))
        manifest = extra.get("system_source_manifest")
        head = self.wt.head(worktree)
        now = iso(utcnow())
        try:
            if not base or not isinstance(manifest, dict):
                raise SystemRepairError("system repair snapshot metadata is missing")
            staged = await asyncio.to_thread(stage_release, self.cfg.repo, self.state_dir, worktree, tid,
                                             base, head, manifest)
            self.db.x(
                "INSERT INTO system_repair_releases(task_id,status,base_commit,candidate_commit,changed_files_json,"
                "release_path,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET "
                "status=excluded.status,base_commit=excluded.base_commit,candidate_commit=excluded.candidate_commit,"
                "changed_files_json=excluded.changed_files_json,release_path=excluded.release_path,error=NULL",
                (tid, "STAGED", base, head, json.dumps(staged.changed_files, ensure_ascii=False),
                 str(staged.path), now))
        except Exception as exc:
            self.db.x(
                "INSERT INTO system_repair_releases(task_id,status,base_commit,candidate_commit,changed_files_json,"
                "error,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET status='FAILED',"
                "error=excluded.error",
                (tid, "FAILED", base or "unknown", head, "[]", str(exc)[:1000], now))
            self.db.set_task_state(tid, TaskState.BLOCKED.value,
                                   f"system activation preflight failed: {str(exc)[:300]}")
            self.db.event("SYSTEM_REPAIR_ACTIVATION_FAILED", task_id=tid, phase="preflight",
                          error=str(exc)[:500])
            return

        ok, out, commit = await asyncio.to_thread(self.wt.merge_to_integration, tid)
        self.db.set_flag(f"review_approved:{tid}", None)
        if not ok:
            self.db.set_task_state(tid, TaskState.BLOCKED.value,
                                   "system repair merge conflict; active manager was not changed")
            self.db.x("UPDATE system_repair_releases SET status='FAILED',error=? WHERE task_id=?",
                      (out[-1000:], tid))
            self.db.event("SYSTEM_REPAIR_ACTIVATION_FAILED", task_id=tid, phase="integration_merge",
                          error=out[-500:])
            return
        try:
            await asyncio.to_thread(activate_release, self.cfg.repo, staged)
        except Exception as exc:
            self.db.x("UPDATE system_repair_releases SET status='FAILED',integration_commit=?,error=? WHERE task_id=?",
                      (commit, str(exc)[:1000], tid))
            self.db.set_task_state(tid, TaskState.BLOCKED.value,
                                   f"system activation rolled back: {str(exc)[:300]}")
            self.db.event("SYSTEM_REPAIR_ACTIVATION_FAILED", task_id=tid, phase="activate_rolled_back",
                          error=str(exc)[:500], integration_commit=commit)
            return

        activated = iso(utcnow())
        self.db.x("UPDATE system_repair_releases SET status='ACTIVATED',integration_commit=?,activated_at=?,error=NULL "
                  "WHERE task_id=?", (commit, activated, tid))
        self.db.set_task_state(tid, TaskState.PASSED.value,
                               "system repair activated; graceful restart requested", passed_commit=commit)
        manager_activation_id = record_activation(self.db)
        self.db.set_flag("system_restart_required", json.dumps({
            "task_id": tid, "candidate_commit": head, "integration_commit": commit,
            "activated_at": activated, "manager_activation_id": manager_activation_id}, ensure_ascii=False))
        self.db.event("SYSTEM_REPAIR_ACTIVATED", task_id=tid, candidate_commit=head,
                      integration_commit=commit, files=staged.changed_files,
                      manager_activation_id=manager_activation_id)
        self._open_followups(tid)
        self.stopping = "restart"
        self.wake.set()

    def _open_followups(self, tid: str) -> None:
        """Follow-up tasks the worker asked for; only for accepted work, so retries never duplicate them."""
        a = self._latest_exec(tid)
        h = json.loads(a["handoff"]) if a and a["handoff"] else {}
        items = h.get("followup_tasks") or []
        if not items:
            return
        try:
            res = mn.propose_followups(self.db, self.cfg, tid, items, self._mcp_names())
        except mn.ManualError as e:
            self.db.event("FOLLOWUP_REJECTED", task_id=tid, reason=str(e)[:300])
            return
        if res.get("proposal"):
            self.svc.notifier.notify(f"followup:{tid}", "follow-up tasks proposed", f"{tid} asked for follow-up tasks")
        self.wake.set()

    def _maybe_all_blocked(self) -> None:
        enabled = [n for n in self.svc.providers if self.cfg.provider(n).get("enabled", True)]
        if enabled and all(not self.quota.availability(n).usable for n in enabled):
            self.db.event("ALL_PROVIDERS_BLOCKED", next_reset=iso(self.quota.next_reset()))
            self.svc.notifier.notify("all_blocked", "all providers blocked",
                                     f"waiting until {iso(self.quota.next_reset()) or 'unknown'}")

    # ======================================================================
    # controls
    # ======================================================================
    async def process_controls(self) -> None:
        for c in self.db.q("SELECT * FROM control_requests WHERE handled_at IS NULL ORDER BY id"):
            args = json.loads(c["args"] or "{}")
            result = "ok"
            cmd = c["command"]
            try:
                if cmd == "stop":
                    self.stopping = self.stopping or "stop"
                elif cmd == "kill":
                    self.stopping = "kill"
                elif cmd == "pause_interrupt":
                    for aid, r in list(self.running.items()):
                        self.intent[aid] = "pause"
                        self.db.set_task_state(r.task_id, TaskState.PAUSING.value, "pause requested")
                        asyncio.create_task(self.svc.sup.shutdown(aid, self.graceful, self.term_grace))
                elif cmd == "skip_running":
                    for aid, r in list(self.running.items()):
                        if r.task_id == args.get("task_id"):
                            self.intent[aid] = "skip_satisfy" if args.get("satisfy") else "skip"
                            asyncio.create_task(self.svc.sup.shutdown(aid, self.graceful, self.term_grace))
                elif cmd == "refresh":
                    rep = await self.refresh_provider(args.get("provider"), manual=True)
                    result = rep.status.value if rep else "provider not enabled"
                else:
                    result = "unknown command"
            except Exception as e:
                result = f"error: {e}"
            self.db.x("UPDATE control_requests SET handled_at=?, result=? WHERE id=?", (iso(utcnow()), result, c["id"]))

    async def shutdown_workers(self, mode: str) -> None:
        keys = list(self.running)
        for k in keys:
            self.intent.setdefault(k, "kill" if mode == "kill" else "stop")
        kill_running_commands()
        if mode == "kill":
            for k in keys:
                self.svc.sup.kill(k)
        else:
            await asyncio.gather(*(self.svc.sup.shutdown(k, self.graceful, self.term_grace) for k in keys),
                                 return_exceptions=True)
        futures = [r.future for r in self.running.values() if r.future]
        if futures:
            await asyncio.wait(futures, timeout=self.graceful + self.term_grace + 15)
        for t in list(self.post.values()):
            t.cancel()

    # ======================================================================
    # restart safety
    # ======================================================================
    async def reconcile(self) -> list[str]:
        notes = []
        for w in self.db.q("SELECT * FROM workers"):
            alive = is_same_process(w["pid"], w["process_started"])
            if alive:   # orphan survived a daemon crash: stop it gracefully
                signal_pid(w["pid"], signal.SIGINT)
                for _ in range(int(self.graceful * 5)):
                    if not is_same_process(w["pid"], w["process_started"]):
                        break
                    await asyncio.sleep(0.2)
                if is_same_process(w["pid"], w["process_started"]):
                    os.killpg(w["pgid"], signal.SIGKILL)
            self.db.update_attempt(w["attempt_id"], status=AttemptStatus.ORPHANED.value, ended_at=iso(utcnow()),
                                   failure_class="daemon_restart")
            self.db.x("DELETE FROM workers WHERE attempt_id=?", (w["attempt_id"],))
            notes.append(f"{w['task_id']}: attempt {w['attempt_id']} orphaned (process {'stopped' if alive else 'gone'})")
        for t in self.db.q("SELECT * FROM tasks WHERE state IN (?,?,?)",
                           (TaskState.RUNNING.value, TaskState.PAUSING.value, TaskState.REVIEWING.value)):
            tid = t["task_id"]
            if t["state"] == TaskState.REVIEWING.value:
                self.db.set_task_state(tid, TaskState.CODE_READY.value, "restart: review interrupted; re-checking")
                continue
            self.db.x("UPDATE task_attempts SET status=?, ended_at=?, failure_class=? WHERE task_id=? AND status=?",
                      (AttemptStatus.ORPHANED.value, iso(utcnow()), "daemon_restart", tid, AttemptStatus.RUNNING.value))
            if t["worktree"] and Path(t["worktree"]).exists() and t["kind"] != "plan":   # planners never commit
                try:
                    head = await asyncio.to_thread(self.wt.commit_all, Path(t["worktree"]),
                                                   f"wwii-build: {tid} work recovered after restart")
                    if head:
                        notes.append(f"{tid}: uncommitted work recovered at {head[:10]}")
                except Exception as e:
                    notes.append(f"{tid}: could not commit recovered work: {e}")
            new_state = TaskState.PAUSED if t["state"] == TaskState.PAUSING.value else TaskState.PENDING
            self.db.set_task_state(tid, new_state.value, "restart: previous run did not finish; work kept")
            notes.append(f"{tid}: {t['state']} -> {new_state.value}")
        for t in self.db.q("SELECT task_id, passed_commit FROM tasks WHERE state=? AND passed_commit IS NOT NULL",
                           (TaskState.PASSED.value,)):
            if self.wt.baseline_exists() and not self.wt.is_ancestor(t["passed_commit"], f"refs/heads/{self.wt.branch}"):
                notes.append(f"{t['task_id']}: PASSED commit not on integration branch (left PASSED; check manually)")
                self.db.event("INTEGRATION_MISMATCH", task_id=t["task_id"])
        self.db.event("RECONCILED", notes=notes)
        return notes

    # ======================================================================
    # main loop
    # ======================================================================
    def next_wakeup(self, now: dt.datetime) -> tuple[dt.datetime | None, str]:
        cands: list[tuple[dt.datetime, str]] = []
        r = self.quota.next_reset(now)
        if r and self.db.one("SELECT 1 FROM tasks WHERE state=?", (TaskState.WAITING_QUOTA.value,)):
            cands.append((r, "quota reset"))
        for t in self.db.q("SELECT task_id, not_before FROM tasks WHERE not_before IS NOT NULL AND state=?",
                           (TaskState.PENDING.value,)):
            nb = parse_iso(t["not_before"])
            if nb and nb > now:
                cands.append((nb, f"retry backoff {t['task_id']}"))
        if not cands:
            return None, ""
        return min(cands)

    def _detect_sleep(self) -> None:
        wall, mono = time.time(), time.monotonic()
        gap = (wall - self._last_wall) - (mono - self._last_mono)
        if gap > float(self.cfg.section("scheduler").get("sleep_gap_seconds", 120)):
            self.db.event("WAKE_FROM_SLEEP", slept_s=round(gap))
        self._last_wall, self._last_mono = wall, mono

    async def cycle(self) -> dict:
        """One scheduling cycle. Returns a summary (used by tests and the loop)."""
        self._detect_sleep()
        await self.process_controls()
        if self.stopping:
            return {"stopping": self.stopping}
        activation = restart_decision(
            self.activation_id, activation_id(self.db), busy=bool(self.running or self.post))
        if activation == "restart":
            self.stopping = "restart"
            return {"stopping": self.stopping}
        if activation == "wait":
            return {"started": [], "running": [r.task_id for r in self.running.values()],
                    "idle": "", "activation_restart": "wait"}
        # Known resets that have passed: re-read machine-readable quota (Codex) once.
        now = self.clock()
        for row in self.quota.rows():
            bu = parse_iso(row["blocked_until"])
            last = self._last_refresh.get(row["provider"], 0.0)
            if row["family"] == "*" and bu and bu <= now and row["provider"] == "codex" and time.time() - last > 300:
                self._last_refresh["codex"] = time.time()
                await self.refresh_provider("codex")
        self._maybe_poll_codex_quota()
        control.auto_approve_pending(self.db, self.cfg, "scheduler")
        # Tasks finished by a worker but not yet accepted (e.g. after restart, or review approval)
        for t in self.db.q("SELECT task_id FROM tasks WHERE state=?", (TaskState.CODE_READY.value,)):
            tid = t["task_id"]
            if tid not in self.post and not any(r.task_id == tid for r in self.running.values()):
                self.post[tid] = asyncio.create_task(self._finalize_task(tid))
        decisions = self.evaluate(now)
        system_quiescing = any(
            json.loads(task["extra"] or "{}").get("system_task")
            for task in self.db.q("SELECT extra FROM tasks WHERE state=?", (TaskState.CODE_READY.value,)))
        started = []
        if not system_quiescing and not self.db.get_flag("paused") and not self.db.get_flag("emergency_stop"):
            picked = self.pick_dispatch(decisions)
            if len(picked) > 1 and self.svc.jev.enabled:
                by_id = {d.task_id: (d, note) for d, note in picked}
                candidates = []
                for d, _ in picked:
                    row = self.db.task(d.task_id)
                    cat = self.db.one("SELECT execution_kind,description FROM deliver_catalog WHERE deliver_id=?", (d.task_id,))
                    candidates.append({"id": d.task_id, "description": (cat["description"] if cat else row["note"]) or d.reason,
                                       "execution_kind": cat["execution_kind"] if cat else "worker"})
                order = await asyncio.to_thread(self.svc.jev.order_delivers, candidates,
                                                "Choose the next eligible Deliver to start; do not change eligibility")
                picked = [by_id[i] for i in order if i in by_id]
            for d, _ in picked:
                aid = await self.start_attempt(d)
                if aid:
                    started.append(d.task_id)
        nw, why = self.next_wakeup(self.clock())
        self.db.set_flag("next_wakeup_at", iso(nw) if nw else None)
        self.db.set_flag("next_wakeup_reason", why or None)
        self._idle_reason = self._compute_idle(decisions)
        self.db.set_flag("idle_reason", self._idle_reason or None)
        return {"started": started, "running": [r.task_id for r in self.running.values()], "idle": self._idle_reason}

    def _graph_context(self, req: TaskRequest) -> list[dict]:
        """Deterministic graph search only; the shared Jev gate selects later."""
        limit = max(0, min(int(self.cfg.section("jev").get("max_context_candidates", 24)), 64))
        if not limit:
            return []
        ids = [req.task_id, *req.depends_on]
        marks = ",".join("?" for _ in ids)
        rows = [dict(r) for r in self.db.q(
            f"SELECT * FROM context_sources WHERE active=1 AND (task_id IN ({marks}) OR deliver_id IN ({marks}) "
            "OR source_key IN (SELECT source_key FROM task_context_bindings WHERE task_id=? AND active=1) "
            "OR (task_id IS NULL AND deliver_id IS NULL)) "
            "ORDER BY CASE WHEN task_id=? OR deliver_id=? OR source_key IN "
            "(SELECT source_key FROM task_context_bindings WHERE task_id=? AND active=1) THEN 0 ELSE 1 END, "
            "updated_at DESC, source_key LIMIT ?",
            (*ids, *ids, req.task_id, req.task_id, req.task_id, req.task_id, limit))]
        # Context-planned tasks normally arrive with persisted bindings. For tasks
        # created over MCP without a planning pass, perform the same minimal
        # Neo4j → Jev selection lazily and persist its provenance for later runs.
        context_request = str(req.extra.get("context_request") or "").strip()
        has_selected = any(r.get("origin_kind") == "graph_rag" for r in rows)
        if context_request and not has_selected:
            result = self.svc.graph_rag.selected_query(
                self.svc.jev, req.task_id, context_request, planner=True)
            now = iso(utcnow())
            for item in result.get("selected") or []:
                excerpt = str(item.get("excerpt") or "")[:24000]
                digest = str(item.get("content_sha256") or hashlib.sha256(excerpt.encode()).hexdigest())
                source_key = str(item.get("source_key") or item.get("id"))
                self.db.x(
                    "INSERT INTO context_sources(source_key,task_id,origin_kind,origin_ref,graph_entity_id,"
                    "graph_revision,title,excerpt,content_sha256,tags_json,active,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,'[]',1,?,?) ON CONFLICT(source_key) DO UPDATE SET active=1,"
                    "updated_at=excluded.updated_at",
                    (source_key, req.task_id, str(item.get("origin_kind") or "graph_rag"),
                     str(item.get("origin_ref") or "unknown"), item.get("graph_entity_id"),
                     item.get("graph_revision"), str(item.get("title") or item.get("description") or source_key)[:500],
                     excerpt, digest, now, now))
                self.db.x(
                    "INSERT INTO task_context_bindings(task_id,source_key,active,created_at,updated_at) VALUES(?,?,1,?,?) "
                    "ON CONFLICT(task_id,source_key) DO UPDATE SET active=1,updated_at=excluded.updated_at",
                    (req.task_id, source_key, now, now))
                saved = self.db.one("SELECT * FROM context_sources WHERE source_key=?", (source_key,))
                if saved:
                    rows.append(dict(saved))
        rows = list({row["source_key"]: row for row in rows}.values())[:limit]
        return rows

    def _context_bundles(self, pack) -> tuple[list[dict], dict[str, list[str]]]:
        """Turn a local ContextPack inventory into a small Jev candidate set."""
        groups: dict[str, list] = {"context:core": []}
        for item in pack.items:
            if item.mode not in ("inline", "reference"):
                continue
            if item.layer in ("global", "domain", "role", "registry") or (
                    item.layer == "task" and item.mode == "inline"):
                key = "context:core"
            elif item.layer == "dependency":
                key = "context:dependencies"
            elif item.layer == "retry":
                key = "context:retry"
            else:
                digest = hashlib.sha256(item.path.encode()).hexdigest()[:12]
                key = f"context:{item.layer}:{digest}"
            groups.setdefault(key, []).append(item)
        paths = {key: [item.path for item in items] for key, items in groups.items() if items}
        candidates = []
        for key, items in groups.items():
            if not items:
                continue
            summary = "; ".join(f"{item.path} [{item.layer}] {item.reason}" for item in items)[:1400]
            candidates.append({"id": key, "description": summary, "execution_kind": "context_bundle",
                               "required_for_execution": key == "context:core"})
        return candidates, paths

    def _jev_gate_whole_pack(self, req: TaskRequest, pack, description: str):
        if not self.cfg.section("jev").get("require_for_all_llm_context", True):
            return pack
        selected = self.svc.jev.select_context_bundles(req.task_id, [{
            "id": "context:whole_pack", "description": description,
            "execution_kind": "context_bundle", "required_for_execution": True}],
            f"{req.task_id}: authorize the minimal prepared context pack")
        if "context:whole_pack" not in selected:
            return None
        pack.routing = {"gate": "jev", "policy": "fail_closed",
                        "selected_bundles": selected, "candidate_bundles": ["context:whole_pack"]}
        return pack

    def _maybe_poll_codex_quota(self) -> None:
        """Codex exposes live limits without inference: read them every quota_poll_seconds, in the background."""
        pc = self.cfg.provider("codex")
        if (not pc.get("enabled", True) or pc.get("quota_source") != "app-server" or self.quota_poll <= 0
                or (self._quota_poll_task and not self._quota_poll_task.done())
                or time.monotonic() - self._last_quota_poll < self.quota_poll):
            return
        self._last_quota_poll = time.monotonic()
        prov = self.svc.providers.get("codex")

        async def poll():
            try:
                res = await prov.read_rate_limits()
                if res:
                    self.quota.record_codex_snapshot(res, float(pc.get("near_limit_percent", 90)),
                                                     float(pc.get("stop_dispatch_at_percent", 100)))
            except Exception as e:
                self.db.event("QUOTA_READ_FAILED", provider="codex", error=str(e)[:200])
        self._quota_poll_task = asyncio.create_task(poll())

    async def _finalize_task(self, tid: str) -> None:
        try:
            await self.finalize(tid)
        except Exception as e:
            self.db.event("MANAGER_ERROR", task_id=tid, error=str(e)[:500], trace=traceback.format_exc()[-1500:])
            self.db.set_task_state(tid, TaskState.BLOCKED.value, f"finalize error: {str(e)[:200]}")
        finally:
            self.post.pop(tid, None)
            self.wake.set()

    def _compute_idle(self, decisions: list[Decision]) -> str:
        if self.running or self.post:
            return ""
        if self.db.get_flag("emergency_stop"):
            return "emergency stop marker set"
        if self.db.get_flag("paused"):
            return "paused"
        counts: dict[str, int] = {}
        for r in self.db.q("SELECT state, COUNT(*) n FROM tasks GROUP BY state"):
            counts[r["state"]] = r["n"]
        if counts.get(TaskState.READY.value):
            return ""
        parts = []
        for st, label in ((TaskState.WAITING_APPROVAL, "manual approval required"),
                          (TaskState.REVIEW_REQUIRED, "manual review required"),
                          (TaskState.WAITING_QUOTA, "quota unavailable"),
                          (TaskState.WAITING_PROVIDER, "no usable provider"),
                          (TaskState.WAITING_REPAIR, "waiting for repair"),
                          (TaskState.ARCHITECTURE_REVIEW_REQUIRED, "architecture review required"),
                          (TaskState.BLOCKED, "blocked/escalation")):
            if counts.get(st.value):
                parts.append(f"{label} ({counts[st.value]})")
        if not parts and all(k in (TaskState.PASSED.value, TaskState.CANCELLED.value, TaskState.FAILED.value)
                             for k in counts):
            return "all work finished"
        return "; ".join(parts) or "no ready work"

    async def run(self, *, dashboard_wake_hook=None) -> str:
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            loop.add_signal_handler(s, self._signal_stop)
        loop.add_signal_handler(signal.SIGUSR1, self.wake.set)
        if dashboard_wake_hook:
            dashboard_wake_hook(lambda: loop.call_soon_threadsafe(self.wake.set))
        self.prepare()
        if self.db.get_flag("emergency_stop"):
            return "refused: emergency-stop marker set (wwii-build resume --clear-emergency)"
        self.db.set_flag("stop_requested", None)
        self.db.set_flag("daemon_started_at", iso(utcnow()))
        self.db.set_flag("daemon_code_version", str(mn.CODE_VERSION))
        self.db.event("DAEMON_STARTED", pid=os.getpid())
        pending_restart = self.db.get_flag("system_restart_required")
        if pending_restart:
            self.db.set_flag("system_restart_required", None)
            self.db.event("SYSTEM_RESTART_COMPLETED", release=json.loads(pending_restart),
                          code_version=mn.CODE_VERSION)
        await self.reconcile()
        await self.refresh_all()
        reason = "stopped"
        while True:
            self.wake.clear()
            summary = await self.cycle()
            if self.stopping:
                break
            if self.exit_when_idle and summary.get("idle"):
                reason = f"idle: {summary['idle']}"
                break
            nw = parse_iso(self.db.get_flag("next_wakeup_at"))
            timeout = self.poll
            if nw:
                timeout = max(0.05, min(timeout, (nw - self.clock()).total_seconds()))
            try:
                await asyncio.wait_for(self.wake.wait(), timeout)
            except asyncio.TimeoutError:
                pass
        mode = self.stopping or "idle"
        if self.stopping:
            event = "SYSTEM_RESTART_REQUESTED" if mode == "restart" else (
                "STOP_REQUESTED" if mode == "stop" else "EMERGENCY_KILL")
            self.db.event(event, running=len(self.running))
            if mode == "kill":
                self.db.set_flag("emergency_stop", iso(utcnow()))
            await self.shutdown_workers("stop" if mode == "restart" else mode)
            reason = "system-restart" if mode == "restart" else ("emergency kill" if mode == "kill" else "stopped")
        self.db.set_flag("daemon_started_at", None)
        self.db.event("DAEMON_EXITED", reason=reason)
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGUSR1):
            loop.remove_signal_handler(s)
        return reason

    def prepare(self) -> None:
        self.schema_path.parent.mkdir(parents=True, exist_ok=True)
        self.schema_path.write_text(json.dumps(RESULT_SCHEMA, indent=1))
        self.review_schema_path.write_text(json.dumps(REVIEW_SCHEMA, indent=1))
        self.repair_schema_path.write_text(json.dumps(rp.REPAIR_SCHEMA, indent=1))
        self.plan_schema_path.write_text(json.dumps(mn.PLAN_SCHEMA, indent=1))

    def _signal_stop(self) -> None:
        if self.stopping:          # second Ctrl-C escalates to kill
            self.stopping = "kill"
        else:
            self.stopping = "stop"
        self.wake.set()


def _report_from_receipt(rc: dict) -> AcceptanceReport:
    from .acceptance import Check
    rep = AcceptanceReport(rc["task_id"], rc.get("head_commit"))
    rep.checks = [Check(**c) for c in rc.get("checks", [])]
    rep.force_review = list(rc.get("force_review", []))
    rep.ran_task_commands = bool(rc.get("ran_task_commands"))
    return rep
