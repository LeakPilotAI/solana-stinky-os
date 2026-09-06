"""Descriptive pattern outcome summaries conditioned on historical regime state.

Regime labels must already be assigned using only evidence visible at each pattern
occurrence. This module then groups factual follow-up outcome changes by those
labels. It does not predict future behavior or grant confidence, risk, quality,
or trading authority.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from stinky_api.market_pattern_outcome_calibration import SUPPORTED_HORIZONS
from stinky_api.market_pattern_outcome_distribution import METRIC_KEYS, _number, _pct_change
from stinky_api.market_pattern_regime_segmentation import REGIME_STATES


def _unknown(reason: str, pattern_hash: str | None = None) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "pattern_hash": pattern_hash,
        "regimes": {},
        "sufficient_regimes": [],
        "insufficient_regimes": [],
        "missing": [reason],
        "evidence_only": True,
    }


def summarize_conditional_pattern_performance(
    calibration: dict[str, Any],
    segmentation: dict[str, Any],
    *,
    min_occurrences_per_regime: int = 3,
) -> dict[str, Any]:
    """Summarize baseline-to-follow-up changes by historically visible regime."""
    pattern_hash = calibration.get("pattern_hash") if isinstance(calibration, dict) else None
    minimum = max(1, int(min_occurrences_per_regime))
    if not isinstance(calibration, dict) or calibration.get("status") != "OBSERVED":
        return _unknown("market_pattern_outcome_calibration", pattern_hash)
    if not isinstance(segmentation, dict) or segmentation.get("status") != "OBSERVED":
        return _unknown("market_pattern_regime_segmentation", pattern_hash)

    regime_by_occurrence: dict[int, str] = {}
    for item in segmentation.get("records", []):
        if not isinstance(item, dict):
            continue
        occurrence_id = item.get("occurrence_id")
        regime = str(item.get("regime_state") or "")
        if isinstance(occurrence_id, int) and regime in REGIME_STATES:
            regime_by_occurrence[occurrence_id] = regime

    grouped: dict[str, list[dict[str, Any]]] = {state: [] for state in REGIME_STATES}
    for record in calibration.get("records", []):
        if not isinstance(record, dict):
            continue
        occurrence_id = record.get("occurrence_id")
        if not isinstance(occurrence_id, int):
            continue
        regime = regime_by_occurrence.get(occurrence_id)
        if regime is not None:
            grouped[regime].append(record)

    regimes: dict[str, Any] = {}
    sufficient: list[str] = []
    insufficient: list[str] = []
    for regime in REGIME_STATES:
        records = grouped[regime]
        occurrence_count = len(records)
        horizon_results: dict[str, Any] = {}
        for horizon in SUPPORTED_HORIZONS:
            metric_values: dict[str, list[float]] = {metric: [] for metric in METRIC_KEYS}
            observed_occurrences = 0
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
                    for metric in METRIC_KEYS:
                        before = _number(baseline.get(metric))
                        after = _number(metrics.get(metric))
                        if before is None or after is None:
                            continue
                        change = _pct_change(before, after)
                        if change is not None:
                            metric_values[metric].append(change)
                            matched = True
                if matched:
                    observed_occurrences += 1
            metric_summary = {
                metric: {
                    "sample_count": len(values),
                    "median_pct_change": float(median(values)) if values else None,
                }
                for metric, values in metric_values.items()
            }
            horizon_results[horizon] = {
                "occurrences_observed": observed_occurrences,
                "occurrence_count": occurrence_count,
                "coverage": (observed_occurrences / occurrence_count) if occurrence_count else None,
                "metrics": metric_summary,
                "evidence_only": True,
            }

        evidence_status = "SUFFICIENT_EVIDENCE" if occurrence_count >= minimum else "INSUFFICIENT_EVIDENCE"
        if evidence_status == "SUFFICIENT_EVIDENCE":
            sufficient.append(regime)
        else:
            insufficient.append(regime)
        regimes[regime] = {
            "evidence_status": evidence_status,
            "occurrence_count": occurrence_count,
            "horizons": horizon_results,
            "evidence_only": True,
        }

    result = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "regimes": regimes,
        "sufficient_regimes": sufficient,
        "insufficient_regimes": insufficient,
        "criteria": {"min_occurrences_per_regime": minimum},
        "missing": [] if sufficient else ["sufficient_regime_conditioned_occurrences"],
        "regime_assignment_source": segmentation.get("temporal_assignment_rule"),
        "future_regime_leakage_permitted": False,
        "evidence_basis": "historical_pattern_followups_grouped_by_occurrence_time_regime",
        "evidence_only": True,
    }
    if calibration.get("as_of") is not None:
        result["as_of"] = calibration.get("as_of")
        result["temporal_cutoff_enforced"] = bool(calibration.get("temporal_cutoff_enforced"))
    return result
