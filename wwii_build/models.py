"""Shared value types.

These are the stable seams for a future ``DeliverRuntimeProvider``: the scheduler
only speaks TaskRequest / ContextPack / ExecutionQuote / ExecutionRun / Artifact /
CapabilityGap / ReviewResult, never CLI specifics.
"""
from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Any


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(ts: dt.datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


class TaskState(str, enum.Enum):
    PENDING = "PENDING"
    READY = "READY"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    WAITING_PROVIDER = "WAITING_PROVIDER"
    WAITING_QUOTA = "WAITING_QUOTA"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    CODE_READY = "CODE_READY"
    WAITING_REPAIR = "WAITING_REPAIR"                           # parent: a scoped repair task is fixing it
    ARCHITECTURE_REVIEW_REQUIRED = "ARCHITECTURE_REVIEW_REQUIRED"   # fix would touch shared/cross-domain contracts
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEWING = "REVIEWING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


# States the scheduler re-evaluates every cycle.
SCHEDULABLE = {
    TaskState.PENDING, TaskState.READY, TaskState.WAITING_DEPENDENCY,
    TaskState.WAITING_PROVIDER, TaskState.WAITING_QUOTA, TaskState.WAITING_APPROVAL,
}
TERMINAL = {TaskState.PASSED, TaskState.CANCELLED, TaskState.FAILED}
ACTIVE = {TaskState.RUNNING, TaskState.PAUSING, TaskState.REVIEWING}


class AttemptStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"            # worker exited cleanly; acceptance decides the rest
    FAILED_ATTEMPT = "FAILED_ATTEMPT"  # acceptance/test/compile failure
    QUOTA_LIMITED = "QUOTA_LIMITED"    # NOT a failure
    AUTH_ERROR = "AUTH_ERROR"
    BILLING_BLOCKED = "BILLING_BLOCKED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    CRASHED = "CRASHED"
    TIMED_OUT = "TIMED_OUT"
    INTERRUPTED = "INTERRUPTED"
    ORPHANED = "ORPHANED"


class ProviderStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    NEAR_LIMIT = "NEAR_LIMIT"
    BLOCKED_SESSION = "BLOCKED_SESSION"
    BLOCKED_WEEKLY = "BLOCKED_WEEKLY"
    BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"
    AUTH_ERROR = "AUTH_ERROR"
    BILLING_BLOCKED = "BILLING_BLOCKED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


QUOTA_BLOCKED = {ProviderStatus.BLOCKED_SESSION, ProviderStatus.BLOCKED_WEEKLY, ProviderStatus.BLOCKED_UNKNOWN}
HARD_UNAVAILABLE = {ProviderStatus.AUTH_ERROR, ProviderStatus.BILLING_BLOCKED,
                    ProviderStatus.MODEL_UNAVAILABLE, ProviderStatus.MISSING}


@dataclass
class ModelProfile:
    key: str            # "sol", "opus", ...
    provider: str       # "codex" | "claude" | future "deliver"
    model: str          # exact CLI model id
    effort: str | None
    tier: str           # cheap | standard | premium
    family: str         # quota family, e.g. "opus", "sonnet", "*"
    automatic: bool = True


@dataclass
class TaskRequest:
    task_id: str
    packet: str
    owner: str
    domain: str | None
    mode: str
    model_profile: str
    lego_ids: list[str]
    write_scope: list[str]
    depends_on: list[str]
    context_entry: str | None
    brief_path: str | None
    note: str | None = None
    acceptance: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    kind: str = "task"                     # task | repair | plan
    parent_task_id: str | None = None

    @property
    def read_only(self) -> bool:
        return self.mode.startswith("read_only")

    @property
    def is_repair(self) -> bool:
        return self.kind == "repair"


@dataclass
class ContextItem:
    path: str
    layer: str          # global | domain | role | task | registry | dependency | evidence | retry
    mode: str           # inline | reference | excluded
    sha256: str | None = None
    bytes: int = 0
    reason: str = ""


@dataclass
class ContextPack:
    task_id: str
    items: list[ContextItem]
    prompt: str
    prompt_sha256: str
    total_bytes: int
    id: int | None = None
    prompt_path: str | None = None
    routing: dict = field(default_factory=dict)

    def manifest(self) -> dict:
        return {
            "task_id": self.task_id,
            "prompt_sha256": self.prompt_sha256,
            "total_bytes": self.total_bytes,
            "items": [vars(i) for i in self.items],
            "routing": self.routing,
        }


@dataclass
class ExecutionQuote:
    """What a run would cost in provider terms. For subscription CLIs we only know
    which quota bucket is touched; money is None unless a provider reports it."""
    provider: str
    model_key: str
    quota_family: str
    billing_mode: str            # subscription | api | unknown
    estimated_cost_usd: float | None = None
    requires_approval: bool = False
    approval_reason: str | None = None


@dataclass
class RunSpec:
    task: TaskRequest
    attempt_id: int
    attempt_no: int
    model: ModelProfile
    worktree: str
    prompt_path: str
    run_dir: str
    result_schema_path: str
    kind: str = "execute"            # execute | review | repair | plan
    schema: dict | None = None       # inline schema (Claude); Codex reads result_schema_path
    mcp_selected: list = field(default_factory=list)   # MCP servers this task opted into
    mcp_all: list = field(default_factory=list)        # Codex: every configured server (others get disabled)
    mcp_config_path: str | None = None                 # Claude: generated --mcp-config file (0600, deleted after)
    attachment_paths: list[str] = field(default_factory=list)  # Jev-selected planner files only
    image_paths: list[str] = field(default_factory=list)       # selected images for native multimodal input
    allow_web: bool = False          # opt-in web research for this run (extra.allow_web); closed by default


@dataclass
class QuotaSignal:
    provider: str
    family: str                  # "*" for account-wide
    kind: str                    # LIMIT_HIT | WARNING | OVERAGE | SNAPSHOT
    window: str                  # session | weekly | model | unknown
    reset_at: dt.datetime | None
    used_percent: float | None = None
    raw: str = ""
    # Account-wide windows reported together by Claude: {"session": (percent, reset_at), "weekly": (...)}.
    windows: dict | None = None


@dataclass
class ExecutionRun:
    """Outcome of one provider invocation, independent of the CLI that produced it."""
    status: AttemptStatus
    exit_code: int | None
    signal: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    last_message_path: str | None = None
    final_text: str | None = None
    structured: Any = None
    session_id: str | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reported_cost_usd: float | None = None
    quota_signals: list[QuotaSignal] = field(default_factory=list)
    error: str | None = None
    failure_class: str | None = None


@dataclass
class Artifact:
    task_id: str
    kind: str
    path: str
    description: str = ""
    source_path: str | None = None
    sha256: str | None = None
    bytes: int | None = None


@dataclass
class CapabilityGap:
    task_id: str
    kind: str
    text: str


@dataclass
class ReviewResult:
    task_id: str
    reviewer: str
    verdict: str
    findings: list[str] = field(default_factory=list)
