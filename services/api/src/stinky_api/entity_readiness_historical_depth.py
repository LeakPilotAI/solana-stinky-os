"""Read-only historical-depth diagnostics for entity readiness evidence."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "ENTITY_READINESS_HISTORICAL_DEPTH_DIAGNOSTIC_ONLY",
    "release_authority": False,
    "predictive_authority": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "trade_signal": False,
    "evidence_only": True,
    "read_only": True,
}

MIN_PRIOR_LAUNCHES = 5
MIN_PRIOR_KNOWN_OUTCOMES = 3
MIN_PRIOR_OUTCOME_COVERAGE = 0.60
MIN_PRIOR_HISTORY_SPAN_DAYS = 7.0
MIN_RELATIONSHIP_SNAPSHOTS = 4


def _empty(status: str = "NO_PERSISTED_HISTORY") -> dict[str, Any]:
    return {
        "status": status,
        "entity_count": 0,
        "developer_history_depth": {
            "entities_with_launch_rows": 0,
            "entities_with_multiple_total_launches": 0,
            "entities_with_prior_launches": 0,
            "entities_meeting_min_prior_launches": 0,
            "entities_meeting_min_prior_known_outcomes": 0,
            "entities_meeting_min_prior_outcome_coverage": 0,
            "entities_meeting_min_prior_history_span": 0,
            "entities_meeting_prior_outcome_gate": 0,
            "max_total_launches": 0,
            "max_prior_launches": 0,
            "max_prior_classified_outcomes": 0,
            "max_prior_history_span_days": 0.0,
        },
        "relationship_history_depth": {
            "entities_with_relationship_snapshots": 0,
            "entities_with_two_distinct_relationship_snapshots": 0,
            "entities_meeting_min_relationship_snapshots": 0,
            "max_distinct_relationship_snapshots": 0,
        },
        "thresholds": {
            "min_prior_launches": MIN_PRIOR_LAUNCHES,
            "min_prior_known_outcomes": MIN_PRIOR_KNOWN_OUTCOMES,
            "min_prior_outcome_coverage": MIN_PRIOR_OUTCOME_COVERAGE,
            "min_prior_history_span_days": MIN_PRIOR_HISTORY_SPAN_DAYS,
            "min_relationship_snapshots": MIN_RELATIONSHIP_SNAPSHOTS,
        },
        **AUTHORITY,
    }


def summarize_historical_depth(
    launch_rows: list[dict[str, Any]],
    relationship_rows: list[dict[str, Any]],
    *,
    entity_count: int,
) -> dict[str, Any]:
    """Summarize raw depth without changing readiness thresholds or semantics."""
    developer = _empty()["developer_history_depth"]
    relationship = _empty()["relationship_history_depth"]

    for row in launch_rows or []:
        total = int(row.get("total_launches") or 0)
        prior = int(row.get("prior_launches") or 0)
        classified = int(row.get("prior_classified_outcomes") or 0)
        coverage = float(classified / prior) if prior > 0 else 0.0
        span_days = float(row.get("prior_history_span_days") or 0.0)

        if total > 0:
            developer["entities_with_launch_rows"] += 1
        if total >= 2:
            developer["entities_with_multiple_total_launches"] += 1
        if prior > 0:
            developer["entities_with_prior_launches"] += 1
        if prior >= MIN_PRIOR_LAUNCHES:
            developer["entities_meeting_min_prior_launches"] += 1
        if classified >= MIN_PRIOR_KNOWN_OUTCOMES:
            developer["entities_meeting_min_prior_known_outcomes"] += 1
        if prior > 0 and coverage >= MIN_PRIOR_OUTCOME_COVERAGE:
            developer["entities_meeting_min_prior_outcome_coverage"] += 1
        if span_days >= MIN_PRIOR_HISTORY_SPAN_DAYS:
            developer["entities_meeting_min_prior_history_span"] += 1
        if (
            prior >= MIN_PRIOR_LAUNCHES
            and classified >= MIN_PRIOR_KNOWN_OUTCOMES
            and coverage >= MIN_PRIOR_OUTCOME_COVERAGE
        ):
            developer["entities_meeting_prior_outcome_gate"] += 1

        developer["max_total_launches"] = max(developer["max_total_launches"], total)
        developer["max_prior_launches"] = max(developer["max_prior_launches"], prior)
        developer["max_prior_classified_outcomes"] = max(
            developer["max_prior_classified_outcomes"], classified
        )
        developer["max_prior_history_span_days"] = max(
            developer["max_prior_history_span_days"], span_days
        )

    for row in relationship_rows or []:
        distinct_count = int(row.get("distinct_snapshot_count") or 0)
        if distinct_count > 0:
            relationship["entities_with_relationship_snapshots"] += 1
        if distinct_count >= 2:
            relationship["entities_with_two_distinct_relationship_snapshots"] += 1
        if distinct_count >= MIN_RELATIONSHIP_SNAPSHOTS:
            relationship["entities_meeting_min_relationship_snapshots"] += 1
        relationship["max_distinct_relationship_snapshots"] = max(
            relationship["max_distinct_relationship_snapshots"], distinct_count
        )

    return {
        "status": "MEASURED" if entity_count else "NO_PERSISTED_HISTORY",
        "entity_count": entity_count,
        "developer_history_depth": developer,
        "relationship_history_depth": relationship,
        "thresholds": _empty()["thresholds"],
        **AUTHORITY,
    }


async def entity_readiness_historical_depth(
    session: AsyncSession,
    *,
    entity_ids: list[str],
    not_before: datetime,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Measure current prior-launch and relationship-snapshot depth for a bounded cohort.

    Current launch outcomes are mutable in ``entity_launches`` and lack a separate
    outcome-ingested timestamp, so historical ``as_of`` reconstruction fails closed.
    """
    ids = [str(value) for value in entity_ids if str(value).strip()][:500]
    if not ids:
        return _empty()
    if as_of is not None:
        result = _empty("HISTORICAL_DEPTH_STATE_UNAVAILABLE")
        result["entity_count"] = len(ids)
        result["reason"] = (
            "entity_launches does not store an independent outcome-ingested timestamp"
        )
        result["historical_as_of_supported"] = False
        return result

    try:
        launch_rows = (
            await session.execute(
                text(
                    """
                    WITH ranked AS (
                        SELECT
                            entity_id,
                            observed_at,
                            outcome_status,
                            ROW_NUMBER() OVER (
                                PARTITION BY entity_id
                                ORDER BY observed_at DESC, id DESC
                            ) AS launch_rank
                        FROM entity_launches
                        WHERE entity_id = ANY(CAST(:entity_ids AS uuid[]))
                    )
                    SELECT
                        entity_id,
                        COUNT(*)::int AS total_launches,
                        COUNT(*) FILTER (WHERE launch_rank > 1)::int AS prior_launches,
                        COUNT(*) FILTER (
                            WHERE launch_rank > 1
                              AND UPPER(COALESCE(outcome_status, '')) IN ('RUNNER','HELD','FADE')
                        )::int AS prior_classified_outcomes,
                        COALESCE(
                            EXTRACT(EPOCH FROM (
                                MAX(observed_at) FILTER (WHERE launch_rank > 1)
                                - MIN(observed_at) FILTER (WHERE launch_rank > 1)
                            )) / 86400.0,
                            0.0
                        )::float8 AS prior_history_span_days
                    FROM ranked
                    GROUP BY entity_id
                    """
                ),
                {"entity_ids": ids},
            )
        ).mappings().all()
    except Exception:
        result = _empty("UNKNOWN")
        result["entity_count"] = len(ids)
        result["missing"] = ["entity_launches"]
        return result

    try:
        relationship_rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        entity_id,
                        COUNT(DISTINCT evidence_hash) FILTER (
                            WHERE evidence_hash IS NOT NULL AND evidence_hash <> ''
                        )::int AS distinct_snapshot_count
                    FROM developer_correlation_snapshots
                    WHERE entity_id = ANY(CAST(:entity_ids AS uuid[]))
                      AND observed_at >= :not_before
                    GROUP BY entity_id
                    """
                ),
                {"entity_ids": ids, "not_before": not_before},
            )
        ).mappings().all()
    except Exception:
        result = summarize_historical_depth(
            [dict(row) for row in launch_rows], [], entity_count=len(ids)
        )
        result["status"] = "PARTIAL"
        result["missing"] = ["developer_correlation_snapshots"]
        return result

    return summarize_historical_depth(
        [dict(row) for row in launch_rows],
        [dict(row) for row in relationship_rows],
        entity_count=len(ids),
    )
