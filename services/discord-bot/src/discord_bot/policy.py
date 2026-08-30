"""Discord alert policy. State-change only. No noise. Not a buy signal.

Pure functions. Tests do not need a Discord connection.
"""

from __future__ import annotations

from typing import Any

POLICY_VERSION = "discord-policy-v1.0.0"

CRITICAL = "CRITICAL"
WARNING = "WARNING"
OPPORTUNITY = "OPPORTUNITY"
INTELLIGENCE = "INTELLIGENCE"
RESOLVED = "RESOLVED"

DIP = {"WATCH", "DETERIORATING", "SEVERE_DETERIORATION", "FAILED"}
SEVERITY_RANK = {
    None: 0,
    "WATCH": 1,
    WARNING: 2,
    CRITICAL: 3,
    RESOLVED: 1,
    INTELLIGENCE: 1,
    OPPORTUNITY: 2,
}

COOLDOWN_SEC = 600.0


def alert_id(*, mint: str, previous: str, current: str, category: str) -> str:
    return f"{mint}:{previous}->{current}:{category}"


def category_for_transition(previous: str | None, current: str) -> str | None:
    prev = (previous or "UNKNOWN").upper()
    cur = (current or "UNKNOWN").upper()
    if prev == cur:
        return None
    if cur == "UNKNOWN":
        return None
    if cur in ("FAILED", "SEVERE_DETERIORATION"):
        return CRITICAL
    if cur == "DETERIORATING":
        return WARNING
    if cur == "WATCH":
        return "WATCH"
    if prev in DIP and cur not in DIP:
        return RESOLVED
    return None


def should_alert(
    *,
    mint: str,
    previous_state: str | None,
    current_state: str,
    last_alert_at: float | None = None,
    last_category: str | None = None,
    now: float,
    event_id: str | None = None,
) -> dict[str, Any] | None:
    """Return an alert spec or None. Same state is silent. Cooldown unless severity upgrades."""
    cur = (current_state or "UNKNOWN").upper()
    prev = (previous_state or "UNKNOWN").upper()
    cat = category_for_transition(prev, cur)
    if cat is None:
        return None
    aid = alert_id(mint=mint, previous=prev, current=cur, category=cat)
    if last_alert_at is not None and last_category == cat:
        if now - last_alert_at < COOLDOWN_SEC:
            new_rank = SEVERITY_RANK.get(cat, 0)
            old_rank = SEVERITY_RANK.get(last_category, 0)
            if new_rank <= old_rank:
                return None
    return {
        "version": POLICY_VERSION,
        "alert_id": aid,
        "event_id": event_id or aid,
        "mint": mint,
        "category": cat,
        "previous_state": prev,
        "current_state": cur,
        "calibrated_probability": False,
        "not_a_buy": True,
        "not_a_sell": True,
        "note": "State-change notification. Not a trade signal.",
    }


def format_quality_alert(
    spec: dict[str, Any],
    *,
    why: list[Any] | None = None,
    evidence_quality: str | None = None,
    timestamp: str | None = None,
    unknown: list[str] | None = None,
) -> str:
    """Render Discord text. Never a buy/sell. Does not send."""
    reasons: list[str] = []
    for item in why or []:
        if isinstance(item, dict):
            exp = str(item.get("explanation") or "").strip()
            if exp:
                reasons.append(exp)
        else:
            s = str(item).strip()
            if s:
                reasons.append(s)
    why_line = "; ".join(reasons[:4]) if reasons else "state change observed"
    unk = ", ".join(unknown or []) if unknown else "—"
    return (
        f"**STINKY {spec.get('category')}**\n"
        f"CA: `{spec.get('mint')}`\n"
        f"{spec.get('previous_state')} → {spec.get('current_state')}\n"
        f"Why: {why_line}\n"
        f"Evidence: {evidence_quality or 'UNKNOWN'}\n"
        f"Time: {timestamp or 'UNKNOWN'}\n"
        f"UNKNOWN fields: {unk}\n"
        f"Not a buy. Not a sell. Quality is setup deterioration, not a trade signal."
    )

