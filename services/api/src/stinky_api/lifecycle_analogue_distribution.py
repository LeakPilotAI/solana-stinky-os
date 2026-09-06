"""Bulk lifecycle memory and descriptive distributions for historical analogues.

This module never predicts. It summarizes persisted, cutoff-safe lifecycle evidence
for a bounded set of historical mints and preserves UNKNOWN at every horizon.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.market_lifecycle_memory import HORIZONS, build_market_lifecycle_memory

AUTHORITY = {
    "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "evidence_only": True,
}


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"observed_count": 0, "min": None, "max": None, "median": None}
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    median = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {"observed_count": n, "min": ordered[0], "max": ordered[-1], "median": median}


def synthesize_lifecycle_distribution(memories: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate factual horizon coverage and observed numeric metrics."""
    outcome_counts = {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0}
    horizon_rows: list[dict[str, Any]] = []
    for name, seconds in HORIZONS:
        observed = 0
        metric_values: dict[str, list[float]] = {}
        for memory in memories:
            outcome = str(memory.get("outcome") or "UNKNOWN").upper()
            if name == HORIZONS[0][0]:
                outcome_counts[outcome if outcome in outcome_counts else "UNKNOWN"] += 1
            slot = next((h for h in memory.get("horizons", []) if h.get("horizon") == name), None)
            observation = slot.get("observation") if isinstance(slot, dict) else None
            if not isinstance(observation, dict):
                continue
            observed += 1
            metrics = observation.get("metrics") if isinstance(observation.get("metrics"), dict) else {}
            for key, value in metrics.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metric_values.setdefault(str(key), []).append(float(value))
        horizon_rows.append({
            "horizon": name,
            "horizon_seconds": seconds,
            "analogue_count": len(memories),
            "observed_count": observed,
            "unknown_count": len(memories) - observed,
            "metrics": {key: _numeric_summary(values) for key, values in sorted(metric_values.items())},
        })
    return {
        "status": "OBSERVED" if memories else "UNKNOWN",
        "analogue_count": len(memories),
        "outcome_counts": outcome_counts,
        "complete_24h_count": sum(1 for memory in memories if memory.get("complete_through_24h") is True),
        "horizons": horizon_rows,
        "distribution_is_historical_description_not_prediction": True,
        **AUTHORITY,
    }


async def load_lifecycle_memories_for_mints(
    session: AsyncSession,
    mints: list[str],
    *,
    as_of: datetime | None = None,
    mint_limit: int = 100,
) -> dict[str, Any]:
    """Load lifecycle evidence in two bounded bulk queries; never N+1 per mint."""
    bounded = max(1, min(200, int(mint_limit)))
    selected = sorted({str(m).strip() for m in mints if str(m).strip()})[:bounded]
    if not selected:
        return {"memories": [], "distribution": synthesize_lifecycle_distribution([]), "bounded": {"mint_limit": bounded, "mint_count": 0}, **AUTHORITY}
    params: dict[str, Any] = {"mints": selected}
    obs_cutoff = event_cutoff = ""
    if as_of is not None:
        params["as_of"] = as_of
        obs_cutoff = "AND o.observed_at <= :as_of AND o.ingested_at <= :as_of"
        event_cutoff = "AND e.occurred_at <= :as_of AND e.ingested_at <= :as_of"
    try:
        observations = (await session.execute(text(f"""
            SELECT o.mint, o.horizon, o.horizon_seconds, o.anchor_observed_at,
                   o.observed_at, o.ingested_at, o.source, o.evidence_basis,
                   o.metrics, o.event_id, o.signature
            FROM market_outcome_observations o
            WHERE o.mint = ANY(:mints) {obs_cutoff}
            ORDER BY o.mint ASC, o.horizon_seconds ASC, o.observed_at ASC, o.id ASC
        """), params)).mappings().all()
    except Exception:
        observations = []
    try:
        events = (await session.execute(text(f"""
            SELECT e.event_id::text AS event_id, e.event_type, e.occurred_at,
                   e.ingested_at, e.signature, e.producer, e.payload
            FROM events e
            WHERE e.event_type = 'post_migration.tracking_completed'
              AND e.payload->>'mint' = ANY(:mints) {event_cutoff}
            ORDER BY e.payload->>'mint' ASC, e.occurred_at DESC, e.ingested_at DESC
        """), params)).mappings().all()
    except Exception:
        events = []
    by_mint: dict[str, list[dict[str, Any]]] = {mint: [] for mint in selected}
    for row in observations:
        mint = str(row.get("mint") or "")
        if mint in by_mint:
            by_mint[mint].append(dict(row))
    event_by_mint: dict[str, dict[str, Any]] = {}
    for row in events:
        item = dict(row)
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        mint = str(payload.get("mint") or "")
        if mint in by_mint and mint not in event_by_mint:
            event_by_mint[mint] = item
    memories = [
        build_market_lifecycle_memory(mint=mint, observations=by_mint[mint], outcome_event=event_by_mint.get(mint), as_of=as_of)
        for mint in selected
    ]
    result = {
        "memories": memories,
        "distribution": synthesize_lifecycle_distribution(memories),
        "bounded": {"mint_limit": bounded, "mint_count": len(selected), "query_count": 2},
        **AUTHORITY,
    }
    if as_of is not None:
        result["as_of"] = _iso(as_of)
        result["temporal_cutoff_enforced"] = True
    return result
