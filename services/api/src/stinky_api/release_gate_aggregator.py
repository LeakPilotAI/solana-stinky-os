"""Fail-closed release-gate aggregation for Project Genesis.

This module combines already-evaluated evidence surfaces. It does not replace
corpus, calibration, paper validation, infrastructure, or safety checks. A pass
means only that the evidence is eligible for isolated-canary review; it never
unlocks live trading automatically.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

AUTHORITY = {
    "interpretation": "RELEASE_GATE_EVIDENCE_AGGREGATION_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "automatic_canary_activation": False,
    "release_evidence_only": True,
}


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "release_gate_result": "UNKNOWN",
        "eligible_for_isolated_canary_review": False,
        "live_canary_unlocked": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _claims_authority(value: dict[str, Any]) -> bool:
    return any(
        value.get(key) is True
        for key in (
            "live_execution",
            "trading_authority",
            "trade_signal",
            "recommendation_authority",
        )
    )


def evaluate_release_gate(
    corpus: dict[str, Any],
    calibration: dict[str, Any],
    walk_forward: dict[str, Any],
    infrastructure: dict[str, Any],
    safety: dict[str, Any],
    *,
    policy_version: str,
) -> dict[str, Any]:
    """Aggregate prerequisite evidence before isolated-canary review.

    No quantitative thresholds are invented here. Threshold-bearing decisions
    must already have been made by their source evidence layers. Missing or
    unsafe evidence fails closed to UNKNOWN. Fully observed but failing evidence
    produces BLOCKED rather than being hidden as UNKNOWN.
    """
    version = str(policy_version or "").strip()
    if not version:
        return _unknown(["release_policy_version"])

    inputs = {
        "corpus": corpus,
        "calibration": calibration,
        "walk_forward": walk_forward,
        "infrastructure": infrastructure,
        "safety": safety,
    }
    malformed = [name for name, value in inputs.items() if not isinstance(value, dict)]
    if malformed:
        return _unknown([f"{name}_evidence" for name in malformed], policy_version=version)

    authority_contamination = [
        name for name, value in inputs.items() if _claims_authority(value)
    ]
    if authority_contamination:
        return _unknown(
            ["non_authoritative_release_evidence"],
            authority_contamination=authority_contamination,
            policy_version=version,
        )

    missing: list[str] = []
    if corpus.get("status") != "OBSERVED":
        missing.append("observed_representative_corpus")
    if corpus.get("representative") is not True:
        missing.append("representative_corpus")
    sample_count = corpus.get("sample_count")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count <= 0:
        missing.append("positive_corpus_sample_count")
    if corpus.get("as_of") is not None and corpus.get("temporal_cutoff_enforced") is not True:
        missing.append("corpus_temporal_cutoff")

    if calibration.get("status") != "CALIBRATED_EMPIRICAL":
        missing.append("calibrated_empirical_probability_evidence")
    if not calibration.get("calibrated_horizons"):
        missing.append("calibrated_horizons")
    if calibration.get("future_evidence_used_in_t0_decisions") is not False:
        missing.append("calibration_future_evidence_excluded")

    if walk_forward.get("status") != "OBSERVED":
        missing.append("observed_walk_forward_validation")
    if walk_forward.get("live_canary_unlocked") is not False:
        missing.append("walk_forward_does_not_unlock_live_canary")

    if infrastructure.get("status") not in {"HEALTHY", "OBSERVED"}:
        missing.append("observed_infrastructure_health")
    if infrastructure.get("critical_services_healthy") is not True:
        missing.append("critical_services_healthy")
    unresolved_incidents = infrastructure.get("unresolved_critical_incidents")
    if unresolved_incidents != 0:
        missing.append("zero_unresolved_critical_incidents")

    if safety.get("status") != "OBSERVED":
        missing.append("observed_safety_evidence")
    if safety.get("safety_checks_complete") is not True:
        missing.append("completed_safety_checks")
    unresolved_safety = safety.get("unresolved_safety_failures")
    if not isinstance(unresolved_safety, list):
        missing.append("unresolved_safety_failures_list")

    if missing:
        return _unknown(missing, policy_version=version)

    blockers: list[str] = []
    if walk_forward.get("release_gate_passed") is not True or walk_forward.get("release_gate_result") != "PASS":
        blockers.append("walk_forward_expectancy_after_costs")
    if unresolved_safety:
        blockers.append("unresolved_safety_failures")

    checks = {
        "representative_corpus": True,
        "calibrated_empirical_probabilities": True,
        "walk_forward_expectancy_after_costs": "walk_forward_expectancy_after_costs" not in blockers,
        "critical_infrastructure_healthy": True,
        "no_unresolved_critical_incidents": True,
        "no_unresolved_safety_failures": "unresolved_safety_failures" not in blockers,
    }
    passed = all(checks.values())

    return {
        "status": "OBSERVED",
        "release_gate_result": "PASS" if passed else "BLOCKED",
        "eligible_for_isolated_canary_review": passed,
        "live_canary_unlocked": False,
        "automatic_canary_activation": False,
        "checks": checks,
        "blockers": blockers,
        "policy_version": version,
        "evidence": deepcopy(inputs),
        "next_step": (
            "HUMAN_RELEASE_REVIEW_FOR_ISOLATED_CANARY"
            if passed
            else "REMAIN_PAPER_ONLY"
        ),
        **AUTHORITY,
    }
