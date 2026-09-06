"""Canonical evidence-only market lifecycle memory for one mint.

The lifecycle record is factual memory, not prediction. Missing horizons remain
UNKNOWN. Historical visibility requires both observation time and ingestion time
to be at or before the requested cutoff.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

HORIZONS: tuple[tuple[str, int], ...] = (
    ("5m", 300), ("15m", 900), ("30m", 1800),
    ("1h", 3600), ("4h", 14400), ("24h", 86400),
)
CANONICAL_OUTCOMES = {"RUNNER", "HELD", "FADE", "UNKNOWN"}
AUTHORITY = {
    "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "evidence_only": True,
}


def _parse(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def canonical_outcome_from_event(event: dict[str, Any] | None) -> str:
    """Use only a canonical immutable completion event to resolve an outcome."""
    if not isinstance(event, dict):
        return "UNKNOWN"
    if event.get("event_type") != "post_migration.tracking_completed":
        return "UNKNOWN"
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    raw = payload.get("outcome_status") or payload.get("outcome") or payload.get("status")
    value = str(raw or "UNKNOWN").upper()
    return value if value in CANONICAL_OUTCOMES else "UNKNOWN"


def build_market_lifecycle_memory(
    *,
    mint: str,
    observations: list[dict[str, Any]],
    outcome_event: dict[str, Any] | None = None,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Build deterministic lifecycle memory from persisted evidence only."""
    cutoff = _parse(as_of)
    horizon_map: dict[str, dict[str, Any]] = {}
    visible_records: list[dict[str, Any]] = []
    for record in observations:
        if not isinstance(record, dict):
            continue
        observed = _parse(record.get("observed_at"))
        ingested = _parse(record.get("ingested_at"))
        if cutoff is not None and (
            observed is None or ingested is None or observed > cutoff or ingested > cutoff
        ):
            continue
        horizon = str(record.get("horizon") or "")
        if horizon not in dict(HORIZONS):
            continue
        item = dict(record)
        item["observed_at"] = _iso(record.get("observed_at"))
        item["ingested_at"] = _iso(record.get("ingested_at"))
        item["anchor_observed_at"] = _iso(record.get("anchor_observed_at"))
        visible_records.append(item)
        horizon_map.setdefault(horizon, item)

    event_visible = False
    event_payload: dict[str, Any] | None = None
    if isinstance(outcome_event, dict):
        observed = _parse(outcome_event.get("occurred_at"))
        ingested = _parse(outcome_event.get("ingested_at"))
        event_visible = cutoff is None or (
            observed is not None and ingested is not None and observed <= cutoff and ingested <= cutoff
        )
        if event_visible:
            event_payload = dict(outcome_event)
            event_payload["occurred_at"] = _iso(outcome_event.get("occurred_at"))
            event_payload["ingested_at"] = _iso(outcome_event.get("ingested_at"))

    outcome = canonical_outcome_from_event(event_payload)
    horizons = []
    for name, seconds in HORIZONS:
        record = horizon_map.get(name)
        horizons.append({
            "horizon": name,
            "horizon_seconds": seconds,
            "status": "OBSERVED" if record is not None else "UNKNOWN",
            "observation": record,
        })

    result = {
        "status": "OBSERVED" if visible_records or outcome != "UNKNOWN" else "UNKNOWN",
        "mint": str(mint or "").strip(),
        "outcome": outcome,
        "outcome_resolution_basis": "immutable_post_migration_tracking_completed_event" if outcome != "UNKNOWN" else "UNKNOWN",
        "outcome_event": event_payload,
        "observed_horizon_count": len(horizon_map),
        "complete_through_24h": all(name in horizon_map for name, _ in HORIZONS),
        "horizons": horizons,
        "records": visible_records,
        "missing_horizons": [name for name, _ in HORIZONS if name not in horizon_map],
        "unknown_before_resolution": outcome != "UNKNOWN" and event_payload is not None,
        **AUTHORITY,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
