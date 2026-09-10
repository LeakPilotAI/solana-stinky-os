from copy import deepcopy

from stinky_api.live_executor_boundary_contract import (
    ALLOWED_SUBMISSION_STATES,
    evaluate_live_executor_boundary_contract,
)


def readiness():
    return {
        "status": "OBSERVED",
        "operational_readiness_result": "PASS",
        "eligible_for_live_executor_review": True,
        "live_canary_unlocked": False,
        "live_executor_implemented": False,
        "policy_version": "release-v1",
        "authorization_id": "auth-exec-boundary",
        "canary_notional_usd": 20.0,
        "max_loss_usd": 5.0,
        "maximum_canary_notional_usd": 20.0,
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
        "rpc_contact_allowed": False,
        "transaction_signing_allowed": False,
        "order_submission_allowed": False,
        "automatic_execution": False,
    }


def authorization_state():
    return {
        "authorization_id": "auth-exec-boundary",
        "policy_version": "release-v1",
        "consumed": False,
        "use_count": 0,
        "version": 0,
    }


def runtime():
    return {
        "requested_notional_usd": 20.0,
        "realized_loss_usd": 0.0,
        "open_positions": 0,
        "kill_switch_armed": True,
        "isolated_funds": True,
        "isolated_account_or_wallet": True,
        "no_borrowing": True,
        "no_leverage": True,
        "evaluated_at": "2026-09-10T03:20:05+00:00",
    }


def quote():
    return {
        "quote_id": "quote-1",
        "quoted_at": "2026-09-10T03:20:00+00:00",
        "expires_at": "2026-09-10T03:20:30+00:00",
        "notional_usd": 20.0,
    }


def request():
    return {
        "authorization_id": "auth-exec-boundary",
        "policy_version": "release-v1",
        "attempt_id": "attempt-1",
        "idempotency_key": "idem-1",
        "quote_id": "quote-1",
        "requested_at": "2026-09-10T03:20:10+00:00",
        "prior_submission_state": "NOT_SENT",
    }


def evaluate(r=None, state=None, rt=None, q=None, req=None):
    return evaluate_live_executor_boundary_contract(
        r or readiness(),
        state or authorization_state(),
        rt or runtime(),
        q or quote(),
        req or request(),
    )


def test_contract_ready_is_still_non_broadcasting():
    result = evaluate()
    assert result["executor_boundary_result"] == "CONTRACT_READY"
    assert result["executor_contract_ready"] is True
    assert result["submission_state"] == "NOT_SENT"
    assert result["safe_to_retry"] is False
    assert result["live_execution"] is False
    assert result["rpc_contact_allowed"] is False
    assert result["transaction_signing_allowed"] is False
    assert result["order_submission_allowed"] is False
    assert result["wallet_mutation_allowed"] is False
    assert result["private_key_material_required"] is False
    assert result["private_key_material_logged"] is False
    assert result["intelligence_direct_executor_access"] is False


def test_final_readiness_must_pass():
    value = readiness()
    value["operational_readiness_result"] = "BLOCKED"
    result = evaluate(r=value)
    assert result["executor_boundary_result"] == "UNKNOWN"
    assert "passed_final_readiness" in result["missing"]


def test_authorization_must_be_fresh_single_use():
    state = authorization_state()
    state["consumed"] = True
    state["use_count"] = 1
    result = evaluate(state=state)
    assert result["executor_boundary_result"] == "BLOCKED"
    assert "authorization_not_fresh_single_use" in result["blockers"]


def test_hard_20_usd_cap_cannot_be_exceeded():
    rt = runtime()
    rt["requested_notional_usd"] = 20.01
    q = quote()
    q["notional_usd"] = 20.01
    result = evaluate(rt=rt, q=q)
    assert result["executor_boundary_result"] == "BLOCKED"
    assert "requested_notional_exceeds_20_usd" in result["blockers"]


def test_loss_cap_and_existing_position_block():
    rt = runtime()
    rt["realized_loss_usd"] = 5.0
    rt["open_positions"] = 1
    result = evaluate(rt=rt)
    assert "max_loss_reached" in result["blockers"]
    assert "existing_open_position" in result["blockers"]


def test_kill_switch_isolation_borrowing_and_leverage_are_immediate_blocks():
    rt = runtime()
    rt.update({
        "kill_switch_armed": False,
        "isolated_funds": False,
        "isolated_account_or_wallet": False,
        "no_borrowing": False,
        "no_leverage": False,
    })
    result = evaluate(rt=rt)
    assert "kill_switch_not_armed" in result["blockers"]
    assert "funds_not_isolated" in result["blockers"]
    assert "account_or_wallet_not_isolated" in result["blockers"]
    assert "borrowing_not_prohibited" in result["blockers"]
    assert "leverage_not_prohibited" in result["blockers"]


def test_expired_quote_blocks():
    q = quote()
    q["expires_at"] = "2026-09-10T03:20:06+00:00"
    req = request()
    req["requested_at"] = "2026-09-10T03:20:10+00:00"
    result = evaluate(q=q, req=req)
    assert "quote_expired" in result["blockers"]


def test_quote_identity_and_notional_must_match():
    q = quote()
    q["notional_usd"] = 19.0
    req = request()
    req["quote_id"] = "quote-other"
    result = evaluate(q=q, req=req)
    assert "quote_notional_mismatch" in result["blockers"]
    assert "quote_id_mismatch" in result["blockers"]


def test_submission_unknown_is_never_safe_to_retry():
    req = request()
    req["prior_submission_state"] = "SUBMISSION_UNKNOWN"
    result = evaluate(req=req)
    assert result["executor_boundary_result"] == "BLOCKED"
    assert result["safe_to_retry"] is False
    assert "prior_submission_not_proven_not_sent" in result["blockers"]
    assert result["next_step"] == "DO_NOT_RETRY; RECONCILE_SUBMISSION_STATE"


def test_any_prior_sent_or_terminal_state_blocks_new_submission():
    for state in ("SUBMITTED", "CONFIRMED", "FAILED"):
        req = request()
        req["prior_submission_state"] = state
        result = evaluate(req=req)
        assert result["executor_boundary_result"] == "BLOCKED"
        assert "prior_submission_not_proven_not_sent" in result["blockers"]


def test_submission_state_vocabulary_is_explicit():
    assert ALLOWED_SUBMISSION_STATES == (
        "NOT_SENT",
        "SUBMISSION_UNKNOWN",
        "SUBMITTED",
        "CONFIRMED",
        "FAILED",
    )


def test_policy_and_authorization_identity_must_match():
    req = request()
    req["authorization_id"] = "other-auth"
    req["policy_version"] = "other-policy"
    result = evaluate(req=req)
    assert "authorization_id_mismatch" in result["blockers"]
    assert "policy_version_mismatch" in result["blockers"]


def test_external_authority_contamination_fails_unknown():
    q = quote()
    q["rpc_contacted"] = True
    result = evaluate(q=q)
    assert result["executor_boundary_result"] == "UNKNOWN"
    assert "non_authoritative_executor_boundary_evidence" in result["missing"]


def test_missing_idempotency_fails_closed():
    req = request()
    req["idempotency_key"] = ""
    result = evaluate(req=req)
    assert result["executor_boundary_result"] == "UNKNOWN"
    assert "idempotency_key" in result["missing"]


def test_result_evidence_is_mutation_isolated():
    source = readiness()
    original = deepcopy(source)
    result = evaluate(r=source)
    source["authorization_id"] = "mutated"
    assert result["evidence"]["final_readiness"] == original
