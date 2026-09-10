from copy import deepcopy

from stinky_api.executor_failure_mode_state_machine import (
    ALLOWED_STATES,
    evaluate_executor_failure_transition,
)


def contract():
    return {
        "status": "OBSERVED",
        "executor_boundary_result": "CONTRACT_READY",
        "executor_contract_ready": True,
        "authorization_id": "auth-172",
        "policy_version": "release-v1",
        "attempt_id": "attempt-172",
        "idempotency_key": "idem-172",
        "submission_state": "NOT_SENT",
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
        "rpc_contact_allowed": False,
        "transaction_signing_allowed": False,
        "order_submission_allowed": False,
        "wallet_mutation_allowed": False,
        "automatic_execution": False,
        "automatic_retry_allowed": False,
    }


def prior(state="NOT_SENT", key="idem-172"):
    return {
        "submission_state": state,
        "authorization_id": "auth-172",
        "policy_version": "release-v1",
        "attempt_id": "attempt-172",
        "idempotency_key": key,
    }


def observation(event, key="idem-172"):
    return {
        "event": event,
        "authorization_id": "auth-172",
        "policy_version": "release-v1",
        "attempt_id": "attempt-172",
        "idempotency_key": key,
    }


def test_submission_timeout_becomes_unknown_and_never_safe_to_retry():
    result = evaluate_executor_failure_transition(contract(), prior(), observation("SUBMISSION_TIMEOUT_UNKNOWN"))
    assert result["submission_state"] == "SUBMISSION_UNKNOWN"
    assert result["reconciliation_required"] is True
    assert result["safe_to_retry"] is False
    assert result["automatic_retry_allowed"] is False
    assert result["duplicate_submission_allowed"] is False
    assert result["next_step"] == "DO_NOT_RETRY; RECONCILE_SUBMISSION_STATE"


def test_crash_after_submission_may_have_occurred_is_unknown():
    result = evaluate_executor_failure_transition(contract(), prior(), observation("PROCESS_CRASH_AFTER_SUBMISSION_MAY_HAVE_OCCURRED"))
    assert result["submission_state"] == "SUBMISSION_UNKNOWN"
    assert result["reconciliation_required"] is True
    assert result["manual_retry_review_eligible"] is False


def test_pre_submission_failures_remain_not_sent_but_do_not_authorize_retry():
    for event in (
        "BUILD_FAILED",
        "SIGNING_PREPARATION_FAILED",
        "RPC_UNREACHABLE_BEFORE_SUBMISSION",
        "RPC_TIMEOUT_BEFORE_SUBMISSION",
        "PROCESS_CRASH_BEFORE_SUBMISSION",
    ):
        result = evaluate_executor_failure_transition(contract(), prior(), observation(event))
        assert result["submission_state"] == "NOT_SENT"
        assert result["safe_to_retry"] is False
        assert result["automatic_retry_allowed"] is False
        assert result["manual_retry_review_eligible"] is True


def test_known_rejection_is_terminal_failed():
    result = evaluate_executor_failure_transition(contract(), prior(), observation("KNOWN_REJECTION"))
    assert result["submission_state"] == "FAILED"
    assert result["reconciliation_required"] is False
    assert result["manual_retry_review_eligible"] is False


def test_submission_accepted_waits_for_confirmation():
    result = evaluate_executor_failure_transition(contract(), prior(), observation("SUBMISSION_ACCEPTED"))
    assert result["submission_state"] == "SUBMITTED"
    assert result["reconciliation_required"] is True
    assert result["safe_to_retry"] is False


def test_confirmation_delayed_stays_submitted_and_no_retry():
    result = evaluate_executor_failure_transition(contract(), prior("SUBMITTED"), observation("CONFIRMATION_DELAYED"))
    assert result["submission_state"] == "SUBMITTED"
    assert result["reconciliation_required"] is True
    assert result["automatic_retry_allowed"] is False


def test_confirmed_success_is_terminal():
    result = evaluate_executor_failure_transition(contract(), prior("SUBMITTED"), observation("CONFIRMED_SUCCESS"))
    assert result["submission_state"] == "CONFIRMED"
    assert result["reconciliation_required"] is False
    assert result["safe_to_retry"] is False


