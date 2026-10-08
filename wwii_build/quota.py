"""QuotaManager: per provider/account/family availability.

Rules:
* Never invent a usage percentage. ``used_percent`` is only stored when a CLI
  reports it machine-readably (Codex app-server). Otherwise it stays NULL and the
  dashboard says "unknown".
* A limit hit blocks only the scope it names (session/weekly/model family).
* Known reset -> blocked until reset + safety margin. Unknown reset -> bounded
  backoff (15m, 30m, 60m, 120m ...), never a busy loop.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

from .db import DB
from .models import (HARD_UNAVAILABLE, QUOTA_BLOCKED, ProviderStatus, QuotaSignal,
                     iso, parse_iso, utcnow)

ACCOUNT = "default"


@dataclass
class Availability:
    status: ProviderStatus
    usable: bool
    until: dt.datetime | None = None
    reason: str = ""


class QuotaManager:
    def __init__(self, db: DB, quota_cfg: dict):
        self.db = db
        self.margin = dt.timedelta(seconds=int(quota_cfg.get("reset_safety_margin_seconds", 120)))
        self.backoff = [int(m) for m in quota_cfg.get("unknown_backoff_minutes", [15, 30, 60, 120])]
        self.near_pct = float(quota_cfg.get("near_limit_percent", 90))

    # --- rows ---------------------------------------------------------------
    def row(self, provider: str, family: str = "*") -> dict:
        r = self.db.one("SELECT * FROM provider_state WHERE provider=? AND account=? AND family=?",
                        (provider, ACCOUNT, family))
        if r is None:
            self.db.x("INSERT OR IGNORE INTO provider_state(provider,account,family,status) VALUES(?,?,?,?)",
                      (provider, ACCOUNT, family, ProviderStatus.UNKNOWN.value))
            r = self.db.one("SELECT * FROM provider_state WHERE provider=? AND account=? AND family=?",
                            (provider, ACCOUNT, family))
        return dict(r)

    def _update(self, provider: str, family: str, **fields) -> None:
        self.row(provider, family)
        fields["last_checked_at"] = fields.get("last_checked_at") or iso(utcnow())
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.x(f"UPDATE provider_state SET {sets} WHERE provider=? AND account=? AND family=?",
                  (*fields.values(), provider, ACCOUNT, family))

    def rows(self, provider: str | None = None) -> list[dict]:
        if provider:
            return [dict(r) for r in self.db.q("SELECT * FROM provider_state WHERE provider=? ORDER BY family", (provider,))]
        return [dict(r) for r in self.db.q("SELECT * FROM provider_state ORDER BY provider, family")]

    def accounts(self) -> list[dict]:
        """One row per provider (the account-wide '*' row: 5-hour session + weekly window). Per-family and
        per-model restrictions stay internal for routing; here they are only a ``notes`` list on that row."""
        out = []
        for provider in [r["provider"] for r in self.db.q("SELECT DISTINCT provider FROM provider_state ORDER BY provider")]:
            rows = self.rows(provider)
            main = next((r for r in rows if r["family"] == "*"), None) or self.row(provider, "*")
            notes = []
            for r in rows:
                if r["family"] == "*" or r["status"] in (ProviderStatus.AVAILABLE.value, ProviderStatus.UNKNOWN.value):
                    continue
                until = f" until {r['blocked_until']}" if r["blocked_until"] else ""
                notes.append(f"{r['family']}: {r['status']}{until}")
            out.append(dict(main, family="*", notes=notes))
        return out

    # --- queries ------------------------------------------------------------
    def availability(self, provider: str, family: str = "*", model: str | None = None,
                     now: dt.datetime | None = None) -> Availability:
        now = now or utcnow()
        scopes = ["*"]
        if family and family != "*":
            scopes.append(family)
        if model:
            scopes.append(f"model:{model}")
        blocked_until: dt.datetime | None = None
        blocked_status = None
        for fam in scopes:
            r = self.db.one("SELECT * FROM provider_state WHERE provider=? AND account=? AND family=?",
                            (provider, ACCOUNT, fam))
            if r is None:
                continue
            st = ProviderStatus(r["status"])
            if st == ProviderStatus.MODEL_UNAVAILABLE and fam.startswith("model:") and self._model_block_expired(r, now):
                continue     # a rejected model ID is re-probed after a while (the CLI may have been upgraded)
            if st in HARD_UNAVAILABLE:
                return Availability(st, False, None, f"{provider}/{fam}: {st.value} {r['detail'] or ''}".strip())
            if st in QUOTA_BLOCKED:
                until = parse_iso(r["blocked_until"])
                if until and until > now:
                    if blocked_until is None or until > blocked_until:
                        blocked_until, blocked_status = until, st
        if blocked_until:
            return Availability(blocked_status, False, blocked_until,
                                f"{provider}: {blocked_status.value} until {iso(blocked_until)}")
        top = self.row(provider, "*")
        st = ProviderStatus(top["status"])
        if st in QUOTA_BLOCKED:   # reset time passed: a probe run is allowed
            return Availability(ProviderStatus.UNKNOWN, True, None, "reset time passed; probing")
        return Availability(st, True, None, "")

    def headroom(self, provider: str, family: str = "*", now: dt.datetime | None = None) -> float:
        """Remaining quota in percent (100 = untouched). Windows whose reset time already passed count as unused;
        unknown usage counts as 100 so a missing reading never penalises a model."""
        now = now or utcnow()
        used = 0.0
        for fam in {"*", family or "*"}:
            r = self.db.one("SELECT * FROM provider_state WHERE provider=? AND account=? AND family=?",
                            (provider, ACCOUNT, fam))
            if r is None:
                continue
            for pct_col, reset_col in (("session_used_percent", "session_reset_at"),
                                       ("weekly_used_percent", "weekly_reset_at")):
                pct, reset = r[pct_col], parse_iso(r[reset_col])
                if pct is None or (reset is not None and reset <= now):
                    continue
                used = max(used, float(pct))
            if r["session_used_percent"] is None and r["weekly_used_percent"] is None and r["used_percent"] is not None:
                reset = parse_iso(r["weekly_reset_at"]) or parse_iso(r["session_reset_at"])
                if reset is None or reset > now:
                    used = max(used, float(r["used_percent"]))
        return max(0.0, 100.0 - used)

    MODEL_RETRY = dt.timedelta(minutes=60)

    def _model_block_expired(self, row, now: dt.datetime) -> bool:
        checked = parse_iso(row["last_checked_at"])
        return checked is None or now - checked >= self.MODEL_RETRY

    def next_reset(self, now: dt.datetime | None = None) -> dt.datetime | None:
        now = now or utcnow()
        best = None
        for r in self.db.q("SELECT blocked_until FROM provider_state WHERE blocked_until IS NOT NULL"):
            t = parse_iso(r["blocked_until"])
            if t and t > now and (best is None or t < best):
                best = t
        return best

    def snapshot(self, provider: str) -> str:
        return json.dumps([{k: r[k] for k in ("family", "status", "blocked_until", "used_percent", "confidence")}
                           for r in self.rows(provider)])

    # --- writes -------------------------------------------------------------
    def set_status(self, provider: str, status: ProviderStatus, detail: str = "", source: str = "",
                   family: str = "*", confidence: str = "high") -> None:
        prev = self.row(provider, family)
        fields = dict(status=status.value, detail=detail[:500], source=source, confidence=confidence)
        if status not in QUOTA_BLOCKED:
            fields["blocked_until"] = None
        self._update(provider, family, **fields)
        if prev["status"] != status.value:
            self.db.event("PROVIDER_STATUS", provider=provider, family=family, status=status.value,
                          previous=prev["status"], detail=detail[:300])

    def record_signal(self, sig: QuotaSignal, attempt_id: int | None = None) -> None:
        now = utcnow()
        self.db.x("INSERT INTO quota_events(at,provider,family,kind,window,reset_at,attempt_id,source,raw) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  (iso(now), sig.provider, sig.family, sig.kind, sig.window, iso(sig.reset_at),
                   attempt_id, "run", (sig.raw or "")[:2000]))
        row = self.row(sig.provider, sig.family)
        reset_fields = {"data_at": iso(now)}
        if sig.windows:
            # One event carries both account-wide windows: refresh them together on the account row so a weekly
            # event can never leave a stale session percentage behind (or vice versa).
            wf = {"data_at": iso(now), "source": "run (rate_limit_event)", "confidence": "high"}
            top = None
            for name, (pct, reset) in sig.windows.items():
                if pct is not None:
                    wf[f"{name}_used_percent"] = pct
                    top = pct if top is None else max(top, pct)
                if reset is not None:
                    wf[f"{name}_reset_at"] = iso(reset)
            if top is not None:
                wf["used_percent"] = top
            self._update(sig.provider, "*", **wf)
            if sig.family == "*":
                row = self.row(sig.provider, "*")
                reset_fields = {"data_at": iso(now)}
        if sig.reset_at:
            reset_fields["weekly_reset_at" if sig.window == "weekly" else "session_reset_at"] = iso(sig.reset_at)
        account_windows = bool(sig.windows) and sig.family == "*"
        if sig.used_percent is not None and not account_windows:
            reset_fields["used_percent"] = sig.used_percent
            if sig.window in ("weekly", "session") and not sig.windows:
                reset_fields[f"{sig.window}_used_percent"] = sig.used_percent
        if sig.kind == "SNAPSHOT":
            blocked = row["status"] in {s.value for s in QUOTA_BLOCKED}
            if not blocked:
                seen = [p for p, _ in (sig.windows or {}).values() if p is not None] if account_windows else []
                top = max(seen) if seen else sig.used_percent
                near = top is not None and top >= self.near_pct
                reset_fields["status"] = (ProviderStatus.NEAR_LIMIT if near else ProviderStatus.AVAILABLE).value
            self._update(sig.provider, sig.family, source="run (rate_limit_event)", confidence="high", **reset_fields)
            return
        if sig.kind == "WARNING":
            if row["status"] not in {s.value for s in QUOTA_BLOCKED}:
                self._update(sig.provider, sig.family, status=ProviderStatus.NEAR_LIMIT.value,
                             last_limit_event=iso(now), source="run", confidence="medium", **reset_fields)
            return
        if sig.kind not in ("LIMIT_HIT", "OVERAGE"):
            return
        status = {"session": ProviderStatus.BLOCKED_SESSION, "weekly": ProviderStatus.BLOCKED_WEEKLY,
                  "model": ProviderStatus.BLOCKED_WEEKLY}.get(sig.window, ProviderStatus.BLOCKED_UNKNOWN)
        level = int(row["backoff_level"] or 0)
        if sig.reset_at:
            until = sig.reset_at + self.margin
            confidence, level = "high", 0
        else:
            minutes = self.backoff[min(level, len(self.backoff) - 1)]
            until = now + dt.timedelta(minutes=minutes)
            confidence, level = "low", level + 1
        self._update(sig.provider, sig.family, status=status.value, blocked_until=iso(until),
                     last_limit_event=iso(now), confidence=confidence, backoff_level=level,
                     source="run" if sig.kind == "LIMIT_HIT" else "run(overage refused)",
                     detail=(sig.raw or "")[:300], **reset_fields)
        self.db.event("PROVIDER_LIMIT", attempt_id=attempt_id, provider=sig.provider, family=sig.family,
                      window=sig.window, blocked_until=iso(until), reset_known=bool(sig.reset_at))

    def record_success(self, provider: str, family: str = "*") -> None:
        now = iso(utcnow())
        for fam in {"*", family}:
            row = self.row(provider, fam)
            fields = dict(last_success_at=now, backoff_level=0)
            if row["status"] in {s.value for s in QUOTA_BLOCKED} | {ProviderStatus.UNKNOWN.value}:
                fields.update(status=ProviderStatus.AVAILABLE.value, blocked_until=None,
                              source="last run succeeded", confidence="low")
            self._update(provider, fam, **fields)

    def record_codex_snapshot(self, result: dict, near_pct: float, stop_pct: float) -> None:
        """Map app-server ``account/rateLimits/read`` into provider_state (family '*')."""
        now = utcnow()
        snap = (result.get("rateLimitsByLimitId") or {}).get("codex") or result.get("rateLimits") or {}
        windows = [w for w in (snap.get("primary"), snap.get("secondary")) if w]
        session_reset = weekly_reset = None
        session_pct = weekly_pct = None
        blocked = None
        max_pct = None
        for w in windows:
            pct = w.get("usedPercent")
            reset = dt.datetime.fromtimestamp(w["resetsAt"], dt.timezone.utc) if w.get("resetsAt") else None
            mins = w.get("windowDurationMins")
            kind = "weekly" if mins and mins >= 7 * 24 * 60 else "session"
            if kind == "weekly":
                weekly_reset, weekly_pct = reset, pct
            else:
                session_reset, session_pct = reset, pct
            if pct is not None:
                max_pct = pct if max_pct is None else max(max_pct, pct)
                if pct >= stop_pct and (blocked is None or (reset and blocked[1] and reset > blocked[1])):
                    blocked = (kind, reset)
        if snap.get("rateLimitReachedType") and not blocked:
            blocked = ("unknown", weekly_reset or session_reset)
        fields = dict(used_percent=max_pct, session_reset_at=iso(session_reset), weekly_reset_at=iso(weekly_reset),
                      session_used_percent=session_pct, weekly_used_percent=weekly_pct, data_at=iso(now),
                      window_minutes=max((w.get("windowDurationMins") or 0) for w in windows) if windows else None,
                      source="codex app-server account/rateLimits/read", confidence="high",
                      detail=f"plan={snap.get('planType')}")
        if blocked:
            status = {"weekly": ProviderStatus.BLOCKED_WEEKLY, "session": ProviderStatus.BLOCKED_SESSION}.get(
                blocked[0], ProviderStatus.BLOCKED_UNKNOWN)
            until = (blocked[1] + self.margin) if blocked[1] else now + dt.timedelta(minutes=self.backoff[0])
            fields.update(status=status.value, blocked_until=iso(until), last_limit_event=iso(now))
        elif max_pct is not None and max_pct >= near_pct:
            fields.update(status=ProviderStatus.NEAR_LIMIT.value, blocked_until=None)
        else:
            fields.update(status=ProviderStatus.AVAILABLE.value, blocked_until=None)
        cur = self.row("codex", "*")
        prev = cur["status"]
        cur_until = parse_iso(cur["blocked_until"])
        if (prev in {s.value for s in QUOTA_BLOCKED} and cur_until and cur_until > now
                and str(cur["source"] or "").startswith("run") and fields["status"] not in {s.value for s in QUOTA_BLOCKED}):
            # A limit observed in a real run wins over a snapshot until its reset time.
            fields.update(status=prev, blocked_until=cur["blocked_until"], source=cur["source"],
                          confidence=cur["confidence"], detail=f"snapshot disagrees (used {max_pct}%); keeping run limit")
            self.db.event("QUOTA_SNAPSHOT_CONFLICT", provider="codex", used_percent=max_pct, kept_until=cur["blocked_until"])
        self._update("codex", "*", **fields)
        self.db.x("INSERT INTO quota_events(at,provider,family,kind,window,reset_at,source,raw) VALUES(?,?,?,?,?,?,?,?)",
                  (iso(now), "codex", "*", "SNAPSHOT", blocked[0] if blocked else None,
                   fields.get("blocked_until"), "app-server", json.dumps({"used_percent": max_pct,
                                                                          "status": fields["status"]})))
        if prev != fields["status"]:
            self.db.event("PROVIDER_STATUS", provider="codex", family="*", status=fields["status"], previous=prev,
                          used_percent=max_pct)

    def user_reset(self, provider: str) -> list[str]:
        """The user reports they performed a usage reset in the provider's own app.
        Clears quota blocks for that provider; the manager never performs a reset itself."""
        cleared = []
        for r in self.rows(provider):
            if r["status"] in {s.value for s in QUOTA_BLOCKED} | {ProviderStatus.NEAR_LIMIT.value}:
                self._update(provider, r["family"], status=ProviderStatus.UNKNOWN.value, blocked_until=None,
                             backoff_level=0, confidence="low", source="user reported reset (in app)",
                             detail=f"was {r['status']} until {r['blocked_until'] or 'unknown'}")
                cleared.append(f"{r['family']}:{r['status']}")
        self.db.x("INSERT INTO quota_events(at,provider,family,kind,source,raw) VALUES(?,?,?,?,?,?)",
                  (iso(utcnow()), provider, "*", "USER_RESET", "user", json.dumps(cleared)))
        self.db.event("PROVIDER_RESET_REPORTED", provider=provider, cleared=cleared)
        return cleared
