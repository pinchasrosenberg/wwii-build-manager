"""Deterministic, transport-neutral request progress contracts.

This module deliberately does not publish events or know about the scheduler,
database, dashboard, game, or a network transport.  A caller owns delivery and
persists the returned :class:`ProgressEvent` values if required.
"""
from __future__ import annotations

import datetime as dt
import enum
import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Iterable, Mapping


CONTRACT_VERSION = "1"
PROGRESS_UPDATES_ENV = "WWII_BUILD_PROGRESS_UPDATES"
PROGRESS_HEARTBEAT_SECONDS_ENV = "WWII_BUILD_PROGRESS_HEARTBEAT_SECONDS"
DEFAULT_HEARTBEAT_SECONDS = 30.0
# Exact flag-name constants are exported as well as the descriptive ``*_ENV``
# spellings, making configuration discovery unambiguous for callers.
WWII_BUILD_PROGRESS_UPDATES = PROGRESS_UPDATES_ENV
WWII_BUILD_PROGRESS_HEARTBEAT_SECONDS = PROGRESS_HEARTBEAT_SECONDS_ENV


class ProgressContractError(ValueError):
    """A progress value or transition violates the public contract."""


class ProgressConfigurationError(ProgressContractError):
    """Progress feature configuration is present but invalid."""