def test_confirmed_chain_failure_is_terminal():
    result = evaluate_executor_failure_transition(contract(), prior("SUBMITTED"), observation("CONFIRMED_CHAIN_FAILURE"))
    assert result["submission_state"] == "FAILED"
    assert result["reconciliation_required"] is False
    assert result["safe_to_retry"] is False


def test_reconcile_unknown_not_found_returns_not_sent_manual_review_only():
    result = evaluate_executor_failure_transition(contract(), prior("SUBMISSION_UNKNOWN"), observation("RECONCILED_NOT_FOUND"))
    assert result["submission_state"] == "NOT_SENT"
    assert result["manual_retry_review_eligible"] is True
    assert result["safe_to_retry"] is False
    assert result["automatic_retry_allowed"] is False


def test_reconcile_unknown_to_submitted_confirmed_and_failed():
    submitted = evaluate_executor_failure_transition(contract(), prior("SUBMISSION_UNKNOWN"), observation("RECONCILED_SUBMITTED"))
    confirmed = evaluate_executor_failure_transition(contract(), prior("SUBMISSION_UNKNOWN"), observation("RECONCILED_CONFIRMED"))
    failed = evaluate_executor_failure_transition(contract(), prior("SUBMISSION_UNKNOWN"), observation("RECONCILED_FAILED"))
    assert submitted["submission_state"] == "SUBMITTED"
    assert confirmed["submission_state"] == "CONFIRMED"
    assert failed["submission_state"] == "FAILED"


def test_invalid_transition_is_blocked_without_state_advance():
    result = evaluate_executor_failure_transition(contract(), prior("SUBMISSION_UNKNOWN"), observation("BUILD_FAILED"))
    assert result["state_machine_result"] == "BLOCKED"
    assert result["submission_state"] == "SUBMISSION_UNKNOWN"
    assert "invalid_submission_state_transition" in result["blockers"]
    assert result["safe_to_retry"] is False


def test_terminal_states_cannot_advance():
    for state in ("CONFIRMED", "FAILED"):
        result = evaluate_executor_failure_transition(contract(), prior(state), observation("RECONCILED_NOT_FOUND"))
        assert result["state_machine_result"] == "BLOCKED"
        assert result["submission_state"] == state
        assert "terminal_submission_state" in result["blockers"]


def test_identity_or_idempotency_mismatch_blocks():
    result = evaluate_executor_failure_transition(contract(), prior(), observation("SUBMISSION_ACCEPTED", key="other-key"))
    assert result["state_machine_result"] == "BLOCKED"
    assert "execution_identity_mismatch" in result["blockers"]


def test_authority_contamination_fails_closed():
    unsafe = contract()
    unsafe["rpc_contact_allowed"] = True
    result = evaluate_executor_failure_transition(unsafe, prior(), observation("BUILD_FAILED"))
    assert result["status"] == "UNKNOWN"
    assert "non_authoritative_failure_mode_evidence" in result["missing"]


def test_missing_or_invalid_event_fails_closed():
    result = evaluate_executor_failure_transition(contract(), prior(), observation("NOT_A_REAL_EVENT"))
    assert result["status"] == "UNKNOWN"
    assert "valid_failure_mode_event" in result["missing"]


def test_state_vocabulary_is_exact_and_stable():
    assert ALLOWED_STATES == (
        "NOT_SENT",
        "SUBMISSION_UNKNOWN",
        "SUBMITTED",
        "CONFIRMED",
        "FAILED",
    )


def test_inputs_are_deep_copied_into_evidence():
    source = contract()
    original = deepcopy(source)
    result = evaluate_executor_failure_transition(source, prior(), observation("BUILD_FAILED"))
    source["authorization_id"] = "mutated"
    assert result["evidence"]["executor_contract"] == original


def test_every_successful_transition_remains_non_broadcasting():
    result = evaluate_executor_failure_transition(contract(), prior(), observation("SUBMISSION_ACCEPTED"))
    assert result["live_execution"] is False
    assert result["rpc_contacted"] is False
    assert result["transaction_signed"] is False
    assert result["order_submitted"] is False
    assert result["wallet_mutated"] is False
    assert result["automatic_execution"] is False
    assert result["automatic_retry_allowed"] is False
