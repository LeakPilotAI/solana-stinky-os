"""Assess historical pattern-distribution stability before calibration.

Readiness here is a mechanical evidence gate only. It does not produce a
prediction, probability, quality/risk score, confidence score, or trading
authority. Historical records are split chronologically to expose instability
rather than hide it in one aggregate distribution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stinky_api.market_pattern_outcome_distribution import (
    METRIC_KEYS,
    summarize_pattern_outcome_distribution,
)
from stinky_api.market_pattern_outcome_calibration import SUPPORTED_HORIZONS


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
    except ValueError:
        return None


def _slice_calibration(calibration: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    horizon_counts = {h: 0 for h in SUPPORTED_HORIZONS}
    for record in records:
        seen = {
            str(item.get("horizon"))
            for item in record.get("followup_records", [])
            if isinstance(item, dict) and str(item.get("horizon") or "") in horizon_counts
        }
        for horizon in seen:
            horizon_counts[horizon] += 1
    return {
        "status": "OBSERVED",
        "pattern_hash": calibration.get("pattern_hash"),
        "occurrence_count": total,
        "horizon_coverage": {
            h: {
                "occurrences_observed": horizon_counts[h],
                "occurrence_count": total,
                "coverage": horizon_counts[h] / total if total else None,
            }
            for h in SUPPORTED_HORIZONS
        },
        "records": records,
        "evidence_only": True,
    }


def assess_pattern_calibration_readiness(
    calibration: dict[str, Any],
    *,
    min_total_occurrences: int = 10,
    min_slice_occurrences: int = 5,
    min_horizon_coverage: float = 0.5,
    max_median_drift_pct_points: float = 25.0,
) -> dict[str, Any]:
    """Compare chronological halves and report mechanical calibration readiness."""
    required_total = max(2, int(min_total_occurrences))
    required_slice = max(1, int(min_slice_occurrences))
    required_coverage = max(0.0, min(float(min_horizon_coverage), 1.0))
    drift_limit = max(0.0, float(max_median_drift_pct_points))
    criteria = {
        "min_total_occurrences": required_total,
        "min_slice_occurrences": required_slice,
        "min_horizon_coverage": required_coverage,
        "max_median_drift_pct_points": drift_limit,
    }
    pattern_hash = calibration.get("pattern_hash") if isinstance(calibration, dict) else None
    if not isinstance(calibration, dict) or calibration.get("status") != "OBSERVED":
        return {
            "status": "UNKNOWN",
            "pattern_hash": pattern_hash,
            "readiness_status": "INSUFFICIENT_EVIDENCE",
            "stable_horizons": [],
            "unstable_horizons": [],
            "slice_sizes": {"early": 0, "late": 0},
            "horizons": {},
            "criteria": criteria,
            "missing": ["market_pattern_outcome_calibration"],
            "evidence_only": True,
        }

    dated: list[tuple[datetime, dict[str, Any]]] = []
    for record in calibration.get("records", []):
        if not isinstance(record, dict):
            continue
        observed_at = _time(record.get("pattern_observed_at"))
        if observed_at is not None:
            dated.append((observed_at, record))
    dated.sort(key=lambda pair: pair[0])
    records = [record for _, record in dated]
    total = len(records)
    if total < 2:
        return {
            "status": "OBSERVED",
            "pattern_hash": pattern_hash,
            "readiness_status": "INSUFFICIENT_EVIDENCE",
            "stable_horizons": [],
            "unstable_horizons": [],
            "slice_sizes": {"early": total, "late": 0},
            "horizons": {},
            "criteria": criteria,
            "missing": ["chronological_pattern_history"],
            "evidence_only": True,
        }

    midpoint = total // 2
    early_records = records[:midpoint]
    late_records = records[midpoint:]
    early = summarize_pattern_outcome_distribution(
        _slice_calibration(calibration, early_records),
        min_sample_count=required_slice,
        min_horizon_coverage=required_coverage,
    )
    late = summarize_pattern_outcome_distribution(
        _slice_calibration(calibration, late_records),
        min_sample_count=required_slice,
        min_horizon_coverage=required_coverage,
    )

    stable_horizons: list[str] = []
    unstable_horizons: list[str] = []
    horizon_results: dict[str, Any] = {}
    for horizon in SUPPORTED_HORIZONS:
        early_h = early.get("horizons", {}).get(horizon, {})
        late_h = late.get("horizons", {}).get(horizon, {})
        metric_drift: dict[str, Any] = {}
        comparable = 0
        drift_exceeded = False
        for metric in METRIC_KEYS:
            early_metric = early_h.get("metric_percent_changes", {}).get(metric, {})
            late_metric = late_h.get("metric_percent_changes", {}).get(metric, {})
            early_median = early_metric.get("median")
            late_median = late_metric.get("median")
            if early_median is None or late_median is None:
                continue
            drift = abs(float(late_median) - float(early_median))
            comparable += 1
            if drift > drift_limit:
                drift_exceeded = True
            metric_drift[metric] = {
                "early_median_pct_change": early_median,
                "late_median_pct_change": late_median,
                "absolute_median_drift_pct_points": drift,
                "within_drift_limit": drift <= drift_limit,
            }
        slice_sufficient = (
            early_h.get("evidence_status") == "SUFFICIENT_EVIDENCE"
            and late_h.get("evidence_status") == "SUFFICIENT_EVIDENCE"
        )
        stable = slice_sufficient and comparable > 0 and not drift_exceeded
        if stable:
            stable_horizons.append(horizon)
        elif comparable > 0 or slice_sufficient:
            unstable_horizons.append(horizon)
        horizon_results[horizon] = {
            "stability_status": "STABLE" if stable else "NOT_ESTABLISHED",
            "early_evidence_status": early_h.get("evidence_status", "INSUFFICIENT_EVIDENCE"),
            "late_evidence_status": late_h.get("evidence_status", "INSUFFICIENT_EVIDENCE"),
            "metric_median_drift": metric_drift,
            "evidence_only": True,
        }

    enough_history = total >= required_total and len(early_records) >= required_slice and len(late_records) >= required_slice
    ready = enough_history and bool(stable_horizons) and not unstable_horizons
    result: dict[str, Any] = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "readiness_status": "CALIBRATION_READY" if ready else "NOT_CALIBRATION_READY",
        "occurrence_count": total,
        "slice_sizes": {"early": len(early_records), "late": len(late_records)},
        "stable_horizons": stable_horizons,
        "unstable_horizons": unstable_horizons,
        "horizons": horizon_results,
        "criteria": criteria,
        "missing": [] if enough_history else ["sufficient_chronological_sample"],
        "evidence_basis": "chronological_market_pattern_followup_distribution",
        "evidence_only": True,
    }
    if calibration.get("as_of") is not None:
        result["as_of"] = calibration.get("as_of")
        result["temporal_cutoff_enforced"] = bool(calibration.get("temporal_cutoff_enforced"))
    return result
