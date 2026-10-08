"""State-driven Deliver listener routing.

Every listener belongs to the Deliver that proposes it.  Deterministic selectors
produce a small candidate set; Jev Choice is the only authority that can turn a
listener proposal into an activation.  Errors, disabled Jev and no_match activate
nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from .jev import JevService
from .models import iso, utcnow

_ID = re.compile(r"^[A-Za-z0-9._:/@-]{1,200}$")
_EVENT = re.compile(r"^[A-Z][A-Z0-9_]{1,100}$")
_STATE_PATH = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _path(value: dict, dotted: str) -> Any:
    current: Any = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.lower()}
    if isinstance(value, list):
        return {str(v).lower() for v in value}
    return set()


def selector_matches(selector: dict, episode: dict, build: dict) -> bool:
    """Evaluate the small declarative selector language without model calls."""
    if not selector:
        return True
    if "any_of" in selector:
        options = selector["any_of"]
        if not isinstance(options, list) or not any(
                isinstance(option, dict) and selector_matches(option, episode, build) for option in options):
            return False
    if "all_of" in selector:
        options = selector["all_of"]
        if not isinstance(options, list) or not all(
                isinstance(option, dict) and selector_matches(option, episode, build) for option in options):
            return False
    if "episode_any_truthy" in selector:
        fields = selector["episode_any_truthy"]
        if not isinstance(fields, list) or not any(bool(_path(episode, str(field))) for field in fields):
            return False
    if "tags_any" in selector:
        wanted = {str(v).lower() for v in selector["tags_any"]}
        present = _values(episode.get("tags")) | _values(_path(episode, "context.tags"))
        if not wanted.intersection(present):
            return False
    if "episode_field_equals" in selector:
        fields = selector["episode_field_equals"]
        if not isinstance(fields, dict) or any(_path(episode, str(key)) != expected for key, expected in fields.items()):
            return False
    if "battle_any" in selector:
        wanted = {str(v).lower() for v in selector["battle_any"]}
        present = (_values(_path(episode, "battle.activities")) |
                   _values(_path(episode, "battle.capabilities")) |
                   _values(episode.get("battle_state")))
        if not wanted.intersection(present):
            return False
    if "build_status_in" in selector:
        status_map = selector["build_status_in"]
        if not isinstance(status_map, dict):
            return False
        actual = build.get("deliver_status", {})
        for deliver_id, allowed in status_map.items():
            if actual.get(deliver_id) not in allowed:
                return False
    known = {"any_of", "all_of", "episode_any_truthy", "tags_any", "episode_field_equals",
             "battle_any", "build_status_in"}
    return not (set(selector) - known)


def scan_episode_context(episode_state: dict) -> dict:
    """Cheap first pass: identify a possible snow signal without claiming snow."""
    tags = _values(episode_state.get("tags")) | _values(_path(episode_state, "context.tags"))
    temperature = _path(episode_state, "weather.temperature_c")
    winter_tag = bool(tags.intersection({"snow", "winter", "freezing", "blizzard"}))
    cold = isinstance(temperature, (int, float)) and not isinstance(temperature, bool) and temperature <= 2
    return {"possible_snow": winter_tag or cold,
            "snow_signal_basis": [x for x, present in (("episode_tag", winter_tag), ("temperature", cold)) if present]}


def compile_snow_state(research: dict) -> dict:
    """Normalize researched fields while retaining unknowns as null."""
    present = research.get("present")
    if present not in (True, False, None):
        raise ValueError("snow.present must be true, false or null")
    depth = research.get("depth_cm")
    if depth is not None and (isinstance(depth, bool) or not isinstance(depth, (int, float)) or depth < 0):
        raise ValueError("snow.depth_cm must be nonnegative or null")
    return {"present": present, "type": research.get("type"), "depth_cm": depth,
            "coverage_fraction": research.get("coverage_fraction"),
            "active_snowfall": research.get("active_snowfall"),
            "blowing_snow": research.get("blowing_snow"),
            "surface": research.get("surface"), "confidence": research.get("confidence"),
            "evidence_refs": list(research.get("evidence_refs") or []),
            "unknown_fields": [key for key in ("present", "type", "depth_cm", "surface") if research.get(key) is None]}


def validate_listener_manifest(manifest: Any, lego_ids: list[str]) -> list[str]:
    """Semantic validation beyond the provider's output JSON Schema."""
    if not isinstance(manifest, list):
        return ["listener_manifest must be a list"]
    problems: list[str] = []
    seen_legos: set[str] = set()
    seen_listeners: set[str] = set()
    for decision in manifest:
        if not isinstance(decision, dict):
            problems.append("listener_manifest item is not an object")
            continue
        lego_id = decision.get("lego_id")
        if lego_id in seen_legos:
            problems.append(f"duplicate listener decision for {lego_id}")
        if isinstance(lego_id, str):
            seen_legos.add(lego_id)
        proposals = decision.get("proposed_listeners")
        if not isinstance(proposals, list):
            problems.append(f"{lego_id}: proposed_listeners must be a list")
            continue
        if not proposals and not str(decision.get("no_listener_reason") or "").strip():
            problems.append(f"{lego_id}: empty proposals require no_listener_reason")
        for proposal in proposals:
            if not isinstance(proposal, dict):
                problems.append(f"{lego_id}: listener proposal is not an object")
                continue
            listener_id = proposal.get("listener_id")
            target = proposal.get("target_deliver_id")
            event_type = proposal.get("event_type")
            if not isinstance(listener_id, str) or not _ID.fullmatch(listener_id):
                problems.append(f"{lego_id}: invalid listener_id")
            elif listener_id in seen_listeners:
                problems.append(f"duplicate listener_id {listener_id}")
            else:
                seen_listeners.add(listener_id)
            if not isinstance(target, str) or not _ID.fullmatch(target):
                problems.append(f"{lego_id}: invalid target_deliver_id")
            if not isinstance(event_type, str) or not _EVENT.fullmatch(event_type):
                problems.append(f"{lego_id}: invalid event_type")
            if not str(proposal.get("reason") or "").strip():
                problems.append(f"{lego_id}: listener reason is required")
            for key in ("episode_truthy_any", "tags_any", "battle_any"):
                values = proposal.get(key)
                if not isinstance(values, list) or any(not isinstance(v, str) or not _STATE_PATH.fullmatch(v)
                                                       for v in values):
                    problems.append(f"{lego_id}: invalid {key}")
            for condition in proposal.get("episode_equals") or []:
                if not isinstance(condition, dict) or not isinstance(condition.get("path"), str) \
                        or not _STATE_PATH.fullmatch(condition["path"]):
                    problems.append(f"{lego_id}: invalid episode_equals path")
            for condition in proposal.get("build_status") or []:
                if not isinstance(condition, dict) or not isinstance(condition.get("deliver_id"), str) \
                        or not _ID.fullmatch(condition["deliver_id"]) or not condition.get("statuses"):
                    problems.append(f"{lego_id}: invalid build_status condition")
    assigned = set(lego_ids)
    if seen_legos != assigned:
        missing, extra = sorted(assigned - seen_legos), sorted(seen_legos - assigned)
        if missing:
            problems.append("listener_manifest missing lego ids: " + ", ".join(missing))
        if extra:
            problems.append("listener_manifest contains unassigned lego ids: " + ", ".join(extra))
    return problems


