"""ContextBuilder: minimal, audited context per task run.

Layers (context/game/README.md): GlobalInvariant + Domain + Role + TaskSlice +
DependencyContext (interfaces/handoffs, never producer implementation) + EvidenceSlice.
Everything sent is recorded (path, sha256, bytes, reason); everything deliberately
withheld is recorded as ``excluded``. Retry runs add only the previous diff, test
errors and previous handoff — never the full history.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .models import ContextItem, ContextPack, TaskRequest
from .prompts import render_prompt

INVARIANTS = "context/game/global/INVARIANTS.md"
INTERFACES_INDEX = "context/game/interfaces/README.md"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass
class DependencyHandoff:
    task_id: str
    state: str
    summary: str = ""
    artifacts: list = field(default_factory=list)
    changed_files: list = field(default_factory=list)
    contracts: list = field(default_factory=list)
    commit: str | None = None


@dataclass
class RetryInfo:
    attempt_no: int
    previous_diff: str = ""
    failed_tests: list[dict] = field(default_factory=list)
    previous_handoff: dict | None = None
    reviewer_note: str | None = None
    failure_class: str | None = None


class ContextBuilder:
    def __init__(self, cfg: Config, registry: dict, source_root: Path | None = None):
        self.cfg = cfg
        self.registry = registry
        self.root = source_root or cfg.repo      # read context from here (repo or integration worktree)
        self.items = {i["lego_id"]: i for i in registry.get("items", [])}
        self.packets = {p["id"]: p for p in registry.get("build_packets", [])}
        self.max_inline = int(cfg.section("context").get("max_inline_bytes", 90000))
        self.max_diff = int(cfg.section("context").get("max_retry_diff_bytes", 20000))
        self.max_test = int(cfg.section("context").get("max_test_output_bytes", 6000))

    # ------------------------------------------------------------------
    def _file(self, rel: str, allow_repo_fallback: bool = False) -> tuple[str | None, str | None, int]:
        p = self.root / rel
        if not p.is_file() and allow_repo_fallback and (self.cfg.repo / rel).is_file():
            p = self.cfg.repo / rel          # user-picked context that only exists in the working tree
        if not p.is_file():
            return None, None, 0
        b = p.read_bytes()
        return b.decode("utf-8", errors="replace"), sha256_bytes(b), len(b)

    def build(self, task: TaskRequest, deps: list[DependencyHandoff], retry: RetryInfo | None = None,
              acceptance_commands: list[dict] | None = None,
              graph_context: list[dict] | None = None,
              selected_paths: set[str] | None = None) -> ContextPack:
        items: list[ContextItem] = []
        inline: list[tuple[str, str, str]] = []   # (label, sha, text)
        seen: set[str] = set()

        def add_inline(rel: str, layer: str, reason: str) -> None:
            if rel in seen:
                return
            if selected_paths is not None and rel not in selected_paths:
                seen.add(rel)
                items.append(ContextItem(rel, layer, "excluded", None, 0,
                                         reason + " (not selected by Jev context gate)"))
                return
            text, sha, n = self._file(rel, allow_repo_fallback=(layer == "evidence"))
            if layer == "evidence" and text is not None and not (self.root / rel).is_file():
                reason += " (read from your working tree; not in the integration branch)"
            seen.add(rel)
            if text is None:
                items.append(ContextItem(rel, layer, "missing", None, 0, reason + " (file not found)"))
                return
            items.append(ContextItem(rel, layer, "inline", sha, n, reason))
            inline.append((rel, sha, text))

        def add_generated(label: str, layer: str, text: str, reason: str) -> None:
            if selected_paths is not None and label not in selected_paths:
                items.append(ContextItem(label, layer, "excluded", None, 0,
                                         reason + " (not selected by Jev context gate)"))
                return
            b = text.encode()
            sha = sha256_bytes(b)
            items.append(ContextItem(label, layer, "inline", sha, len(b), reason))
            inline.append((label, sha, text))

        def add_ref(rel: str, layer: str, reason: str) -> None:
            if rel in seen:
                return
            seen.add(rel)
            if selected_paths is not None and rel not in selected_paths:
                items.append(ContextItem(rel, layer, "excluded", None, 0,
                                         reason + " (not selected by Jev context gate)"))
                return
            _, sha, n = self._file(rel)
            items.append(ContextItem(rel, layer, "reference" if sha else "missing", sha, n, reason))

        def exclude(rel: str, layer: str, reason: str) -> None:
            if rel in seen:
                return
            seen.add(rel)
            items.append(ContextItem(rel, layer, "excluded", None, 0, reason))

        packet = self.packets.get(task.packet, {})
        own_role = task.context_entry or ""
        own_domain_dir = f"context/game/domains/{task.domain}/" if task.domain else None

        # 1. Global invariants
        add_inline(INVARIANTS, "global", "GlobalInvariantContext")
        # 2. Domain
        if own_domain_dir:
            add_inline(own_domain_dir + "DOMAIN.md", "domain", f"DomainContext for {task.domain}")
        # 3. Role
        if own_role:
            add_inline(own_role, "role", f"role card for owner {task.owner}")
        # 4. Task slice: brief + registry records for exactly this task's lego ids
        if task.brief_path:
            add_inline(task.brief_path, "task", f"packet {task.packet} brief")
        slice_obj = {
            "task_id": task.task_id, "packet": task.packet, "owner": task.owner, "mode": task.mode,
            "model_profile": task.model_profile, "depends_on": task.depends_on, "note_he": task.note,
            "write_scope": task.write_scope,
            "lego_items": [self.items[i] for i in task.lego_ids if i in self.items],
        }
        add_generated(f"registry:dispatch_tasks[{task.task_id}]", "registry",
                      json.dumps(slice_obj, ensure_ascii=False, indent=1),
                      "TaskSlice: dispatch record + registry items for assigned lego ids only")
        # 5. Dependency interfaces
        iface_names = sorted({n for i in task.lego_ids if i in self.items
                              for n in self.items[i].get("dependency_interfaces", [])})
        if iface_names or deps:
            add_inline(INTERFACES_INDEX, "dependency", "interface index (names are proposals, not APIs)")
        for d in deps:
            add_generated(f"handoff:{d.task_id}", "dependency", json.dumps({
                "task_id": d.task_id, "state": d.state, "integrated_commit": d.commit, "summary": d.summary,
                "artifacts": d.artifacts, "contracts": d.contracts, "changed_files": d.changed_files[:80],
            }, ensure_ascii=False, indent=1), "dependency handoff (interface/summary only, no implementation)")
        # 6. Evidence
        for ev in task.extra.get("evidence", []):
            add_inline(ev, "evidence", "EvidenceSlice from plan overlay")
        # Optional context selected from a trusted graph projection. Every fragment
        # carries its source/revision/hash inside the prompt and the manifest.
        for row in graph_context or []:
            payload = {"source_key": row["source_key"], "origin_kind": row["origin_kind"],
                       "origin_ref": row["origin_ref"], "graph_entity_id": row.get("graph_entity_id"),
                       "graph_revision": row.get("graph_revision"), "content_sha256": row["content_sha256"],
                       "title": row["title"], "excerpt": row["excerpt"]}
            add_generated("graph:" + row["source_key"], "evidence",
                          json.dumps(payload, ensure_ascii=False, indent=1),
                          "Jev-selected graph context with explicit provenance")
        # Packet read docs / context files: reference or excluded
        for rel in list(packet.get("context_files", [])) + list(packet.get("read", [])):
            if rel == INVARIANTS or rel == own_role or (own_domain_dir and rel == own_domain_dir + "DOMAIN.md"):
                continue
            if rel.startswith("context/game/domains/"):
                if "/roles/" in rel:
                    exclude(rel, "role", "another owner's role card in the same packet (separate TaskSlice)")
                else:
                    exclude(rel, "domain", "another domain listed by the packet; not this task's owner")
                continue
            add_ref(rel, "task", "packet background doc: open only relevant sections if needed")
        for rel in task.extra.get("reference_extra", []):
            add_ref(rel, "task", "overlay reference")
        # 7. Retry context
        retry_text = None
        if retry:
            retry_text = self._retry_text(retry)
            add_generated(f"retry:attempt-{retry.attempt_no}", "retry", retry_text,
                          "previous diff + test errors + previous handoff only")

        # Budget: shrink retry diff / demote evidence if over limit
        total = sum(len(t.encode()) for _, _, t in inline)
        if total > self.max_inline:
            for idx in range(len(inline) - 1, -1, -1):
                label, sha, text = inline[idx]
                it = next(i for i in items if i.path == label and i.mode == "inline")
                if it.layer in ("evidence", "dependency") and label != INTERFACES_INDEX:
                    it.mode, it.reason = "reference", it.reason + " (demoted: context budget)"
                    inline.pop(idx)
                    total = sum(len(t.encode()) for _, _, t in inline)
                    if total <= self.max_inline:
                        break

        prompt = render_prompt(task, packet, items, inline, deps, iface_names, retry is not None,
                               acceptance_commands or [])
        pb = prompt.encode()
        return ContextPack(task_id=task.task_id, items=items, prompt=prompt, prompt_sha256=sha256_bytes(pb),
                           total_bytes=len(pb))

    def _retry_text(self, r: RetryInfo) -> str:
        diff = r.previous_diff or ""
        if len(diff.encode()) > self.max_diff:
            diff = diff.encode()[: self.max_diff].decode("utf-8", "ignore") + "\n... [diff truncated]"
        tests = []
        for t in r.failed_tests:
            out = (t.get("output_tail") or "")[-self.max_test:]
            tests.append(f"- {t.get('name')} (exit {t.get('exit_code')}):\n{out}")
        return "\n".join([
            f"This is retry attempt {r.attempt_no}. The worktree already contains your previous changes.",
            f"Previous failure class: {r.failure_class or 'unknown'}",
            (f"Reviewer note: {r.reviewer_note}" if r.reviewer_note else ""),
            "## Failed acceptance checks", "\n".join(tests) or "(none recorded)",
            "## Previous handoff", json.dumps(r.previous_handoff, ensure_ascii=False, indent=1) if r.previous_handoff else "(none)",
            "## Previous diff (base..task branch)", diff or "(empty)",
        ])


def materialize(pack: ContextPack, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.md").write_text(pack.prompt, encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps(pack.manifest(), ensure_ascii=False, indent=1), encoding="utf-8")
    pack.prompt_path = str(out_dir / "prompt.md")
    return out_dir / "prompt.md"
