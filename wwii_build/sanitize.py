"""Secret redaction and child-process environment construction.

Children never inherit the parent environment wholesale: this prevents API keys
(pay-as-you-go billing) and host-session variables (e.g. a desktop app's
messaging socket/token) from reaching the worker CLIs.
"""
from __future__ import annotations

import os
import re

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|secret|password)"
               r"\"?\s*[:=]\s*\"?)[^\s\",]{8,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
]


def redact(text: str | None) -> str | None:
    if not text:
        return text
    out = text
    for p in _PATTERNS:
        out = p.sub(lambda m: (m.group(1) if m.lastindex else "") + "<redacted>", out)
    return out


# Variables a worker legitimately needs. Everything else is dropped.
BASE_ENV_ALLOW = ("HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ")

# Never forwarded, even if a config asks (billing / host-session leakage).
DENY_PREFIXES = ("ANTHROPIC_", "OPENAI_", "CODEX_API", "CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_PID",
                 "CLAUDE_AGENT_SDK", "AWS_", "GOOGLE_APPLICATION", "AZURE_OPENAI")


def child_env(extra: dict[str, str] | None = None, path_extra: list[str] | None = None,
              allow_api_env: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: os.environ[k] for k in BASE_ENV_ALLOW if k in os.environ}
    base_path = ["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/opt/homebrew/bin", "/usr/local/bin",
                 os.path.expanduser("~/.local/bin")]
    env["PATH"] = ":".join([*(path_extra or []), *base_path])
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    for k, v in (extra or {}).items():
        if not k.startswith(DENY_PREFIXES):
            env[k] = v
    # Only reachable when config explicitly allows API billing.
    env.update(allow_api_env or {})
    return env