def register_listener_manifest(db, source_deliver_id: str, manifest: list[dict], *, source_ref: str,
                               enabled: bool = False) -> dict:
    """Persist validated model proposals; unknown targets are inert placeholders."""
    now = iso(utcnow())
    registered, placeholders, conflicts = 0, 0, []
    proposed_ids = [proposal["listener_id"] for decision in manifest
                    for proposal in decision.get("proposed_listeners", [])]
    with db.tx():
        db.conn.execute("UPDATE deliver_listener_edges SET enabled=0,updated_at=? "
                        "WHERE source_deliver_id=? AND source_kind='model_listener_manifest'",
                        (now, source_deliver_id))
        for decision in manifest:
            for proposal in decision.get("proposed_listeners", []):
                old = db.one("SELECT source_deliver_id FROM deliver_listener_edges WHERE listener_id=?",
                             (proposal["listener_id"],))
                if old and old["source_deliver_id"] != source_deliver_id:
                    conflicts.append(proposal["listener_id"])
                    continue
                target = proposal["target_deliver_id"]
                if not db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=?", (target,)):
                    db.conn.execute(
                        "INSERT INTO deliver_catalog(deliver_id,description,source_kind,source_ref,execution_kind,definition_hash,enabled,availability,updated_at) VALUES(?,?,?,?,?,?,0,'proposed',?)",
                        (target, "Placeholder proposed by " + source_deliver_id, "model_listener_manifest", source_ref,
                         "unknown", hashlib.sha256(target.encode()).hexdigest()[:16], now))
                    placeholders += 1
                selector: dict[str, Any] = {}
                if proposal["episode_truthy_any"]:
                    selector["episode_any_truthy"] = proposal["episode_truthy_any"]
                if proposal["tags_any"]:
                    selector["tags_any"] = proposal["tags_any"]
                if proposal["battle_any"]:
                    selector["battle_any"] = proposal["battle_any"]
                if proposal["episode_equals"]:
                    selector["episode_field_equals"] = {item["path"]: item["value"]
                                                         for item in proposal["episode_equals"]}
                if proposal["build_status"]:
                    selector["build_status_in"] = {item["deliver_id"]: item["statuses"]
                                                    for item in proposal["build_status"]}
                db.conn.execute(
                    "INSERT INTO deliver_listener_edges(listener_id,source_deliver_id,target_deliver_id,event_type,context_selector,source_kind,edge_type,jev_gate,enabled,proposal_reason,source_lego_id,updated_at) "
                    "VALUES(?,?,?,?,?,'model_listener_manifest','listener',1,?,?,?,?) ON CONFLICT(listener_id) DO UPDATE SET target_deliver_id=excluded.target_deliver_id,event_type=excluded.event_type,context_selector=excluded.context_selector,jev_gate=1,enabled=excluded.enabled,proposal_reason=excluded.proposal_reason,source_lego_id=excluded.source_lego_id,updated_at=excluded.updated_at",
                    (proposal["listener_id"], source_deliver_id, target, proposal["event_type"],
                     _canonical(selector), int(enabled), proposal["reason"], decision["lego_id"], now))
                registered += 1
    db.event("LISTENER_MANIFEST_REGISTERED", task_id=source_deliver_id, registered=registered, enabled=enabled,
             placeholders=placeholders, conflicts=conflicts, listener_ids=proposed_ids)
    return {"registered": registered, "placeholders": placeholders, "conflicts": conflicts}


