"""Evidence-only readiness gate over a held-out score-threshold evaluation.

This module does not select a threshold, provision a policy, activate a policy,
or change live behavior. It only states whether caller-supplied evidence criteria
are satisfied by an already chronological held-out evaluation.
"""
from __future__ import annotations
import math
from typing import Any

AUTHORITY = {
    "interpretation": "HELD_OUT_SCORE_EVIDENCE_READINESS",
    "paper_only": True,
    "read_only": True,
    "evidence_only": True,
    "policy_provisioning_authority": False,
    "automatic_activation": False,
    "live_threshold_changed": False,
    "score_weights_changed": False,
    "trading_authority": False,
    "live_execution": False,
}

def _prob(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n=float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and 0.0 <= n <= 1.0 else None

def assess_held_out_score_readiness(
    evaluation: dict[str, Any], *,
    min_holdout_sample: int,
    min_holdout_runners: int,
    min_holdout_negatives: int,
    max_unknown_score_rate: float,
    min_runner_precision: float,
    max_false_discovery_rate: float,
    max_false_positive_rate: float,
    min_runner_recall: float,
    max_missed_runners: int,
) -> dict[str, Any]:
    criteria = {
        "min_holdout_sample": int(min_holdout_sample),
        "min_holdout_runners": int(min_holdout_runners),
        "min_holdout_negatives": int(min_holdout_negatives),
        "max_unknown_score_rate": max_unknown_score_rate,
        "min_runner_precision": min_runner_precision,
        "max_false_discovery_rate": max_false_discovery_rate,
        "max_false_positive_rate": max_false_positive_rate,
        "min_runner_recall": min_runner_recall,
        "max_missed_runners": int(max_missed_runners),
    }
    probs = [max_unknown_score_rate,min_runner_precision,max_false_discovery_rate,max_false_positive_rate,min_runner_recall]
    if (
        any(x < 1 for x in (criteria["min_holdout_sample"], criteria["min_holdout_runners"], criteria["min_holdout_negatives"]))
        or criteria["max_missed_runners"] < 0
        or any(_prob(x) is None for x in probs)
    ):
        return {"status":"UNKNOWN","readiness_status":"NOT_READY","missing":["valid_explicit_readiness_criteria"],"criteria":criteria,**AUTHORITY}
    if not isinstance(evaluation,dict) or evaluation.get("evaluation_status")!="HELD_OUT_EVALUATED":
        return {"status":"UNKNOWN","readiness_status":"NOT_READY","missing":["held_out_evaluated_evidence"],"criteria":criteria,**AUTHORITY}
    if evaluation.get("candidate_selection")!="TRAINING_ONLY" or evaluation.get("threshold_change_authorized") is not False:
        return {"status":"UNKNOWN","readiness_status":"NOT_READY","missing":["training_only_non_authoritative_evaluation"],"criteria":criteria,**AUTHORITY}
    metrics=evaluation.get("holdout_metrics")
    window=evaluation.get("holdout_window")
    if not isinstance(metrics,dict) or not isinstance(window,dict):
        return {"status":"UNKNOWN","readiness_status":"NOT_READY","missing":["holdout_metrics"],"criteria":criteria,**AUTHORITY}

    checks = {
        "sufficient_holdout_sample": int(window.get("sample_count") or 0) >= criteria["min_holdout_sample"],
        "sufficient_holdout_runners": int(window.get("runner_count") or 0) >= criteria["min_holdout_runners"],
        "sufficient_holdout_negatives": int(window.get("negative_count") or 0) >= criteria["min_holdout_negatives"],
        "acceptable_unknown_score_rate": _prob(metrics.get("unknown_score_rate")) is not None and float(metrics["unknown_score_rate"]) <= max_unknown_score_rate,
        "minimum_runner_precision": _prob(metrics.get("runner_precision")) is not None and float(metrics["runner_precision"]) >= min_runner_precision,
        "maximum_false_discovery_rate": _prob(metrics.get("false_discovery_rate")) is not None and float(metrics["false_discovery_rate"]) <= max_false_discovery_rate,
        "maximum_false_positive_rate": _prob(metrics.get("false_positive_rate")) is not None and float(metrics["false_positive_rate"]) <= max_false_positive_rate,
        "minimum_runner_recall": _prob(metrics.get("runner_recall")) is not None and float(metrics["runner_recall"]) >= min_runner_recall,
        "maximum_missed_runners": int(metrics.get("missed_runner_count") or 0) <= criteria["max_missed_runners"],
    }
    failed=[name for name,passed in checks.items() if not passed]
    ready=not failed
    return {
        "status":"OBSERVED",
        "readiness_status":"READY_FOR_PAPER_CANDIDATE_REVIEW" if ready else "NOT_READY",
        "selected_threshold":evaluation.get("selected_threshold"),
        "intelligence_model_version":evaluation.get("intelligence_model_version"),
        "score_model_version":evaluation.get("score_model_version"),
        "outcome_label_version":evaluation.get("outcome_label_version"),
        "holdout_window":window,
        "holdout_metrics":metrics,
        "checks":checks,
        "criteria":criteria,
        "missing":failed,
        "requires_separate_versioned_paper_policy_provisioning": True,
        **AUTHORITY,
    }
