"""Non-broadcasting executor failure-mode state machine for Project Genesis.

This module models dangerous live-executor outcomes without contacting RPCs,
signing transactions, mutating wallets, or submitting orders. It exists to prove
state-transition and retry semantics before a real executor implementation exists.

The central invariant is conservative uncertainty handling: once submission may
have occurred, automatic retry is forbidden until an external reconciliation step
proves the chain outcome. UNKNOWN is a valid state and never implies safe retry.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ALLOWED_STATES = (
    "NOT_SENT",
    "SUBMISSION_UNKNOWN",
    "SUBMITTED",
    "CONFIRMED",
    "FAILED",
)

ALLOWED_EVENTS = (
    "BUILD_FAILED",
    "SIGNING_PREPARATION_FAILED",
    "RPC_UNREACHABLE_BEFORE_SUBMISSION",
    "RPC_TIMEOUT_BEFORE_SUBMISSION",
    "SUBMISSION_TIMEOUT_UNKNOWN",
    "KNOWN_REJECTION",
    "SUBMISSION_ACCEPTED",
    "CONFIRMATION_DELAYED",
    "CONFIRMED_SUCCESS",
    "CONFIRMED_CHAIN_FAILURE",
    "PROCESS_CRASH_BEFORE_SUBMISSION",
    "PROCESS_CRASH_AFTER_SUBMISSION_MAY_HAVE_OCCURRED",
    "RECONCILED_NOT_FOUND",
    "RECONCILED_SUBMITTED",
    "RECONCILED_CONFIRMED",
    "RECONCILED_FAILED",
)

AUTHORITY = {
    "interpretation": "NON_BROADCASTING_EXECUTOR_FAILURE_MODE_STATE_MACHINE_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
    "automatic_execution": False,
    "automatic_retry_allowed": False,
}


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "state_machine_result": "UNKNOWN",
        "submission_state": extra.pop("submission_state", "NOT_SENT"),
        "safe_to_retry": False,
        "reconciliation_required": True,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _blocked(blockers: list[str], *, submission_state: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "OBSERVED",
        "state_machine_result": "BLOCKED",
        "submission_state": submission_state,
        "safe_to_retry": False,
        "reconciliation_required": submission_state in {"SUBMISSION_UNKNOWN", "SUBMITTED"},
        "blockers": list(dict.fromkeys(blockers)),
        **extra,
        **AUTHORITY,
    }


def _claims_external_authority(value: dict[str, Any]) -> bool:
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
            "wallet_mutation_allowed",
            "automatic_execution",
            "automatic_retry_allowed",
        )
    )


def evaluate_executor_failure_transition(
    executor_contract: dict[str, Any],
    prior: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one non-broadcasting executor failure-mode transition."""
    inputs = {
        "executor_contract": executor_contract,
        "prior": prior,
        "observation": observation,
    }
    malformed = [name for name, value in inputs.items() if not isinstance(value, dict)]
    if malformed:
        return _unknown([f"{name}_evidence" for name in malformed])

    contaminated = [name for name, value in inputs.items() if _claims_external_authority(value)]
    if contaminated:
        return _unknown(
            ["non_authoritative_failure_mode_evidence"],
            authority_contamination=contaminated,
        )

    missing: list[str] = []
    if executor_contract.get("status") != "OBSERVED":
        missing.append("observed_executor_contract")
    if executor_contract.get("executor_boundary_result") != "CONTRACT_READY":
        missing.append("ready_executor_contract")
    if executor_contract.get("executor_contract_ready") is not True:
        missing.append("executor_contract_readiness")
    if executor_contract.get("submission_state") != "NOT_SENT":
        missing.append("contract_submission_state_not_sent")

    contract_auth = str(executor_contract.get("authorization_id") or "").strip()
    contract_policy = str(executor_contract.get("policy_version") or "").strip()
    contract_attempt = str(executor_contract.get("attempt_id") or "").strip()
    contract_key = str(executor_contract.get("idempotency_key") or "").strip()
    for name, value in (("authorization_id", contract_auth),("policy_version", contract_policy),("attempt_id", contract_attempt),("idempotency_key", contract_key)):
        if not value:
            missing.append(f"contract_{name}")

    prior_state = str(prior.get("submission_state") or "").strip()
    prior_auth = str(prior.get("authorization_id") or "").strip()
    prior_policy = str(prior.get("policy_version") or "").strip()
    prior_attempt = str(prior.get("attempt_id") or "").strip()
    prior_key = str(prior.get("idempotency_key") or "").strip()
    if prior_state not in ALLOWED_STATES:
        missing.append("valid_prior_submission_state")
    for name, value in (("authorization_id", prior_auth),("policy_version", prior_policy),("attempt_id", prior_attempt),("idempotency_key", prior_key)):
        if not value:
            missing.append(f"prior_{name}")

    event = str(observation.get("event") or "").strip()
    observed_auth = str(observation.get("authorization_id") or "").strip()
    observed_policy = str(observation.get("policy_version") or "").strip()
    observed_attempt = str(observation.get("attempt_id") or "").strip()
    observed_key = str(observation.get("idempotency_key") or "").strip()
    if event not in ALLOWED_EVENTS:
        missing.append("valid_failure_mode_event")
    for name, value in (("authorization_id", observed_auth),("policy_version", observed_policy),("attempt_id", observed_attempt),("idempotency_key", observed_key)):
        if not value:
            missing.append(f"observation_{name}")

    if missing:
        return _unknown(missing, submission_state=prior_state if prior_state in ALLOWED_STATES else "NOT_SENT")

    if not (
        contract_auth == prior_auth == observed_auth
        and contract_policy == prior_policy == observed_policy
        and contract_attempt == prior_attempt == observed_attempt
        and contract_key == prior_key == observed_key
    ):
        return _blocked(
            ["execution_identity_mismatch"],
            submission_state=prior_state,
            evidence=deepcopy(inputs),
            next_step="DO_NOT_ADVANCE_STATE",
        )

    if prior_state in {"CONFIRMED", "FAILED"}:
        return _blocked(
            ["terminal_submission_state"],
            submission_state=prior_state,
            evidence=deepcopy(inputs),
            next_step="NO_RETRY_TERMINAL_STATE",
        )

    table: dict[tuple[str, str], tuple[str, bool, bool, str]] = {
        ("NOT_SENT", "BUILD_FAILED"): ("NOT_SENT", False, True, "MAY_REQUEST_NEW_MANUAL_EXECUTOR_REVIEW"),
        ("NOT_SENT", "SIGNING_PREPARATION_FAILED"): ("NOT_SENT", False, True, "MAY_REQUEST_NEW_MANUAL_EXECUTOR_REVIEW"),
        ("NOT_SENT", "RPC_UNREACHABLE_BEFORE_SUBMISSION"): ("NOT_SENT", False, True, "MAY_REQUEST_NEW_MANUAL_EXECUTOR_REVIEW"),
        ("NOT_SENT", "RPC_TIMEOUT_BEFORE_SUBMISSION"): ("NOT_SENT", False, True, "MAY_REQUEST_NEW_MANUAL_EXECUTOR_REVIEW"),
        ("NOT_SENT", "KNOWN_REJECTION"): ("FAILED", False, False, "NO_RETRY_TERMINAL_FAILURE"),
        ("NOT_SENT", "PROCESS_CRASH_BEFORE_SUBMISSION"): ("NOT_SENT", False, True, "MAY_REQUEST_NEW_MANUAL_EXECUTOR_REVIEW"),
        ("NOT_SENT", "SUBMISSION_TIMEOUT_UNKNOWN"): ("SUBMISSION_UNKNOWN", True, False, "DO_NOT_RETRY; RECONCILE_SUBMISSION_STATE"),
        ("NOT_SENT", "PROCESS_CRASH_AFTER_SUBMISSION_MAY_HAVE_OCCURRED"): ("SUBMISSION_UNKNOWN", True, False, "DO_NOT_RETRY; RECONCILE_SUBMISSION_STATE"),
        ("NOT_SENT", "SUBMISSION_ACCEPTED"): ("SUBMITTED", True, False, "WAIT_OR_RECONCILE_CONFIRMATION"),
        ("SUBMISSION_UNKNOWN", "RECONCILED_NOT_FOUND"): ("NOT_SENT", False, True, "MAY_REQUEST_NEW_MANUAL_EXECUTOR_REVIEW"),
        ("SUBMISSION_UNKNOWN", "RECONCILED_SUBMITTED"): ("SUBMITTED", True, False, "WAIT_OR_RECONCILE_CONFIRMATION"),
        ("SUBMISSION_UNKNOWN", "RECONCILED_CONFIRMED"): ("CONFIRMED", False, False, "NO_RETRY_CONFIRMED"),
        ("SUBMISSION_UNKNOWN", "RECONCILED_FAILED"): ("FAILED", False, False, "NO_RETRY_TERMINAL_FAILURE"),
        ("SUBMITTED", "CONFIRMATION_DELAYED"): ("SUBMITTED", True, False, "WAIT_OR_RECONCILE_CONFIRMATION"),
        ("SUBMITTED", "CONFIRMED_SUCCESS"): ("CONFIRMED", False, False, "NO_RETRY_CONFIRMED"),
        ("SUBMITTED", "CONFIRMED_CHAIN_FAILURE"): ("FAILED", False, False, "NO_RETRY_TERMINAL_FAILURE"),
        ("SUBMITTED", "RECONCILED_CONFIRMED"): ("CONFIRMED", False, False, "NO_RETRY_CONFIRMED"),
        ("SUBMITTED", "RECONCILED_FAILED"): ("FAILED", False, False, "NO_RETRY_TERMINAL_FAILURE"),
    }
    transition = table.get((prior_state, event))
    if transition is None:
        return _blocked(
            ["invalid_submission_state_transition"],
            submission_state=prior_state,
            event=event,
            evidence=deepcopy(inputs),
            next_step="DO_NOT_RETRY; INVALID_STATE_TRANSITION",
        )

    new_state, reconciliation_required, manual_retry_review_eligible, next_step = transition
    return {
        "status": "OBSERVED",
        "state_machine_result": "TRANSITION_OBSERVED",
        "prior_submission_state": prior_state,
        "submission_state": new_state,
        "event": event,
        "authorization_id": contract_auth,
        "policy_version": contract_policy,
        "attempt_id": contract_attempt,
        "idempotency_key": contract_key,
        "reconciliation_required": reconciliation_required,
        "safe_to_retry": False,
        "manual_retry_review_eligible": manual_retry_review_eligible,
        "automatic_retry_allowed": False,
        "duplicate_submission_allowed": False,
        "evidence": deepcopy(inputs),
        "next_step": next_step,
        **AUTHORITY,
    }
