"""Evidence-only provenance for a stored historical launch outcome."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.market_lifecycle_memory import build_market_lifecycle_memory

AUTHORITY = {"interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "predictive_authority": False, "trade_signal": False, "risk_inferred": False, "quality_inferred": False, "evidence_only": True}


def _parse(value: datetime | str | None) -> datetime | None:
    if value is None: return None
    if isinstance(value, datetime): return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip(); raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(raw); return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError: return None


def _iso(value: Any) -> Any: return value.isoformat() if hasattr(value, "isoformat") else value


async def historical_launch_outcome_provenance(session: AsyncSession, mint: str, *, as_of: datetime | str | None = None, observation_limit: int = 20) -> dict[str, Any]:
    mint = str(mint or "").strip(); observation_limit = max(1, min(100, int(observation_limit))); cutoff = _parse(as_of)
    if not mint or (as_of is not None and cutoff is None):
        return {"status": "UNKNOWN", "mint": mint or None, "outcome": "UNKNOWN", "observations": [], "missing": ["mint" if not mint else "valid_as_of"], **AUTHORITY}
    params: dict[str, Any] = {"mint": mint, "limit": observation_limit}
    launch_cutoff = "AND l.observed_at <= :as_of" if cutoff else ""
    event_cutoff = "AND e.occurred_at <= :as_of AND e.ingested_at <= :as_of" if cutoff else ""
    observation_cutoff = "AND o.observed_at <= :as_of AND o.ingested_at <= :as_of" if cutoff else ""
    if cutoff: params["as_of"] = cutoff
    try:
        launch = (await session.execute(text(f"""
            SELECT l.entity_id::text AS entity_id, l.mint, l.event_id, l.observed_at AS launch_observed_at,
                   l.outcome_status AS mutable_outcome_status, l.outcome_meta, l.created_at AS launch_ingested_at,
                   oe.event_id::text AS outcome_event_id, oe.event_type AS outcome_event_type,
                   oe.occurred_at AS outcome_event_observed_at, oe.ingested_at AS outcome_event_ingested_at,
                   oe.signature AS outcome_event_signature, oe.producer AS outcome_event_producer,
                   oe.payload AS outcome_event_payload
            FROM entity_launches l
            LEFT JOIN LATERAL (
                SELECT e.event_id, e.event_type, e.occurred_at, e.ingested_at, e.signature, e.producer, e.payload
                FROM events e
                WHERE e.event_type = 'post_migration.tracking_completed'
                  AND e.payload->>'mint' = l.mint {event_cutoff}
                ORDER BY e.occurred_at DESC, e.ingested_at DESC LIMIT 1
            ) oe ON TRUE
            WHERE l.mint = :mint {launch_cutoff}
            ORDER BY l.observed_at DESC, l.id DESC LIMIT 1
        """), params)).mappings().first()
    except Exception: launch = None
    if launch is None:
        result = {"status": "UNKNOWN", "mint": mint, "outcome": "UNKNOWN", "observations": [], "missing": ["entity_launch"], **AUTHORITY}
        if cutoff: result.update({"as_of": cutoff.isoformat(), "temporal_cutoff_enforced": True})
        return result
    try:
        rows = (await session.execute(text(f"""
            SELECT id, horizon, horizon_seconds, anchor_observed_at, observed_at, ingested_at,
                   source, evidence_basis, metrics, event_id, signature
            FROM market_outcome_observations o WHERE o.mint = :mint {observation_cutoff}
            ORDER BY observed_at ASC, horizon_seconds ASC, id ASC LIMIT :limit
        """), params)).mappings().all()
    except Exception: rows = []
    observations = []
    for row in rows:
        item = dict(row)
        for key in ("anchor_observed_at", "observed_at", "ingested_at"): item[key] = _iso(item.get(key))
        observations.append(item)

    outcome_event = None
    if launch.get("outcome_event_id"):
        outcome_event = {
            "event_id": launch.get("outcome_event_id"),
            "event_type": launch.get("outcome_event_type"),
            "occurred_at": launch.get("outcome_event_observed_at"),
            "ingested_at": launch.get("outcome_event_ingested_at"),
            "signature": launch.get("outcome_event_signature"),
            "producer": launch.get("outcome_event_producer"),
            "payload": launch.get("outcome_event_payload") if isinstance(launch.get("outcome_event_payload"), dict) else {},
        }
    lifecycle = build_market_lifecycle_memory(mint=mint, observations=observations, outcome_event=outcome_event, as_of=cutoff)
    outcome = lifecycle.get("outcome", "UNKNOWN")
    meta = launch.get("outcome_meta") if isinstance(launch.get("outcome_meta"), dict) else {}
    result = {
        "status": "OBSERVED" if lifecycle.get("status") == "OBSERVED" else "UNKNOWN",
        "mint": mint, "entity_id": launch.get("entity_id"), "launch_event_id": launch.get("event_id"),
        "launch_observed_at": _iso(launch.get("launch_observed_at")), "launch_ingested_at": _iso(launch.get("launch_ingested_at")),
        "outcome": outcome,
        "outcome_resolution_basis": lifecycle.get("outcome_resolution_basis"),
        "mutable_outcome_status": launch.get("mutable_outcome_status"),
        "mutable_outcome_status_is_historical_authority": False,
        "outcome_observed_at": lifecycle.get("outcome_event", {}).get("occurred_at") if isinstance(lifecycle.get("outcome_event"), dict) else None,
        "outcome_ingested_at": lifecycle.get("outcome_event", {}).get("ingested_at") if isinstance(lifecycle.get("outcome_event"), dict) else None,
        "outcome_source_event": lifecycle.get("outcome_event", {}).get("event_type") if isinstance(lifecycle.get("outcome_event"), dict) else None,
        "outcome_event_id": lifecycle.get("outcome_event", {}).get("event_id") if isinstance(lifecycle.get("outcome_event"), dict) else None,
        "outcome_signature": lifecycle.get("outcome_event", {}).get("signature") if isinstance(lifecycle.get("outcome_event"), dict) else None,
        "outcome_producer": lifecycle.get("outcome_event", {}).get("producer") if isinstance(lifecycle.get("outcome_event"), dict) else None,
        "outcome_metadata": meta,
        "observations": observations,
        "observation_count": len(observations),
        "lifecycle_memory": lifecycle,
        "unknown_before_resolution": lifecycle.get("unknown_before_resolution", False),
        "missing": [key for key, value in (("outcome_event", lifecycle.get("outcome_event")),) if not value],
        "bounded": {"observation_limit": observation_limit}, **AUTHORITY,
    }
    if cutoff: result.update({"as_of": cutoff.isoformat(), "temporal_cutoff_enforced": True})
    return result
