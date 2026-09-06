"""Persist and retrieve bounded historical coverage for market path patterns.

Patterns are descriptive computed evidence. Frequency is never converted into a
prediction, probability, quality score, risk score, or trading authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.market_path_patterns import canonical_pattern_hash


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
        "distinct_market_count": 0,
        "first_observed_at": None,
        "last_observed_at": None,
        "records": [],
        "missing": [reason],
        "bounded": {"limit": limit},
        "evidence_only": True,
    }


async def persist_market_pattern_occurrence(
    session: AsyncSession,
    *,
    mint: str,
    signature: dict[str, Any],
    observed_at: datetime | str,
    source: str = "investigation_market_path_signature",
    evidence_basis: str = "observed_market_lifecycle_analysis",
) -> str | None:
    """Persist one idempotent observed market↔pattern occurrence."""
    mint = str(mint or "").strip()
    observed = _parse_time(observed_at)
    if not mint or not isinstance(signature, dict) or not signature or observed is None:
        return None
    pattern_hash = canonical_pattern_hash(signature)
    payload = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    try:
        await session.execute(
            text(
                """
                INSERT INTO market_path_patterns (
                    pattern_hash, signature, evidence_basis,
                    first_observed_at, last_observed_at, occurrence_count
                ) VALUES (
                    :pattern_hash, CAST(:signature AS jsonb), :evidence_basis,
                    :observed_at, :observed_at, 0
                )
                ON CONFLICT (pattern_hash) DO NOTHING
                """
            ),
            {
                "pattern_hash": pattern_hash,
                "signature": payload,
                "evidence_basis": evidence_basis,
                "observed_at": observed,
            },
        )
        inserted = (
            await session.execute(
                text(
                    """
                    INSERT INTO market_path_pattern_occurrences (
                        pattern_hash, mint, observed_at, source, evidence_basis, signature
                    ) VALUES (
                        :pattern_hash, :mint, :observed_at, :source, :evidence_basis,
                        CAST(:signature AS jsonb)
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "pattern_hash": pattern_hash,
                    "mint": mint,
                    "observed_at": observed,
                    "source": source,
                    "evidence_basis": evidence_basis,
                    "signature": payload,
                },
            )
        ).first()
        if inserted:
            await session.execute(
                text(
                    """
                    UPDATE market_path_patterns
                    SET occurrence_count = occurrence_count + 1,
                        first_observed_at = LEAST(first_observed_at, :observed_at),
                        last_observed_at = GREATEST(last_observed_at, :observed_at),
                        updated_at = now()
                    WHERE pattern_hash = :pattern_hash
                    """
                ),
                {"pattern_hash": pattern_hash, "observed_at": observed},
            )
        await session.commit()
        return pattern_hash
    except Exception:
        await session.rollback()
        return None


async def market_pattern_history(
    session: AsyncSession,
    pattern_hash: str,
    *,
    limit: int = 100,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Return bounded occurrence evidence and cutoff-safe historical coverage."""
    pattern_hash = str(pattern_hash or "").strip()
    bounded_limit = max(1, min(int(limit), 500))
    if not pattern_hash:
        return _unknown("pattern_hash", pattern_hash=None, limit=bounded_limit)
    cutoff = _parse_time(as_of)
    if as_of is not None and cutoff is None:
        return _unknown("invalid_as_of", pattern_hash=pattern_hash, limit=bounded_limit)

    cutoff_clause = ""
    params: dict[str, Any] = {"pattern_hash": pattern_hash, "limit": bounded_limit}
    if cutoff is not None:
        cutoff_clause = "AND observed_at <= :as_of"
        params["as_of"] = cutoff
    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT mint, observed_at, ingested_at, source, evidence_basis, signature, created_at
                    FROM market_path_pattern_occurrences
                    WHERE pattern_hash = :pattern_hash
                      {cutoff_clause}
                    ORDER BY observed_at ASC, id ASC
                    LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()
    except Exception:
        return _unknown("market_path_pattern_occurrences", pattern_hash=pattern_hash, limit=bounded_limit)

    records: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("observed_at", "ingested_at", "created_at"):
            value = item.get(key)
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        records.append(item)
    if not records:
        result = _unknown("market_path_pattern_occurrences", pattern_hash=pattern_hash, limit=bounded_limit)
    else:
        result = {
            "status": "OBSERVED",
            "pattern_hash": pattern_hash,
            "occurrence_count": len(records),
            "distinct_market_count": len({str(r.get("mint")) for r in records if r.get("mint")}),
            "first_observed_at": records[0].get("observed_at"),
            "last_observed_at": records[-1].get("observed_at"),
            "records": records,
            "missing": [],
            "bounded": {"limit": bounded_limit},
            "evidence_basis": "market_path_pattern_occurrences",
            "evidence_only": True,
        }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
