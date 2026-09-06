"""Describe factual follow-up lifecycle evidence for persisted market patterns.

This layer measures historical evidence coverage only. It does not convert
follow-up observations into predictions, probabilities, quality/risk scores,
or trading authority. Missing follow-up remains UNKNOWN.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SUPPORTED_HORIZONS = ("5m", "15m", "30m", "1h", "4h", "24h")


def _parse_time(value: datetime | str | None) -> datetime | None:
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


def _unknown(reason: str, *, pattern_hash: str | None, limit: int) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "pattern_hash": pattern_hash,
        "occurrence_count": 0,
        "occurrences_with_followup": 0,
        "occurrences_without_followup": 0,
        "followup_coverage": None,
        "horizon_coverage": {},
        "records": [],
        "missing": [reason],
        "bounded": {"occurrence_limit": limit},
        "evidence_basis": "market_path_pattern_occurrences+market_outcome_observations",
        "evidence_only": True,
    }


async def calibrate_market_pattern_outcomes(
    session: AsyncSession,
    pattern_hash: str,
    *,
    occurrence_limit: int = 100,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Measure cutoff-safe follow-up evidence after historical pattern occurrences."""
    pattern_hash = str(pattern_hash or "").strip()
    bounded_limit = max(1, min(int(occurrence_limit), 500))
    if not pattern_hash:
        return _unknown("pattern_hash", pattern_hash=None, limit=bounded_limit)

    cutoff = _parse_time(as_of)
    if as_of is not None and cutoff is None:
        return _unknown("invalid_as_of", pattern_hash=pattern_hash, limit=bounded_limit)

    occurrence_cutoff = ""
    followup_cutoff = ""
    params: dict[str, Any] = {"pattern_hash": pattern_hash, "limit": bounded_limit}
    if cutoff is not None:
        occurrence_cutoff = "AND observed_at <= :as_of"
        followup_cutoff = "AND mo.observed_at <= :as_of"
        params["as_of"] = cutoff

    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    WITH occurrences AS (
                        SELECT id, mint, observed_at
                        FROM market_path_pattern_occurrences
                        WHERE pattern_hash = :pattern_hash
                          {occurrence_cutoff}
                        ORDER BY observed_at ASC, id ASC
                        LIMIT :limit
                    )
                    SELECT o.id AS occurrence_id,
                           o.mint,
                           o.observed_at AS pattern_observed_at,
                           mo.horizon,
                           mo.horizon_seconds,
                           mo.observed_at AS followup_observed_at,
                           mo.ingested_at AS followup_ingested_at,
                           mo.source,
                           mo.evidence_basis,
                           mo.metrics
                    FROM occurrences o
                    LEFT JOIN market_outcome_observations mo
                      ON mo.mint = o.mint
                     AND mo.observed_at > o.observed_at
                     {followup_cutoff}
                    ORDER BY o.observed_at ASC, o.id ASC,
                             mo.observed_at ASC NULLS LAST,
                             mo.horizon_seconds ASC NULLS LAST
                    """
                ),
                params,
            )
        ).mappings().all()
    except Exception:
        return _unknown("market_pattern_followup_evidence", pattern_hash=pattern_hash, limit=bounded_limit)

    if not rows:
        result = _unknown("market_path_pattern_occurrences", pattern_hash=pattern_hash, limit=bounded_limit)
        if cutoff is not None:
            result["as_of"] = cutoff.isoformat()
            result["temporal_cutoff_enforced"] = True
        return result

    grouped: dict[int, dict[str, Any]] = {}
    horizon_counts: Counter[str] = Counter()
    for row in rows:
        item = dict(row)
        occurrence_id = int(item["occurrence_id"])
        record = grouped.setdefault(
            occurrence_id,
            {
                "occurrence_id": occurrence_id,
                "mint": str(item["mint"]),
                "pattern_observed_at": item["pattern_observed_at"],
                "followup_horizons": [],
                "followup_records": [],
                "evidence_only": True,
            },
        )
        horizon = item.get("horizon")
        if not horizon:
            continue
        horizon = str(horizon)
        followup = {
            "horizon": horizon,
            "horizon_seconds": item.get("horizon_seconds"),
            "observed_at": item.get("followup_observed_at"),
            "ingested_at": item.get("followup_ingested_at"),
            "source": item.get("source"),
            "evidence_basis": item.get("evidence_basis"),
            "metrics": item.get("metrics") if isinstance(item.get("metrics"), dict) else {},
        }
        record["followup_horizons"].append(horizon)
        record["followup_records"].append(followup)

    records = list(grouped.values())
    with_followup = 0
    for record in records:
        for key in ("pattern_observed_at",):
            value = record.get(key)
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()
        seen = set(record["followup_horizons"])
        if seen:
            with_followup += 1
            for horizon in seen:
                horizon_counts[horizon] += 1
        for followup in record["followup_records"]:
            for key in ("observed_at", "ingested_at"):
                value = followup.get(key)
                if hasattr(value, "isoformat"):
                    followup[key] = value.isoformat()

    total = len(records)
    without_followup = total - with_followup
    horizon_coverage = {
        horizon: {
            "occurrences_observed": horizon_counts.get(horizon, 0),
            "occurrence_count": total,
            "coverage": (horizon_counts.get(horizon, 0) / total) if total else None,
        }
        for horizon in SUPPORTED_HORIZONS
    }

    result: dict[str, Any] = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "occurrence_count": total,
        "occurrences_with_followup": with_followup,
        "occurrences_without_followup": without_followup,
        "followup_coverage": (with_followup / total) if total else None,
        "horizon_coverage": horizon_coverage,
        "records": records,
        "missing": [] if with_followup else ["followup_market_outcome_observations"],
        "bounded": {"occurrence_limit": bounded_limit},
        "evidence_basis": "market_path_pattern_occurrences+market_outcome_observations",
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
