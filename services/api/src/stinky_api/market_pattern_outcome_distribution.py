"""Summarize factual outcome distributions for historical market pattern follow-up.

This module is descriptive only. Evidence sufficiency is a mechanical sample/
coverage check for whether a distribution is worth analyzing further; it is not
a prediction, confidence score, quality score, risk score, or trading signal.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any

from stinky_api.market_pattern_outcome_calibration import SUPPORTED_HORIZONS


METRIC_KEYS = (
    "price_usd",
    "liquidity_usd",
    "volume_5m_usd",
    "volume_usd",
    "fdv_usd",
    "market_cap_usd",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return ordered[lower]
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: list[float]) -> dict[str, Any]:
    q1 = _percentile(values, 0.25)
    q3 = _percentile(values, 0.75)
    return {
        "sample_count": len(values),
        "median": median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "q1": q1,
        "q3": q3,
        "iqr": (q3 - q1) if q1 is not None and q3 is not None else None,
    }


def _pct_change(baseline: float, later: float) -> float | None:
    if baseline == 0:
        return None
    return ((later - baseline) / abs(baseline)) * 100.0


def summarize_pattern_outcome_distribution(
    calibration: dict[str, Any],
    *,
    min_sample_count: int = 5,
    min_horizon_coverage: float = 0.5,
) -> dict[str, Any]:
    """Return per-horizon distributions and mechanical evidence sufficiency."""
    required_samples = max(1, int(min_sample_count))
    required_coverage = max(0.0, min(float(min_horizon_coverage), 1.0))
    pattern_hash = calibration.get("pattern_hash") if isinstance(calibration, dict) else None
    if not isinstance(calibration, dict) or calibration.get("status") != "OBSERVED":
        return {
            "status": "UNKNOWN",
            "pattern_hash": pattern_hash,
            "horizons": {},
            "sufficient_horizons": [],
            "insufficient_horizons": list(SUPPORTED_HORIZONS),
            "criteria": {"min_sample_count": required_samples, "min_horizon_coverage": required_coverage},
            "missing": ["market_pattern_outcome_calibration"],
            "evidence_only": True,
        }

    total_occurrences = int(calibration.get("occurrence_count") or 0)
    horizon_coverage = calibration.get("horizon_coverage") if isinstance(calibration.get("horizon_coverage"), dict) else {}
    metric_changes: dict[str, dict[str, list[float]]] = {
        horizon: {metric: [] for metric in METRIC_KEYS} for horizon in SUPPORTED_HORIZONS
    }

    for occurrence in calibration.get("records", []):
        if not isinstance(occurrence, dict):
            continue
        baseline = occurrence.get("baseline_metrics")
        if not isinstance(baseline, dict):
            baseline = {}
        for followup in occurrence.get("followup_records", []):
            if not isinstance(followup, dict):
                continue
            horizon = str(followup.get("horizon") or "")
            if horizon not in metric_changes:
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
                    metric_changes[horizon][metric].append(change)

    horizons: dict[str, Any] = {}
    sufficient_horizons: list[str] = []
    insufficient_horizons: list[str] = []
    for horizon in SUPPORTED_HORIZONS:
        coverage_block = horizon_coverage.get(horizon) if isinstance(horizon_coverage.get(horizon), dict) else {}
        coverage = _number(coverage_block.get("coverage"))
        distributions = {
            metric: _distribution(values)
            for metric, values in metric_changes[horizon].items()
            if values
        }
        max_samples = max((d["sample_count"] for d in distributions.values()), default=0)
        sufficient = (
            coverage is not None
            and coverage >= required_coverage
            and max_samples >= required_samples
        )
        evidence_status = "SUFFICIENT_EVIDENCE" if sufficient else "INSUFFICIENT_EVIDENCE"
        if sufficient:
            sufficient_horizons.append(horizon)
        else:
            insufficient_horizons.append(horizon)
        horizons[horizon] = {
            "evidence_status": evidence_status,
            "coverage": coverage,
            "occurrence_count": total_occurrences,
            "max_metric_sample_count": max_samples,
            "metric_percent_changes": distributions,
            "missing": [] if distributions else ["baseline_or_followup_metric_evidence"],
            "evidence_only": True,
        }

    result: dict[str, Any] = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "occurrence_count": total_occurrences,
        "horizons": horizons,
        "sufficient_horizons": sufficient_horizons,
        "insufficient_horizons": insufficient_horizons,
        "criteria": {"min_sample_count": required_samples, "min_horizon_coverage": required_coverage},
        "evidence_basis": "market_pattern_followup_calibration+baseline_market_outcome_observations",
        "evidence_only": True,
    }
    if calibration.get("as_of") is not None:
        result["as_of"] = calibration.get("as_of")
        result["temporal_cutoff_enforced"] = bool(calibration.get("temporal_cutoff_enforced"))
    return result
