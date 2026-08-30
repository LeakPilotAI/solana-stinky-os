"""Quality state of a Gate-1 investigation. Post-decision. Not a score. Not a buy.

A quality dip is meaningful deterioration of the observed setup, not "price down".
Missing data stays UNKNOWN. Tiny fluctuations are ignored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stinky_core.memory import IntelligenceMemory, _parse_ts

QUALITY_VERSION = "quality-state-v1.0.0"

UNKNOWN = "UNKNOWN"
HEALTHY = "HEALTHY"
IMPROVING = "IMPROVING"
STABLE = "STABLE"
WATCH = "WATCH"
DETERIORATING = "DETERIORATING"
SEVERE_DETERIORATION = "SEVERE_DETERIORATION"
FAILED = "FAILED"

STATES = (
    UNKNOWN,
    HEALTHY,
    IMPROVING,
    STABLE,
    WATCH,
    DETERIORATING,
    SEVERE_DETERIORATION,
    FAILED,
)
DIP_STATES = {WATCH, DETERIORATING, SEVERE_DETERIORATION, FAILED}
RANK = {
    UNKNOWN: 0,
    HEALTHY: 1,
    IMPROVING: 2,
    STABLE: 3,
    WATCH: 4,
    DETERIORATING: 5,
    SEVERE_DETERIORATION: 6,
    FAILED: 7,
}

# Material floors. Not score weights. Documented, versioned, testable.
NOISE_BAND = 0.15
LIQ_WATCH = 0.40
LIQ_DETERIORATING = 0.70
LIQ_FAILED = 0.90
VOL_WATCH = 0.70
VOL_SEVERE = 0.90
SELL_WATCH = 0.35
SELL_DETERIORATING = 0.20
MIN_TXNS_PRESSURE = 10
IMPROVE_LIFT = 0.25


def ui_severity(state: str) -> str | None:
    if state in (FAILED, SEVERE_DETERIORATION):
        return "CRITICAL"
    if state == DETERIORATING:
        return "WARNING"
    if state == WATCH:
        return "WATCH"
    return None


def _change(prev: float | None, cur: float | None) -> float | None:
    if prev is None or cur is None or prev == 0:
        return None
    return (cur - prev) / abs(prev)


def _drop(prev: float | None, cur: float | None) -> float | None:
    ch = _change(prev, cur)
    if ch is None:
        return None
    return -ch if ch < 0 else 0.0


def _evidence_quality(missing: list[str], later_n: int) -> str:
    if later_n <= 0:
        return "UNKNOWN"
    if len(missing) >= 4:
        return "POOR"
    if missing or later_n < 2:
        return "LIMITED"
    return "GOOD"


def evaluate_quality_state(
    memory: IntelligenceMemory,
    *,
    mint: str,
    t0: Any,
    as_of: Any = None,
    rug_level: str | None = None,
    previous_state: str | None = None,
) -> dict[str, Any]:
    """Label current quality from stored ticks vs Gate-1 snapshot.

    Wallet/creator stay T+0. Later ticks after as_of are hidden.
    """
    start = _parse_ts(t0)
    cutoff = _parse_ts(as_of) or datetime.now(timezone.utc)
    empty = {
        "version": QUALITY_VERSION,
        "mint": mint,
        "t0": start.isoformat() if start else None,
        "as_of": cutoff.isoformat() if cutoff else None,
        "state": UNKNOWN,
        "previous_state": previous_state or UNKNOWN,
        "severity": None,
        "is_dip": False,
        "why": [],
        "known": [],
        "unknown": ["later_market_path"],
        "evidence_quality": "UNKNOWN",
        "calibrated_probability": False,
        "note": "Only T+0 or missing decision time — cannot assess deterioration.",
    }
    if start is None:
        return empty

    ticks = sorted(
        (t for t in getattr(memory, "market_ticks", []) if t.mint == mint),
        key=lambda x: x.observed_at,
    )
    gate = next((t for t in ticks if t.observed_at == start), None)
    later = [t for t in ticks if t.observed_at > start and t.observed_at <= cutoff]
    if gate is None and ticks:
        gate = next((t for t in ticks if t.observed_at <= start), None)
    if not later:
        return empty

    latest = later[-1]
    why: list[dict[str, Any]] = []
    unknown: list[str] = []
    known: list[str] = []
    worst = STABLE

    def consider(state: str) -> None:
        nonlocal worst
        if RANK.get(state, 0) > RANK.get(worst, 0):
            worst = state

    g_liq = gate.liquidity_usd if gate else None
    l_liq = latest.liquidity_usd
    liq_drop = _drop(g_liq, l_liq)
    liq_ch = _change(g_liq, l_liq)
    if g_liq is None or l_liq is None:
        unknown.append("liquidity")
    else:
        known.append("liquidity")
        if liq_drop is not None and liq_drop >= LIQ_FAILED:
            consider(FAILED)
            why.append(_why("liquidity_usd", g_liq, l_liq, liq_ch, latest.observed_at, "liquidity collapsed ≥ 90% vs Gate 1"))
        elif liq_drop is not None and liq_drop >= LIQ_DETERIORATING:
            consider(SEVERE_DETERIORATION)
            why.append(_why("liquidity_usd", g_liq, l_liq, liq_ch, latest.observed_at, "liquidity down ≥ 70% vs Gate 1"))
        elif liq_drop is not None and liq_drop >= LIQ_WATCH:
            consider(WATCH)
            why.append(_why("liquidity_usd", g_liq, l_liq, liq_ch, latest.observed_at, "liquidity down ≥ 40% vs Gate 1"))
        elif liq_ch is not None and liq_ch >= IMPROVE_LIFT:
            consider(IMPROVING)
            why.append(_why("liquidity_usd", g_liq, l_liq, liq_ch, latest.observed_at, "liquidity up ≥ 25% vs Gate 1"))

    g_vol = gate.volume_m5_usd if gate else None
    l_vol = latest.volume_m5_usd
    vol_drop = _drop(g_vol, l_vol)
    vol_ch = _change(g_vol, l_vol)
    if g_vol is None or l_vol is None:
        unknown.append("volume_5m")
    else:
        known.append("volume_5m")
        if vol_drop is not None and vol_drop >= VOL_SEVERE:
            consider(SEVERE_DETERIORATION)
            why.append(_why("volume_m5_usd", g_vol, l_vol, vol_ch, latest.observed_at, "5m volume down ≥ 90% vs Gate 1"))
        elif vol_drop is not None and vol_drop >= VOL_WATCH:
            consider(WATCH)
            why.append(_why("volume_m5_usd", g_vol, l_vol, vol_ch, latest.observed_at, "5m volume down ≥ 70% vs Gate 1"))
        elif vol_ch is not None and vol_ch >= IMPROVE_LIFT and RANK[worst] <= RANK[STABLE]:
            consider(IMPROVING)
            why.append(_why("volume_m5_usd", g_vol, l_vol, vol_ch, latest.observed_at, "5m volume up ≥ 25% vs Gate 1"))

    ratio = latest.buy_sell_ratio
    txns = latest.txns
    if ratio is None or txns is None or txns < MIN_TXNS_PRESSURE:
        unknown.append("buy_sell_pressure")
    else:
        known.append("buy_sell_pressure")
        if ratio <= SELL_DETERIORATING:
            consider(DETERIORATING)
            why.append(_why("buy_sell_ratio", None, ratio, None, latest.observed_at, "buy share ≤ 0.20 with ≥ 10 txns"))
        elif ratio <= SELL_WATCH:
            consider(WATCH)
            why.append(_why("buy_sell_ratio", None, ratio, None, latest.observed_at, "buy share ≤ 0.35 with ≥ 10 txns"))

    rug = (rug_level or "").upper() or None
    if rug in ("HIGH", "CRITICAL") and liq_drop is not None and liq_drop >= LIQ_DETERIORATING:
        consider(FAILED if rug == "CRITICAL" or (liq_drop >= LIQ_FAILED) else SEVERE_DETERIORATION)
        why.append(_why("rug_level", None, rug, liq_drop, latest.observed_at, "stored rug evidence plus liquidity collapse"))
    elif rug in (None, "", "UNKNOWN"):
        unknown.append("rug_evidence")

    # Noise-only path with observed later ticks and no material why → STABLE, not HEALTHY.
    if not why:
        if unknown and len(known) == 0:
            worst = UNKNOWN
        elif RANK[worst] <= RANK[STABLE]:
            worst = STABLE
            why.append(_why("path", None, None, None, latest.observed_at, "later ticks observed; no material deterioration or lift"))

    # HEALTHY only if we have liq+vol, no dip, and no large unknown set.
    if worst == STABLE and "liquidity" in known and "volume_5m" in known and not any(
        w.get("state_hint") in DIP_STATES for w in []
    ):
        liq_ok = liq_drop is None or liq_drop < NOISE_BAND
        vol_ok = vol_drop is None or vol_drop < NOISE_BAND
        if liq_ok and vol_ok and liq_ch is not None and vol_ch is not None and liq_ch > -NOISE_BAND and vol_ch > -NOISE_BAND:
            if (liq_ch or 0) >= IMPROVE_LIFT or (vol_ch or 0) >= IMPROVE_LIFT:
                worst = IMPROVING
            else:
                worst = HEALTHY

    eq = _evidence_quality(unknown, len(later))
    if worst in (HEALTHY, IMPROVING, STABLE) and eq in ("POOR", "UNKNOWN"):
        worst = UNKNOWN

    prev = previous_state or UNKNOWN
    severity = ui_severity(worst)
    if prev in DIP_STATES and worst not in DIP_STATES and worst != UNKNOWN:
        severity = "RESOLVED"

    return {
        "version": QUALITY_VERSION,
        "mint": mint,
        "t0": start.isoformat(),
        "as_of": latest.observed_at.isoformat() if latest.observed_at else cutoff.isoformat(),
        "state": worst,
        "previous_state": prev,
        "severity": severity,
        "is_dip": worst in DIP_STATES,
        "why": why,
        "known": known,
        "unknown": unknown,
        "gate": {
            "volume_m5_usd": g_vol,
            "liquidity_usd": g_liq,
            "price_usd": gate.price_usd if gate else None,
        },
        "latest": {
            "volume_m5_usd": l_vol,
            "liquidity_usd": l_liq,
            "price_usd": latest.price_usd,
            "buy_sell_ratio": ratio,
            "observed_at": latest.observed_at.isoformat() if latest.observed_at else None,
            "source": latest.source,
        },
        "later_tick_count": len(later),
        "evidence_quality": eq,
        "calibrated_probability": False,
        "note": "Quality is setup deterioration, not a price-down trade signal. Not a probability.",
    }


def _why(metric: str, prev: Any, cur: Any, change: Any, ts: Any, explanation: str) -> dict[str, Any]:
    at = ts.isoformat() if isinstance(ts, datetime) else (str(ts) if ts else None)
    return {
        "metric": metric,
        "previous_value": prev,
        "current_value": cur,
        "change": round(change, 4) if isinstance(change, float) else change,
        "timestamp": at,
        "explanation": explanation,
        "source": "observed_market_tick",
    }


def quality_dip(row: dict[str, Any]) -> dict[str, Any] | None:
    """UI dip card. None if not a dip and not a resolve."""
    state = str(row.get("state") or UNKNOWN)
    prev = str(row.get("previous_state") or UNKNOWN)
    if state not in DIP_STATES and not (prev in DIP_STATES and state not in DIP_STATES and state != UNKNOWN):
        return None
    return {
        "mint": row.get("mint"),
        "current_state": state,
        "previous_state": prev,
        "severity": row.get("severity"),
        "time": row.get("as_of"),
        "why": list(row.get("why") or []),
        "evidence_quality": row.get("evidence_quality") or "UNKNOWN",
        "known": list(row.get("known") or []),
        "unknown": list(row.get("unknown") or []),
        "gate": row.get("gate"),
        "latest": row.get("latest"),
        "calibrated_probability": False,
        "note": row.get("note"),
        "version": QUALITY_VERSION,
    }


def quality_dips(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        card = quality_dip(r)
        if card:
            out.append(card)
    out.sort(key=lambda r: str(r.get("time") or ""), reverse=True)
    return out


def evaluate_book(memory: IntelligenceMemory, *, as_of: Any = None) -> list[dict[str, Any]]:
    """Latest quality state per investigated mint. Empty is empty."""
    cutoff = _parse_ts(as_of)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    source = list(getattr(memory, "investigations", []) or []) or list(memory.decisions)
    for rec in source:
        mint = str(rec.get("mint") or "").strip()
        if not mint or mint in seen:
            continue
        ts = rec.get("gate1_at") or rec.get("decision_timestamp")
        parsed = _parse_ts(ts)
        if cutoff is not None and parsed is not None and parsed > cutoff:
            continue
        seen.add(mint)
        last = None
        prev = None
        for q in reversed(getattr(memory, "quality_states", []) or []):
            if q.get("mint") == mint:
                last = q
                prev = q.get("state")
                break
        row = evaluate_quality_state(
            memory,
            mint=mint,
            t0=ts,
            as_of=as_of,
            rug_level=rec.get("rug_level"),
            previous_state=prev,
        )
        if last and row.get("state") == last.get("state"):
            row["previous_state"] = last.get("previous_state") or UNKNOWN
        rows.append(row)
    return rows
