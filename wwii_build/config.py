"""Configuration: built-in defaults deep-merged with the user's TOML file.

Model names live here (and in the user's config), never deep in code.
"""
from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .models import ModelProfile

REGISTRY_REL = "docs/game/LEGO_OWNERSHIP_REGISTRY.json"
STATE_DIRNAME = ".wwii-build"
WORKTREES_DIRNAME = ".worktrees"
PACKAGE_DIR = Path(__file__).resolve().parent
MANAGER_DIR = PACKAGE_DIR.parent

DEFAULTS: dict = {
    "scheduler": {
        "max_parallel": 3,
        "control_poll_seconds": 2.0,
        "escalation_threshold": 3,       # failed attempts before ESCALATION_REQUIRED
        "technical_retry_limit": 2,      # CLI crashes retried on the same model
        "retry_backoff_seconds": [60, 300, 900],
        "task_timeout_minutes": 90,
        "sleep_gap_seconds": 120,        # loop gap that counts as "Mac was asleep"
    },
    "stop": {"graceful_timeout_seconds": 20, "kill_after_term_seconds": 5},
    "billing": {"allow_api_billing": False, "allow_claude_overage": False},
    "approvals": {
        "astra": "required",
        "opus": "optional",
        "api_billing": "required",
        "destructive_commands": "never",
        "dependency_changes": "review",   # allow | review | block
        "auto_max_per_task": 3,           # full automatic mode: max auto-approved retry/repair loops per task
        "auto_after_cap": "reject",       # reject (task -> FAILED, nothing waits for you) | ask (leave pending)
    },
    "deep": {"require_manual_approval": True},
    "fallback": {"enabled": True, "wait_when_exhausted": True},
    "providers": {
        "codex": {
            "enabled": True,
            "command": ["codex"],
            "sandbox": "workspace-write",
            "read_only_sandbox": "read-only",
            "ignore_user_config": True,
            "quota_source": "app-server",     # app-server | none
            "quota_refresh_minutes": 20,
            "quota_poll_seconds": 120,       # live limits read (no inference) while the daemon runs; 0 = off
            "near_limit_percent": 90,
            "stop_dispatch_at_percent": 100,
            "extra_args": [],
        },
        "claude": {
            "enabled": True,
            "command": [],                     # empty = auto-discover
            "safe_mode": True,
            "permission_mode": "acceptEdits",
            "allowed_tools": [
                "Read", "Edit", "Write", "Glob", "Grep",
                "Bash(python3 *)", "Bash(python *)", "Bash(pytest *)",
                "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)",
                "Bash(ls *)", "Bash(godot *)",
            ],
            "disallowed_tools": [
                "Bash(git push*)", "Bash(git reset*)", "Bash(git clean*)",
                "Bash(git checkout*)", "Bash(git rebase*)", "Bash(rm -rf*)",
                "Bash(curl*)", "Bash(wget*)", "WebFetch", "WebSearch",
            ],
            "read_only_tools": ["Read", "Glob", "Grep"],
            "subscription_auth_methods": ["claude.ai", "oauth", "oauth_token", "subscription", "claude_ai"],
            "unknown_reset_backoff_only": True,
            "extra_args": [],
        },
    },
    "models": {
        "sol":    {"provider": "codex",  "model": "gpt-5.6-sol",  "effort": "high", "tier": "standard", "family": "*"},
        "astra":  {"provider": "codex",  "model": "gpt-6-astra",  "effort": "high", "tier": "premium",  "family": "*", "automatic": False},
        "luna":   {"provider": "codex",  "model": "gpt-5.6-luna", "effort": "low",  "tier": "cheap",    "family": "*"},
        "sonnet": {"provider": "claude", "model": "claude-sonnet-5-5", "effort": "high", "tier": "standard", "family": "sonnet"},
        "opus":   {"provider": "claude", "model": "claude-opus-5-5", "effort": "high", "tier": "premium",  "family": "opus"},
        "haiku":  {"provider": "claude", "model": "claude-haiku-4-5-20251001", "effort": None, "tier": "cheap", "family": "haiku"},
    },
    # Routing is by FIT only: for each task profile every model gets a suitability score (0-10) and the chain is
    # the models sorted by that score. A model that is absent from a profile is not a candidate for it (e.g. the
    # premium models only appear where a premium model is really warranted). Provider never matters: equal scores
    # are separated by cost tier (cheaper first), then by remaining quota headroom, then by key (see routing.py).
    # To force an order for one profile, set [routing] <PROFILE> = [...] in config.toml (explicit pin).
    "routing": {},
    "fit": {
        "IMPLEMENT":           {"sol": 8, "sonnet": 8},
        "DESIGN":              {"sonnet": 9, "sol": 7},
        "RESEARCH":            {"opus": 9, "sonnet": 8, "sol": 7},
        "DEEP":                {"astra": 9, "opus": 8, "sonnet": 6, "sol": 6},
        "VISUAL":              {"sol": 8, "sonnet": 8},
        "EXTRACT":             {"luna": 8, "haiku": 8, "sol": 5, "sonnet": 5},
        "REVIEW":              {"opus": 9, "sonnet": 8, "sol": 8},
        # Repair tasks: scoped fixes after an acceptance failure; premium models only when escalated.
        "REPAIR_CODE":         {"sol": 8, "sonnet": 8},
        "REPAIR_TEXT":         {"sonnet": 9, "sol": 7},
        "REPAIR_EVIDENCE":     {"sonnet": 9, "sol": 7},
        "REPAIR_HANDOFF":      {"sol": 8, "sonnet": 8},
        "REPAIR_ESCALATED":    {"opus": 9, "sonnet": 7, "sol": 7},     # opus here always needs approval
        "REPAIR_ARCHITECTURE": {"opus": 9, "astra": 8},                # only after an architecture review approval
        "MANUAL":              {"sol": 8, "sonnet": 8},
        "PLAN":                {"sol": 9, "sonnet": 9},                # capable planner; no small-model fallback
        "CHAT":                {"sonnet": 9, "sol": 9, "haiku": 6, "luna": 6},   # dashboard talk about the state
    },
    "planner": {"max_tasks": 20},
    "model_watch": {"enabled": True, "check_interval_hours": 24},
    # Public, read-only WWII Atlas graph API (HTTPS only). Empty = graph access disabled.
    "graph_rag": {"url": "", "cypher_url": "", "timeout_seconds": 45, "allow_ingest": False,
                  "llm_timeout_seconds": 180,
                  "planner_max_chunks": 24, "planner_max_chars": 24000},
    # Worker-requested follow-up tasks: opened when the parent passes. safe = auto-create only cheap models inside
    # the parent's write scope without MCP; everything else becomes a proposal for your approval.
    "followups": {"enabled": True, "auto_create": "safe", "max_per_task": 5, "max_depth": 2},
    "subtasks": {"promotion_threshold": 3, "max_per_parent": 12},
    "mcp": {"claude_config_paths": ["~/.claude.json", "{repo}/.mcp.json"]},
    "repair": {
        "enabled": True,
        "max_repairs_per_task": 3,
        "effort": "medium",                  # reasoning effort for repair runs (original tasks keep theirs)
        "escalate_from_repair": 3,           # repair #3 uses REPAIR_ESCALATED
        "premium_requires_approval": True,   # opus/astra in a repair chain always ask first
        "repair_malformed_handoff": True,
        "max_diff_bytes": 30000,
        "shared_contract_paths": ["game/contracts.py", "schemas/game/", "context/game/interfaces/"],
    },
    "quota": {
        "unknown_backoff_minutes": [15, 30, 60, 120],
        "reset_safety_margin_seconds": 120,
    },
    "context": {"max_inline_bytes": 90000, "max_retry_diff_bytes": 20000, "max_test_output_bytes": 6000},
    "acceptance": {
        "python": "",   # empty = auto (existing research venv from game/README, else python3)
        "default_commands": [
            {
                "name": "game-contract-tests",
                "argv": ["{python}", "-m", "pytest", "game/tests", "-q", "-p", "no:cacheprovider"],
                "env": {"PYTHONPATH": "{repo}/.runtime-deps/driver-runtime"},
                "timeout_seconds": 600,
                "when_exists": "game/tests",
            }
        ],
        "run_scope_pytests": True,
        "command_timeout_seconds": 900,
    },
    "review": {
        "auto_pass_requires_task_commands": True,
        "llm_review_profiles": [],   # e.g. ["DEEP"]: cross-provider LLM review for these profiles
        "cross_provider": True,
    },
    "dashboard": {"host": "127.0.0.1", "port": 8765, "language": "he"},   # he | en (toggle on the page)
    "notifications": {"enabled": True, "min_interval_seconds": 300},
    "jev": {
        "enabled": True,
        "model": "jev-latest",
        "timeout_seconds": 8,
        "docs_ttl_hours": 24,
        "max_candidates": 64,
        "max_context_candidates": 24,
        "max_context_items": 1,
        "max_context_bundles_per_run": 4,
        "require_for_all_llm_context": True,
        "max_listener_activations_per_event": 2,
        # No balance endpoint is documented. This optional value enables a clearly
        # labeled local estimate only; absent means UNKNOWN.
        "local_budget": None,
        "budget_unit": "tokens",
        "input_rate_per_million": None,
        "output_rate_per_million": None,
        "warning_fraction": 0.25,
        "critical_fraction": 0.10,
    },
    "baseline": {
        "branch": "wwii-build/integration",
        "include_paths": ["AGENTS.md", "context", "docs/game", "game", "schemas/game", "skills",
                          "tools/build_manager"],
    },
    "worktree": {"sparse": False},   # true = small worktrees, but git sets extensions.worktreeConfig
    "plan": {"registry": REGISTRY_REL, "overlay": ""},
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def find_repo_root(start: Path | None = None) -> Path:
    env = os.environ.get("WWII_BUILD_REPO")
    if env:
        return Path(env).resolve()
    for base in [start or Path.cwd(), MANAGER_DIR]:
        p = base.resolve()
        for cand in [p, *p.parents]:
            if (cand / REGISTRY_REL).is_file():
                return cand
    raise SystemExit("Cannot locate repo root (no docs/game/LEGO_OWNERSHIP_REGISTRY.json). Use --repo or WWII_BUILD_REPO.")


@dataclass
class Config:
    repo: Path
    data: dict
    path: Path | None

    @property
    def state_dir(self) -> Path:
        return self.repo / STATE_DIRNAME

    @property
    def worktrees_dir(self) -> Path:
        return self.repo / WORKTREES_DIRNAME

    @property
    def db_path(self) -> Path:
        return self.state_dir / "state.sqlite3"

    def section(self, name: str) -> dict:
        return self.data.get(name, {})

    def provider(self, name: str) -> dict:
        return self.data["providers"].get(name, {})

    def model(self, key: str) -> ModelProfile:
        m = self.data["models"][key]
        return ModelProfile(
            key=key, provider=m["provider"], model=m["model"], effort=m.get("effort"),
            tier=m.get("tier", "standard"), family=m.get("family", "*"),
            automatic=bool(m.get("automatic", True)),
        )

    def models(self) -> dict[str, ModelProfile]:
        return {k: self.model(k) for k in self.data["models"]}

    def fit_scores(self, profile: str) -> dict[str, float]:
        """Suitability of every configured model for ``profile`` (absent = not a candidate)."""
        table = self.data.get("fit", {}).get(profile) or {}
        return {k: float(v) for k, v in table.items() if k in self.data["models"]}

    def chain(self, profile: str) -> list[str]:
        """Models for ``profile`` ordered by fit. Only an explicit [routing] pin in config.toml overrides that."""
        pinned = self.data.get("routing", {}).get(profile)
        if pinned:
            return list(pinned)
        scores = self.fit_scores(profile)
        tier_cost = {"cheap": 0, "standard": 1, "premium": 2}
        return sorted(scores, key=lambda k: (-scores[k], tier_cost.get(self.data["models"][k].get("tier"), 1), k))

    @property
    def overlay_path(self) -> Path:
        o = self.data["plan"].get("overlay")
        return Path(o) if o else MANAGER_DIR / "plan_overlay.toml"


def load_config(repo: Path | None = None, path: Path | None = None) -> Config:
    repo = repo or find_repo_root()
    if path is not None:
        cfg_path = path
    elif os.environ.get("WWII_BUILD_CONFIG"):
        cfg_path = Path(os.environ["WWII_BUILD_CONFIG"])
    else:
        cfg_path = repo / STATE_DIRNAME / "config.toml"
    data = copy.deepcopy(DEFAULTS)
    if cfg_path and cfg_path.is_file():
        with open(cfg_path, "rb") as f:
            data = deep_merge(data, tomllib.load(f))
    else:
        cfg_path = None
    cfg = Config(repo=repo, data=data, path=cfg_path)
    from .model_watch import apply_overrides
    apply_overrides(cfg)
    return cfg
