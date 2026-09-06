"""Chronological stability and unseen-window checks for regime-conditioned pattern evidence.

This module evaluates whether descriptive regime-conditioned outcome distributions
remain similar across time. It never converts historical stability into prediction,
probability, confidence, quality/risk scoring, causality, or trading authority.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from stinky_api.market_pattern_outcome_distribution import METRIC_KEYS, _number, _pct_change
from stinky_api.market_pattern_regime_segmentation import REGIME_STATES


def _unknown(reason: str, pattern_hash: str | None = None) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "pattern_hash": pattern_hash,
        "regimes": {},
        "stable_regimes": [],
        "unstable_regimes": [],
        "insufficient_regimes": [],
        "missing": [reason],
        "evidence_only": True,
    }


def _summary(records: list[dict[str, Any]], horizon: str, metric: str) -> dict[str, Any]:
    values: list[float] = []
    observed = 0
    for record in records:
        baseline = record.get("baseline_metrics")
        if not isinstance(baseline, dict):
            continue
        matched = False
        for followup in record.get("followup_records", []):
            if not isinstance(followup, dict) or str(followup.get("horizon") or "") != horizon:
                continue
            metrics = followup.get("metrics")
            if not isinstance(metrics, dict):
                continue
            before = _number(baseline.get(metric))
            after = _number(metrics.get(metric))
            if before is None or after is None:
                continue
            change = _pct_change(before, after)
            if change is not None:
                values.append(change)
                matched = True
        if matched:
            observed += 1
    return {
        "sample_count": len(values),
        "occurrences_observed": observed,
        "median_pct_change": float(median(values)) if values else None,
    }


def assess_regime_conditioned_stability(
    calibration: dict[str, Any],
    segmentation: dict[str, Any],
    *,
    horizon: str = "1h",
    metric: str = "price_usd",
    min_reference_occurrences: int = 4,
    min_evaluation_occurrences: int = 2,
    max_median_drift_pct_points: float = 25.0,
) -> dict[str, Any]:
    """Freeze earlier regime evidence, then compare against a later unseen slice."""
    pattern_hash = calibration.get("pattern_hash") if isinstance(calibration, dict) else None
    min_ref = max(1, int(min_reference_occurrences))
    min_eval = max(1, int(min_evaluation_occurrences))
    max_drift = max(0.0, float(max_median_drift_pct_points))
    if not isinstance(calibration, dict) or calibration.get("status") != "OBSERVED":
        return _unknown("market_pattern_outcome_calibration", pattern_hash)
    if not isinstance(segmentation, dict) or segmentation.get("status") != "OBSERVED":
        return _unknown("market_pattern_regime_segmentation", pattern_hash)
    if metric not in METRIC_KEYS:
        return _unknown("unsupported_metric", pattern_hash)

    regime_meta: dict[int, dict[str, Any]] = {}
    for item in segmentation.get("records", []):
        if not isinstance(item, dict):
            continue
        oid = item.get("occurrence_id")
        state = str(item.get("regime_state") or "")
        if isinstance(oid, int) and state in REGIME_STATES:
            regime_meta[oid] = item

    grouped: dict[str, list[dict[str, Any]]] = {state: [] for state in REGIME_STATES}
    for record in calibration.get("records", []):
        if not isinstance(record, dict):
            continue
        oid = record.get("occurrence_id")
        if not isinstance(oid, int) or oid not in regime_meta:
            continue
        observed_at = str(record.get("pattern_observed_at") or regime_meta[oid].get("pattern_observed_at") or "")
        enriched = dict(record)
        enriched["_sort_time"] = observed_at
        grouped[str(regime_meta[oid]["regime_state"])].append(enriched)

    regimes: dict[str, Any] = {}
    stable: list[str] = []
    unstable: list[str] = []
    insufficient: list[str] = []
    for regime in REGIME_STATES:
        records = sorted(grouped[regime], key=lambda r: (r.get("_sort_time", ""), int(r.get("occurrence_id", 0))))
        n = len(records)
        evaluation = records[-min_eval:] if n >= min_eval else []
        reference = records[:-min_eval] if n >= min_eval else records
        ref = _summary(reference, horizon, metric)
        eva = _summary(evaluation, horizon, metric)
        ref_median = ref["median_pct_change"]
        eval_median = eva["median_pct_change"]
        drift = abs(eval_median - ref_median) if ref_median is not None and eval_median is not None else None

        enough = ref["occurrences_observed"] >= min_ref and eva["occurrences_observed"] >= min_eval
        if not enough:
            stability = "INSUFFICIENT_EVIDENCE"
            insufficient.append(regime)
        elif drift is not None and drift <= max_drift:
            stability = "STABLE"
            stable.append(regime)
        else:
            stability = "UNSTABLE"
            unstable.append(regime)

        regimes[regime] = {
            "stability_status": stability,
            "occurrence_count": n,
            "reference": ref,
            "evaluation": eva,
            "median_drift_pct_points": drift,
            "reference_occurrence_ids": [r.get("occurrence_id") for r in reference],
            "evaluation_occurrence_ids": [r.get("occurrence_id") for r in evaluation],
            "chronological_split": True,
            "evaluation_window_unseen_by_reference": True,
            "evidence_only": True,
        }

    result: dict[str, Any] = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "horizon": horizon,
        "metric": metric,
        "regimes": regimes,
        "stable_regimes": stable,
        "unstable_regimes": unstable,
        "insufficient_regimes": insufficient,
        "criteria": {
            "min_reference_occurrences": min_ref,
            "min_evaluation_occurrences": min_eval,
            "max_median_drift_pct_points": max_drift,
        },
        "missing": [] if stable or unstable else ["sufficient_regime_conditioned_chronological_evidence"],
        "split_policy": "chronological_reference_then_unseen_later_evaluation",
        "future_evaluation_leakage_permitted": False,
        "regime_assignment_leakage_permitted": False,
        "evidence_basis": "regime_conditioned_historical_followups_chronologically_split",
        "evidence_only": True,
    }
    if calibration.get("as_of") is not None:
        result["as_of"] = calibration.get("as_of")
        result["temporal_cutoff_enforced"] = bool(calibration.get("temporal_cutoff_enforced"))
    return result
