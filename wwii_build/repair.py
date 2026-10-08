"""Failure classification and scoped Repair Tasks.

When a worker finishes but deterministic acceptance fails, the manager classifies the
failure instead of re-sending the whole task:

  GENERATED_ARTIFACT_FALSE_POSITIVE  deterministic cleanup + re-run acceptance, no LLM
  REPAIRABLE_CODE / SCOPE_ERROR /    create REPAIR/<parent>/<n>: a small task that fixes only
  REPAIRABLE_HANDOFF                 the failure, in the parent's existing worktree
  DEPENDENCY_MISSING                 parent BLOCKED + cross-domain gap; never "invent" it
  ARCHITECTURAL_CONFLICT             parent ARCHITECTURE_REVIEW_REQUIRED; human decides
  NO_OUTPUT                          nothing to repair; the normal task retry applies
(QUOTA / AUTH / PROVIDER / TECHNICAL are handled at run level and never reach here.)

The repair worker never decides whether the parent passed: the manager re-runs the
parent's acceptance after every repair.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .acceptance import AcceptanceReport, in_scope
from .config import Config
from .context_builder import INVARIANTS, sha256_bytes
from .db import DB
from .generated import is_generated
from .models import ContextItem, ContextPack, TaskRequest, TaskState, iso, utcnow
from .result_parser import _candidates

GENERATED = "GENERATED_ARTIFACT_FALSE_POSITIVE"
REPAIRABLE_CODE = "REPAIRABLE_CODE"
REPAIRABLE_HANDOFF = "REPAIRABLE_HANDOFF"
SCOPE_ERROR = "SCOPE_ERROR"
DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
ARCHITECTURAL_CONFLICT = "ARCHITECTURAL_CONFLICT"
NO_OUTPUT = "NO_OUTPUT"
REPAIRABLE = {REPAIRABLE_CODE, REPAIRABLE_HANDOFF, SCOPE_ERROR}
TEXT_EXT = (".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".csv")
_MISSING_MOD = re.compile(r"No module named '([\w.]+)'")
_FILE_REF = re.compile(r"([\w./\-]+\.[A-Za-z0-9]{1,6})(?::\d+)?")

_STR_LIST = {"type": "array", "items": {"type": "string"}}
REPAIR_SCHEMA: dict = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "repair_task_id": {"type": "string"}, "parent_task_id": {"type": "string"},
        "failure_addressed": {"type": "string"}, "summary": {"type": "string"},
        "changed_files": _STR_LIST, "tests_run": _STR_LIST, "tests_passed": _STR_LIST,
        "remaining_failures": _STR_LIST, "cross_domain_requests": _STR_LIST,
        "requires_architecture_change": {"type": "boolean"},
    },
}
REPAIR_SCHEMA["required"] = list(REPAIR_SCHEMA["properties"])


def repair_cfg(cfg: Config) -> dict:
    return cfg.section("repair")


@dataclass
class Classification:
    cls: str
    summary: str
    failing: list[str] = field(default_factory=list)
    violating: list[str] = field(default_factory=list)
    foreign: dict[str, str] = field(default_factory=dict)      # path -> owning task
    shared: list[str] = field(default_factory=list)
    missing_deps: dict[str, str] = field(default_factory=dict)  # module -> task that should provide it
    outputs: list[dict] = field(default_factory=list)

    def context(self) -> dict:
        return {"class": self.cls, "summary": self.summary, "failing_checks": self.failing,
                "violating_paths": self.violating, "foreign_owned": self.foreign, "shared_contracts": self.shared,
                "missing_dependencies": self.missing_deps, "check_outputs": self.outputs}


def classify_failure(cfg: Config, req: TaskRequest, rep: AcceptanceReport,
                     other_tasks: dict[str, tuple[list[str], str]]) -> Classification:
    """other_tasks: task_id -> (write_scope, state) for every *other* plan task."""
    failed = rep.failed()
    names = [c.name for c in failed]
    outputs = [{"name": c.name, "kind": c.kind, "exit_code": c.exit_code, "output_tail": c.output_tail[-4000:],
                "paths": c.paths} for c in failed]
    blocking_ok = not failed
    own = next((c for c in failed if c.name == "ownership"), None)
    violating = list(own.paths) if own else []
    base = dict(failing=names, violating=violating, outputs=outputs)
    if blocking_ok:   # only advisory problems left (malformed handoff)
        return Classification(REPAIRABLE_HANDOFF, "all checks pass but the handoff is not valid JSON", **base)
    real, gen = [p for p in violating if not is_generated(p)], [p for p in violating if is_generated(p)]
    if own and not real and gen and names == ["ownership"]:
        return Classification(GENERATED, f"{len(gen)} generated artifacts counted as changes", **base)
    shared_roots = repair_cfg(cfg).get("shared_contract_paths", [])
    shared = [p for p in real if in_scope(p, shared_roots)]
    if shared:
        return Classification(ARCHITECTURAL_CONFLICT,
                              "change touches shared contracts outside the task's scope: " + ", ".join(shared[:5]),
                              shared=shared, **base)
    missing: dict[str, str] = {}
    for c in failed:
        for mod in _MISSING_MOD.findall(c.output_tail or ""):
            cand = mod.replace(".", "/")
            if cand.count("/") < 2 or in_scope(cand + "/", req.write_scope):
                continue
            for tid, (scope, state) in other_tasks.items():
                if state != TaskState.PASSED.value and any(
                        cand.startswith(s.rstrip("/")) or s.startswith(cand + "/") for s in scope):
                    missing[mod] = tid
    if missing:
        return Classification(DEPENDENCY_MISSING, "imports not produced yet: " +
                              ", ".join(f"{m} (owner task {t})" for m, t in missing.items()),
                              missing_deps=missing, **base)
    if "nonempty-change" in names:
        return Classification(NO_OUTPUT, "worker produced no change", **base)
    if real:
        foreign = {p: tid for p in real for tid, (scope, _) in other_tasks.items() if in_scope(p, scope)}
        return Classification(SCOPE_ERROR, f"{len(real)} real file(s) outside the write scope: " + ", ".join(real[:5]),
                              foreign=foreign, **base)
    return Classification(REPAIRABLE_CODE, "failed checks: " + ", ".join(names), **base)


def repair_profile(cfg: Config, parent: TaskRequest, c: Classification, repair_no: int) -> str:
    rc = repair_cfg(cfg)
    if c.cls == REPAIRABLE_HANDOFF:
        return "REPAIR_HANDOFF"
    if repair_no >= int(rc.get("escalate_from_repair", 3)):
        return "REPAIR_ESCALATED"
    if parent.model_profile in ("RESEARCH",) or (parent.domain or "") == "historical_evidence":
        return "REPAIR_EVIDENCE"
    textual = c.failing and set(c.failing) <= {"diff-check", "ownership"} and all(
        p.endswith(TEXT_EXT) for p in c.violating)
    return "REPAIR_TEXT" if textual else "REPAIR_CODE"


def repair_id(parent_id: str, n: int) -> str:
    return f"REPAIR/{parent_id}/{n}"


def budget(cfg: Config, parent_row) -> int:
    return int(repair_cfg(cfg).get("max_repairs_per_task", 3)) + int(parent_row["repair_budget_extra"] or 0)


def create_repair(db: DB, cfg: Config, parent_id: str, failed_attempt_id: int | None, c: Classification,
                  head: str | None, preferred_model: str | None = None, profile: str | None = None) -> str:
    """Insert REPAIR/<parent>/<n> and move the parent to WAITING_REPAIR (one transaction)."""
    from .plan_importer import request_from_row
    p = db.task(parent_id)
    parent = request_from_row(p, db.deps(parent_id))
    n = int(p["repairs_count"] or 0) + 1
    rid = repair_id(parent_id, n)
    prof = profile or repair_profile(cfg, parent, c, n)
    now = iso(utcnow())
    ctx = dict(c.context(), head=head, parent_profile=parent.model_profile)
    mode = "read_only_handoff" if c.cls == REPAIRABLE_HANDOFF else "build"
    with db.tx():
        db.conn.execute(
            "INSERT INTO tasks(task_id, packet, owner, domain, mode, model_profile, lego_ids, write_scope, context_entry, "
            "brief_path, note, acceptance, extra, definition_hash, wave, state, state_reason, created_at, updated_at, "
            "kind, parent_task_id, repair_no, failed_attempt_id, failure_class, failure_summary, repair_context, "
            "branch, worktree, preferred_model_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, p["packet"], p["owner"], p["domain"], mode, prof, "[]", p["write_scope"], p["context_entry"], None,
             f"repair #{n} of {parent_id}: {c.summary}"[:500], p["acceptance"], "{}", f"repair-{n}", p["wave"],
             TaskState.PENDING.value, f"repair for {c.cls}", now, now, "repair", parent_id, n, failed_attempt_id,
             c.cls, c.summary[:1000], json.dumps(ctx, ensure_ascii=False), p["branch"], p["worktree"],
             preferred_model))
        db.conn.execute("UPDATE tasks SET state=?, state_reason=?, repairs_count=?, active_repair_id=?, updated_at=? "
                        "WHERE task_id=?", (TaskState.WAITING_REPAIR.value, f"{rid}: {c.cls} — {c.summary}"[:500],
                                            n, rid, now, parent_id))
    db.event("REPAIR_CREATED", task_id=parent_id, repair_task_id=rid, repair_no=n, failure_class=c.cls,
             profile=prof, summary=c.summary[:300], failed_attempt_id=failed_attempt_id)
    return rid


# --------------------------------------------------------------------------------- context
def _trim(text: str, n: int) -> str:
    b = text.encode()
    return text if len(b) <= n else b[:n].decode("utf-8", "ignore") + "\n... [truncated]"


def related_files(c: Classification, worktree: Path, scope: list[str], limit: int = 4,
                  max_bytes: int = 20000) -> list[str]:
    seen: list[str] = []
    for o in c.outputs:
        for m in _FILE_REF.findall(o.get("output_tail") or ""):
            p = m.lstrip("./")
            if p in seen or is_generated(p) or not in_scope(p, scope):
                continue
            f = worktree / p
            if f.is_file() and f.stat().st_size <= max_bytes:
                seen.append(p)
            if len(seen) >= limit:
                return seen
    return seen


def build_repair_pack(cfg: Config, worktree: Path, parent: TaskRequest, repair_row, diff: str,
                      parent_handoff: dict | None, history: list[dict], acceptance_cmds: list[dict],
                      max_repairs: int) -> ContextPack:
    rc = repair_cfg(cfg)
    ctx = json.loads(repair_row["repair_context"] or "{}")
    c = Classification(ctx.get("class", repair_row["failure_class"]), ctx.get("summary", ""),
                       ctx.get("failing_checks", []), ctx.get("violating_paths", []), ctx.get("foreign_owned", {}),
                       ctx.get("shared_contracts", []), ctx.get("missing_dependencies", {}), ctx.get("check_outputs", []))
    items: list[ContextItem] = []
    inline: list[tuple[str, str, str]] = []

    def add_file(rel: str, layer: str, reason: str) -> None:
        f = worktree / rel
        if not f.is_file():
            items.append(ContextItem(rel, layer, "missing", None, 0, reason))
            return
        b = f.read_bytes()
        items.append(ContextItem(rel, layer, "inline", sha256_bytes(b), len(b), reason))
        inline.append((rel, sha256_bytes(b), b.decode("utf-8", "replace")))

    def add_gen(label: str, layer: str, text: str, reason: str) -> None:
        b = text.encode()
        items.append(ContextItem(label, layer, "inline", sha256_bytes(b), len(b), reason))
        inline.append((label, sha256_bytes(b), text))

    add_file(INVARIANTS, "global", "global invariants")
    if parent.context_entry:
        add_file(parent.context_entry, "role", f"role card of owner {parent.owner}")
    failure_text = json.dumps({k: v for k, v in c.context().items() if k != "check_outputs"}, ensure_ascii=False,
                              indent=1) + "\n\n" + "\n\n".join(
        f"### {o['name']} ({o['kind']}, exit {o['exit_code']})\n{_trim(o['output_tail'] or '', 4000)}" for o in c.outputs)
    add_gen(f"repair:failure[{repair_row['task_id']}]", "failure", failure_text, "exact failing checks and output")
    add_gen("repair:current-diff", "diff", _trim(diff, int(rc.get("max_diff_bytes", 30000))),
            "the parent's current candidate implementation (base..HEAD)")
    if parent_handoff:
        slim = {k: parent_handoff.get(k) for k in ("status", "summary", "changed_files", "tests_run", "tests_failed",
                                                   "assumptions", "uncertainties", "capability_gaps")}
        add_gen("handoff:parent", "handoff", json.dumps(slim, ensure_ascii=False, indent=1), "previous handoff")
    if history:
        add_gen("repair:history", "history", _trim(json.dumps(history, ensure_ascii=False, indent=1), 12000),
                "previous repairs of this parent: failure, result, diff")
    for rel in related_files(c, worktree, parent.write_scope):
        add_file(rel, "related", "file named in the failing output")
    for rel, why in ((parent.brief_path or f"context/game/build_packets/{parent.packet}/BRIEF.md", "packet brief"),
                     (f"context/game/domains/{parent.domain}/DOMAIN.md", "domain overview"),
                     (f"registry:dispatch_tasks[{parent.task_id}]", "full task slice")):
        items.append(ContextItem(rel, "excluded", "excluded", None, 0, f"{why}: not needed to fix this failure"))

    handoff_mode = repair_row["mode"] == "read_only_handoff"
    L = [f"TASK_ID: {repair_row['task_id']}",
         "You are a scoped REPAIR worker. Fix only the recorded acceptance failure. Do not redesign or re-implement.",
         "", "## ROLE", f"Owner `{parent.owner}` ({parent.domain}), repairing `{parent.task_id}`.", "",
         "## REPAIR TASK",
         f"Parent: {parent.task_id} (packet {parent.packet}). Repair #{repair_row['repair_no']} of max {max_repairs}.",
         f"Failure class: {c.cls}. Summary: {c.summary}",
         "Goal: " + ("return a valid handoff JSON that accurately describes the EXISTING diff; do not change files."
                     if handoff_mode else
                     "make the failing checks pass with the smallest change to the existing worktree."), ""]
    L.append("## FAILURE")
    L += [f"- failed check: `{n}`" for n in c.failing] or ["- (advisory only: handoff)"]
    for p in c.violating:
        owner = c.foreign.get(p)
        L.append(f"- OUT-OF-SCOPE PATH: `{p}`" + (f" (owned by {owner}: revert it; request the change via "
                                                   "cross_domain_requests instead)" if owner else
                                                   " (revert it, or move it inside the write scope)"))
    L += ["", "## WRITE SCOPE"]
    if handoff_mode:
        L.append("READ-ONLY repair. Do not modify files.")
    L += [f"- `{p}`" for p in parent.write_scope]
    L += ["Never edit outside these paths. Never touch shared contracts. Do not commit; the manager commits.",
          "", "## TEST COMMANDS (the manager re-runs these itself; your claims do not decide the result)"]
    L += [f"- `{c_['name']}`: `{' '.join(c_['argv'])}`" for c_ in acceptance_cmds]
    L += ["- built-in: ownership (write scope), `git diff --check`, secret scan", "", "## RETURN FORMAT"]
    L.append("Write human-readable summaries and findings in Hebrew; preserve exact code identifiers and paths.")
    if handoff_mode:
        L.append("One JSON object with the full task handoff keys (task_id, status, summary, changed_files, artifacts, "
                 "tests_run, tests_passed, tests_failed, context_used, contracts_used, evidence_used, assumptions, "
                 f"uncertainties, untested_limits, capability_gaps, cross_domain_requests, next_dependency, "
                 f"review_required, report_markdown). task_id = {parent.task_id}.")
    else:
        L.append("REPAIR_RESULT: one JSON object with keys repair_task_id, parent_task_id, failure_addressed, summary, "
                 "changed_files, tests_run, tests_passed, remaining_failures, cross_domain_requests, "
                 "requires_architecture_change (true only if the fix needs another owner's or a shared contract).")
    L += ["", "---- CONTEXT ----"]
    for label, sha, text in inline:
        L += [f"<<<BEGIN {label} sha256={sha[:12]}>>>", text.rstrip(), f"<<<END {label}>>>"]
    prompt = "\n".join(L) + "\n"
    pb = prompt.encode()
    return ContextPack(task_id=repair_row["task_id"], items=items, prompt=prompt, prompt_sha256=sha256_bytes(pb),
                       total_bytes=len(pb))


def parse_repair_result(repair_task_id: str, parent_id: str, structured, text: str | None) -> tuple[dict | None, str]:
    obj = structured if isinstance(structured, dict) else None
    if obj is None and isinstance(structured, str):
        try:
            obj = json.loads(structured)
        except ValueError:
            obj = None
    if obj is None and text:
        for cand in _candidates(text):
            try:
                c = json.loads(cand)
            except ValueError:
                continue
            if isinstance(c, dict) and ("failure_addressed" in c or "remaining_failures" in c):
                obj = c
                break
    if obj is None:
        return None, ("MALFORMED" if text and text.strip() else "MISSING")
    missing = [k for k in REPAIR_SCHEMA["required"] if k not in obj]
    obj.setdefault("repair_task_id", repair_task_id)
    obj.setdefault("parent_task_id", parent_id)
    for k in ("changed_files", "tests_run", "tests_passed", "remaining_failures", "cross_domain_requests"):
        obj.setdefault(k, [])
    obj.setdefault("requires_architecture_change", False)
    return obj, ("VALID" if not missing else "MALFORMED")
