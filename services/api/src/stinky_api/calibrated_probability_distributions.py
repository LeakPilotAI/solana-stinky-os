"""Calibrated empirical probability distributions over temporal-safe evidence.

This module is a thin bridge over existing cutoff-safe calibration, descriptive
outcome distributions, out-of-sample evaluation, and counterfactual journal
records. It emits probabilities only when evidence is sufficient and the
chronological out-of-sample evaluation is within tolerance. Otherwise it fails
closed to UNKNOWN.

Probabilities here are empirical historical frequencies, not live trading
signals, recommendations, confidence scores, causal claims, or guarantees.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from stinky_api.market_pattern_outcome_calibration import SUPPORTED_HORIZONS
from stinky_api.market_pattern_outcome_distribution import _number, _pct_change

AUTHORITY = {
    "interpretation": "CALIBRATED_EMPIRICAL_PROBABILITY_DISTRIBUTION",
    "predictive_authority": False,
    "trading_authority": False,
    "trade_signal": False,
    "live_execution": False,
    "causal_claim": False,
    "guarantee": False,
    "paper_only": True,
    "evidence_only": True,
}

_ALLOWED_OUTCOMES = ("RUNNER", "HELD", "FADE")
_MARKET_CAP_BANDS = (
    ("DOWN_GT_50", lambda x: x < -50.0),
    ("DOWN_0_TO_50", lambda x: -50.0 <= x < 0.0),
    ("UP_0_TO_100", lambda x: 0.0 <= x < 100.0),
    ("UP_GTE_100", lambda x: x >= 100.0),
)


def _probabilities(counts: Counter[str], labels: tuple[str, ...]) -> dict[str, float]:
    total = sum(counts.get(label, 0) for label in labels)
    if total <= 0:
        return {}
    return {label: counts.get(label, 0) / total for label in labels}


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _journal_outcomes(entries: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("status") != "OBSERVED":
            continue
        if entry.get("outcome_attached_after_decision") is not True:
            continue
        decision = entry.get("decision")
        if not isinstance(decision, dict):
            continue
        if decision.get("temporal_cutoff_enforced") is not True:
            continue
        if decision.get("future_evidence_used") is not False:
            continue
        if entry.get("t0_decision_rewritten_by_outcome") is not False:
            continue
        outcome = entry.get("outcome")
        if not isinstance(outcome, dict):
            continue
        label = str(outcome.get("label") or "").strip().upper()
        if label in _ALLOWED_OUTCOMES:
            counts[label] += 1
    return counts


def _market_cap_changes(calibration: dict[str, Any]) -> dict[str, list[float]]:
    values = {horizon: [] for horizon in SUPPORTED_HORIZONS}
    for record in calibration.get("records", []):
        if not isinstance(record, dict):
            continue
        baseline = record.get("baseline_metrics")
        if not isinstance(baseline, dict):
            continue
        before = _number(baseline.get("market_cap_usd"))
        if before is None:
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
            after = _number(metrics.get("market_cap_usd"))
            if after is None:
                continue
            change = _pct_change(before, after)
            if change is not None:
                values[horizon].append(change)
    return values


def build_calibrated_probability_distributions(
    calibration: dict[str, Any],
    distribution: dict[str, Any],
    evaluation: dict[str, Any],
    journal_entries: list[dict[str, Any]],
    *,
    min_closed_outcomes: int = 5,
) -> dict[str, Any]:
    """Emit empirical probabilities only after cutoff-safe calibration succeeds."""
    required_outcomes = max(1, int(min_closed_outcomes))
    missing: list[str] = []

    if not isinstance(calibration, dict) or calibration.get("status") != "OBSERVED":
        missing.append("observed_market_pattern_calibration")
    if not isinstance(distribution, dict) or distribution.get("status") != "OBSERVED":
        missing.append("observed_market_pattern_distribution")
    if not isinstance(evaluation, dict) or evaluation.get("status") != "OBSERVED":
        missing.append("observed_out_of_sample_evaluation")
    elif evaluation.get("evaluation_status") != "OUT_OF_SAMPLE_WITHIN_TOLERANCE":
        missing.append("out_of_sample_calibration_within_tolerance")

    if isinstance(calibration, dict) and calibration.get("as_of") is not None:
        if calibration.get("temporal_cutoff_enforced") is not True:
            missing.append("calibration_temporal_cutoff")
    if isinstance(distribution, dict) and distribution.get("as_of") is not None:
        if distribution.get("temporal_cutoff_enforced") is not True:
            missing.append("distribution_temporal_cutoff")
    if isinstance(evaluation, dict) and evaluation.get("as_of") is not None:
        if evaluation.get("temporal_cutoff_enforced") is not True:
            missing.append("evaluation_temporal_cutoff")

    sufficient_horizons = set(distribution.get("sufficient_horizons") or []) if isinstance(distribution, dict) else set()
    evaluated_horizons = set(evaluation.get("within_tolerance_horizons") or []) if isinstance(evaluation, dict) else set()
    calibrated_horizons = [h for h in SUPPORTED_HORIZONS if h in sufficient_horizons and h in evaluated_horizons]
    if not calibrated_horizons:
        missing.append("calibrated_market_cap_horizon")

    outcome_counts = _journal_outcomes(journal_entries if isinstance(journal_entries, list) else [])
    closed_outcome_count = sum(outcome_counts.values())
    if closed_outcome_count < required_outcomes:
        missing.append("sufficient_closed_counterfactual_outcomes")

    if missing:
        return _unknown(
            missing,
            pattern_hash=calibration.get("pattern_hash") if isinstance(calibration, dict) else None,
            calibrated_horizons=calibrated_horizons,
            closed_outcome_count=closed_outcome_count,
            criteria={"min_closed_outcomes": required_outcomes},
        )

    changes = _market_cap_changes(calibration)
    market_cap: dict[str, Any] = {}
    for horizon in calibrated_horizons:
        samples = changes.get(horizon, [])
        if not samples:
            market_cap[horizon] = {
                "status": "UNKNOWN",
                "sample_count": 0,
                "missing": ["market_cap_followup_samples"],
                "evidence_only": True,
            }
            continue
        band_counts: Counter[str] = Counter()
        for value in samples:
            for label, predicate in _MARKET_CAP_BANDS:
                if predicate(value):
                    band_counts[label] += 1
                    break
        labels = tuple(label for label, _ in _MARKET_CAP_BANDS)
        market_cap[horizon] = {
            "status": "CALIBRATED_EMPIRICAL",
            "sample_count": len(samples),
            "probabilities": _probabilities(band_counts, labels),
            "bands_pct_change": {
                "DOWN_GT_50": "< -50%",
                "DOWN_0_TO_50": "-50% to <0%",
                "UP_0_TO_100": "0% to <100%",
                "UP_GTE_100": ">=100%",
            },
            "probabilities_sum_to_one": abs(sum(_probabilities(band_counts, labels).values()) - 1.0) < 1e-12,
            "evidence_only": True,
        }

    return {
        "status": "CALIBRATED_EMPIRICAL",
        "pattern_hash": calibration.get("pattern_hash"),
        "outcome_distribution": {
            "sample_count": closed_outcome_count,
            "counts": {label: outcome_counts.get(label, 0) for label in _ALLOWED_OUTCOMES},
            "probabilities": _probabilities(outcome_counts, _ALLOWED_OUTCOMES),
            "probabilities_sum_to_one": abs(sum(_probabilities(outcome_counts, _ALLOWED_OUTCOMES).values()) - 1.0) < 1e-12,
            "source": "temporal_safe_counterfactual_journal",
        },
        "market_cap_change_distributions": market_cap,
        "calibrated_horizons": calibrated_horizons,
        "calibration_basis": "chronological_out_of_sample_within_tolerance+mechanically_sufficient_horizon_evidence",
        "future_evidence_used_in_t0_decisions": False,
        "criteria": {"min_closed_outcomes": required_outcomes},
        "missing": [],
        **AUTHORITY,
    }
