"""Descriptive runner-vs-impostor comparison over temporal-safe memory records.

Only frozen T0 feature snapshots are compared. Later canonical outcomes are used
solely to place records into observed RUNNER and FADE cohorts; they never become
features or trading/predictive authority.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

AUTHORITY = {
    "interpretation": "RUNNER_VS_IMPOSTOR_COMPARISON_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "intent_inferred": False,
    "ownership_inferred": False,
    "collusion_inferred": False,
    "evidence_only": True,
}


def _cohort(record: dict[str, Any]) -> str | None:
    if record.get("status") != "OBSERVED":
        return None
    outcome = record.get("outcome")
    if not isinstance(outcome, dict):
        return None
    label = str(outcome.get("label") or "").strip().upper()
    if label == "RUNNER" and record.get("adversarial_case") is False:
        return "RUNNER"
    if label == "FADE" and record.get("adversarial_case") is True:
        return "IMPOSTOR"
    return None


def _frozen_features(record: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = record.get("feature_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        return None
    if record.get("future_evidence_used_in_t0_features") is not False:
        return None
    if record.get("temporal_cutoff_enforced") is not True:
        return None
    return dict(snapshot)


def _distribution(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    values = Counter(repr(record["features"].get(key)) for record in records)
    return dict(sorted(values.items(), key=lambda item: item[0]))


def compare_runner_vs_impostor(memory_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare observed RUNNER and later-FADE cases using T0 features only.

    The result is deliberately descriptive. It reports cohort feature
    distributions and observed differences but does not rank, score, predict,
    infer causality, or recommend a trade.
    """
    runners: list[dict[str, Any]] = []
    impostors: list[dict[str, Any]] = []
    excluded = 0

    for record in memory_records:
        cohort = _cohort(record)
        features = _frozen_features(record)
        if cohort is None or features is None:
            excluded += 1
            continue
        item = {"mint": record.get("mint"), "features": features}
        (runners if cohort == "RUNNER" else impostors).append(item)

    missing: list[str] = []
    if not runners:
        missing.append("observed_runner_cases")
    if not impostors:
        missing.append("observed_impostor_cases")
    if missing:
        return {
            "status": "UNKNOWN",
            "missing": missing,
            "runner_count": len(runners),
            "impostor_count": len(impostors),
            "excluded_count": excluded,
            **AUTHORITY,
        }

    feature_keys = sorted(
        set.intersection(
            *(set(item["features"].keys()) for item in runners + impostors)
        )
    )
    comparisons: list[dict[str, Any]] = []
    for key in feature_keys:
        runner_distribution = _distribution(runners, key)
        impostor_distribution = _distribution(impostors, key)
        comparisons.append(
            {
                "feature": key,
                "runner_distribution": runner_distribution,
                "impostor_distribution": impostor_distribution,
                "observed_difference": runner_distribution != impostor_distribution,
            }
        )

    return {
        "status": "OBSERVED",
        "runner_count": len(runners),
        "impostor_count": len(impostors),
        "excluded_count": excluded,
        "compared_feature_count": len(feature_keys),
        "comparisons": comparisons,
        "outcomes_used_only_for_cohort_assignment": True,
        "future_evidence_used_as_feature": False,
        "causal_claim": False,
        **AUTHORITY,
    }
