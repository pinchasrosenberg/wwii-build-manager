"""Parse limit / auth / model errors out of CLI output into QuotaSignals.

Only formats observed in the installed binaries are relied on:
* Codex 0.148: "You've hit your usage limit ... Try again at <time>" and
  error codes ``usage_limit_reached`` / ``UsageLimitReached``.
* Claude Code 2.1.280: stream-json ``rate_limit_event`` with ``rate_limit_info``
  {status, resetsAt, rateLimitType (five_hour | seven_day | seven_day_opus |
  seven_day_sonnet), utilization, isUsingOverage, overageStatus}; plus text
  "Usage limit reached" / "You've hit your ... limit".
Unknown shapes degrade to a limit with ``reset_at=None`` (bounded backoff).
"""
from __future__ import annotations

import datetime as dt
import re

from ..models import QuotaSignal

_CODEX_LIMIT = re.compile(r"(you'?ve hit your usage limit|usage_limit_reached|UsageLimitReached|rate[_ ]limit[_ ]reached)", re.I)
_CLAUDE_LIMIT = re.compile(r"(usage limit reached|you'?ve hit your [\w -]*limit|\b5-hour limit|weekly limit|limit reached\s*[∙·|]\s*resets)", re.I)
_TRY_AGAIN = re.compile(r"try again (?:at|in)\s+([^.\n\"]+)", re.I)
_RESETS = re.compile(r"resets?\s+(?:at\s+)?([^\n\"·∙|)]+)", re.I)
_PIPE_EPOCH = re.compile(r"limit reached\|(\d{9,11})", re.I)
_AUTH = re.compile(r"(not logged in|please (?:run )?/?login|invalid api key|authentication[_ ]error|401 unauthorized|"
                   r"token (?:has )?expired|oauth token|login required|unauthori[sz]ed)", re.I)
_MODEL = re.compile(r"(model[_ ]not[_ ]found|unrecognized_model|unknown model|model .{0,60}(?:does not exist|not available|not supported|"
                    r"unavailable)|invalid model|no access to model|not_found_error|issue with the selected model|"
                    r"may not exist or you may not have access|requires a newer version of (?:codex|claude)|"
                    r"model is not supported (?:in|by) this version)", re.I)
_WEEKLY = re.compile(r"(weekly|seven[_ ]day|7[- ]day)", re.I)
_SESSION = re.compile(r"(five[_ ]hour|5[- ]hour|session)", re.I)
_FAMILY_LIMIT = re.compile(r"\b(opus|sonnet)\b[^.\n]{0,24}\blimit", re.I)


def parse_time_phrase(phrase: str, now: dt.datetime) -> dt.datetime | None:
    """Best-effort parse of a reset phrase. Returns None rather than guessing."""
    s = phrase.strip().rstrip(".").strip()
    s = re.sub(r"\s*\((?:[A-Za-z_]+/[A-Za-z_]+|UTC|GMT[+-]?\d*)\)\s*$", "", s)   # drop tz label
    m = re.fullmatch(r"(\d+)\s*(second|sec|minute|min|hour|hr|day)s?", s, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        mult = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400}[unit]
        return now + dt.timedelta(seconds=n * mult)
    if re.fullmatch(r"\d{9,11}", s):
        return dt.datetime.fromtimestamp(int(s), dt.timezone.utc)
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.astimezone()
    except ValueError:
        pass
    local_now = now.astimezone()
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"):
        try:
            t = dt.datetime.strptime(s.upper(), fmt).time()
        except ValueError:
            continue
        cand = local_now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if cand <= local_now - dt.timedelta(minutes=2):   # clearly past -> tomorrow; same minute -> imminent
            cand += dt.timedelta(days=1)
        return cand.astimezone(dt.timezone.utc)
    for fmt in ("%b %d, %Y %I:%M %p", "%b %d %I:%M %p", "%b %d, %I:%M %p", "%b %d at %I:%M %p", "%B %d, %Y %I:%M %p"):
        try:
            d = dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
        if d.year == 1900:
            d = d.replace(year=local_now.year)
        d = d.replace(tzinfo=local_now.tzinfo)
        if d < local_now - dt.timedelta(days=1):
            d = d.replace(year=d.year + 1)
        return d.astimezone(dt.timezone.utc)
    return None