class LifecycleState(str, enum.Enum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_DEPENDENCY = "waiting_dependency"
    RETRYING = "retrying"
    TESTING = "testing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in TERMINAL_STATES


# A descriptive alias for consumers that use ``ProgressState`` in their API.
ProgressState = LifecycleState


class ProgressEventType(str, enum.Enum):
    ACCEPTED = "accepted"
    TRANSITION = "transition"
    HEARTBEAT = "heartbeat"


TERMINAL_STATES = frozenset({
    LifecycleState.SUCCEEDED,
    LifecycleState.FAILED,
    LifecycleState.CANCELLED,
})
ACTIVE_HEARTBEAT_STATES = frozenset({
    LifecycleState.RUNNING,
    LifecycleState.RETRYING,
    LifecycleState.TESTING,
})


# Explicit boundary mapping from existing Task Manager vocabulary and provider
# attempt outcomes.  No fuzzy matching is used: an unknown state is an error.
LIFECYCLE_STATE_MAP: dict[str, LifecycleState] = {
    # Public lifecycle spelling.
    **{state.value: state for state in LifecycleState},
    # TaskState values.
    "PENDING": LifecycleState.QUEUED,
    "READY": LifecycleState.QUEUED,
    "WAITING_DEPENDENCY": LifecycleState.WAITING_DEPENDENCY,
    "WAITING_PROVIDER": LifecycleState.WAITING_DEPENDENCY,
    "WAITING_QUOTA": LifecycleState.WAITING_DEPENDENCY,
    "WAITING_APPROVAL": LifecycleState.WAITING_DEPENDENCY,
    "WAITING_REPAIR": LifecycleState.WAITING_DEPENDENCY,
    "PAUSING": LifecycleState.WAITING_DEPENDENCY,
    "PAUSED": LifecycleState.WAITING_DEPENDENCY,
    "RUNNING": LifecycleState.RUNNING,
    "CODE_READY": LifecycleState.TESTING,
    "REVIEW_REQUIRED": LifecycleState.WAITING_DEPENDENCY,
    "ARCHITECTURE_REVIEW_REQUIRED": LifecycleState.WAITING_DEPENDENCY,
    "REVIEWING": LifecycleState.TESTING,
    "PASSED": LifecycleState.SUCCEEDED,
    "FAILED": LifecycleState.FAILED,
    "BLOCKED": LifecycleState.WAITING_DEPENDENCY,
    "CANCELLED": LifecycleState.CANCELLED,
    # AttemptStatus values.
    "SUCCEEDED": LifecycleState.TESTING,
    "FAILED_ATTEMPT": LifecycleState.RETRYING,
    "QUOTA_LIMITED": LifecycleState.WAITING_DEPENDENCY,
    "AUTH_ERROR": LifecycleState.FAILED,
    "BILLING_BLOCKED": LifecycleState.FAILED,
    "MODEL_UNAVAILABLE": LifecycleState.RETRYING,
    "CRASHED": LifecycleState.RETRYING,
    "TIMED_OUT": LifecycleState.RETRYING,
    "INTERRUPTED": LifecycleState.CANCELLED,
    "ORPHANED": LifecycleState.RETRYING,
}


def map_lifecycle_state(value: object) -> LifecycleState:
    """Map one known manager/provider state to the public lifecycle."""
    if isinstance(value, LifecycleState):
        return value
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        raise ProgressContractError(f"progress state must be a string or enum, got {type(value).__name__}")
    try:
        return LIFECYCLE_STATE_MAP[raw]
    except KeyError as exc:
        raise ProgressContractError(f"unknown progress state: {raw!r}") from exc


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProgressContractError(f"{name} must be a non-empty string")


def _utc(value: dt.datetime, name: str) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProgressContractError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return _utc(value, "timestamp").isoformat()


def _parse_time(value: object, name: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ProgressContractError(f"{name} must be an ISO-8601 string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProgressContractError(f"{name} must be an ISO-8601 string") from exc
    return _utc(parsed, name)


@dataclass(frozen=True)
class LocalizedMessage:
    """Already-localized user text plus an optional stable translation key."""

    locale: str
    text: str
    key: str | None = None
    parameters: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required_text("message.locale", self.locale)
        _required_text("message.text", self.text)
        if self.key is not None:
            _required_text("message.key", self.key)
        if not isinstance(self.parameters, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in self.parameters.items()
        ):
            raise ProgressContractError("message.parameters must map strings to strings")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    def to_dict(self) -> dict:
        return {
            "locale": self.locale,
            "text": self.text,
            "key": self.key,
            "parameters": dict(sorted(self.parameters.items())),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "LocalizedMessage":
        return cls(
            locale=value["locale"],  # type: ignore[arg-type]
            text=value["text"],  # type: ignore[arg-type]
            key=value.get("key"),  # type: ignore[arg-type]
            parameters=value.get("parameters", {}),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class WorkItemCounts:
    """Known work-item counts; ``None`` is preserved rather than read as zero."""

    completed: int | None = None
    total: int | None = None

    def __post_init__(self) -> None:
        if self.completed is not None and (
            isinstance(self.completed, bool) or not isinstance(self.completed, int) or self.completed < 0
        ):
            raise ProgressContractError("completed work-item count must be a non-negative integer or null")
        if self.total is not None:
            if isinstance(self.total, bool) or not isinstance(self.total, int) or self.total < 0:
                raise ProgressContractError("total work-item count must be a non-negative integer or null")
            if self.completed is not None and self.completed > self.total:
                raise ProgressContractError("completed work-item count cannot exceed total")

    @property
    def indeterminate(self) -> bool:
        return self.completed is None or self.total is None

    @property
    def percentage(self) -> float | None:
        """Return a percentage only when the denominator is known."""
        if self.completed is None or self.total is None:
            return None
        return 100.0 if self.total == 0 else (self.completed / self.total) * 100.0

    def to_dict(self) -> dict:
        return {
            "completed": self.completed,
            "total": self.total,
            "indeterminate": self.indeterminate,
            "percentage": self.percentage,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorkItemCounts":
        counts = cls(completed=value.get("completed"), total=value.get("total"))  # type: ignore[arg-type]
        # Derived fields are checked when supplied so corrupt persisted events do
        # not silently acquire a different meaning.
        if "indeterminate" in value:
            supplied = value["indeterminate"]
            if not isinstance(supplied, bool) or supplied != counts.indeterminate:
                raise ProgressContractError("indeterminate disagrees with work-item counts")
        if "percentage" in value and value["percentage"] != counts.percentage:
            raise ProgressContractError("percentage disagrees with work-item counts")
        return counts


def aggregate_counts(counts: Iterable[WorkItemCounts]) -> WorkItemCounts:
    """Aggregate children without inventing a denominator for unknown work."""
    completed = 0
    total = 0
    completed_unknown = False
    total_unknown = False
    for item in counts:
        if not isinstance(item, WorkItemCounts):
            raise ProgressContractError("aggregate items must be WorkItemCounts")
        if item.completed is None:
            completed_unknown = True
        else:
            completed += item.completed
        if item.total is None:
            total_unknown = True
        else:
            total += item.total
    return WorkItemCounts(completed=None if completed_unknown else completed,
                          total=None if total_unknown else total)


@dataclass(frozen=True)
class ErrorMetadata:
    code: str
    message: str
    retryable: bool = False
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required_text("error.code", self.code)
        _required_text("error.message", self.message)
        if not isinstance(self.retryable, bool):
            raise ProgressContractError("error.retryable must be a boolean")
        if not isinstance(self.details, Mapping) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in self.details.items()
        ):
            raise ProgressContractError("error.details must map strings to strings")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable,
                "details": dict(sorted(self.details.items()))}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ErrorMetadata":
        return cls(code=value["code"], message=value["message"],  # type: ignore[arg-type]
                   retryable=value.get("retryable", False), details=value.get("details", {}))  # type: ignore[arg-type]


@dataclass(frozen=True)
class TerminalMetadata:
    finished_at: dt.datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "finished_at", _utc(self.finished_at, "terminal.finished_at"))
        if self.reason is not None:
            _required_text("terminal.reason", self.reason)

    def to_dict(self) -> dict:
        return {"finished_at": _iso(self.finished_at), "reason": self.reason}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "TerminalMetadata":
        return cls(finished_at=_parse_time(value["finished_at"], "terminal.finished_at"),  # type: ignore[arg-type]
                   reason=value.get("reason"))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ProgressSnapshot:
    request_id: str
    run_id: str
    task_id: str
    sequence: int
    lifecycle_state: LifecycleState
    current_phase: str
    current_task_label: str
    counts: WorkItemCounts
    message: LocalizedMessage
    event_timestamp: dt.datetime
    last_activity_timestamp: dt.datetime
    terminal: TerminalMetadata | None = None
    error: ErrorMetadata | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "run_id", "task_id", "current_phase", "current_task_label"):
            _required_text(name, getattr(self, name))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ProgressContractError("sequence must be a non-negative integer")
        object.__setattr__(self, "lifecycle_state", map_lifecycle_state(self.lifecycle_state))
        if not isinstance(self.counts, WorkItemCounts):
            raise ProgressContractError("counts must be WorkItemCounts")
        if not isinstance(self.message, LocalizedMessage):
            raise ProgressContractError("message must be LocalizedMessage")
        event_at = _utc(self.event_timestamp, "event_timestamp")
        activity_at = _utc(self.last_activity_timestamp, "last_activity_timestamp")
        if activity_at > event_at:
            raise ProgressContractError("last_activity_timestamp cannot be after event_timestamp")
        object.__setattr__(self, "event_timestamp", event_at)
        object.__setattr__(self, "last_activity_timestamp", activity_at)
        if self.lifecycle_state.terminal != (self.terminal is not None):
            raise ProgressContractError("terminal metadata must be present exactly for terminal states")
        if self.terminal is not None and self.terminal.finished_at != event_at:
            raise ProgressContractError("terminal.finished_at must equal event_timestamp")
        if self.error is not None and not isinstance(self.error, ErrorMetadata):
            raise ProgressContractError("error must be ErrorMetadata or null")

    @property
    def state(self) -> LifecycleState:
        """Short compatibility spelling for ``lifecycle_state``."""
        return self.lifecycle_state

    @property
    def completed_work_items(self) -> int | None:
        return self.counts.completed

    @property
    def total_work_items(self) -> int | None:
        return self.counts.total

    @property
    def indeterminate(self) -> bool:
        return self.counts.indeterminate

    @property
    def percentage(self) -> float | None:
        return self.counts.percentage

    def to_dict(self) -> dict:
        return {
            "contract_version": CONTRACT_VERSION,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "sequence": self.sequence,
            "lifecycle_state": self.lifecycle_state.value,
            "current_phase": self.current_phase,
            "current_task_label": self.current_task_label,
            "work_items": self.counts.to_dict(),
            "message": self.message.to_dict(),
            "event_timestamp": _iso(self.event_timestamp),
            "last_activity_timestamp": _iso(self.last_activity_timestamp),
            "terminal": None if self.terminal is None else self.terminal.to_dict(),
            "error": None if self.error is None else self.error.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ProgressSnapshot":
        if value.get("contract_version") != CONTRACT_VERSION:
            raise ProgressContractError(f"unsupported progress contract version: {value.get('contract_version')!r}")
        terminal = value.get("terminal")
        error = value.get("error")
        if terminal is not None and not isinstance(terminal, Mapping):
            raise ProgressContractError("terminal must be an object or null")
        if error is not None and not isinstance(error, Mapping):
            raise ProgressContractError("error must be an object or null")
        return cls(
            request_id=value["request_id"], run_id=value["run_id"], task_id=value["task_id"],  # type: ignore[arg-type]
            sequence=value["sequence"],  # type: ignore[arg-type]
            lifecycle_state=map_lifecycle_state(value["lifecycle_state"]),
            current_phase=value["current_phase"],  # type: ignore[arg-type]
            current_task_label=value["current_task_label"],  # type: ignore[arg-type]
            counts=WorkItemCounts.from_dict(value["work_items"]),  # type: ignore[arg-type]
            message=LocalizedMessage.from_dict(value["message"]),  # type: ignore[arg-type]
            event_timestamp=_parse_time(value["event_timestamp"], "event_timestamp"),
            last_activity_timestamp=_parse_time(value["last_activity_timestamp"], "last_activity_timestamp"),
            terminal=TerminalMetadata.from_dict(terminal) if terminal is not None else None,
            error=ErrorMetadata.from_dict(error) if error is not None else None,
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> "ProgressSnapshot":
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProgressContractError("progress snapshot must be valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ProgressContractError("progress snapshot JSON must be an object")
        return cls.from_dict(decoded)


@dataclass(frozen=True)
class ProgressEvent:
    event_type: ProgressEventType
    snapshot: ProgressSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, ProgressEventType):
            try:
                object.__setattr__(self, "event_type", ProgressEventType(self.event_type))
            except (TypeError, ValueError) as exc:
                raise ProgressContractError(f"unknown progress event type: {self.event_type!r}") from exc
        if not isinstance(self.snapshot, ProgressSnapshot):
            raise ProgressContractError("snapshot must be ProgressSnapshot")
        if self.event_type is ProgressEventType.ACCEPTED and (
            self.snapshot.lifecycle_state is not LifecycleState.ACCEPTED or self.snapshot.sequence != 1
        ):
            raise ProgressContractError("accepted event must be sequence 1 in accepted state")

    def __getattr__(self, name: str) -> object:
        # Events expose all snapshot fields directly while retaining one canonical
        # serializable representation.
        return getattr(self.snapshot, name)

    def to_dict(self) -> dict:
        value = self.snapshot.to_dict()
        value["event_type"] = self.event_type.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ProgressEvent":
        try:
            event_type = ProgressEventType(value["event_type"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProgressContractError("unknown or missing progress event type") from exc
        return cls(event_type=event_type, snapshot=ProgressSnapshot.from_dict(value))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> "ProgressEvent":
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProgressContractError("progress event must be valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ProgressContractError("progress event JSON must be an object")
        return cls.from_dict(decoded)


@dataclass(frozen=True)
class ProgressConfig:
    enabled: bool = False
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ProgressConfigurationError("progress updates enabled flag must be a boolean")
        if (isinstance(self.heartbeat_seconds, bool)
                or not isinstance(self.heartbeat_seconds, (int, float))
                or not math.isfinite(float(self.heartbeat_seconds))
                or float(self.heartbeat_seconds) <= 0):
            raise ProgressConfigurationError("progress heartbeat seconds must be a finite number greater than zero")
        object.__setattr__(self, "heartbeat_seconds", float(self.heartbeat_seconds))

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ProgressConfig":
        if env is None:
            import os
            env = os.environ
        raw_enabled = env.get(PROGRESS_UPDATES_ENV, "").strip().lower()
        enabled_values = {"1": True, "true": True, "yes": True, "on": True,
                          "": False, "0": False, "false": False, "no": False, "off": False}
        if raw_enabled not in enabled_values:
            raise ProgressConfigurationError(
                f"{PROGRESS_UPDATES_ENV} must be one of 1/0, true/false, yes/no, or on/off"
            )
        raw_seconds = env.get(PROGRESS_HEARTBEAT_SECONDS_ENV)
        if raw_seconds is None or not raw_seconds.strip():
            seconds = DEFAULT_HEARTBEAT_SECONDS
        else:
            try:
                seconds = float(raw_seconds)
            except ValueError as exc:
                raise ProgressConfigurationError(
                    f"{PROGRESS_HEARTBEAT_SECONDS_ENV} must be a finite number greater than zero"
                ) from exc
        return cls(enabled=enabled_values[raw_enabled], heartbeat_seconds=seconds)


ProgressSettings = ProgressConfig


_ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.ACCEPTED: frozenset({LifecycleState.QUEUED, LifecycleState.RUNNING,
                                        LifecycleState.FAILED, LifecycleState.CANCELLED}),
    LifecycleState.QUEUED: frozenset({LifecycleState.RUNNING, LifecycleState.WAITING_DEPENDENCY,
                                      LifecycleState.FAILED, LifecycleState.CANCELLED}),
    LifecycleState.RUNNING: frozenset({LifecycleState.WAITING_DEPENDENCY, LifecycleState.RETRYING,
                                       LifecycleState.TESTING, LifecycleState.SUCCEEDED,
                                       LifecycleState.FAILED, LifecycleState.CANCELLED}),
    LifecycleState.WAITING_DEPENDENCY: frozenset({LifecycleState.QUEUED, LifecycleState.RUNNING,
                                                  LifecycleState.RETRYING, LifecycleState.FAILED,
                                                  LifecycleState.CANCELLED}),
    LifecycleState.RETRYING: frozenset({LifecycleState.QUEUED, LifecycleState.RUNNING,
                                        LifecycleState.WAITING_DEPENDENCY, LifecycleState.TESTING,
                                        LifecycleState.FAILED, LifecycleState.CANCELLED}),
    LifecycleState.TESTING: frozenset({LifecycleState.RETRYING, LifecycleState.SUCCEEDED,
                                       LifecycleState.FAILED, LifecycleState.CANCELLED}),
    LifecycleState.SUCCEEDED: frozenset(),
    LifecycleState.FAILED: frozenset(),
    LifecycleState.CANCELLED: frozenset(),
}


Clock = Callable[[], dt.datetime]


class ProgressTracker:
    """Create ordered progress events using only an injected clock.

    Calls return ``None`` while the feature flag is disabled, for duplicate
    material updates, for an early heartbeat, or after a terminal event.
    """

    def __init__(self, request_id: str, run_id: str, task_id: str, *, clock: Clock,
                 config: ProgressConfig | None = None) -> None:
        for name, value in (("request_id", request_id), ("run_id", run_id), ("task_id", task_id)):
            _required_text(name, value)
        if not callable(clock):
            raise ProgressContractError("clock must be callable")
        self.request_id = request_id
        self.run_id = run_id
        self.task_id = task_id
        self.clock = clock
        self.config = ProgressConfig.from_env() if config is None else config
        self._snapshot: ProgressSnapshot | None = None
        self._last_event_at: dt.datetime | None = None

    @property
    def snapshot(self) -> ProgressSnapshot | None:
        return self._snapshot

    def _now(self) -> dt.datetime:
        now = _utc(self.clock(), "clock result")
        if self._last_event_at is not None and now < self._last_event_at:
            raise ProgressContractError("injected clock moved backwards")
        return now

    def accept(self, *, current_phase: str, current_task_label: str,
               message: LocalizedMessage, counts: WorkItemCounts | None = None) -> ProgressEvent | None:
        if not self.config.enabled:
            return None
        if self._snapshot is not None:
            return None
        now = self._now()
        snapshot = ProgressSnapshot(
            request_id=self.request_id, run_id=self.run_id, task_id=self.task_id, sequence=1,
            lifecycle_state=LifecycleState.ACCEPTED, current_phase=current_phase,
            current_task_label=current_task_label, counts=counts or WorkItemCounts(), message=message,
            event_timestamp=now, last_activity_timestamp=now,
        )
        return self._record(ProgressEventType.ACCEPTED, snapshot)

    emit_acceptance = accept

    def transition(self, lifecycle_state: LifecycleState | str, *, current_phase: str,
                   current_task_label: str, message: LocalizedMessage,
                   counts: WorkItemCounts | None = None, error: ErrorMetadata | None = None,
                   terminal_reason: str | None = None) -> ProgressEvent | None:
        if not self.config.enabled:
            return None
        previous = self._snapshot
        if previous is None:
            raise ProgressContractError("acceptance must be emitted before a transition")
        if previous.lifecycle_state.terminal:
            return None
        state = map_lifecycle_state(lifecycle_state)
        next_counts = previous.counts if counts is None else counts
        material = (state, current_phase, current_task_label, next_counts, message, error, terminal_reason)
        prior_material = (previous.lifecycle_state, previous.current_phase, previous.current_task_label,
                          previous.counts, previous.message, previous.error,
                          previous.terminal.reason if previous.terminal else None)
        if material == prior_material:
            return None
        if state is previous.lifecycle_state:
            # Same-state changes to phase, counts, label, message, or error are
            # material and intentionally allowed.
            pass
        elif state not in _ALLOWED_TRANSITIONS[previous.lifecycle_state]:
            raise ProgressContractError(
                f"invalid lifecycle transition: {previous.lifecycle_state.value} -> {state.value}"
            )
        now = self._now()
        terminal = TerminalMetadata(now, terminal_reason) if state.terminal else None
        snapshot = ProgressSnapshot(
            request_id=self.request_id, run_id=self.run_id, task_id=self.task_id,
            sequence=previous.sequence + 1, lifecycle_state=state, current_phase=current_phase,
            current_task_label=current_task_label, counts=next_counts, message=message,
            event_timestamp=now, last_activity_timestamp=now, terminal=terminal, error=error,
        )
        return self._record(ProgressEventType.TRANSITION, snapshot)

    emit_transition = transition

    def heartbeat(self) -> ProgressEvent | None:
        if not self.config.enabled or self._snapshot is None:
            return None
        previous = self._snapshot
        if previous.lifecycle_state not in ACTIVE_HEARTBEAT_STATES:
            return None
        now = self._now()
        if self._last_event_at is not None and (
            now - self._last_event_at
        ).total_seconds() < self.config.heartbeat_seconds:
            return None
        snapshot = ProgressSnapshot(
            request_id=previous.request_id, run_id=previous.run_id, task_id=previous.task_id,
            sequence=previous.sequence + 1, lifecycle_state=previous.lifecycle_state,
            current_phase=previous.current_phase, current_task_label=previous.current_task_label,
            counts=previous.counts, message=previous.message, event_timestamp=now,
            last_activity_timestamp=now, error=previous.error,
        )
        return self._record(ProgressEventType.HEARTBEAT, snapshot)

    emit_heartbeat = heartbeat

    def _record(self, event_type: ProgressEventType, snapshot: ProgressSnapshot) -> ProgressEvent:
        self._snapshot = snapshot
        self._last_event_at = snapshot.event_timestamp
        return ProgressEvent(event_type=event_type, snapshot=snapshot)


__all__ = [
    "ACTIVE_HEARTBEAT_STATES", "CONTRACT_VERSION", "DEFAULT_HEARTBEAT_SECONDS",
    "ErrorMetadata", "LIFECYCLE_STATE_MAP", "LifecycleState", "LocalizedMessage",
    "PROGRESS_HEARTBEAT_SECONDS_ENV", "PROGRESS_UPDATES_ENV", "ProgressConfig",
    "ProgressConfigurationError", "ProgressContractError", "ProgressEvent", "ProgressEventType",
    "ProgressSettings", "ProgressSnapshot", "ProgressState", "ProgressTracker", "TERMINAL_STATES",
    "TerminalMetadata", "WWII_BUILD_PROGRESS_HEARTBEAT_SECONDS", "WWII_BUILD_PROGRESS_UPDATES",
    "WorkItemCounts", "aggregate_counts", "map_lifecycle_state",
]
