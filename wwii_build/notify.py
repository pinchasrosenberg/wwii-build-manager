"""Optional local macOS notifications, debounced per key (no spam per small task)."""
from __future__ import annotations

import subprocess
import sys
import time


class Notifier:
    def __init__(self, cfg: dict, db=None):
        self.enabled = bool(cfg.get("enabled", True)) and sys.platform == "darwin"
        self.min_interval = float(cfg.get("min_interval_seconds", 300))
        self.last: dict[str, float] = {}
        self.db = db

    def notify(self, key: str, title: str, message: str) -> None:
        now = time.time()
        if now - self.last.get(key, 0) < self.min_interval:
            return
        self.last[key] = now
        if self.db:
            self.db.event("NOTIFICATION", key=key, title=title, message=message[:200])
        if not self.enabled:
            return
        script = f'display notification {_q(message[:200])} with title {_q("WWII Build: " + title)}'
        try:
            subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
