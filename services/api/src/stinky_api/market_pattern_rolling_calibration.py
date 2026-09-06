"""Rolling out-of-sample calibration and degradation tracking.

Each window freezes only observations available before its evaluation slice and
then evaluates the next chronological slice. Later observations may enter a
future window's reference history only after they have already been evaluated.
This is descriptive calibration evidence only: no prediction, probability,
confidence, quality/risk score, or trading authority is produced.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

from stinky_api.market_pattern_outcome_distribution import METRIC_KEYS, _number, _pct_change
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


def _collect(records: list[dict[str, Any]]) -> dict[str, dict[str, list[float]]]:
    values = {h: {m: [] for m in METRIC_KEYS} for h in SUPPORTED_HORIZONS}
    for record in records:
        if not isinstance(record, dict):
            continue
        baseline = record.get("baseline_metrics")
        if not isinstance(baseline, dict):
            continue
        for followup in record.get("followup_records", []):
            if not isinstance(followup, dict):
                continue
            horizon = str(followup.get("horizon") or "")
            metrics = followup.get("metrics")
            if horizon not in values or not isinstance(metrics, dict):
                continue
            for metric in METRIC_KEYS:
                before = _number(baseline.get(metric))
                after = _number(metrics.get(metric))
                if before is None or after is None:
                    continue
                change = _pct_change(before, after)
                if change is not None:
                    values[horizon][metric].append(change)
    return values


def _window(
    reference_records: list[dict[str, Any]],
    evaluation_records: list[dict[str, Any]],
    *,
    tolerance: float,
    index: int,
) -> dict[str, Any]:
    reference = _collect(reference_records)
    evaluation = _collect(evaluation_records)
    horizon_results: dict[str, Any] = {}
    errors: list[float] = []
    evaluated_horizons: list[str] = []
    outside_tolerance_horizons: list[str] = []

    for horizon in SUPPORTED_HORIZONS:
        metrics: dict[str, Any] = {}
        horizon_outside = False
        for metric in METRIC_KEYS:
            train = reference[horizon][metric]
            test = evaluation[horizon][metric]
            if not train or not test:
                continue
            reference_median = float(median(train))
            evaluation_median = float(median(test))
            error = abs(evaluation_median - reference_median)
            errors.append(error)
            if error > tolerance:
                horizon_outside = True
            metrics[metric] = {
                "reference_sample_count": len(train),
                "evaluation_sample_count": len(test),
                "reference_median_pct_change": reference_median,
                "evaluation_median_pct_change": evaluation_median,
                "absolute_median_error_pct_points": error,
                "within_tolerance": error <= tolerance,
            }
        if metrics:
            evaluated_horizons.append(horizon)
            if horizon_outside:
                outside_tolerance_horizons.append(horizon)
        horizon_results[horizon] = {
            "status": "EVALUATED" if metrics else "UNKNOWN",
            "metrics": metrics,
            "evidence_only": True,
        }

    status = (
        "OUT_OF_SAMPLE_WITHIN_TOLERANCE"
        if evaluated_horizons and not outside_tolerance_horizons
        else "OUT_OF_SAMPLE_DEVIATION_OBSERVED"
        if evaluated_horizons
        else "NOT_EVALUATION_READY"
    )
    return {
        "window_index": index,
        "evaluation_status": status,
        "reference_occurrence_count": len(reference_records),
        "evaluation_occurrence_count": len(evaluation_records),
        "reference_window": {
            "first_observed_at": _time(reference_records[0].get("pattern_observed_at")).isoformat(),
            "last_observed_at": _time(reference_records[-1].get("pattern_observed_at")).isoformat(),
        },
        "evaluation_window": {
            "first_observed_at": _time(evaluation_records[0].get("pattern_observed_at")).isoformat(),
            "last_observed_at": _time(evaluation_records[-1].get("pattern_observed_at")).isoformat(),
        },
        "evaluated_horizons": evaluated_horizons,
        "outside_tolerance_horizons": outside_tolerance_horizons,
        "mean_absolute_median_error_pct_points": mean(errors) if errors else None,
        "horizons": horizon_results,
        "evidence_only": True,
    }


def track_rolling_pattern_calibration(
    calibration: dict[str, Any],
    readiness: dict[str, Any],
    *,
    min_reference_occurrences: int = 8,
    evaluation_window_occurrences: int = 2,
    max_windows: int = 20,
    max_median_error_pct_points: float = 25.0,
    trend_change_threshold_pct_points: float = 5.0,
) -> dict[str, Any]:
    """Evaluate successive chronological windows and describe calibration trend."""
    min_reference = max(1, int(min_reference_occurrences))
    eval_size = max(1, int(evaluation_window_occurrences))
    window_limit = max(1, min(int(max_windows), 100))
    tolerance = max(0.0, float(max_median_error_pct_points))
    trend_threshold = max(0.0, float(trend_change_threshold_pct_points))
    criteria = {
        "min_reference_occurrences": min_reference,
        "evaluation_window_occurrences": eval_size,
        "max_windows": window_limit,
        "max_median_error_pct_points": tolerance,
        "trend_change_threshold_pct_points": trend_threshold,
    }
    pattern_hash = calibration.get("pattern_hash") if isinstance(calibration, dict) else None
    if (
        not isinstance(calibration, dict)
        or calibration.get("status") != "OBSERVED"
        or not isinstance(readiness, dict)
        or readiness.get("readiness_status") != "CALIBRATION_READY"
    ):
        return {
            "status": "UNKNOWN",
            "pattern_hash": pattern_hash,
            "trend_status": "INSUFFICIENT_EVIDENCE",
            "window_count": 0,
            "windows": [],
            "criteria": criteria,
            "missing": ["calibration_ready_history"],
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

    windows: list[dict[str, Any]] = []
    evaluation_start = min_reference
    while evaluation_start + eval_size <= len(records) and len(windows) < window_limit:
        reference_records = records[:evaluation_start]
        evaluation_records = records[evaluation_start : evaluation_start + eval_size]
        windows.append(
            _window(
                reference_records,
                evaluation_records,
                tolerance=tolerance,
                index=len(windows) + 1,
            )
        )
        evaluation_start += eval_size

    evaluated = [
        window
        for window in windows
        if window.get("mean_absolute_median_error_pct_points") is not None
    ]
    if len(evaluated) < 2:
        trend_status = "INSUFFICIENT_EVIDENCE"
        trend_change = None
    else:
        first_error = float(evaluated[0]["mean_absolute_median_error_pct_points"])
        last_error = float(evaluated[-1]["mean_absolute_median_error_pct_points"])
        trend_change = last_error - first_error
        if trend_change > trend_threshold:
            trend_status = "DEGRADING"
        elif trend_change < -trend_threshold:
            trend_status = "IMPROVING"
        else:
            trend_status = "STABLE"

    result: dict[str, Any] = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "trend_status": trend_status,
        "window_count": len(windows),
        "evaluated_window_count": len(evaluated),
        "mean_error_change_first_to_last_pct_points": trend_change,
        "windows": windows,
        "criteria": criteria,
        "missing": [] if len(evaluated) >= 2 else ["multiple_evaluated_windows"],
        "evidence_basis": "successive_chronological_reference_and_evaluation_windows",
        "evidence_only": True,
    }
    if calibration.get("as_of") is not None:
        result["as_of"] = calibration.get("as_of")
        result["temporal_cutoff_enforced"] = bool(calibration.get("temporal_cutoff_enforced"))
    return result
