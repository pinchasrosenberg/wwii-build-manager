"""Provider registry. The scheduler only sees WorkerProvider."""
from __future__ import annotations

from ..config import Config
from .base import WorkerProvider
from .claude import ClaudeCliProvider
from .codex import CodexCliProvider


def build_providers(cfg: Config) -> dict[str, WorkerProvider]:
    billing = cfg.section("billing")
    api = bool(billing.get("allow_api_billing", False))
    return {
        "codex": CodexCliProvider(cfg.provider("codex"), allow_api_billing=api),
        "claude": ClaudeCliProvider(cfg.provider("claude"), allow_api_billing=api,
                                    allow_overage=bool(billing.get("allow_claude_overage", False))),
    }
