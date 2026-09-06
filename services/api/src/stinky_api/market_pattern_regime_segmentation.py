"""Temporally safe market-pattern regime segmentation.

Each historical occurrence is assigned only the broader calibration regime that
was observable at that occurrence timestamp. Regime evidence comes from other
patterns' persisted calibration snapshots whose evidence, computation, and
ingestion timestamps all existed by the occurrence. This is descriptive evidence
only and does not produce prediction, probability, confidence, quality/risk
scoring, causality, or trading authority.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

REGIME_STATES = (
    "STABLE_DOMINANT",
    "IMPROVING_DOMINANT",
    "DEGRADING_DOMINANT",
    "MIXED",
    "INSUFFICIENT_EVIDENCE",
)


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def classify_regime_state(state_counts: dict[str, int], *, min_independent_patterns: int = 3) -> str:
    """Classify a descriptive regime from independent-pattern state counts."""
    minimum = max(1, int(min_independent_patterns))
    stable = max(0, int(state_counts.get("STABLE", 0)))
    improving = max(0, int(state_counts.get("IMPROVING", 0)))
    degrading = max(0, int(state_counts.get("DEGRADING", 0)))
    informative = stable + improving + degrading
    if informative < minimum:
        return "INSUFFICIENT_EVIDENCE"
    maximum = max(stable, improving, degrading)
    winners = sum(1 for value in (stable, improving, degrading) if value == maximum)
    if winners != 1:
        return "MIXED"
    if stable == maximum:
        return "STABLE_DOMINANT"
    if improving == maximum:
        return "IMPROVING_DOMINANT"
    return "DEGRADING_DOMINANT"


def _unknown(reason: str, *, pattern_hash: str | None, occurrence_limit: int, lookback_hours: int) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "pattern_hash": pattern_hash,
        "occurrence_count": 0,
        "segmented_occurrence_count": 0,
        "records": [],
        "regime_counts": {},
        "missing": [reason],
        "bounded": {"occurrence_limit": occurrence_limit, "regime_lookback_hours": lookback_hours},
        "temporal_assignment_rule": "regime_snapshot_visible_by_occurrence_time",
        "evidence_only": True,
    }


async def segment_pattern_occurrences_by_regime(
    session: AsyncSession,
    pattern_hash: str,
    *,
    occurrence_limit: int = 100,
    regime_lookback_hours: int = 24,
    min_independent_patterns: int = 3,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Assign each historical occurrence the broader regime visible at that time."""
    pattern_hash = str(pattern_hash or "").strip()
    limit = max(1, min(int(occurrence_limit), 500))
    hours = max(1, min(int(regime_lookback_hours), 24 * 30))
    minimum = max(1, min(int(min_independent_patterns), 100))
    if not pattern_hash:
        return _unknown("pattern_hash", pattern_hash=None, occurrence_limit=limit, lookback_hours=hours)
    cutoff = _time(as_of)
    if as_of is not None and cutoff is None:
        return _unknown("invalid_as_of", pattern_hash=pattern_hash, occurrence_limit=limit, lookback_hours=hours)

    occurrence_cutoff = "AND o.observed_at <= :as_of" if cutoff is not None else ""
    params: dict[str, Any] = {
        "pattern_hash": pattern_hash,
        "limit": limit,
        "lookback": timedelta(hours=hours),
    }
    if cutoff is not None:
        params["as_of"] = cutoff

    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    WITH occurrences AS (
                        SELECT o.id, o.mint, o.observed_at
                        FROM market_path_pattern_occurrences o
                        WHERE o.pattern_hash = :pattern_hash
                          {occurrence_cutoff}
                        ORDER BY o.observed_at ASC, o.id ASC
                        LIMIT :limit
                    )
                    SELECT occ.id AS occurrence_id,
                           occ.mint,
                           occ.observed_at AS pattern_observed_at,
                           snap.pattern_hash AS regime_pattern_hash,
                           snap.trend_status,
                           snap.evidence_through_observed_at,
                           snap.computed_at,
                           snap.ingested_at
                    FROM occurrences occ
                    LEFT JOIN LATERAL (
                        SELECT DISTINCT ON (s.pattern_hash)
                               s.pattern_hash, s.trend_status,
                               s.evidence_through_observed_at, s.computed_at, s.ingested_at
                        FROM market_pattern_calibration_snapshots s
                        WHERE s.pattern_hash <> :pattern_hash
                          AND s.evidence_through_observed_at <= occ.observed_at
                          AND s.computed_at <= occ.observed_at
                          AND s.ingested_at <= occ.observed_at
                          AND s.evidence_through_observed_at >= occ.observed_at - :lookback
                        ORDER BY s.pattern_hash, s.evidence_through_observed_at DESC, s.id DESC
                    ) snap ON TRUE
                    ORDER BY occ.observed_at ASC, occ.id ASC, snap.pattern_hash ASC NULLS LAST
                    """
                ),
                params,
            )
        ).mappings().all()
    except Exception:
        return _unknown("historical_regime_evidence", pattern_hash=pattern_hash, occurrence_limit=limit, lookback_hours=hours)

    if not rows:
        result = _unknown("market_path_pattern_occurrences", pattern_hash=pattern_hash, occurrence_limit=limit, lookback_hours=hours)
        if cutoff is not None:
            result["as_of"] = cutoff.isoformat()
            result["temporal_cutoff_enforced"] = True
        return result

    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        occurrence_id = int(row["occurrence_id"])
        record = grouped.setdefault(
            occurrence_id,
            {
                "occurrence_id": occurrence_id,
                "mint": str(row["mint"]),
                "pattern_observed_at": row["pattern_observed_at"],
                "state_counts": {"STABLE": 0, "IMPROVING": 0, "DEGRADING": 0, "INSUFFICIENT_EVIDENCE": 0},
                "independent_pattern_count": 0,
                "regime_state": "INSUFFICIENT_EVIDENCE",
                "evidence_only": True,
            },
        )
        regime_pattern_hash = str(row.get("regime_pattern_hash") or "").strip()
        state = str(row.get("trend_status") or "").strip()
        if not regime_pattern_hash or state not in record["state_counts"]:
            continue
        record["state_counts"][state] += 1
        record["independent_pattern_count"] += 1

    records = list(grouped.values())
    regime_counts = {state: 0 for state in REGIME_STATES}
    segmented = 0
    for record in records:
        observed_at = record.get("pattern_observed_at")
        if hasattr(observed_at, "isoformat"):
            record["pattern_observed_at"] = observed_at.isoformat()
        record["regime_state"] = classify_regime_state(
            record["state_counts"],
            min_independent_patterns=minimum,
        )
        regime_counts[record["regime_state"]] += 1
        if record["regime_state"] != "INSUFFICIENT_EVIDENCE":
            segmented += 1

    result: dict[str, Any] = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "occurrence_count": len(records),
        "segmented_occurrence_count": segmented,
        "records": records,
        "regime_counts": regime_counts,
        "criteria": {"min_independent_patterns": minimum, "regime_lookback_hours": hours},
        "missing": [] if segmented else ["sufficient_independent_regime_evidence"],
        "bounded": {"occurrence_limit": limit, "regime_lookback_hours": hours},
        "temporal_assignment_rule": "evidence_through+computed_at+ingested_at<=pattern_observed_at",
        "target_pattern_excluded_from_regime": True,
        "future_regime_leakage_permitted": False,
        "evidence_basis": "persisted_calibration_snapshots_visible_at_each_pattern_occurrence",
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
