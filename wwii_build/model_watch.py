"""Daily, no-inference discovery of current Codex and Claude model releases.

Only same-family cheap/standard roles can advance automatically. Codex additionally
requires the model in the local CLI list. Claude Code has no list command, so an
official same-family ID and a CLI that accepts --model are used; a model error
restores the previous ID before the task retries. Premium profiles stay pinned.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import threading
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

from .models import iso, parse_iso, utcnow

OPENAI_URL = "https://developers.openai.com/api/docs/models"
CLAUDE_URL = "https://platform.claude.com/docs/en/models/overview"
_PATTERNS = {
    "sol": re.compile(r"gpt-(\d+(?:\.\d+)?)-sol\b"),
    "luna": re.compile(r"gpt-(\d+(?:\.\d+)?)-luna\b"),
    "astra": re.compile(r"gpt-(\d+(?:\.\d+)?)-astra\b"),
    "sonnet": re.compile(r"claude-sonnet-(\d+(?:-\d+)?)\b"),
    "haiku": re.compile(r"claude-haiku-(\d+(?:-\d+){0,2})\b"),
    "opus": re.compile(r"claude-opus-(\d+(?:-\d+)?)\b"),
    "fable": re.compile(r"claude-fable-(\d+(?:-\d+)?)\b"),
}
_AUTO_ROLES = frozenset({"sol", "luna", "sonnet", "haiku"})
_LOCK = threading.RLock()


def _version(model: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", model)
    return tuple(int(x) for x in numbers)


def _official_page(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname
    if host not in {"developers.openai.com", "platform.claude.com"}:
        raise ValueError("untrusted model source")
    request = urllib.request.Request(url, headers={"User-Agent": "WWII-Task-Manager/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if urllib.parse.urlparse(response.geturl()).hostname != host:
            raise ValueError("model source redirected to another host")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("model source too large")
    return raw.decode("utf-8", errors="replace")


def _latest(text: str, role: str) -> str | None:
    prefix = "gpt-" if role in {"sol", "luna", "astra"} else "claude-"
    family = role
    candidates = {f"{prefix}{m.group(1)}-{family}" if prefix == "gpt-" else
                  f"{prefix}{family}-{m.group(1)}" for m in _PATTERNS[role].finditer(text)}
    return max(candidates, key=_version) if candidates else None


def _codex_available() -> set[str]:
    binary = shutil.which("codex")
    if not binary:
        return set()
    result = subprocess.run([binary, "debug", "models"], capture_output=True, text=True, timeout=20,
                            check=False)
    if result.returncode:
        return set()
    data = json.loads(result.stdout)
    return {m["slug"] for m in data.get("models", []) if m.get("visibility") == "list" and m.get("slug")}


def _claude_accepts_model() -> bool:
    binary = shutil.which("claude")
    if not binary:
        return False
    result = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=15, check=False)
    return result.returncode == 0 and "--model" in result.stdout


def _override_path(cfg) -> Path:
    return cfg.state_dir / "model_overrides.json"


def _user_pinned_roles(cfg) -> set[str]:
    if not cfg.path or not cfg.path.is_file():
        return set()
    try:
        with open(cfg.path, "rb") as source:
            models = tomllib.load(source).get("models", {})
        return {role for role, options in models.items() if isinstance(options, dict) and "model" in options}
    except (OSError, ValueError):
        return set()


def read_overrides(cfg) -> dict:
    try:
        data = json.loads(_override_path(cfg).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def apply_overrides(cfg) -> None:
    pinned = _user_pinned_roles(cfg)
    for role, value in read_overrides(cfg).items():
        if role in _AUTO_ROLES and isinstance(value, dict) and isinstance(value.get("model"), str):
            if (role in cfg.data["models"] and role not in pinned
                    and value.get("baseline", value.get("previous")) == cfg.data["models"][role]["model"]):
                cfg.data["models"][role] = {**cfg.data["models"][role], "model": value["model"]}


def _write_overrides(cfg, data: dict) -> None:
    path = _override_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)


class ModelWatch:
    def __init__(self, cfg, db):
        self.cfg, self.db = cfg, db

    def due(self) -> bool:
        last = parse_iso(self.db.get_flag("model_watch_checked_at"))
        interval = max(1, float(self.cfg.section("model_watch").get("check_interval_hours", 24)))
        if self.status().get("status") in {"PARTIAL", "UNREACHABLE"}:
            interval = min(interval, 1)
        return last is None or utcnow() - last >= dt.timedelta(hours=interval)

    def status(self) -> dict:
        raw = self.db.get_flag("model_watch_status")
        return json.loads(raw) if raw else {"status": "NOT_CHECKED"}

    def check(self, *, force: bool = False) -> dict:
        with _LOCK:
            if not force and not self.due():
                return self.status()
            checked = iso(utcnow())
            result = {"status": "CHECKED", "checked_at": checked, "sources": [OPENAI_URL, CLAUDE_URL],
                      "discovered": {}, "updated": {}, "waiting_for_local_access": {},
                      "review_candidates": {}, "errors": []}
            pages = {}
            for provider, url in (("codex", OPENAI_URL), ("claude", CLAUDE_URL)):
                try:
                    pages[provider] = _official_page(url)
                except (OSError, ValueError, TimeoutError) as exc:
                    result["errors"].append(f"{provider}: {type(exc).__name__}")
            try:
                codex_models = _codex_available()
            except (OSError, ValueError, subprocess.TimeoutExpired):
                codex_models = set()
            try:
                claude_ready = _claude_accepts_model()
            except (OSError, subprocess.TimeoutExpired):
                claude_ready = False
            overrides = read_overrides(self.cfg)
            pinned = _user_pinned_roles(self.cfg)
            for role in ("astra", "opus", "fable"):
                provider = "codex" if role == "astra" else "claude"
                latest = _latest(pages.get(provider, ""), role)
                if latest:
                    result["discovered"][role] = latest
                    current = self.cfg.data["models"].get(role, {}).get("model")
                    if not current or _version(latest) > _version(current):
                        result["review_candidates"][role] = latest
            for role in _AUTO_ROLES:
                if role in pinned:
                    continue
                provider = self.cfg.data["models"][role]["provider"]
                latest = _latest(pages.get(provider, ""), role)
                if not latest:
                    continue
                result["discovered"][role] = latest
                current = self.cfg.data["models"][role]["model"]
                if _version(latest) <= _version(current):
                    continue
                if overrides.get("_rejected", {}).get(role) == latest:
                    result["waiting_for_local_access"][role] = latest
                    continue
                if (provider == "codex" and latest not in codex_models) or (provider == "claude" and not claude_ready):
                    result["waiting_for_local_access"][role] = latest
                    continue
                source = OPENAI_URL if provider == "codex" else CLAUDE_URL
                overrides[role] = {"model": latest, "previous": current,
                                   "baseline": overrides.get(role, {}).get("baseline", current), "source_url": source,
                                   "updated_at": checked}
                self.cfg.data["models"][role] = {**self.cfg.data["models"][role], "model": latest}
                result["updated"][role] = {"previous": current, "model": latest}
                self.db.event("MODEL_AUTO_UPDATED", provider=provider, role=role, previous=current,
                              model=latest, source_url=source)
            if result["updated"]:
                _write_overrides(self.cfg, overrides)
            if result["errors"]:
                result["status"] = "PARTIAL" if pages else "UNREACHABLE"
            self.db.set_flag("model_watch_checked_at", checked)
            self.db.set_flag("model_watch_status", json.dumps(result, ensure_ascii=False))
            self.db.event("MODEL_WATCH_CHECKED", status=result["status"], discovered=result["discovered"],
                          updated=result["updated"], waiting=result["waiting_for_local_access"],
                          review_candidates=result["review_candidates"], errors=result["errors"])
            return result

    def rollback_on_model_error(self, role: str, model: str) -> bool:
        with _LOCK:
            overrides = read_overrides(self.cfg)
            item = overrides.get(role)
            if not item or item.get("model") != model:
                return False
            previous = item["previous"]
            self.cfg.data["models"][role] = {**self.cfg.data["models"][role], "model": previous}
            overrides.setdefault("_rejected", {})[role] = model
            if previous == item.get("baseline", previous):
                overrides.pop(role)
            else:
                overrides[role] = {**item, "model": previous, "previous": item["baseline"]}
            _write_overrides(self.cfg, overrides)
            status = self.status()
            status.setdefault("rolled_back", {})[role] = {"rejected_model": model, "restored_model": previous}
            status.setdefault("updated", {}).pop(role, None)
            status.setdefault("waiting_for_local_access", {})[role] = model
            self.db.set_flag("model_watch_status", json.dumps(status, ensure_ascii=False))
            self.db.event("MODEL_AUTO_UPDATE_ROLLED_BACK", provider=self.cfg.data["models"][role]["provider"],
                          role=role, rejected_model=model, restored_model=previous)
            return True
