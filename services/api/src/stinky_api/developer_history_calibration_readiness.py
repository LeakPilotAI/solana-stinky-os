"""Fail-closed readiness gate for descriptive developer-history calibration.

Readiness means the evidence base is sufficiently deep and temporally broad to
enter a descriptive calibration phase. It never creates predictive authority,
risk/quality scores, probabilities, confidence, expected return, or trade
signals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MIN_DISTINCT_PRIOR_LAUNCHES = 5
MIN_KNOWN_OUTCOMES = 3
MIN_KNOWN_OUTCOME_RATIO = 0.60
MIN_OBSERVATION_SPAN_DAYS = 7.0
MIN_DISTINCT_EVIDENCE_HASHES = 3

KNOWN_OUTCOMES = {"RUNNER", "HELD", "FADE"}


def _parse_time(value: Any) -> datetime | None:
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
    except (TypeError, ValueError):
        return None


def _visible_snapshot(record: dict[str, Any], cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    observed = _parse_time(record.get("observed_at"))
    ingested = _parse_time(record.get("ingested_at"))
    return observed is not None and ingested is not None and observed <= cutoff and ingested <= cutoff


def _visible_launches(evidence: dict[str, Any], cutoff: datetime | None) -> tuple[list[dict[str, Any]], int]:
    launch_history = evidence.get("launch_history") if isinstance(evidence.get("launch_history"), dict) else {}
    raw = launch_history.get("records") if isinstance(launch_history.get("records"), list) else []
    visible: list[dict[str, Any]] = []
    excluded = 0
    for item in raw:
        if not isinstance(item, dict):
            excluded += 1
            continue
        row = dict(item)
        mint = str(row.get("mint") or "").strip()
        if not mint:
            excluded += 1
            continue
        if cutoff is not None:
            observed = _parse_time(row.get("observed_at"))
            ingested_raw = row.get("ingested_at")
            ingested = _parse_time(ingested_raw) if ingested_raw is not None else None
            if observed is None or observed > cutoff or (ingested_raw is not None and (ingested is None or ingested > cutoff)):
                excluded += 1
                continue
        visible.append(row)
    return visible, excluded


def assess_developer_history_calibration_readiness(
    records: list[dict[str, Any]],
    *,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Assess whether immutable developer history is ready for descriptive calibration."""
    cutoff = _parse_time(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        return {
            "status": "UNKNOWN",
            "ready": False,
            "blockers": ["INVALID_AS_OF"],
            "missing": ["valid_as_of"],
            "interpretation": "DESCRIPTIVE_READINESS_ONLY",
            "predictive_authority": False,
            "risk_inferred": False,
            "quality_inferred": False,
            "trade_signal": False,
            "evidence_only": True,
        }

    normalized = [dict(row) for row in records if isinstance(row, dict)]
    visible_records = [row for row in normalized if _visible_snapshot(row, cutoff)]
    excluded_snapshots = len(normalized) - len(visible_records)
    visible_records.sort(
        key=lambda row: (
            _parse_time(row.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc),
            int(row.get("id") or 0),
        )
    )

    latest = visible_records[-1] if visible_records else None
    latest_evidence = dict(latest.get("evidence") or {}) if latest else {}
    launches, excluded_launches = _visible_launches(latest_evidence, cutoff)

    # One mint contributes once even if duplicate evidence is present.
    by_mint: dict[str, dict[str, Any]] = {}
    for row in launches:
        mint = str(row.get("mint") or "").strip()
        if mint and mint not in by_mint:
            by_mint[mint] = row
    distinct_launches = list(by_mint.values())

    known_outcome_count = 0
    unknown_outcome_count = 0
    launch_times: list[datetime] = []
    for row in distinct_launches:
        outcome = str(row.get("outcome_status") or "UNKNOWN").upper()
        if outcome in KNOWN_OUTCOMES:
            known_outcome_count += 1
        else:
            unknown_outcome_count += 1
        observed = _parse_time(row.get("observed_at"))
        if observed is not None:
            launch_times.append(observed)

    distinct_launch_count = len(distinct_launches)
    known_outcome_ratio = (
        known_outcome_count / distinct_launch_count if distinct_launch_count else 0.0
    )
    if len(launch_times) >= 2:
        observation_span_days = (max(launch_times) - min(launch_times)).total_seconds() / 86400.0
    else:
        observation_span_days = 0.0

    distinct_hashes = {
        str(row.get("evidence_hash"))
        for row in visible_records
        if str(row.get("evidence_hash") or "").strip()
    }

    blockers: list[str] = []
    if distinct_launch_count < MIN_DISTINCT_PRIOR_LAUNCHES:
        blockers.append("INSUFFICIENT_DISTINCT_LAUNCHES")
    if known_outcome_count < MIN_KNOWN_OUTCOMES:
        blockers.append("INSUFFICIENT_KNOWN_OUTCOMES")
    if known_outcome_ratio < MIN_KNOWN_OUTCOME_RATIO:
        blockers.append("INSUFFICIENT_OUTCOME_COVERAGE")
    if observation_span_days < MIN_OBSERVATION_SPAN_DAYS:
        blockers.append("INSUFFICIENT_TIME_SPAN")
    if len(distinct_hashes) < MIN_DISTINCT_EVIDENCE_HASHES:
        blockers.append("INSUFFICIENT_EVIDENCE_DIVERSITY")

    if not visible_records:
        status = "INSUFFICIENT_HISTORY"
    elif not blockers:
        status = "READY_FOR_DESCRIPTIVE_CALIBRATION"
    elif "INSUFFICIENT_DISTINCT_LAUNCHES" in blockers:
        status = "INSUFFICIENT_HISTORY"
    elif "INSUFFICIENT_KNOWN_OUTCOMES" in blockers or "INSUFFICIENT_OUTCOME_COVERAGE" in blockers:
        status = "INSUFFICIENT_OUTCOMES"
    elif "INSUFFICIENT_TIME_SPAN" in blockers:
        status = "INSUFFICIENT_TIME_SPAN"
    else:
        status = "INSUFFICIENT_EVIDENCE_DIVERSITY"

    result: dict[str, Any] = {
        "status": status,
        "ready": status == "READY_FOR_DESCRIPTIVE_CALIBRATION",
        "blockers": blockers,
        "metrics": {
            "visible_snapshot_count": len(visible_records),
            "distinct_evidence_hash_count": len(distinct_hashes),
            "distinct_prior_launch_count": distinct_launch_count,
            "known_outcome_count": known_outcome_count,
            "unknown_outcome_count": unknown_outcome_count,
            "known_outcome_ratio": round(known_outcome_ratio, 6),
            "observation_span_days": round(observation_span_days, 6),
        },
        "thresholds": {
            "min_distinct_prior_launches": MIN_DISTINCT_PRIOR_LAUNCHES,
            "min_known_outcomes": MIN_KNOWN_OUTCOMES,
            "min_known_outcome_ratio": MIN_KNOWN_OUTCOME_RATIO,
            "min_observation_span_days": MIN_OBSERVATION_SPAN_DAYS,
            "min_distinct_evidence_hashes": MIN_DISTINCT_EVIDENCE_HASHES,
        },
        "temporal_integrity": {
            "cutoff_enforced": cutoff is not None,
            "excluded_snapshot_count": excluded_snapshots,
            "excluded_launch_count": excluded_launches,
            "missing_or_invalid_timestamps_fail_closed": cutoff is not None,
        },
        "interpretation": "DESCRIPTIVE_READINESS_ONLY",
        "calibration_scope": "DEVELOPER_HISTORY_DESCRIPTIVE_ONLY",
        "predictive_authority": False,
        "risk_inferred": False,
        "quality_inferred": False,
        "trade_signal": False,
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