def _window(text: str) -> str:
    if _WEEKLY.search(text):
        return "weekly"
    if _SESSION.search(text):
        return "session"
    return "unknown"


def codex_limit_from_text(text: str, now: dt.datetime) -> QuotaSignal | None:
    if not text or not _CODEX_LIMIT.search(text):
        return None
    reset = None
    m = _TRY_AGAIN.search(text)
    if m:
        reset = parse_time_phrase(m.group(1), now)
    return QuotaSignal("codex", "*", "LIMIT_HIT", _window(text), reset, raw=text[-600:])


def claude_limit_from_text(text: str, now: dt.datetime, model_family: str) -> QuotaSignal | None:
    if not text or not _CLAUDE_LIMIT.search(text):
        return None
    reset = None
    m = _PIPE_EPOCH.search(text)
    if m:
        reset = dt.datetime.fromtimestamp(int(m.group(1)), dt.timezone.utc)
    else:
        m = _RESETS.search(text) or _TRY_AGAIN.search(text)
        if m:
            reset = parse_time_phrase(m.group(1), now)
    m = _FAMILY_LIMIT.search(text)
    fam = m.group(1).lower() if m else "*"
    return QuotaSignal("claude", fam, "LIMIT_HIT", _window(text), reset, raw=text[-600:])


def _utilization_percent(value) -> float | None:
    """Claude reports utilization as a 0..1 fraction; anything above 1 is already a percentage."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return float(value) * 100 if value <= 1 else float(value)


def _claude_windows(info: dict) -> dict | None:
    """Both account-wide windows of one rate_limit_event (it names only one in ``rateLimitType``)."""
    out = {}
    for name, key in (("session", "five_hour"), ("weekly", "seven_day")):
        w = (info.get("unifiedWindows") or {}).get(key)
        if not isinstance(w, dict):
            continue
        reset = w.get("resetsAt")
        out[name] = (_utilization_percent(w.get("utilization")),
                     dt.datetime.fromtimestamp(int(reset), dt.timezone.utc) if isinstance(reset, (int, float)) else None)
    return out or None


def claude_rate_limit_event(info: dict) -> QuotaSignal | None:
    """Map Claude stream-json ``rate_limit_info``."""
    status = str(info.get("status") or "")
    rtype = str(info.get("rateLimitType") or "")
    reset = info.get("resetsAt")
    reset_at = dt.datetime.fromtimestamp(int(reset), dt.timezone.utc) if isinstance(reset, (int, float)) else None
    family = {"seven_day_opus": "opus", "seven_day_sonnet": "sonnet"}.get(rtype, "*")
    window = "session" if rtype == "five_hour" else ("weekly" if rtype.startswith("seven_day") else "unknown")
    used = _utilization_percent(info.get("utilization"))
    windows = _claude_windows(info)
    raw = str(info)[:600]
    if info.get("isUsingOverage"):
        return QuotaSignal("claude", family, "OVERAGE", window, reset_at, used, raw=raw, windows=windows)
    if status == "rejected":
        return QuotaSignal("claude", family, "LIMIT_HIT", window, reset_at, used, raw=raw, windows=windows)
    if status == "allowed_warning":
        return QuotaSignal("claude", family, "WARNING", window, reset_at, used, raw=raw, windows=windows)
    if used is not None or reset_at is not None or windows:   # ordinary "allowed" event: still fresh usage data
        return QuotaSignal("claude", family, "SNAPSHOT", window, reset_at, used, raw=raw, windows=windows)
    return None


def is_auth_error(text: str) -> bool:
    return bool(text and _AUTH.search(text))


def is_model_error(text: str) -> bool:
    return bool(text and _MODEL.search(text))
