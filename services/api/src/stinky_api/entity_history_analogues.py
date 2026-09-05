"""Descriptive historical analogues from persisted entity behavior.

Analogue matching is evidence discovery only. Missing dimensions are excluded
from comparisons rather than treated as zero, and the result never implies
quality, risk, intent, prediction, or a trading decision.

Important temporal rule: analogue selection must not use outcome-derived
fields, and an explicit ``as_of`` cutoff must exclude fingerprint snapshots
computed after the historical investigation point.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_SELECTION_NUMERIC_KEYS = (
    "launch_count",
    "median_launch_interval_sec",
    "wallet_count",
    "early_buyer_wallet_count",
    "early_buyer_mint_count",
    "repeat_early_buyer_wallet_count",
)


def _parse_as_of(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text_value = str(value).strip()
        if text_value.endswith("Z"):
            text_value = text_value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text_value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _distance(target: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, int, list[str]]:
    distances: list[float] = []
    matched: list[str] = []
    for key in _SELECTION_NUMERIC_KEYS:
        left = _number(target.get(key))
        right = _number(candidate.get(key))
        if left is None or right is None:
            continue
        scale = max(abs(left), abs(right), 1.0)
        distances.append(abs(left - right) / scale)
        matched.append(key)
    cadence = target.get("cadence_bucket")
    candidate_cadence = candidate.get("cadence_bucket")
    if cadence and candidate_cadence and cadence != "unknown" and cadence == candidate_cadence:
        matched.append("cadence_bucket")
    if not distances and not matched:
        return float("inf"), 0, []
    numeric_distance = sum(distances) / len(distances) if distances else 0.0
    return numeric_distance, len(matched), matched


def _unknown(reason: str, *, as_of: datetime | None = None) -> dict[str, Any]:
    result = {
        "status": "UNKNOWN",
        "records": [],
        "missing": [reason],
        "evidence_basis": "entity_behavior_fingerprints",
        "selection_basis": "activity_and_network_structure_only",
        "outcome_dimensions_excluded": True,
        "evidence_only": True,
    }
    if as_of is not None:
        result["as_of"] = as_of.isoformat()
    return result


async def find_historical_analogues(
    session: AsyncSession,
    entity_id: UUID,
    *,
    limit: int = 10,
    candidate_limit: int = 500,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Find bounded entities using outcome-independent dimensions at an optional cutoff."""
    limit = max(1, min(50, int(limit)))
    candidate_limit = max(limit, min(500, int(candidate_limit)))
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return _unknown("invalid_as_of")

    try:
        cutoff_clause = "AND computed_at <= :as_of" if cutoff is not None else ""
        params: dict[str, Any] = {"entity_id": entity_id}
        if cutoff is not None:
            params["as_of"] = cutoff
        target_row = (
            await session.execute(
                text(
                    f"""
                    SELECT fingerprint, computed_at
                    FROM entity_behavior_fingerprints
                    WHERE entity_id = :entity_id
                      {cutoff_clause}
                    ORDER BY computed_at DESC
                    LIMIT 1
                    """
                ),
                params,
            )
        ).mappings().first()
        if not target_row or not isinstance(target_row.get("fingerprint"), dict):
            return _unknown("behavior_fingerprint", as_of=cutoff)

        candidate_params = {"entity_id": entity_id, "candidate_limit": candidate_limit}
        if cutoff is not None:
            candidate_params["as_of"] = cutoff
        candidate_rows = (
            await session.execute(
                text(
                    f"""
                    SELECT entity_id::text AS entity_id, fingerprint, computed_at
                    FROM entity_behavior_fingerprints
                    WHERE entity_id <> :entity_id
                      {cutoff_clause}
                    ORDER BY computed_at DESC, entity_id
                    LIMIT :candidate_limit
                    """
                ),
                candidate_params,
            )
        ).mappings().all()
    except Exception:
        return _unknown("historical_analogues", as_of=cutoff) | {"evidence_basis": "unknown_table_or_query"}

    target = target_row["fingerprint"]
    records: list[dict[str, Any]] = []
    for row in candidate_rows:
        candidate = row.get("fingerprint")
        if not isinstance(candidate, dict):
            continue
        distance, matched_count, matched_dimensions = _distance(target, candidate)
        if matched_count == 0:
            continue
        records.append(
            {
                "entity_id": row["entity_id"],
                "similarity_distance": distance,
                "matched_dimension_count": matched_count,
                "matched_dimensions": matched_dimensions,
                "candidate_fingerprint_computed_at": (
                    row["computed_at"].isoformat()
                    if hasattr(row.get("computed_at"), "isoformat")
                    else row.get("computed_at")
                ),
                "evidence_basis": "entity_behavior_fingerprints",
                "selection_basis": "activity_and_network_structure_only",
                "outcome_dimensions_excluded": True,
            }
        )

    records.sort(key=lambda item: (item["similarity_distance"], -item["matched_dimension_count"], item["entity_id"]))
    result = {
        "status": "OBSERVED",
        "records": records[:limit],
        "evidence_basis": "entity_behavior_fingerprints",
        "selection_basis": "activity_and_network_structure_only",
        "outcome_dimensions_excluded": True,
        "bounded": {"limit": limit, "candidate_limit": candidate_limit},
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
