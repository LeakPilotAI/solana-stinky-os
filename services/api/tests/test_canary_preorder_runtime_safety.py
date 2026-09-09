from copy import deepcopy

from stinky_api.canary_preorder_runtime_safety import evaluate_canary_preorder_runtime_safety


def _authorization():
    return {
        "status": "OBSERVED",
        "canary_authorization_result": "PASS",
        "canary_execution_eligible": True,
        "canary_notional_usd": 20.0,
        "max_loss_usd": 5.0,
        "authorization_id": "auth-1",
        "policy_version": "v1",
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
        "rpc_contact_allowed": False,
        "transaction_signing_allowed": False,
        "order_submission_allowed": False,
        "automatic_execution": False,
    }


def _runtime():
    return {
        "requested_notional_usd": 20.0,
        "realized_loss_usd": 0.0,
        "open_positions": 0,
        "kill_switch_armed": True,
        "isolated_funds": True,
        "isolated_account_or_wallet": True,
        "no_borrowing": True,
        "no_leverage": True,
        "evaluated_at": "2026-09-09T14:35:00+00:00",
        "max_infrastructure_age_seconds": 60,
    }


def _infra():
    return {
        "status": "HEALTHY",
        "critical_services_healthy": True,
        "unresolved_critical_incidents": 0,
        "checked_at": "2026-09-09T14:34:30+00:00",
    }


def _state():
    return {"authorization_id": "auth-1", "consumed": False, "use_count": 0}


def test_pass_is_single_use_adapter_eligibility_without_execution_authority():
    result = evaluate_canary_preorder_runtime_safety(_authorization(), _runtime(), _infra(), _state())
    assert result["preorder_result"] == "PASS"
    assert result["execution_adapter_eligible"] is True
    assert result["authorization_consumable"] is True
    assert result["single_use"] is True
    assert result["live_execution"] is False
    assert result["rpc_contact_allowed"] is False
    assert result["transaction_signing_allowed"] is False
    assert result["order_submission_allowed"] is False


def test_already_consumed_authorization_blocks():
    state = _state()
    state["consumed"] = True
    state["use_count"] = 1
    result = evaluate_canary_preorder_runtime_safety(_authorization(), _runtime(), _infra(), state)
    assert result["preorder_result"] == "BLOCKED"
    assert "authorization_already_consumed" in result["blockers"]


def test_authorization_state_id_must_match():
    state = _state()
    state["authorization_id"] = "other"
    result = evaluate_canary_preorder_runtime_safety(_authorization(), _runtime(), _infra(), state)
    assert "authorization_state_mismatch" in result["blockers"]


def test_requested_notional_cannot_exceed_20_or_authorized_amount():
    runtime = _runtime()
    runtime["requested_notional_usd"] = 21.0
    result = evaluate_canary_preorder_runtime_safety(_authorization(), runtime, _infra(), _state())
    assert "requested_notional_exceeds_20_usd" in result["blockers"]
    assert "requested_notional_exceeds_authorized_notional" in result["blockers"]


def test_loss_cap_reached_blocks():
    runtime = _runtime()
    runtime["realized_loss_usd"] = 5.0
    result = evaluate_canary_preorder_runtime_safety(_authorization(), runtime, _infra(), _state())
    assert "loss_cap_reached" in result["blockers"]


def test_existing_position_blocks_new_canary():
    runtime = _runtime()
    runtime["open_positions"] = 1
    result = evaluate_canary_preorder_runtime_safety(_authorization(), runtime, _infra(), _state())
    assert "existing_open_position_blocks_new_canary" in result["blockers"]


def test_kill_switch_and_isolation_are_rechecked():
    runtime = _runtime()
    runtime["kill_switch_armed"] = False
    runtime["isolated_funds"] = False
    result = evaluate_canary_preorder_runtime_safety(_authorization(), runtime, _infra(), _state())
    assert "kill_switch_not_armed" in result["blockers"]
    assert "funds_not_isolated" in result["blockers"]


def test_infrastructure_must_be_healthy_and_fresh():
    infra = _infra()
    infra["critical_services_healthy"] = False
    runtime = _runtime()
    runtime["evaluated_at"] = "2026-09-09T14:36:00+00:00"
    result = evaluate_canary_preorder_runtime_safety(_authorization(), runtime, infra, _state())
    assert "critical_services_unhealthy" in result["blockers"]
    assert "infrastructure_recheck_stale" in result["blockers"]


def test_authority_contamination_fails_closed_unknown():
    authorization = _authorization()
    authorization["live_execution"] = True
    result = evaluate_canary_preorder_runtime_safety(authorization, _runtime(), _infra(), _state())
    assert result["status"] == "UNKNOWN"
    assert result["execution_adapter_eligible"] is False
    assert "non_authoritative_preorder_evidence" in result["missing"]


def test_missing_required_runtime_evidence_fails_closed_unknown():
    runtime = _runtime()
    del runtime["kill_switch_armed"]
    result = evaluate_canary_preorder_runtime_safety(_authorization(), runtime, _infra(), _state())
    assert result["status"] == "UNKNOWN"
    assert "kill_switch_armed" in result["missing"]


def test_authorized_loss_cap_cannot_exceed_authorized_notional():
    authorization = _authorization()
    authorization["canary_notional_usd"] = 10.0
    authorization["max_loss_usd"] = 11.0
    runtime = _runtime()
    runtime["requested_notional_usd"] = 10.0
    result = evaluate_canary_preorder_runtime_safety(authorization, runtime, _infra(), _state())
    assert "loss_cap_exceeds_authorized_notional" in result["blockers"]


def test_evidence_is_deep_copied():
    authorization = _authorization()
    result = evaluate_canary_preorder_runtime_safety(authorization, _runtime(), _infra(), _state())
    authorization["authorization_id"] = "mutated"
    assert result["evidence"]["canary_authorization"]["authorization_id"] == "auth-1"
