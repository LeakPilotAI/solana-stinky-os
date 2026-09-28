"""Deterministic evidence artifact for a reviewable score paper candidate.

Builds no database state and performs no provisioning or activation. The artifact
binds a selected training-only threshold to the exact held-out evidence that
passed the separate readiness gate.
"""
from __future__ import annotations
import hashlib
import json
import math
from typing import Any

CANDIDATE_SCHEMA_VERSION = "score-paper-candidate-v1"
AUTHORITY = {
    "paper_only": True,
    "read_only": True,
    "evidence_only": True,
    "artifact_only": True,
    "policy_provisioning_authority": False,
    "automatic_activation": False,
    "live_threshold_changed": False,
    "score_weights_changed": False,
    "trading_authority": False,
    "live_execution": False,
}

def _text(value: Any) -> str | None:
    s=str(value or "").strip()
    return s or None

def _number(value: Any) -> float | None:
    if value is None or isinstance(value,bool):
        return None
    try:
        n=float(value)
    except (TypeError,ValueError):
        return None
    return n if math.isfinite(n) else None

def build_score_paper_candidate(evaluation: dict[str,Any], readiness: dict[str,Any]) -> dict[str,Any]:
    if not isinstance(evaluation,dict) or evaluation.get("evaluation_status")!="HELD_OUT_EVALUATED":
        return {"status":"UNKNOWN","missing":["held_out_evaluated_evidence"],**AUTHORITY}
    if not isinstance(readiness,dict) or readiness.get("readiness_status")!="READY_FOR_PAPER_CANDIDATE_REVIEW":
        return {"status":"UNKNOWN","missing":["ready_for_paper_candidate_review"],**AUTHORITY}
    if evaluation.get("candidate_selection")!="TRAINING_ONLY" or evaluation.get("threshold_change_authorized") is not False:
        return {"status":"UNKNOWN","missing":["training_only_non_authoritative_evaluation"],**AUTHORITY}
    versions={
        "intelligence_model_version":_text(evaluation.get("intelligence_model_version")),
        "score_model_version":_text(evaluation.get("score_model_version")),
        "outcome_label_version":_text(evaluation.get("outcome_label_version")),
    }
    threshold=_number(evaluation.get("selected_threshold"))
    training=evaluation.get("training_window")
    holdout=evaluation.get("holdout_window")
    metrics=evaluation.get("holdout_metrics")
    criteria=readiness.get("criteria")
    checks=readiness.get("checks")
    missing=[k for k,v in versions.items() if v is None]
    if threshold is None or not 0.0 <= threshold <= 100.0:
        missing.append("selected_threshold_score_domain")
    if not isinstance(training,dict): missing.append("training_window")
    if not isinstance(holdout,dict): missing.append("holdout_window")
    if not isinstance(metrics,dict): missing.append("holdout_metrics")
    if not isinstance(criteria,dict): missing.append("readiness_criteria")
    if not isinstance(checks,dict) or not checks or not all(v is True for v in checks.values()):
        missing.append("passing_readiness_checks")
    # Readiness must describe the same frozen evaluation, not a different result.
    for key in versions:
        if readiness.get(key)!=evaluation.get(key):
            missing.append(f"readiness_{key}_match")
    if readiness.get("selected_threshold")!=evaluation.get("selected_threshold"):
        missing.append("readiness_selected_threshold_match")
    if readiness.get("holdout_window")!=holdout or readiness.get("holdout_metrics")!=metrics:
        missing.append("readiness_holdout_evidence_match")
    if missing:
        return {"status":"UNKNOWN","missing":list(dict.fromkeys(missing)),**AUTHORITY}

    payload={
        "schema_version":CANDIDATE_SCHEMA_VERSION,
        "versions":versions,
        "selected_threshold":threshold,
        "selection_basis":evaluation.get("selection_basis"),
        "evaluation_as_of":evaluation.get("as_of"),
        "training_window":training,
        "holdout_window":holdout,
        "selected_training_metrics":evaluation.get("selected_training_metrics"),
        "holdout_metrics":metrics,
        "evaluation_criteria":evaluation.get("criteria"),
        "readiness_criteria":criteria,
        "readiness_checks":checks,
    }
    try:
        canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    except (TypeError, ValueError):
        return {"status":"UNKNOWN","missing":["canonical_json_safe_finite_evidence"],**AUTHORITY}
    evidence_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    candidate_version=f"{CANDIDATE_SCHEMA_VERSION}:{evidence_sha256[:16]}"
    return {
        "status":"PAPER_CANDIDATE_ARTIFACT",
        "candidate_version":candidate_version,
        "evidence_sha256":evidence_sha256,
        "payload":payload,
        "requires_separate_policy_provisioning":True,
        "requires_explicit_activation":True,
        **AUTHORITY,
    }
