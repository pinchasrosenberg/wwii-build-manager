"""MCP server discovery for manual tasks (names only are shown; definitions stay local).

Codex: `codex mcp list --json` (no inference).  Claude: user/project entries in
~/.claude.json and the repo's .mcp.json. A task opts into servers by name; nothing is
enabled by default (Claude workers otherwise run with --safe-mode + --strict-mcp-config,
Codex workers with --ignore-user-config).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .config import Config
from .sanitize import child_env


def _writes_hint(defn: dict) -> bool:
    env = defn.get("env") or {}
    return any("WRITE" in str(k).upper() and str(v) not in ("", "0", "false") for k, v in env.items())


def codex_servers(cfg: Config) -> dict[str, dict]:
    cmd = list(cfg.provider("codex").get("command") or ["codex"])
    try:
        out = subprocess.run([*cmd, "mcp", "list", "--json"], capture_output=True, text=True, timeout=30,
                             env=child_env({k: os.environ[k] for k in ("CODEX_HOME",) if k in os.environ})).stdout
        items = json.loads(out)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}
    res = {}
    for s in items if isinstance(items, list) else []:
        t = s.get("transport") or {}
        res[s["name"]] = {"enabled_in_user_config": bool(s.get("enabled")), "command": t.get("command"),
                          "writes": _writes_hint(t)}
    return res


def claude_definitions(cfg: Config) -> dict[str, dict]:
    paths = [Path(p).expanduser() for p in cfg.section("mcp").get("claude_config_paths",
                                                                  ["~/.claude.json", "{repo}/.mcp.json"])]
    out: dict[str, dict] = {}
    for p in paths:
        p = Path(str(p).replace("{repo}", str(cfg.repo)))
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text())
        except ValueError:
            continue
        out.update(d.get("mcpServers") or {})
        proj = (d.get("projects") or {}).get(str(cfg.repo)) or {}
        out.update(proj.get("mcpServers") or {})
    return out


def claude_servers(cfg: Config) -> dict[str, dict]:
    return {n: {"command": d.get("command") or d.get("url"), "writes": _writes_hint(d)}
            for n, d in claude_definitions(cfg).items()}


def available(cfg: Config) -> dict[str, dict[str, dict]]:
    return {"codex": codex_servers(cfg), "claude": claude_servers(cfg)}
