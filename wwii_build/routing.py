"""Deterministic provider/model selection along a profile's fallback chain.

No LLM is consulted. Order of preference:
  user override  >  previous model (retry affinity)  >  best fit for the task profile.
Fit is the only ranking criterion: provider never matters. Equal-fit models are separated by cost tier
(cheaper first) and then by remaining quota headroom.
A premium model that needs approval stops the chain with WAITING_APPROVAL rather
than silently skipping to something else; rejecting it moves to the next entry.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .config import Config
from .models import ExecutionQuote, ProviderStatus, TaskRequest
from .quota import QuotaManager

RUN, WAIT_APPROVAL, WAIT_QUOTA, WAIT_PROVIDER = "RUN", "WAIT_APPROVAL", "WAIT_QUOTA", "WAIT_PROVIDER"


@dataclass
class RouteDecision:
    kind: str
    model_key: str | None = None
    until: dt.datetime | None = None
    reason: str = ""
    chain: list[dict] = field(default_factory=list)   # per-candidate evaluation, for dry-run / dashboard
    quote: ExecutionQuote | None = None


def approval_reason(cfg: Config, task: TaskRequest, key: str) -> str | None:
    m = cfg.model(key)
    appr = cfg.section("approvals")
    if appr.get(key) == "required":
        return f"approvals.{key} = required"
    if not m.automatic:
        return f"models.{key}.automatic = false"
    if task.is_repair and m.tier == "premium" and cfg.section("repair").get("premium_requires_approval", True):
        return "premium model for a repair task (repair.premium_requires_approval)"
    if task.model_profile == "DEEP" and cfg.section("deep").get("require_manual_approval", True):
        return "DEEP profile requires manual approval (deep.require_manual_approval)"
    return None


def fit_chain(cfg: Config, quota: QuotaManager | None, profile: str,
              now: dt.datetime | None = None) -> list[str]:
    """Models for ``profile`` ordered purely by fit; headroom only breaks exact ties."""
    base = cfg.chain(profile) or cfg.chain("IMPLEMENT")
    if quota is None or profile in cfg.data.get("routing", {}):
        return base
    scores = cfg.fit_scores(profile) or cfg.fit_scores("IMPLEMENT")
    tier_cost = {"cheap": 0, "standard": 1, "premium": 2}

    def key(k: str):
        m = cfg.model(k)
        return (-scores.get(k, 0), tier_cost.get(m.tier, 1), -quota.headroom(m.provider, m.family, now), k)
    return sorted(base, key=key)


def candidate_chain(cfg: Config, task: TaskRequest, last_model_key: str | None,
                    preferred: str | None, retry_affinity: bool,
                    quota: QuotaManager | None = None, now: dt.datetime | None = None) -> list[str]:
    chain = fit_chain(cfg, quota, task.model_profile, now)
    if not cfg.section("fallback").get("enabled", True):
        chain = chain[:1]
    if task.extra.get("no_fallback") and preferred:
        chain = []                       # manual task pinned to the chosen model
    out: list[str] = []
    if preferred:
        out.append(preferred)
    if retry_affinity and last_model_key and last_model_key in cfg.data["models"]:
        out.append(last_model_key)
    out.extend(chain)
    seen, uniq = set(), []
    for k in out:
        if k not in seen and k in cfg.data["models"]:
            seen.add(k)
            uniq.append(k)
    return uniq


def select_route(cfg: Config, quota: QuotaManager, task: TaskRequest, *, approvals: dict[str, str],
                 last_model_key: str | None = None, preferred: str | None = None,
                 retry_affinity: bool = False, now: dt.datetime | None = None) -> RouteDecision:
    """``approvals`` maps model_key -> 'approved' | 'rejected' | 'pending' for this task."""
    chain = candidate_chain(cfg, task, last_model_key, preferred, retry_affinity, quota, now)
    report: list[dict] = []

    def rest(after: str) -> list[dict]:
        """Annotate the not-yet-needed fallbacks with their current usability (display only)."""
        out = []
        for k in chain[chain.index(after) + 1:]:
            m = cfg.model(k)
            if not cfg.provider(m.provider).get("enabled", True):
                v = "fallback: provider disabled"
            else:
                av = quota.availability(m.provider, m.family, m.model, now=now)
                v = f"fallback: {'usable' if av.usable else av.status.value}"
                if av.usable and approval_reason(cfg, task, k) and approvals.get(k) != "approved":
                    v += ", needs approval"
            out.append({"model_key": k, "provider": m.provider, "model": m.model, "effort": m.effort, "verdict": v})
        return out
    earliest_reset: dt.datetime | None = None
    hard_reasons: list[str] = []
    for key in chain:
        m = cfg.model(key)
        pcfg = cfg.provider(m.provider)
        entry = {"model_key": key, "provider": m.provider, "model": m.model, "effort": m.effort}
        report.append(entry)
        if not pcfg or not pcfg.get("enabled", True):
            entry["verdict"] = "skip: provider disabled"
            hard_reasons.append(f"{m.provider} disabled")
            continue
        if approvals.get(key) == "rejected":
            entry["verdict"] = "skip: approval rejected"
            continue
        av = quota.availability(m.provider, m.family, m.model, now=now)
        entry["quota_status"] = av.status.value
        if not av.usable:
            if av.until is not None:
                entry["verdict"] = f"skip: quota blocked until {av.until.isoformat(timespec='minutes')}"
                earliest_reset = av.until if earliest_reset is None or av.until < earliest_reset else earliest_reset
            else:
                entry["verdict"] = f"skip: {av.reason or av.status.value}"
                hard_reasons.append(av.reason or f"{m.provider}: {av.status.value}")
            continue
        quote = ExecutionQuote(provider=m.provider, model_key=key, quota_family=m.family,
                               billing_mode="subscription")
        need = approval_reason(cfg, task, key)
        if need and approvals.get(key) != "approved":
            quote.requires_approval, quote.approval_reason = True, need
            entry["verdict"] = f"needs approval ({need})"
            return RouteDecision(WAIT_APPROVAL, key, reason=f"approval required for {key}: {need}",
                                 chain=report + rest(key), quote=quote)
        entry["verdict"] = "selected"
        warn = " (NEAR_LIMIT)" if av.status == ProviderStatus.NEAR_LIMIT else ""
        return RouteDecision(RUN, key, reason=f"{m.provider}/{m.model}{warn}", chain=report + rest(key), quote=quote)
    if earliest_reset is not None and cfg.section("fallback").get("wait_when_exhausted", True):
        return RouteDecision(WAIT_QUOTA, None, until=earliest_reset,
                             reason=f"all candidates quota-blocked; earliest reset {earliest_reset.isoformat(timespec='minutes')}",
                             chain=report)
    return RouteDecision(WAIT_PROVIDER, None, reason="; ".join(hard_reasons) or "no provider candidate",
                         chain=report)
