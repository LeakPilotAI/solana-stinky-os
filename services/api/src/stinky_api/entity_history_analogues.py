"""Descriptive historical analogues from persisted entity behavior.

Analogue matching is evidence discovery only. Missing dimensions are excluded
from comparisons rather than treated as zero, and the result never implies
quality, risk, intent, prediction, or a trading decision.
"""

from __future__ import annotations

from math import isfinite
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_NUMERIC_KEYS = (
    "launch_count",
    "outcomes_known",
    "completed_count",
    "outcomes_unknown",
    "outcome_coverage",
    "median_launch_interval_sec",
    "wallet_count",
    "early_buyer_wallet_count",
    "early_buyer_mint_count",
    "repeat_early_buyer_wallet_count",
)


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
    for key in _NUMERIC_KEYS:
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


async def find_historical_analogues(
    session: AsyncSession,
    entity_id: UUID,
    *,
    limit: int = 10,
    candidate_limit: int = 500,
) -> dict[str, Any]:
    """Find bounded entities with descriptively similar observed fingerprints."""
    limit = max(1, min(50, int(limit)))
    candidate_limit = max(limit, min(500, int(candidate_limit)))
    try:
        target_row = (
            await session.execute(
                text(
                    """
                    SELECT fingerprint
                    FROM entity_behavior_fingerprints
                    WHERE entity_id = :entity_id
                    LIMIT 1
                    """
                ),
                {"entity_id": entity_id},
            )
        ).mappings().first()
        if not target_row or not isinstance(target_row.get("fingerprint"), dict):
            return {
                "status": "UNKNOWN",
                "records": [],
                "missing": ["behavior_fingerprint"],
                "evidence_basis": "entity_behavior_fingerprints",
            }

        candidate_rows = (
            await session.execute(
                text(
                    """
                    SELECT entity_id::text AS entity_id, fingerprint, computed_at
                    FROM entity_behavior_fingerprints
                    WHERE entity_id <> :entity_id
                    ORDER BY computed_at DESC, entity_id
                    LIMIT :candidate_limit
                    """
                ),
                {"entity_id": entity_id, "candidate_limit": candidate_limit},
            )
        ).mappings().all()
    except Exception:
        return {
            "status": "UNKNOWN",
            "records": [],
            "missing": ["historical_analogues"],
            "evidence_basis": "unknown_table_or_query",
        }

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
            }
        )

    records.sort(key=lambda item: (item["similarity_distance"], -item["matched_dimension_count"], item["entity_id"]))
    return {
        "status": "OBSERVED" if records else "OBSERVED_EMPTY",
        "records": records[:limit],
        "evidence_basis": "entity_behavior_fingerprints",
        "bounded": {"limit": limit, "candidate_limit": candidate_limit},
        "evidence_only": True,
    }
