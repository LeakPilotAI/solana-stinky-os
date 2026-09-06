"""Retrieve bounded measured market-lifecycle evidence for investigations.

This adapter reads the persistent market outcome observation store directly
through the API session. It exposes observations only: no outcome labels,
predictions, probabilities, quality, risk, or trading authority are derived.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


HORIZON_ORDER = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "24h": 86400}


def _parse_as_of(value: datetime | str | None) -> datetime | None:
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


def _unknown(reason: str, *, limit: int) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "mint": None,
        "records": [],
        "missing": [reason],
        "bounded": {"limit": limit},
        "evidence_only": True,
    }


async def market_lifecycle_for_mint(
    session: AsyncSession,
    mint: str,
    *,
    limit: int = 100,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Return measured lifecycle observations for one mint, bounded and as-of safe."""
    mint = str(mint or "").strip()
    bounded_limit = max(1, min(int(limit), 500))
    if not mint:
        return _unknown("mint", limit=bounded_limit)

    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        result = _unknown("invalid_as_of", limit=bounded_limit)
        result["mint"] = mint
        return result

    params: dict[str, Any] = {"mint": mint, "limit": bounded_limit}
    cutoff_clause = ""
    if cutoff is not None:
        cutoff_clause = "AND observed_at <= :as_of"
        params["as_of"] = cutoff

    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT id, mint, horizon, horizon_seconds, anchor_observed_at,
                           observed_at, ingested_at, source, evidence_basis,
                           metrics, event_id, signature, created_at
                    FROM market_outcome_observations
                    WHERE mint = :mint
                      {cutoff_clause}
                    ORDER BY horizon_seconds ASC, observed_at ASC, id ASC
                    LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()
    except Exception:
        result = _unknown("market_outcome_observations", limit=bounded_limit)
        result["mint"] = mint
        if cutoff is not None:
            result["as_of"] = cutoff.isoformat()
            result["temporal_cutoff_enforced"] = True
        return result

    records: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("anchor_observed_at", "observed_at", "ingested_at", "created_at"):
            value = item.get(key)
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        records.append(item)

    result: dict[str, Any] = {
        "status": "OBSERVED" if records else "UNKNOWN",
        "mint": mint,
        "records": records,
        "missing": [] if records else ["market_outcome_observations"],
        "bounded": {"limit": bounded_limit},
        "evidence_basis": "market_snapshot_observation",
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
