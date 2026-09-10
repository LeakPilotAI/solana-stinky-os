"""Final pre-live operational readiness aggregation for Project Genesis.

This module combines already-produced release, authorization, infrastructure,
safety, and verification evidence. It never enables live execution. PASS means
only that the engineering evidence is complete enough for a separate live-
executor interface review.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

MAX_CANARY_NOTIONAL_USD = 20.0

AUTHORITY = {
    "interpretation": "FINAL_PRELIVE_CANARY_READINESS_EVIDENCE_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "rpc_contact_allowed": False,
    "transaction_signing_allowed": False,
    "order_submission_allowed": False,
    "automatic_execution": False,
    "automatic_canary_activation": False,
}

_REQUIRED_VERIFICATIONS = (
    "paper_walk_forward_integration_verified",
    "authorization_provisioning_verified",
    "real_postgres_concurrency_verified",
    "persisted_dry_run_lifecycle_verified",
    "restart_persistence_verified",
    "replay_rejection_verified",
    "rollback_before_commit_verified",
    "audit_failure_atomic_rollback_verified",
    "kill_switch_pre_persistence_recheck_verified",
    "zero_external_side_effects_verified",
)


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "operational_readiness_result": "UNKNOWN",
        "eligible_for_live_executor_review": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _blocked(blockers: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "OBSERVED",
        "operational_readiness_result": "BLOCKED",
        "eligible_for_live_executor_review": False,
        "blockers": list(dict.fromkeys(blockers)),
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
            "rpc_contact_allowed",
            "transaction_signing_allowed",
            "order_submission_allowed",
            "rpc_contacted",
            "transaction_signed",
            "order_submitted",
            "wallet_mutated",
            "automatic_execution",
            "automatic_canary_activation",
        )
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def evaluate_final_canary_readiness(
    release_gate: dict[str, Any],
    canary_authorization: dict[str, Any],
    verification: dict[str, Any],
    infrastructure: dict[str, Any],
    safety: dict[str, Any],
    *,
    policy_version: str,
) -> dict[str, Any]:
    """Aggregate all pre-live proof families into one fail-closed verdict.

    Verification evidence is explicit because CI/restart/concurrency history
    cannot be reconstructed safely from current runtime state. Missing proof is
    UNKNOWN; fully observed failing proof is BLOCKED. PASS grants no execution
    authority and only permits separate review of a future live-executor boundary.
    """
    version = str(policy_version or "").strip()
    if not version:
        return _unknown(["operational_policy_version"])

    inputs = {
        "release_gate": release_gate,
        "canary_authorization": canary_authorization,
        "verification": verification,
        "infrastructure": infrastructure,
        "safety": safety,
    }
    malformed = [name for name, value in inputs.items() if not isinstance(value, dict)]
    if malformed:
        return _unknown([f"{name}_evidence" for name in malformed], policy_version=version)

    contaminated = [name for name, value in inputs.items() if _claims_authority(value)]
    if contaminated:
        return _unknown(
            ["non_authoritative_operational_evidence"],
            authority_contamination=contaminated,
            policy_version=version,
        )

    missing: list[str] = []

    if release_gate.get("status") != "OBSERVED":
        missing.append("observed_release_gate")
    if release_gate.get("release_gate_result") != "PASS":
        missing.append("passed_release_gate")
    if release_gate.get("eligible_for_isolated_canary_review") is not True:
        missing.append("release_gate_canary_review_eligibility")
    if release_gate.get("live_canary_unlocked") is not False:
        missing.append("release_gate_does_not_unlock_live")
    release_policy = str(release_gate.get("policy_version") or "").strip()
    if not release_policy:
        missing.append("release_gate_policy_version")

    if canary_authorization.get("status") != "OBSERVED":
        missing.append("observed_canary_authorization")
    if canary_authorization.get("canary_authorization_result") != "PASS":
        missing.append("passed_canary_authorization")
    if canary_authorization.get("canary_execution_eligible") is not True:
        missing.append("canary_execution_eligibility")
    if canary_authorization.get("human_authorized") is not True:
        missing.append("human_authorization")
    authorization_id = str(canary_authorization.get("authorization_id") or "").strip()
    authorization_policy = str(canary_authorization.get("policy_version") or "").strip()
    notional = _number(canary_authorization.get("canary_notional_usd"))
    max_loss = _number(canary_authorization.get("max_loss_usd"))
    if not authorization_id:
        missing.append("authorization_id")
    if not authorization_policy:
        missing.append("authorization_policy_version")
    if notional is None or notional <= 0:
        missing.append("valid_canary_notional_usd")
    if max_loss is None or max_loss <= 0:
        missing.append("valid_max_loss_usd")

    if verification.get("status") != "OBSERVED":
        missing.append("observed_verification_evidence")
    proof_policy = str(verification.get("policy_version") or "").strip()
    tested_main_sha = str(verification.get("tested_main_sha") or "").strip()
    proof_source = str(verification.get("proof_source") or "").strip()
    if not proof_policy:
        missing.append("verification_policy_version")
    if not tested_main_sha:
        missing.append("tested_main_sha")
    if not proof_source:
        missing.append("verification_proof_source")
    for key in _REQUIRED_VERIFICATIONS:
        if key not in verification:
            missing.append(key)

    if infrastructure.get("status") not in {"HEALTHY", "OBSERVED"}:
        missing.append("observed_infrastructure_health")
    if "critical_services_healthy" not in infrastructure:
        missing.append("critical_services_healthy_evidence")
    if "unresolved_critical_incidents" not in infrastructure:
        missing.append("critical_incident_evidence")
    if infrastructure.get("revalidated_for_canary") is not True:
        missing.append("canary_infrastructure_revalidated")
    if not str(infrastructure.get("checked_at") or "").strip():
        missing.append("infrastructure_checked_at")

    if safety.get("status") != "OBSERVED":
        missing.append("observed_safety_evidence")
    if safety.get("safety_checks_complete") is not True:
        missing.append("completed_safety_checks")
    if not isinstance(safety.get("unresolved_safety_failures"), list):
        missing.append("unresolved_safety_failures_list")

    if missing:
        return _unknown(missing, policy_version=version, authorization_id=authorization_id or None)

    blockers: list[str] = []
    if release_policy != version or authorization_policy != version or proof_policy != version:
        blockers.append("policy_version_mismatch")
    if notional is not None and notional > MAX_CANARY_NOTIONAL_USD:
        blockers.append("canary_notional_exceeds_20_usd")
    if max_loss is not None and notional is not None and max_loss > notional:
        blockers.append("loss_cap_exceeds_canary_notional")
    if canary_authorization.get("max_open_positions") != 1:
        blockers.append("single_position_isolation_required")
    for key in ("kill_switch_armed", "isolated_funds", "isolated_account_or_wallet"):
        if canary_authorization.get(key) is not True:
            blockers.append(f"{key}_required")

    failed_proofs = [key for key in _REQUIRED_VERIFICATIONS if verification.get(key) is not True]
    if failed_proofs:
        blockers.extend(failed_proofs)

    if infrastructure.get("critical_services_healthy") is not True:
        blockers.append("critical_services_unhealthy")
    if infrastructure.get("unresolved_critical_incidents") != 0:
        blockers.append("unresolved_critical_incidents")
    unresolved_safety = safety.get("unresolved_safety_failures")
    if unresolved_safety:
        blockers.append("unresolved_safety_failures")

    if blockers:
        return _blocked(
            blockers,
            policy_version=version,
            authorization_id=authorization_id,
            tested_main_sha=tested_main_sha,
            evidence=deepcopy(inputs),
            next_step="REMAIN_NON_LIVE_AND_FIX_BLOCKERS",
        )

    checks = {
        "release_gate_passed": True,
        "isolated_canary_authorization_passed": True,
        "paper_walk_forward_integration_verified": True,
        "authorization_provisioning_verified": True,
        "real_postgres_concurrency_verified": True,
        "persisted_dry_run_lifecycle_verified": True,
        "restart_persistence_verified": True,
        "replay_rejection_verified": True,
        "rollback_before_commit_verified": True,
        "audit_failure_atomic_rollback_verified": True,
        "kill_switch_pre_persistence_recheck_verified": True,
        "zero_external_side_effects_verified": True,
        "critical_infrastructure_healthy": True,
        "no_unresolved_critical_incidents": True,
        "no_unresolved_safety_failures": True,
    }

    return {
        "status": "OBSERVED",
        "operational_readiness_result": "PASS",
        "eligible_for_live_executor_review": True,
        "live_canary_unlocked": False,
        "live_executor_implemented": False,
        "policy_version": version,
        "authorization_id": authorization_id,
        "canary_notional_usd": notional,
        "max_loss_usd": max_loss,
        "maximum_canary_notional_usd": MAX_CANARY_NOTIONAL_USD,
        "tested_main_sha": tested_main_sha,
        "proof_source": proof_source,
        "checks": checks,
        "evidence": deepcopy(inputs),
        "next_step": "SEPARATE_REVIEW_OF_NON_AUTOMATIC_LIVE_EXECUTOR_BOUNDARY",
        **AUTHORITY,
    }