@dataclass(frozen=True)
class ListenerRoutingResult:
    event_id: str
    state_version: int
    candidate_listener_ids: list[str]
    activation_ids: list[str]
    status: str


class ListenerEngine:
    def __init__(self, cfg, db, jev: JevService | None = None):
        self.cfg, self.db = cfg, db
        self.jev = jev or JevService(cfg, db)

    def state(self, episode_id: str) -> dict | None:
        row = self.db.one("SELECT * FROM episode_build_states WHERE episode_id=?", (episode_id,))
        if not row:
            return None
        return {"episode_id": row["episode_id"], "version": row["version"], "objective": row["objective"],
                "phase": row["phase"], "episode": json.loads(row["episode_state_json"]),
                "build": json.loads(row["build_state_json"]),
                "context_refs": json.loads(row["context_refs_json"]),
                "updated_by_deliver_id": row["updated_by_deliver_id"], "updated_at": row["updated_at"]}

    def emit(self, *, episode_id: str, source_deliver_id: str, event_type: str,
             episode_patch: dict | None = None, build_patch: dict | None = None,
             result: dict | None = None, context_refs: list[str] | None = None,
             objective: str | None = None, phase: str | None = None) -> ListenerRoutingResult:
        if not self.db.one("SELECT 1 FROM deliver_catalog WHERE deliver_id=? AND enabled=1", (source_deliver_id,)):
            raise ValueError(f"unknown or disabled source Deliver {source_deliver_id}")
        now = iso(utcnow())
        event_id = "event:" + str(uuid.uuid4())
        with self.db.tx():
            row = self.db.one("SELECT * FROM episode_build_states WHERE episode_id=?", (episode_id,))
            old_episode = json.loads(row["episode_state_json"]) if row else {}
            old_build = json.loads(row["build_state_json"]) if row else {}
            old_refs = json.loads(row["context_refs_json"]) if row else []
            new_episode = _merge(old_episode, episode_patch or {})
            new_build = _merge(old_build, build_patch or {})
            new_refs = list(dict.fromkeys(old_refs + list(context_refs or [])))[:200]
            version = (int(row["version"]) if row else 0) + 1
            self.db.conn.execute(
                "INSERT INTO episode_build_states(episode_id,version,objective,phase,episode_state_json,build_state_json,context_refs_json,updated_by_deliver_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(episode_id) DO UPDATE SET version=excluded.version,objective=excluded.objective,phase=excluded.phase,episode_state_json=excluded.episode_state_json,build_state_json=excluded.build_state_json,context_refs_json=excluded.context_refs_json,updated_by_deliver_id=excluded.updated_by_deliver_id,updated_at=excluded.updated_at",
                (episode_id, version, objective if objective is not None else (row["objective"] if row else ""),
                 phase if phase is not None else (row["phase"] if row else "DISCOVERY"),
                 _canonical(new_episode), _canonical(new_build), _canonical(new_refs), source_deliver_id,
                 row["created_at"] if row else now, now))
            self.db.conn.execute(
                "INSERT INTO deliver_state_events(event_id,episode_id,source_deliver_id,event_type,state_version,result_json,context_refs_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id, episode_id, source_deliver_id, event_type, version, _canonical(result or {}),
                 _canonical(new_refs), "ROUTING", now))

        rows = self.db.q(
            "SELECT e.*,c.description,c.execution_kind,c.availability FROM deliver_listener_edges e "
            "JOIN deliver_catalog c ON c.deliver_id=e.target_deliver_id "
            "WHERE e.source_deliver_id=? AND e.event_type=? AND e.edge_type='listener' AND e.jev_gate=1 "
            "AND e.enabled=1 AND c.enabled=1 ORDER BY e.listener_id",
            (source_deliver_id, event_type))
        candidates: list[dict] = []
        for row in rows:
            try:
                selector = json.loads(row["context_selector"] or "{}")
            except ValueError:
                continue
            if selector_matches(selector, new_episode, new_build):
                candidates.append({"id": row["listener_id"], "target_deliver_id": row["target_deliver_id"],
                                   "description": f"{row['target_deliver_id']}: {row['description']}",
                                   "execution_kind": row["execution_kind"],
                                   "proposal_reason": row["proposal_reason"], "availability": row["availability"]})

        max_selected = max(1, min(int(self.cfg.section("jev").get("max_listener_activations_per_event", 2)), 8))
        remaining = list(candidates)
        selected_listeners: list[str] = []
        activation_ids: list[str] = []
        for _ in range(min(max_selected, len(remaining))):
            decision = self.jev.choose_listener(
                episode_id=episode_id, source_deliver_id=source_deliver_id, event_type=event_type,
                episode_state=new_episode, build_state=new_build, context_refs=new_refs,
                candidates=remaining, already_selected=selected_listeners)
            if not decision.selected_id:
                break
            chosen = next((candidate for candidate in remaining if candidate["id"] == decision.selected_id), None)
            if not chosen or not decision.request_id:
                break
            activation_id = "activation:" + str(uuid.uuid4())
            self.db.x(
                "INSERT INTO listener_activations(activation_id,event_id,listener_id,source_deliver_id,target_deliver_id,jev_request_id,selected_state_version,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (activation_id, event_id, chosen["id"], source_deliver_id, chosen["target_deliver_id"],
                 decision.request_id, version, "SELECTED", iso(utcnow())))
            selected_listeners.append(chosen["id"])
            activation_ids.append(activation_id)
            remaining = [candidate for candidate in remaining if candidate["id"] != chosen["id"]]

        status = "SELECTED" if activation_ids else "NO_ACTIVATION"
        self.db.x("UPDATE deliver_state_events SET status=?,completed_at=? WHERE event_id=?",
                  (status, iso(utcnow()), event_id))
        if activation_ids:
            state = self.state(episode_id) or {}
            routing = dict((state.get("build") or {}).get("routing") or {})
            prior = list(routing.get("selected_listeners") or [])
            routing["selected_listeners"] = (prior + [{"event_id": event_id, "listener_id": lid}
                                                        for lid in selected_listeners])[-100:]
            build = _merge(state.get("build") or {}, {"routing": routing})
            self.db.x("UPDATE episode_build_states SET version=version+1,build_state_json=?,updated_at=? WHERE episode_id=?",
                      (_canonical(build), iso(utcnow()), episode_id))
        self.db.event("DELIVER_LISTENERS_ROUTED", provider="jev", episode_id=episode_id,
                      source_deliver_id=source_deliver_id, event_type=event_type,
                      candidate_listener_ids=[c["id"] for c in candidates], selected_listener_ids=selected_listeners,
                      state_version=version, status=status)
        return ListenerRoutingResult(event_id, version, [c["id"] for c in candidates], activation_ids, status)
