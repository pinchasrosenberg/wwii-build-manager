"""Trusted TypeSafe/Jev integration for the build manager.

Jev receives a closed candidate set after deterministic eligibility checks. It
cannot create Deliver IDs, activate tasks, alter prices, read credentials, or
write application state. The API key exists only inside the default transport.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from .credentials import CredentialError, TypeSafeCredentialStore
from .models import iso, utcnow

API_URL = "https://api.typesafe.ai/v1/systemone"
DOCS = {
    "index": "https://docs.typesafe.ai/llms.txt",
    "api": "https://docs.typesafe.ai/api",
    "choice": "https://docs.typesafe.ai/primitives/choice",
    "responses": "https://docs.typesafe.ai/sdk/python/api/types/responses",
    "models": "https://docs.typesafe.ai/models",
}
NO_MATCH = "__no_match__"
SAFE_ID = re.compile(r"^[A-Za-z0-9._:/@-]{1,200}$")


class JevError(RuntimeError):
    def __init__(self, kind: str, status: int | None = None, *, uncertain: bool = False):
        self.kind, self.status, self.uncertain = kind, status, uncertain
        super().__init__(f"Jev request failed ({kind})")

    def __repr__(self) -> str:
        return f"JevError(kind={self.kind!r}, status={self.status!r}, uncertain={self.uncertain!r})"


@dataclass(frozen=True)
class ChoiceReply:
    choice: str
    probabilities: dict[str, float]
    confidence: float
    model: str | None
    usage: dict[str, int | None]
    request_id: str | None = None


@dataclass(frozen=True)
class RouteDecision:
    request_id: str | None
    selected_id: str | None
    status: str
    error_kind: str | None = None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _compact(value: Any, depth: int = 0) -> Any:
    """Bound user/graph state before it can enter a paid routing request."""
    if depth > 6:
        return "[depth limit]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:600]
    if isinstance(value, dict):
        return {str(k)[:80]: _compact(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_compact(v, depth + 1) for v in list(value)[:40]]
    return str(value)[:200]


def _safe_payload(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise JevError("invalid_request")
    if isinstance(value, dict):
        for key, child in value.items():
            low = str(key).lower().replace("-", "_")
            if low in {"authorization", "api_key", "apikey", "token", "secret", "password"}:
                raise JevError("invalid_request")
            _safe_payload(child, depth + 1)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _safe_payload(child, depth + 1)
    elif isinstance(value, str) and ("bearer " in value.lower() or "typesafe_api_key" in value.lower()):
        raise JevError("invalid_request")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


class JevClient:
    def __init__(self, timeout_seconds: float = 8.0,
                 transport: Callable[[dict, float], dict] | None = None,
                 credential_store: TypeSafeCredentialStore | None = None):
        if not 0.1 <= float(timeout_seconds) <= 60:
            raise ValueError("timeout_seconds must be 0.1..60")
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport
        self.credentials = credential_store or TypeSafeCredentialStore()

    @staticmethod
    def _map_sdk_error(exc: Exception) -> JevError:
        try:
            from typesafe_sdk import (TypeSafeAPIConnectionError, TypeSafeAPIError,
                                      TypeSafeAPIResponseValidationError, TypeSafeAPITimeoutError,
                                      TypeSafeAuthenticationError, TypeSafeRateLimitError)
        except ImportError:
            return JevError("sdk_missing")
        status = getattr(exc, "status", None)
        if isinstance(exc, TypeSafeAuthenticationError) or status in (401, 403):
            return JevError("authentication", status)
        if isinstance(exc, TypeSafeRateLimitError) or status == 429:
            return JevError("rate_limit", status)
        if status == 402:
            return JevError("no_credits", status)
        if isinstance(exc, TypeSafeAPIResponseValidationError):
            return JevError("unexpected_schema", status)
        if isinstance(exc, (TypeSafeAPIConnectionError, TypeSafeAPITimeoutError)):
            return JevError("api_unreachable", status, uncertain=True)
        if isinstance(exc, TypeSafeAPIError):
            return JevError("upstream" if status and status >= 500 else "invalid_request",
                            status, uncertain=bool(status and status >= 500))
        return JevError("api_unreachable", uncertain=True)

    def _sdk_client(self, model: str):
        try:
            from typesafe_sdk import TypeSafeClient
        except ImportError:
            raise JevError("sdk_missing") from None
        try:
            key = self.credentials.get()
        except CredentialError:
            raise JevError("missing_credential") from None
        if not key:
            raise JevError("missing_credential")
        return TypeSafeClient(api_key=key, model=model, timeout=self.timeout_seconds)

    def list_models(self, model: str = "jev-latest") -> list[dict[str, str]]:
        client = self._sdk_client(model)
        try:
            response = client.models.list()
            return [{"name": item.name, "description": item.description,
                     "release_date": item.release_date} for item in response.models]
        except Exception as exc:
            raise self._map_sdk_error(exc) from None
        finally:
            client.close()

    def choice(self, *, state: dict, criteria: dict[str, Any], model: str = "jev-latest",
               instructions: str = "Which candidate is the most appropriate next handler for the current state?") -> ChoiceReply:
        if not isinstance(state, dict) or not 2 <= len(criteria) <= 255:
            raise JevError("invalid_request")
        if not isinstance(model, str) or not SAFE_ID.fullmatch(model):
            raise JevError("invalid_request")
        if any(not isinstance(k, str) or not SAFE_ID.fullmatch(k) for k in criteria):
            raise JevError("invalid_request")
        body = {"state": state, "model": model, "questions": {"route": {
            "type": "choice", "instructions": instructions, "criteria": criteria}}}
        _safe_payload(body)
        try:
            if self.transport:
                raw = self.transport(body, self.timeout_seconds)
            else:
                from typesafe_sdk import Choice
                client = self._sdk_client(model)
                try:
                    response = client.system_one(
                        state=state,
                        questions={"route": Choice(instructions=instructions, criteria=criteria)},
                        model=model,
                    )
                    answer_obj = response.answers["route"]
                    raw = {"answers": {"route": answer_obj.model_dump()},
                           "usage": response.usage.model_dump(), "model": response.model,
                           "request_id": getattr(response, "request_id", None)}
                finally:
                    client.close()
        except JevError:
            raise
        except ImportError:
            raise JevError("sdk_missing") from None
        except Exception as exc:
            raise self._map_sdk_error(exc) from None
        try:
            answer = raw["answers"]["route"]
            if answer["type"] != "choice" or answer["choice"] not in criteria:
                raise ValueError
            probs = answer["probabilities"]
            if set(probs) != set(criteria):
                raise ValueError
            clean: dict[str, float] = {}
            for key, value in probs.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError
                clean[key] = float(value)
            if not math.isclose(sum(clean.values()), 1.0, abs_tol=0.02):
                raise ValueError
            conf = answer["confidence"]
            if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf) or not 0 <= conf <= 1:
                raise ValueError
            usage = raw.get("usage") or {}
            cleaned_usage: dict[str, int | None] = {}
            for key in ("input_tokens", "output_tokens"):
                val = usage.get(key)
                if val is not None and (type(val) is not int or val < 0):
                    raise ValueError
                cleaned_usage[key] = val
            returned_model = raw.get("model")
            if returned_model is not None and (not isinstance(returned_model, str) or not returned_model.startswith("jev-")):
                raise ValueError
            rid = raw.get("request_id") or raw.get("id")
            if rid is not None and (not isinstance(rid, str) or not SAFE_ID.fullmatch(rid)):
                rid = None
            return ChoiceReply(answer["choice"], clean, float(conf), returned_model, cleaned_usage, rid)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise JevError("unexpected_schema") from None


class JevKnowledgeAgent:
    """Documentation fetch/cache tooling; no LLM is kept alive."""
    def __init__(self, cache_dir: Path, ttl_seconds: float = 86400,
                 fetcher: Callable[[str], str] | None = None, clock: Callable[[], float] = time.time):
        self.cache_dir, self.ttl, self.fetcher, self.clock = Path(cache_dir), float(ttl_seconds), fetcher, clock
        if self.ttl < 0:
            raise ValueError("ttl_seconds must be nonnegative")

    def _path(self, topic: str) -> Path:
        if topic not in DOCS:
            raise ValueError("unknown documentation topic")
        return self.cache_dir / (topic + ".json")

    def _read(self, topic: str) -> dict | None:
        p = self._path(topic)
        try:
            row = json.loads(p.read_text())
            if row.get("url") != DOCS[topic] or hashlib.sha256(row["content"].encode()).hexdigest() != row["sha256"]:
                return None
            return row
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _fetch(self, url: str) -> str:
        if self.fetcher:
            return self.fetcher(url)
        req = urllib.request.Request(url, headers={"Accept": "text/plain,text/markdown,text/html"})
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=10) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("document too large")
            return raw.decode("utf-8")

    def get(self, topic: str, force_refresh: bool = False) -> dict:
        cached = self._read(topic)
        now = self.clock()
        if cached and not force_refresh and now - float(cached["fetched_at"]) <= self.ttl:
            return {**cached, "freshness": "fresh_cache", "cached": True}
        try:
            content = self._fetch(DOCS[topic])
            if not isinstance(content, str) or not content.strip():
                raise ValueError
            row = {"topic": topic, "url": DOCS[topic], "fetched_at": now,
                   "sha256": hashlib.sha256(content.encode()).hexdigest(), "content": content}
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path(topic).with_suffix(".tmp")
            tmp.write_text(json.dumps(row, ensure_ascii=False))
            tmp.replace(self._path(topic))
            return {**row, "freshness": "fresh_network", "cached": False}
        except Exception:
            if cached:
                return {**cached, "freshness": "stale_cache", "cached": True, "error": "refresh_failed"}
            return {"topic": topic, "url": DOCS[topic], "freshness": "unavailable", "cached": False,
                    "error": "refresh_failed"}

    def status(self) -> dict:
        topics = {}
        for topic in DOCS:
            row = self._read(topic)
            topics[topic] = ({"url": DOCS[topic], "cached": False} if not row else
                             {"url": row["url"], "cached": True, "fetched_at": row["fetched_at"],
                              "sha256": row["sha256"], "stale": self.clock() - row["fetched_at"] > self.ttl})
        return {"topics": topics, "ttl_seconds": self.ttl}

    def refresh(self, topics=("index", "api", "choice", "responses", "models"), force: bool = False) -> dict:
        return {topic: {k: v for k, v in self.get(topic, force_refresh=force).items() if k != "content"}
                for topic in topics}


@dataclass(frozen=True)
class UsageConfig:
    initial_budget: float | None = None
    unit: str = "tokens"
    input_rate_per_million: float | None = None
    output_rate_per_million: float | None = None
    warning_fraction: float = 0.25
    critical_fraction: float = 0.10
    warning_absolute: float | None = None
    critical_absolute: float | None = None

    def validate(self) -> None:
        for value in (self.initial_budget, self.input_rate_per_million, self.output_rate_per_million,
                      self.warning_absolute, self.critical_absolute):
            if value is not None and (isinstance(value, bool) or not math.isfinite(value) or value < 0):
                raise ValueError("usage configuration values must be finite and nonnegative")
        if not 0 <= self.critical_fraction <= self.warning_fraction <= 1:
            raise ValueError("usage fractions must satisfy 0 <= critical <= warning <= 1")


class JevUsageMonitor:
    def __init__(self, db, config: UsageConfig, notifier=None):
        config.validate()
        self.db, self.config, self.notifier = db, config, notifier

    def _amount(self, usage: dict | None) -> float | None:
        if not usage or usage.get("input_tokens") is None or usage.get("output_tokens") is None:
            return None
        inp, out = usage["input_tokens"], usage["output_tokens"]
        if type(inp) is not int or type(out) is not int or inp < 0 or out < 0:
            return None
        if self.config.unit == "tokens":
            return float(inp + out)
        if self.config.input_rate_per_million is None or self.config.output_rate_per_million is None:
            return None
        return inp * self.config.input_rate_per_million / 1_000_000 + out * self.config.output_rate_per_million / 1_000_000

    def snapshot(self) -> dict:
        rows = self.db.q("SELECT input_tokens,output_tokens,estimated_cost,unit,uncertain FROM jev_usage_requests")
        unknown = any(r["uncertain"] or r["input_tokens"] is None or r["output_tokens"] is None for r in rows)
        consumed = sum(float(r["estimated_cost"] if self.config.unit != "tokens" else
                             (r["input_tokens"] + r["output_tokens"])) for r in rows
                       if not r["uncertain"] and r["input_tokens"] is not None and r["output_tokens"] is not None
                       and (self.config.unit == "tokens" or r["estimated_cost"] is not None))
        budget = self.config.initial_budget
        remaining = None if budget is None else max(0.0, budget - consumed)
        fraction = None if budget in (None, 0) else remaining / budget
        state = "UNKNOWN" if budget is None or unknown else "EXHAUSTED" if remaining <= 0 else "CRITICAL" if (
            remaining <= (self.config.critical_absolute if self.config.critical_absolute is not None else budget * self.config.critical_fraction)
        ) else "WARNING" if remaining <= (
            self.config.warning_absolute if self.config.warning_absolute is not None else budget * self.config.warning_fraction
        ) else "HEALTHY"
        return {"state": state, "basis": "LOCAL_ESTIMATE", "unit": self.config.unit,
                "consumed": consumed, "remaining": remaining, "remaining_fraction": fraction,
                "projected_requests_remaining": None, "official_balance_available": False}

    def record(self, request_id: str, usage: dict | None, *, uncertain: bool = False) -> dict:
        amount = self._amount(usage)
        inp = usage.get("input_tokens") if usage else None
        out = usage.get("output_tokens") if usage else None
        before = self.snapshot()["state"]
        self.db.x("INSERT OR IGNORE INTO jev_usage_requests(request_id,created_at,input_tokens,output_tokens,estimated_cost,unit,uncertain) VALUES(?,?,?,?,?,?,?)",
                  (request_id, iso(utcnow()), inp, out, amount if self.config.unit != "tokens" else None,
                   self.config.unit, int(uncertain or amount is None)))
        snap = self.snapshot()
        self.db.x("INSERT INTO jev_usage_state(singleton,state,basis,unit,consumed,remaining,remaining_fraction,updated_at) VALUES(1,?,?,?,?,?,?,?) "
                  "ON CONFLICT(singleton) DO UPDATE SET state=excluded.state,basis=excluded.basis,unit=excluded.unit,consumed=excluded.consumed,remaining=excluded.remaining,remaining_fraction=excluded.remaining_fraction,updated_at=excluded.updated_at",
                  (snap["state"], snap["basis"], snap["unit"], snap["consumed"], snap["remaining"], snap["remaining_fraction"], iso(utcnow())))
        if before != snap["state"]:
            event = "JEV_USAGE_" + snap["state"]
            self.db.x("INSERT INTO jev_usage_events(created_at,previous_state,state,event_type,detail_json) VALUES(?,?,?,?,?)",
                      (iso(utcnow()), before, snap["state"], event, _canonical(snap)))
            self.db.event(event, provider="jev", previous=before, **snap)
            if self.notifier and snap["state"] in {"WARNING", "CRITICAL", "EXHAUSTED", "UNKNOWN"}:
                try:
                    self.notifier.notify("jev:" + snap["state"], "Jev usage", snap["state"])
                except Exception:
                    pass
        return snap


class JevService:
    def __init__(self, cfg, db, notifier=None, client: JevClient | None = None,
                 credential_store: TypeSafeCredentialStore | None = None):
        self.cfg, self.db, self.notifier = cfg, db, notifier
        jc = cfg.section("jev")
        self.enabled = bool(jc.get("enabled", True))
        self.model = str(jc.get("model", "jev-latest"))
        self.credentials = credential_store or TypeSafeCredentialStore()
        self.client = client or JevClient(float(jc.get("timeout_seconds", 8)),
                                          credential_store=self.credentials)
        self.knowledge = JevKnowledgeAgent(cfg.state_dir / "jev" / "docs", float(jc.get("docs_ttl_hours", 24)) * 3600)
        self.usage = JevUsageMonitor(db, UsageConfig(
            initial_budget=jc.get("local_budget"), unit=str(jc.get("budget_unit", "tokens")),
            input_rate_per_million=jc.get("input_rate_per_million"),
            output_rate_per_million=jc.get("output_rate_per_million"),
            warning_fraction=float(jc.get("warning_fraction", .25)),
            critical_fraction=float(jc.get("critical_fraction", .10))), notifier)

    def _decision(self, route_kind: str, state: dict, candidates: list[dict], fallback_id: str | None,
                  task_id: str | None = None, *, require_explicit: bool = False,
                  instructions: str | None = None) -> RouteDecision:
        if not candidates:
            return RouteDecision(None, None if require_explicit else fallback_id, "NO_CANDIDATES")
        bounded = candidates[:254]
        aliases = {f"c{i:03}": c["id"] for i, c in enumerate(bounded)}
        criteria = {alias: {"deliver_id": cid, "description": str(bounded[i].get("description", ""))[:500],
                            "execution_kind": str(bounded[i].get("execution_kind", "unknown"))[:40],
                            "proposal_reason": str(bounded[i].get("proposal_reason", ""))[:400]}
                    for i, (alias, cid) in enumerate(aliases.items())}
        criteria[NO_MATCH] = "None of the listed candidates is an appropriate next handler."
        safe_state = _compact({"objective": str(state.get("objective", ""))[:1000],
                               "workflow": state.get("workflow", {}),
                               "episode": state.get("episode", {}),
                               "build": state.get("build", {}),
                               "context_refs": state.get("context_refs", [])[:50]})
        request_id = "jev:" + str(uuid.uuid4())
        preview = {"sent_to_jev": self.enabled, "state": safe_state, "question": "route", "criteria": criteria}
        if not self.enabled:
            selected = None if require_explicit else fallback_id
            status = "JEV_DISABLED_NO_ACTIVATION" if require_explicit else "DETERMINISTIC_FALLBACK"
            self.db.x("INSERT INTO jev_route_decisions(request_id,created_at,route_kind,task_id,state_fingerprint,candidates_json,selected_id,latency_ms,status,fallback_id,source_refs_json,request_preview_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (request_id, iso(utcnow()), route_kind, task_id, _fingerprint(safe_state),
                       _canonical([c["id"] for c in bounded]), selected, 0, status, fallback_id,
                       _canonical(safe_state.get("context_refs", [])), _canonical(preview)))
            self.db.event("JEV_ROUTE_DECISION", task_id=task_id, provider="jev", route_kind=route_kind,
                          selected=selected, fallback=fallback_id, status=status)
            return RouteDecision(request_id, selected, status)
        started = time.monotonic()
        status, error = "SUCCESS", None
        selected = None if require_explicit else fallback_id
        reply = None
        try:
            reply = self.client.choice(state=safe_state, criteria=criteria, model=self.model,
                                       instructions=instructions or "Which candidate is the most appropriate next handler for the current state?")
            picked = aliases.get(reply.choice)
            if picked in {c["id"] for c in bounded}:
                selected = picked
            elif reply.choice != NO_MATCH:
                raise JevError("unexpected_schema")
            elif reply.choice == NO_MATCH:
                status = "NO_MATCH" if require_explicit else "NO_MATCH_FALLBACK"
        except JevError as exc:
            status, error = ("ERROR_NO_ACTIVATION" if require_explicit else "FALLBACK"), exc.kind
        latency = int((time.monotonic() - started) * 1000)
        probs = ({aliases.get(k, k): v for k, v in reply.probabilities.items()} if reply else None)
        usage = reply.usage if reply else None
        self.db.x("INSERT INTO jev_route_decisions(request_id,created_at,route_kind,task_id,state_fingerprint,candidates_json,selected_id,probabilities_json,confidence,model,input_tokens,output_tokens,latency_ms,status,error_kind,fallback_id,source_refs_json,request_preview_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (request_id, iso(utcnow()), route_kind, task_id, _fingerprint(safe_state),
                   _canonical([c["id"] for c in bounded]), selected, _canonical(probs) if probs else None,
                   reply.confidence if reply else None, reply.model if reply else None,
                   usage.get("input_tokens") if usage else None, usage.get("output_tokens") if usage else None,
                   latency, status, error, fallback_id, _canonical(safe_state["context_refs"]), _canonical(preview)))
        self.usage.record(request_id, usage, uncertain=bool(error == "timeout_network"))
        self.db.event("JEV_ROUTE_DECISION", task_id=task_id, provider="jev", route_kind=route_kind,
                      selected=selected, fallback=fallback_id, status=status, error_kind=error)
        return RouteDecision(request_id, selected, status, error)

    def order_delivers(self, candidates: list[dict], objective: str = "") -> list[str]:
        if not candidates:
            return []
        fallback = candidates[0]["id"]
        decision = self._decision("deliver", {"objective": objective,
            "workflow": {"ready_count": len(candidates), "selection_scope": "deterministically_eligible_only"}},
            candidates, fallback)
        selected = decision.selected_id or fallback
        return [selected] + [c["id"] for c in candidates if c["id"] != selected]

    def choose_context(self, task_id: str, candidates: list[dict], objective: str) -> str | None:
        if not candidates:
            return None
        return self._decision("context", {"objective": objective,
            "workflow": {"task_id": task_id, "selection_scope": "registered_context_only"},
            "context_refs": [c["id"] for c in candidates]}, candidates, None, task_id,
            require_explicit=True,
            instructions="Select this context only if it is needed for the stated LLM task; otherwise choose __no_match__.").selected_id

    def select_context_bundles(self, task_id: str, candidates: list[dict], objective: str) -> list[str]:
        """Select a bounded set of context bundles; never fall back around Jev."""
        bounded = list(candidates)[:254]
        required = [candidate for candidate in bounded if candidate.get("required_for_execution")]
        remaining = [candidate for candidate in bounded if not candidate.get("required_for_execution")]
        selected: list[str] = []
        limit = max(1, min(int(self.cfg.section("jev").get("max_context_bundles_per_run", 4)), 12))
        # Required means the worker cannot execute coherently without the bundle;
        # it still needs an explicit Jev yes/no decision and has no fallback.
        for candidate in required:
            decision = self._decision(
                "llm_context",
                {"objective": objective,
                 "workflow": {"task_id": task_id, "selection_scope": "required_context_gate"},
                 "context_refs": [candidate["id"]]},
                [candidate], None, task_id, require_explicit=True,
                instructions=("Select this required execution-context bundle only if it is appropriate for the "
                              "stated LLM task. Otherwise choose __no_match__ and the task will not run."))
            if decision.selected_id:
                selected.append(decision.selected_id)
            else:
                return selected
        optional_limit = max(0, limit - len(selected))
        for _ in range(min(optional_limit, len(remaining))):
            decision = self._decision(
                "llm_context",
                {"objective": objective,
                 "workflow": {"task_id": task_id, "selection_scope": "all_llm_context",
                              "already_selected": selected},
                 "context_refs": [candidate["id"] for candidate in remaining]},
                remaining, None, task_id, require_explicit=True,
                instructions=("Select one context bundle that should be provided to this LLM task. "
                              "Choose __no_match__ when no remaining bundle is needed."))
            if not decision.selected_id:
                break
            selected.append(decision.selected_id)
            remaining = [candidate for candidate in remaining if candidate["id"] != decision.selected_id]
        return selected

    def choose_listener(self, *, episode_id: str, source_deliver_id: str, event_type: str,
                        episode_state: dict, build_state: dict, context_refs: list[str],
                        candidates: list[dict], already_selected: list[str] | None = None) -> RouteDecision:
        """Require an explicit Jev Choice before any proposed listener activates.

        Disabled Jev, errors and ``no_match`` all produce no activation.  There is
        deliberately no deterministic fallback for listener routing.
        """
        return self._decision(
            "listener",
            {"objective": f"Choose the next useful listener for episode {episode_id}",
             "workflow": {"episode_id": episode_id, "source_deliver_id": source_deliver_id,
                          "event_type": event_type, "selection_scope": "deliver_proposals_after_deterministic_filter",
                          "already_selected": already_selected or []},
             "episode": episode_state, "build": build_state, "context_refs": context_refs},
            candidates, None, require_explicit=True,
            instructions=("Select one proposed listener that should run next given what is known about the episode "
                          "and the current build state. Choose __no_match__ when none adds useful work now."))

    def status(self) -> dict:
        last = self.db.one("SELECT * FROM jev_route_decisions ORDER BY id DESC LIMIT 1")
        health = self.db.one("SELECT * FROM jev_health_checks ORDER BY id DESC LIMIT 1")
        required = bool(self.cfg.section("jev").get("require_for_all_llm_context", True))
        try:
            source = self.credentials.source()
        except CredentialError:
            source = None
        health_status = health["status"] if health else ("NOT_CHECKED" if source else "MISSING_CREDENTIAL")
        return {"enabled": self.enabled, "status": health_status,
                "credential_present": bool(source), "credential_source": source,
                "api": ("reachable" if health and health["api_reachable"] else "not_checked"),
                "authentication": ("OK" if health and health["authentication_ok"] else "not_checked"),
                "model": (health["model_resolved"] if health else self.model),
                "last_health_check": (health["checked_at"] if health else None),
                "docs_cache": self.knowledge.status(),
                "routing": ("READY" if health_status == "READY" else health_status),
                "all_llm_context_requires_jev": required,
                "usage": self.usage.snapshot(), "last_success": last["created_at"] if last and last["status"] == "SUCCESS" else None,
                "fallback": {"deliver_order": "available", "llm_context": "forbidden", "listeners": "forbidden"}}

    @staticmethod
    def _health_status(error_kind: str) -> str:
        return {"missing_credential": "MISSING_CREDENTIAL", "authentication": "AUTH_FAILED",
                "api_unreachable": "API_UNREACHABLE", "timeout_network": "API_UNREACHABLE",
                "rate_limit": "RATE_LIMITED", "no_credits": "NO_CREDITS",
                "unexpected_schema": "INVALID_RESPONSE", "invalid_request": "INVALID_RESPONSE",
                "sdk_missing": "INVALID_RESPONSE"}.get(error_kind, "API_UNREACHABLE")

    def _record_health(self, *, status: str, credential_present: bool,
                       api_reachable: bool = False, authentication_ok: bool = False,
                       available_models: list[dict] | None = None, evaluation_ok: bool = False,
                       selected_id: str | None = None, candidate_ids: list[str] | None = None,
                       usage: dict | None = None, latency_ms: int = 0,
                       error_kind: str | None = None, detail: str | None = None,
                       model_resolved: str | None = None) -> dict:
        now = iso(utcnow())
        self.db.x(
            "INSERT INTO jev_health_checks(checked_at,status,credential_present,api_reachable,authentication_ok,"
            "model_requested,model_resolved,available_models_json,evaluation_ok,selected_deliver_id,"
            "candidate_deliver_ids_json,input_tokens,output_tokens,latency_ms,error_kind,detail) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, status, int(credential_present), int(api_reachable), int(authentication_ok), self.model,
             model_resolved, _canonical(available_models or []), int(evaluation_ok), selected_id,
             _canonical(candidate_ids or []), (usage or {}).get("input_tokens"),
             (usage or {}).get("output_tokens"), latency_ms, error_kind, detail))
        return {"status": status, "credential_present": credential_present,
                "api_reachable": api_reachable, "authentication_ok": authentication_ok,
                "model_requested": self.model, "model_resolved": model_resolved,
                "available_models": available_models or [], "evaluation_ok": evaluation_ok,
                "selected_deliver_id": selected_id, "candidate_deliver_ids": candidate_ids or [],
                "usage": usage or {"input_tokens": None, "output_tokens": None},
                "latency_ms": latency_ms, "error_kind": error_kind, "detail": detail,
                "credits": "unknown"}

    def health_check(self) -> dict:
        """Probe credentials, model listing and one small closed-set Choice request."""
        started = time.monotonic()
        try:
            credential_present = self.credentials.present()
        except CredentialError:
            credential_present = False
        if not credential_present:
            return self._record_health(status="MISSING_CREDENTIAL", credential_present=False,
                                       error_kind="missing_credential", detail="No TypeSafe credential is available")
        candidates = [dict(row) for row in self.db.q(
            "SELECT deliver_id id,description,execution_kind FROM deliver_catalog "
            "WHERE enabled=1 ORDER BY deliver_id LIMIT 3")]
        if len(candidates) < 2:
            return self._record_health(status="INVALID_RESPONSE", credential_present=True,
                                       error_kind="invalid_request",
                                       detail="Health evaluation needs 2 existing candidate Deliver IDs",
                                       candidate_ids=[c["id"] for c in candidates])
        try:
            models = self.client.list_models(self.model)
            reply = self.client.choice(
                state={"objective": "Verify TypeSafe routing with registered Deliver IDs",
                       "workflow": {"selection_scope": "health_check", "candidate_count": len(candidates)},
                       "context_refs": []},
                criteria={c["id"]: {"description": str(c.get("description") or "")[:240],
                                     "execution_kind": str(c.get("execution_kind") or "unknown")}
                          for c in candidates}, model=self.model,
                instructions="Select the most suitable registered Deliver for a generic integration health check.")
            candidate_ids = [c["id"] for c in candidates]
            if reply.choice not in candidate_ids:
                raise JevError("unexpected_schema")
            request_id = reply.request_id or "jev-health:" + str(uuid.uuid4())
            self.usage.record(request_id, reply.usage)
            return self._record_health(
                status="READY", credential_present=True, api_reachable=True, authentication_ok=True,
                available_models=models, evaluation_ok=True, selected_id=reply.choice,
                candidate_ids=candidate_ids, usage=reply.usage,
                latency_ms=int((time.monotonic() - started) * 1000), model_resolved=reply.model)
        except JevError as exc:
            status = self._health_status(exc.kind)
            reached = exc.kind not in {"api_unreachable", "timeout_network", "sdk_missing", "missing_credential"}
            authenticated = reached and exc.kind != "authentication"
            return self._record_health(
                status=status, credential_present=True, api_reachable=reached,
                authentication_ok=authenticated, candidate_ids=[c["id"] for c in candidates],
                latency_ms=int((time.monotonic() - started) * 1000), error_kind=exc.kind,
                detail="TypeSafe health check failed")
