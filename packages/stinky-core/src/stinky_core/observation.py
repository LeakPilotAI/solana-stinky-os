"""Live observation window around every Gate-1 investigation.

Immutable decision-time snapshot + later ticks. Missing stays UNKNOWN.
Never interpolates. Never leaks later ticks into the original decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from stinky_core.memory import IntelligenceMemory, MarketTick, _maybe_float, _parse_ts
from stinky_core.outcomes import LABEL_VERSION, label_outcome
from stinky_core.stages import STAGES_VERSION, slice_stage

OBSERVATION_VERSION = "observation-v1.1.0"

WATCH_STOP_REASONS = frozenset(
    {
        "PROTOCOL_DISABLED",
        "PROTOCOL_UNKNOWN",
        "INVALID_MINT",
        "INVALID_MARKET_DATA",
        "NOT_PUMP_MINT",
    }
)


def watch_tick_decision(*, investigated: bool, gate_ok: bool, reason: str | None) -> str:
    """Live watch action for one DexScreener poll.

    After Gate 1, keep recording ticks even if 5m volume falls below $150k.
    Quality cannot observe deterioration without those ticks.
    Returns: stop | wait | investigate | tick
    """
    reason_u = (reason or "").upper()
    if not investigated:
        if gate_ok:
            return "investigate"
        if reason_u in WATCH_STOP_REASONS:
            return "stop"
        return "wait"
    if reason_u in ("PROTOCOL_DISABLED", "INVALID_MINT"):
        return "stop"
    return "tick"


def watch_should_resume(*, elapsed_sec: float, max_watch_sec: float = 1800.0) -> bool:
    """After restart: resume only if still inside the T+1800 window."""
    try:
        e = float(elapsed_sec)
        m = float(max_watch_sec)
    except (TypeError, ValueError):
        return False
    return 0 <= e < m


OBSERVATION_SLICES_SEC = (0, 15, 30, 60, 90, 120, 180, 300, 600, 900, 1200, 1800)


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.isoformat()
    s = str(v).strip()
    return s or None


def _i(v: Any) -> int | None:
    if v is None or v is True or v is False:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def correlation_id(mint: str | None, at: Any) -> str:
    m = (mint or "unknown").strip() or "unknown"
    ts = _iso(at) or "na"
    return f"{m}:{ts}"


def investigation_record(
    bundle: Mapping[str, Any],
    *,
    gate1_passed: bool,
    rejection_reason: str | None = None,
    investigation_status: str | None = None,
    correlation: str | None = None,
) -> dict[str, Any]:
    """Immutable Gate-1 snapshot. Decision-time values only. Never the future path."""
    mint = str(bundle.get("mint") or "").strip() or None
    at = bundle.get("decision_timestamp") or bundle.get("gate1_at") or bundle.get("as_of")
    discovered = bundle.get("discovered_at") or at
    vol = _maybe_float(bundle.get("volume_m5_usd") if bundle.get("volume_m5_usd") is not None else bundle.get("volume_usd"))
    cid = correlation or correlation_id(mint, at)
    return {
        "version": OBSERVATION_VERSION,
        "mint": mint,
        "protocol": str(bundle.get("protocol") or bundle.get("dex_id") or "") or None,
        "discovered_at": _iso(discovered),
        "gate1_at": _iso(at),
        "volume_5m_at_gate": vol,
        "liquidity_at_gate": _maybe_float(bundle.get("liquidity_usd")),
        "market_cap_at_gate": _maybe_float(bundle.get("market_cap_usd")),
        "price_at_gate": _maybe_float(bundle.get("price_usd") if bundle.get("price_usd") is not None else bundle.get("entry_price")),
        "pair_identifier": str(bundle.get("pair") or bundle.get("pair_address") or "") or None,
        "creator": str(bundle["creator"]).strip() if bundle.get("creator") else None,
        "gate_decision": "PASSED" if gate1_passed else "REJECTED",
        "rejection_reason": rejection_reason,
        "investigation_status": investigation_status or ("INVESTIGATING" if gate1_passed else "REJECTED"),
        "correlation_id": cid,
        "immutable": True,
        "calibrated_probability": False,
        "note": "Decision-time snapshot. Later ticks and outcomes are stored separately and must not overwrite these fields.",
    }


def tick_dict(tick: MarketTick) -> dict[str, Any]:
    buys = getattr(tick, "buys", None)
    sells = getattr(tick, "sells", None)
    ratio = None
    if buys is not None and sells is not None and (buys + sells) > 0:
        ratio = round(buys / (buys + sells), 4)
    return {
        "timestamp": tick.observed_at.isoformat() if tick.observed_at else None,
        "price": tick.price_usd,
        "market_cap": getattr(tick, "market_cap_usd", None),
        "liquidity": tick.liquidity_usd,
        "volume_5m": tick.volume_m5_usd,
        "volume_since_gate": getattr(tick, "volume_since_gate", None),
        "buys": buys,
        "sells": sells,
        "transaction_count": getattr(tick, "txns", None),
        "unique_buyers": getattr(tick, "unique_buyers", None),
        "unique_sellers": getattr(tick, "unique_sellers", None),
        "buy_sell_ratio": ratio if ratio is not None else getattr(tick, "buy_sell_ratio", None),
        "source": tick.source,
        "missing": [k for k, v in (
            ("price", tick.price_usd),
            ("liquidity", tick.liquidity_usd),
            ("volume_5m", tick.volume_m5_usd),
        ) if v is None],
    }


def observation_slices(
    memory: IntelligenceMemory,
    *,
    mint: str,
    t0: Any,
    as_of: Any = None,
) -> dict[str, Any]:
    """T+ path from stored ticks only. Future after as_of is hidden. No interpolation."""
    start = _parse_ts(t0)
    cutoff = _parse_ts(as_of)
    if start is None:
        return {
            "version": OBSERVATION_VERSION,
            "mint": mint,
            "t0": None,
            "slices": [],
            "calibrated_probability": False,
            "note": "decision timestamp UNKNOWN",
        }

    def visible(ts: datetime) -> bool:
        if ts < start:
            return False
        if cutoff is None:
            return True
        return ts <= cutoff

    ticks = sorted(
        (t for t in getattr(memory, "market_ticks", []) if t.mint == mint),
        key=lambda x: x.observed_at,
    )
    t0_ticks = [t for t in ticks if t.observed_at == start]
    base = t0_ticks[0] if t0_ticks else None
    base_vol = base.volume_m5_usd if base else None
    base_px = base.price_usd if base else None
    base_liq = base.liquidity_usd if base else None
    base_mc = getattr(base, "market_cap_usd", None) if base else None

    slices: list[dict[str, Any]] = []
    for offset in OBSERVATION_SLICES_SEC:
        horizon = start + timedelta(seconds=int(offset))
        chosen = None
        for t in ticks:
            if not visible(t.observed_at):
                continue
            if t.observed_at > horizon:
                continue
            chosen = t
        payload = tick_dict(chosen) if chosen else {
            "timestamp": None, "price": None, "market_cap": None, "liquidity": None,
            "volume_5m": None, "volume_since_gate": None, "buys": None, "sells": None,
            "transaction_count": None, "unique_buyers": None, "unique_sellers": None,
            "buy_sell_ratio": None, "source": None, "missing": ["market_tick"],
        }
        px = payload.get("price")
        liq = payload.get("liquidity")
        mc = payload.get("market_cap")
        vol = payload.get("volume_5m")
        payload["price_change"] = round(px - base_px, 8) if px is not None and base_px is not None else None
        payload["liquidity_change"] = round(liq - base_liq, 4) if liq is not None and base_liq is not None else None
        payload["market_cap_change"] = round(mc - base_mc, 4) if mc is not None and base_mc is not None else None
        accel = None
        if offset and base_vol is not None and vol is not None:
            accel = round((vol - base_vol) / offset, 6)
        payload["volume_acceleration"] = accel
        payload["offset_sec"] = offset
        payload["label"] = f"T+{offset}s" if offset else "T+0"
        payload["stage"] = slice_stage(offset)
        payload["observed"] = chosen is not None
        slices.append(payload)
    observed_n = sum(1 for s in slices if s.get("observed"))
    return {
        "version": OBSERVATION_VERSION,
        "stages_version": STAGES_VERSION,
        "mint": mint,
        "t0": start.isoformat(),
        "as_of": cutoff.isoformat() if cutoff else None,
        "future_hidden": True,
        "slices": slices,
        "observed_slice_count": observed_n,
        "expected_slice_count": len(OBSERVATION_SLICES_SEC),
        "completeness": round(observed_n / len(OBSERVATION_SLICES_SEC), 2),
        "calibrated_probability": False,
        "note": "Missing offsets stay UNKNOWN. Values are last-known ticks at or before the offset, never interpolated, never from the future. A tick at as_of is visible.",
    }


def what_happened_next(
    memory: IntelligenceMemory,
    *,
    mint: str,
    t0: Any,
    as_of: Any = None,
    observation_window: float = 3600.0,
) -> dict[str, Any]:
    """Answer: what happened after we detected it? Stored ticks only."""
    path = observation_slices(memory, mint=mint, t0=t0, as_of=as_of)
    start = _parse_ts(t0)
    cutoff = _parse_ts(as_of)
    if start is None:
        return {
            "version": OBSERVATION_VERSION,
            "mint": mint,
            "path": path,
            "peak_price": None,
            "peak_volume": None,
            "peak_market_cap": None,
            "time_to_peak": None,
            "outcome": {"label": "UNKNOWN", "reason": "decision timestamp UNKNOWN", "label_version": LABEL_VERSION},
            "calibrated_probability": False,
        }
    later = [
        t for t in getattr(memory, "market_ticks", [])
        if t.mint == mint and t.observed_at > start and (cutoff is None or t.observed_at <= cutoff)
    ]
    entry = next(
        (t for t in sorted(getattr(memory, "market_ticks", []), key=lambda x: x.observed_at)
         if t.mint == mint and t.observed_at <= start),
        None,
    )
    entry_px = entry.price_usd if entry else None
    entry_vol = entry.volume_m5_usd if entry else None
    entry_mc = getattr(entry, "market_cap_usd", None) if entry else None
    prices = [t.price_usd for t in later if t.price_usd is not None]
    vols = [t.volume_m5_usd for t in later if t.volume_m5_usd is not None]
    mcaps = [getattr(t, "market_cap_usd", None) for t in later if getattr(t, "market_cap_usd", None) is not None]
    peak_px = max(prices) if prices else None
    peak_vol = max(vols) if vols else None
    peak_mc = max(mcaps) if mcaps else None
    multiple = None
    if entry_px and peak_px and entry_px > 0:
        multiple = peak_px / entry_px
    elif entry_vol and peak_vol and entry_vol > 0:
        multiple = peak_vol / entry_vol
    ttp = None
    if peak_px is not None:
        peak_tick = next((t for t in sorted(later, key=lambda x: x.observed_at) if t.price_usd == peak_px), None)
        if peak_tick is not None:
            ttp = (peak_tick.observed_at - start).total_seconds()
    elif peak_vol is not None:
        peak_tick = next((t for t in sorted(later, key=lambda x: x.observed_at) if t.volume_m5_usd == peak_vol), None)
        if peak_tick is not None:
            ttp = (peak_tick.observed_at - start).total_seconds()
    end = cutoff or datetime.now(timezone.utc)
    horizon = start + timedelta(seconds=float(observation_window or 3600.0))
    complete = end >= horizon or len(later) >= 3
    oc = label_outcome(
        peak_multiple=multiple,
        peak_volume=peak_vol,
        entry_volume=entry_vol,
        entry_price=entry_px,
        decision_timestamp=start.isoformat(),
        time_to_peak=ttp,
        observation_window=observation_window,
        observation_complete=complete,
    )
    d = oc.to_dict()
    d["peak_price"] = peak_px
    d["peak_market_cap"] = peak_mc
    d["return_from_gate"] = multiple
    d["observation_duration"] = (max((t.observed_at for t in later), default=start) - start).total_seconds() if later else None
    return {
        "version": OBSERVATION_VERSION,
        "mint": mint,
        "gate": {
            "at": start.isoformat(),
            "volume_5m": entry_vol,
            "price": entry_px,
            "market_cap": entry_mc,
            "liquidity": entry.liquidity_usd if entry else None,
        },
        "path": path,
        "peak_price": peak_px,
        "peak_volume": peak_vol,
        "peak_market_cap": peak_mc,
        "time_to_peak": ttp,
        "outcome": d,
        "calibrated_probability": False,
        "note": "Generated from stored observations. Missing ticks stay UNKNOWN. Outcome is later, never a decision input.",
    }


def observation_book(memory: IntelligenceMemory, *, as_of: Any = None) -> list[dict[str, Any]]:
    """One row per investigated mint. Completeness from stored ticks. Empty is empty."""
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
        path = observation_slices(memory, mint=mint, t0=ts, as_of=as_of) if ts else {"slices": [], "observed_slice_count": 0, "expected_slice_count": len(OBSERVATION_SLICES_SEC), "completeness": 0}
        later = what_happened_next(memory, mint=mint, t0=ts, as_of=as_of) if ts else {}
        oc = later.get("outcome") if isinstance(later.get("outcome"), dict) else {}
        rows.append({
            "mint": mint,
            "protocol": rec.get("protocol"),
            "gate1_at": rec.get("gate1_at") or rec.get("decision_timestamp"),
            "volume_5m_at_gate": rec.get("volume_5m_at_gate") if rec.get("volume_5m_at_gate") is not None else rec.get("volume_m5_usd"),
            "investigation_status": rec.get("investigation_status") or rec.get("pipeline_status"),
            "correlation_id": rec.get("correlation_id"),
            "observed_slice_count": path.get("observed_slice_count"),
            "expected_slice_count": path.get("expected_slice_count"),
            "completeness": path.get("completeness"),
            "outcome_label": (oc or {}).get("label") or rec.get("outcome_label") or "UNKNOWN",
            "immutable": bool(rec.get("immutable", True)),
            "calibrated_probability": False,
        })
    rows.sort(key=lambda r: str(r.get("gate1_at") or ""), reverse=True)
    return rows


def slice_analogues(
    memory: IntelligenceMemory,
    *,
    mint: str,
    offset_sec: int,
    t0: Any,
    as_of: Any = None,
) -> dict[str, Any]:
    """Compare this mint's slice at T+offset to other mints at the SAME offset.

    Age-aware. T+15 only compares with T+15. Empty fingerprint / missing slice stays UNKNOWN.
    Not a probability. Sample under 5 stays UNKNOWN.
    """
    from stinky_core.stages import slice_stage

    offset = int(offset_sec)
    path = observation_slices(memory, mint=mint, t0=t0, as_of=as_of)
    by = {s["offset_sec"]: s for s in path.get("slices") or []}
    cur = by.get(offset)
    if not cur or cur.get("volume_5m") is None:
        return {
            "version": OBSERVATION_VERSION,
            "mint": mint,
            "offset_sec": offset,
            "stage": slice_stage(offset),
            "analogue_count": 0,
            "sample_sufficient": False,
            "outcome_distribution": {"RUNNER": 0, "HELD": 0, "FADE": 0, "RUG": 0, "UNKNOWN": 0},
            "calibrated_probability": False,
            "note": "Current slice volume UNKNOWN — cannot compare.",
        }
    cur_vol = cur.get("volume_5m")
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    source = list(getattr(memory, "investigations", []) or []) or list(memory.decisions)
    cutoff = _parse_ts(as_of)
    for rec in source:
        other = str(rec.get("mint") or "").strip()
        if not other or other == mint or other in seen:
            continue
        ots = rec.get("gate1_at") or rec.get("decision_timestamp")
        parsed = _parse_ts(ots)
        if cutoff is not None and parsed is not None and parsed >= cutoff:
            continue
        seen.add(other)
        opath = observation_slices(memory, mint=other, t0=ots, as_of=as_of)
        oby = {s["offset_sec"]: s for s in opath.get("slices") or []}
        oslice = oby.get(offset)
        if not oslice or oslice.get("volume_5m") is None:
            continue
        ov = oslice.get("volume_5m")
        if ov is None or cur_vol is None or cur_vol <= 0:
            continue
        rel = abs(ov - cur_vol) / cur_vol
        if rel > 0.35:
            continue
        later = what_happened_next(memory, mint=other, t0=ots, as_of=as_of)
        oc = later.get("outcome") if isinstance(later.get("outcome"), dict) else {}
        lab = str((oc or {}).get("label") or rec.get("outcome_label") or "UNKNOWN").upper()
        if lab not in ("RUNNER", "HELD", "FADE", "RUG", "UNKNOWN"):
            lab = "UNKNOWN"
        matches.append({"mint": other, "offset_sec": offset, "volume_5m": ov, "outcome": lab, "rel_volume_delta": round(rel, 4)})
    dist = {"RUNNER": 0, "HELD": 0, "FADE": 0, "RUG": 0, "UNKNOWN": 0}
    for m in matches:
        dist[m["outcome"]] = dist.get(m["outcome"], 0) + 1
    n = len(matches)
    return {
        "version": OBSERVATION_VERSION,
        "mint": mint,
        "offset_sec": offset,
        "stage": slice_stage(offset),
        "methodology": "same-offset 5m volume within 35% of current slice; stored ticks only",
        "analogue_count": n,
        "sample_sufficient": n >= 5,
        "outcome_distribution": dist,
        "matches": matches[:24],
        "calibrated_probability": False,
        "note": (
            f"{n} same-offset analogues. Not a chance of running."
            if n
            else "No same-offset analogues as-of."
        ),
    }
