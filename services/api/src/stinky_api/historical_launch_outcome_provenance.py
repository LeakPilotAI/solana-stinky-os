"""Evidence-only provenance for a stored historical launch outcome."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "evidence_only": True,
}


def _parse(value: datetime | str | None) -> datetime | None:
    if value is None: return None
    if isinstance(value, datetime): return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip(); raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError: return None


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


async def historical_launch_outcome_provenance(session: AsyncSession, mint: str, *, as_of: datetime | str | None = None, observation_limit: int = 20) -> dict[str, Any]:
    mint = str(mint or "").strip(); observation_limit = max(1, min(100, int(observation_limit)))
    cutoff = _parse(as_of)
    if not mint or (as_of is not None and cutoff is None):
        return {"status": "UNKNOWN", "mint": mint or None, "outcome": "UNKNOWN", "observations": [], "missing": ["mint" if not mint else "valid_as_of"], **AUTHORITY}
    params: dict[str, Any] = {"mint": mint, "limit": observation_limit}
    launch_cutoff = "AND l.observed_at <= :as_of" if cutoff else ""
    observation_cutoff = "AND o.observed_at <= :as_of AND o.ingested_at <= :as_of" if cutoff else ""
    if cutoff: params["as_of"] = cutoff
    try:
        launch = (await session.execute(text(f"""
            SELECT l.entity_id::text AS entity_id, l.mint, l.event_id, l.observed_at AS launch_observed_at,
                   l.outcome_status, l.outcome_meta, l.created_at AS launch_ingested_at
            FROM entity_launches l WHERE l.mint = :mint {launch_cutoff}
            ORDER BY l.observed_at DESC, l.id DESC LIMIT 1
        """), params)).mappings().first()
    except Exception:
        launch = None
    if launch is None:
        result = {"status": "UNKNOWN", "mint": mint, "outcome": "UNKNOWN", "observations": [], "missing": ["entity_launch"], **AUTHORITY}
        if cutoff: result.update({"as_of": cutoff.isoformat(), "temporal_cutoff_enforced": True})
        return result
    meta = launch.get("outcome_meta") if isinstance(launch.get("outcome_meta"), dict) else {}
    raw_outcome = str(launch.get("outcome_status") or "UNKNOWN").upper()
    outcome = raw_outcome if raw_outcome in {"RUNNER", "HELD", "FADE", "UNKNOWN"} else "UNKNOWN"
    outcome_observed = _parse(meta.get("observed_at"))
    outcome_ingested = _parse(meta.get("ingested_at"))
    visible = outcome == "UNKNOWN" or (outcome_observed is not None and (cutoff is None or outcome_observed <= cutoff) and (cutoff is None or (outcome_ingested is not None and outcome_ingested <= cutoff)))
    if not visible: outcome = "UNKNOWN"
    try:
        rows = (await session.execute(text(f"""
            SELECT id, horizon, horizon_seconds, anchor_observed_at, observed_at, ingested_at,
                   source, evidence_basis, metrics, event_id, signature
            FROM market_outcome_observations o
            WHERE o.mint = :mint {observation_cutoff}
            ORDER BY observed_at ASC, horizon_seconds ASC, id ASC LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        rows = []
    observations = []
    for row in rows:
        item = dict(row)
        for key in ("anchor_observed_at", "observed_at", "ingested_at"): item[key] = _iso(item.get(key))
        observations.append(item)
    source_event = meta.get("source_event") or ("post_migration.tracking_completed" if outcome_observed else None)
    result = {
        "status": "OBSERVED" if outcome != "UNKNOWN" else "UNKNOWN",
        "mint": mint, "entity_id": launch.get("entity_id"), "launch_event_id": launch.get("event_id"),
        "launch_observed_at": _iso(launch.get("launch_observed_at")), "launch_ingested_at": _iso(launch.get("launch_ingested_at")),
        "outcome": outcome, "outcome_observed_at": _iso(meta.get("observed_at")), "outcome_ingested_at": _iso(meta.get("ingested_at")),
        "outcome_source_event": source_event, "outcome_event_id": meta.get("event_id"), "outcome_signature": meta.get("signature"),
        "outcome_metadata": meta, "observations": observations, "observation_count": len(observations),
        "unknown_before_resolution": outcome_observed is not None,
        "missing": [key for key, value in (("outcome_ingested_at", meta.get("ingested_at")), ("outcome_event_id", meta.get("event_id"))) if value is None],
        "bounded": {"observation_limit": observation_limit}, **AUTHORITY,
    }
    if cutoff: result.update({"as_of": cutoff.isoformat(), "temporal_cutoff_enforced": True})
    return result
