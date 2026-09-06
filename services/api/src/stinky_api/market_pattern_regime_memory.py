"""Cross-pattern calibration regime evidence.

A regime observation is descriptive corroboration: it counts independent pattern
snapshots whose latest visible calibration state changed in the same direction
within a bounded evidence-time window. It does not infer a shared cause or grant
prediction, confidence, risk, quality, or trading authority.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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


def _unknown(reason: str, *, lookback_hours: int) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "as_of": None,
        "lookback_hours": lookback_hours,
        "pattern_count": 0,
        "state_counts": {},
        "degrading_pattern_count": 0,
        "improving_pattern_count": 0,
        "stable_pattern_count": 0,
        "insufficient_evidence_pattern_count": 0,
        "degrading_patterns": [],
        "improving_patterns": [],
        "missing": [reason],
        "evidence_basis": "latest_visible_persisted_calibration_snapshot_per_pattern",
        "evidence_only": True,
    }


async def calibration_regime_memory(
    session: AsyncSession,
    *,
    as_of: datetime | str | None = None,
    lookback_hours: int = 24,
    pattern_limit: int = 500,
) -> dict[str, Any]:
    """Summarize latest visible calibration states across independent patterns."""
    hours = max(1, min(int(lookback_hours), 24 * 30))
    limit = max(1, min(int(pattern_limit), 2000))
    cutoff = _time(as_of) if as_of is not None else datetime.now(timezone.utc)
    if cutoff is None:
        return _unknown("invalid_as_of", lookback_hours=hours)
    window_start = cutoff - timedelta(hours=hours)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT ON (pattern_hash)
                           pattern_hash, trend_status, evidence_through_observed_at,
                           computed_at, ingested_at
                    FROM market_pattern_calibration_snapshots
                    WHERE evidence_through_observed_at <= :as_of
                      AND computed_at <= :as_of
                      AND ingested_at <= :as_of
                      AND evidence_through_observed_at >= :window_start
                    ORDER BY pattern_hash, evidence_through_observed_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"as_of": cutoff, "window_start": window_start, "limit": limit},
            )
        ).mappings().all()
    except Exception:
        result = _unknown("market_pattern_calibration_snapshots", lookback_hours=hours)
        result["as_of"] = cutoff.isoformat()
        return result

    state_counts = {"STABLE": 0, "IMPROVING": 0, "DEGRADING": 0, "INSUFFICIENT_EVIDENCE": 0}
    degrading: list[dict[str, Any]] = []
    improving: list[dict[str, Any]] = []
    for row in rows:
        state = str(row.get("trend_status") or "")
        if state not in state_counts:
            continue
        state_counts[state] += 1
        item = {
            "pattern_hash": str(row.get("pattern_hash") or ""),
            "evidence_through_observed_at": row["evidence_through_observed_at"].isoformat() if hasattr(row.get("evidence_through_observed_at"), "isoformat") else str(row.get("evidence_through_observed_at") or ""),
            "evidence_only": True,
        }
        if state == "DEGRADING":
            degrading.append(item)
        elif state == "IMPROVING":
            improving.append(item)

    observed_count = sum(state_counts.values())
    return {
        "status": "OBSERVED" if observed_count else "UNKNOWN",
        "as_of": cutoff.isoformat(),
        "window_start": window_start.isoformat(),
        "lookback_hours": hours,
        "pattern_count": observed_count,
        "state_counts": state_counts,
        "degrading_pattern_count": state_counts["DEGRADING"],
        "improving_pattern_count": state_counts["IMPROVING"],
        "stable_pattern_count": state_counts["STABLE"],
        "insufficient_evidence_pattern_count": state_counts["INSUFFICIENT_EVIDENCE"],
        "degrading_patterns": degrading,
        "improving_patterns": improving,
        "missing": [] if observed_count else ["calibration_snapshots_in_window"],
        "bounded": {"pattern_limit": limit},
        "temporal_cutoff_enforced": True,
        "shared_cause_inferred": False,
        "evidence_basis": "latest_visible_persisted_calibration_snapshot_per_pattern",
        "evidence_only": True,
    }
