"""Out-of-sample calibration foundation for historical market patterns.

This module freezes an earlier chronological reference window and evaluates only
later occurrences against that reference. It measures factual distribution
stability out of sample; it does not produce a trading signal, probability,
confidence score, quality score, or risk score.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
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
        baseline = record.get("baseline_metrics") if isinstance(record, dict) else None
        if not isinstance(baseline, dict):
            continue
        for followup in record.get("followup_records", []):
            if not isinstance(followup, dict):
                continue
            horizon = str(followup.get("horizon") or "")
            if horizon not in values:
                continue
            metrics = followup.get("metrics")
            if not isinstance(metrics, dict):
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


def evaluate_pattern_calibration_out_of_sample(
    calibration: dict[str, Any],
    readiness: dict[str, Any],
    *,
    evaluation_fraction: float = 0.25,
    min_reference_occurrences: int = 8,
    min_evaluation_occurrences: int = 2,
    max_median_error_pct_points: float = 25.0,
) -> dict[str, Any]:
    """Freeze earlier history and evaluate later unseen occurrences descriptively."""
    fraction = min(max(float(evaluation_fraction), 0.1), 0.5)
    min_reference = max(1, int(min_reference_occurrences))
    min_evaluation = max(1, int(min_evaluation_occurrences))
    tolerance = max(0.0, float(max_median_error_pct_points))
    criteria = {
        "evaluation_fraction": fraction,
        "min_reference_occurrences": min_reference,
        "min_evaluation_occurrences": min_evaluation,
        "max_median_error_pct_points": tolerance,
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
            "evaluation_status": "NOT_EVALUATION_READY",
            "reference_occurrence_count": 0,
            "evaluation_occurrence_count": 0,
            "horizons": {},
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
    total = len(records)
    evaluation_count = max(min_evaluation, int(round(total * fraction))) if total else 0
    reference_count = total - evaluation_count
    if reference_count < min_reference or evaluation_count < min_evaluation:
        result = {
            "status": "OBSERVED",
            "pattern_hash": pattern_hash,
            "evaluation_status": "NOT_EVALUATION_READY",
            "reference_occurrence_count": max(reference_count, 0),
            "evaluation_occurrence_count": max(evaluation_count, 0),
            "horizons": {},
            "criteria": criteria,
            "missing": ["sufficient_out_of_sample_split"],
            "evidence_basis": "chronological_reference_and_later_evaluation_windows",
            "evidence_only": True,
        }
        if calibration.get("as_of") is not None:
            result["as_of"] = calibration.get("as_of")
            result["temporal_cutoff_enforced"] = bool(calibration.get("temporal_cutoff_enforced"))
        return result

    reference_records = records[:reference_count]
    evaluation_records = records[reference_count:]
    reference_values = _collect(reference_records)
    evaluation_values = _collect(evaluation_records)

    horizon_results: dict[str, Any] = {}
    evaluated_horizons: list[str] = []
    within_tolerance_horizons: list[str] = []
    outside_tolerance_horizons: list[str] = []
    for horizon in SUPPORTED_HORIZONS:
        metric_results: dict[str, Any] = {}
        comparable = 0
        horizon_within = True
        for metric in METRIC_KEYS:
            train = reference_values[horizon][metric]
            test = evaluation_values[horizon][metric]
            if not train or not test:
                continue
            reference_median = float(median(train))
            evaluation_median = float(median(test))
            error = abs(evaluation_median - reference_median)
            comparable += 1
            if error > tolerance:
                horizon_within = False
            metric_results[metric] = {
                "reference_sample_count": len(train),
                "evaluation_sample_count": len(test),
                "reference_median_pct_change": reference_median,
                "evaluation_median_pct_change": evaluation_median,
                "absolute_median_error_pct_points": error,
                "within_tolerance": error <= tolerance,
            }
        if comparable:
            evaluated_horizons.append(horizon)
            if horizon_within:
                within_tolerance_horizons.append(horizon)
            else:
                outside_tolerance_horizons.append(horizon)
        horizon_results[horizon] = {
            "status": "EVALUATED" if comparable else "UNKNOWN",
            "metrics": metric_results,
            "evidence_only": True,
        }

    evaluation_status = (
        "OUT_OF_SAMPLE_WITHIN_TOLERANCE"
        if evaluated_horizons and not outside_tolerance_horizons
        else "OUT_OF_SAMPLE_DEVIATION_OBSERVED"
        if evaluated_horizons
        else "NOT_EVALUATION_READY"
    )
    result: dict[str, Any] = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "evaluation_status": evaluation_status,
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
        "within_tolerance_horizons": within_tolerance_horizons,
        "outside_tolerance_horizons": outside_tolerance_horizons,
        "horizons": horizon_results,
        "criteria": criteria,
        "missing": [] if evaluated_horizons else ["comparable_reference_and_evaluation_metrics"],
        "evidence_basis": "chronological_reference_and_later_evaluation_windows",
        "evidence_only": True,
    }
    if calibration.get("as_of") is not None:
        result["as_of"] = calibration.get("as_of")
        result["temporal_cutoff_enforced"] = bool(calibration.get("temporal_cutoff_enforced"))
    return result
