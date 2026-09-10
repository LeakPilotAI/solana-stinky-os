from copy import deepcopy

from stinky_api.dry_run_execution_adapter import prepare_dry_run_canary_execution


def _preorder():
    return {
        "status": "OBSERVED",
        "preorder_result": "PASS",
        "execution_adapter_eligible": True,
        "authorization_consumable": True,
        "single_use": True,
        "authorization_id": "auth-1",
        "policy_version": "v1",
        "requested_notional_usd": 20.0,
        "max_loss_usd": 5.0,
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
        "rpc_contacted": False,
        "transaction_signed": False,
        "order_submitted": False,
        "automatic_execution": False,
    }


def _state():
    return {
        "authorization_id": "auth-1",
        "consumed": False,
        "use_count": 0,
        "version": 7,
    }


def _request():
    return {
        "attempt_id": "attempt-1",
        "requested_at": "2026-09-09T20:34:00-05:00",
        "authorization_id": "auth-1",
        "policy_version": "v1",
        "requested_notional_usd": 20.0,
        "adapter_mode": "DRY_RUN",
        "idempotency_key": "idem-1",
    }


def test_ready_prepares_cas_transition_without_external_side_effects():
    result = prepare_dry_run_canary_execution(_preorder(), _state(), _request())
    assert result["adapter_result"] == "DRY_RUN_READY"
    assert result["dry_run_ready"] is True
    assert result["authorization_transition_prepared"] is True
    transition = result["authorization_transition"]
    assert transition["operation"] == "COMPARE_AND_SWAP_AUTHORIZATION_CONSUMPTION"
    assert transition["expected"] == {"consumed": False, "use_count": 0, "version": 7}
    assert transition["proposed"]["consumed"] is True
    assert transition["proposed"]["use_count"] == 1
    assert transition["proposed"]["version"] == 8
    assert transition["applied"] is False
    assert result["live_execution"] is False
    assert result["rpc_contacted"] is False
    assert result["transaction_signed"] is False
    assert result["order_submitted"] is False
    assert result["persistence_mutated"] is False


def test_audit_record_is_dry_run_and_no_side_effects():
    result = prepare_dry_run_canary_execution(_preorder(), _state(), _request())
    audit = result["post_order_audit_record"]
    assert audit["event"] == "CANARY_EXECUTION_ADAPTER_DRY_RUN_PREPARED"
    assert audit["adapter_mode"] == "DRY_RUN"
    assert audit["external_side_effects"] is False
    assert audit["authorization_transition_applied"] is False
    assert audit["rpc_contacted"] is False
    assert audit["transaction_signed"] is False
    assert audit["order_submitted"] is False


def test_live_adapter_mode_is_blocked():
    request = _request()
    request["adapter_mode"] = "LIVE"
    result = prepare_dry_run_canary_execution(_preorder(), _state(), request)
    assert result["adapter_result"] == "BLOCKED"
    assert "adapter_mode_must_be_dry_run" in result["blockers"]


def test_consumed_authorization_is_blocked():
    state = _state()
    state["consumed"] = True
    state["use_count"] = 1
    result = prepare_dry_run_canary_execution(_preorder(), state, _request())
    assert "authorization_already_consumed" in result["blockers"]


def test_authorization_ids_must_match_everywhere():
    request = _request()
    request["authorization_id"] = "other"
    result = prepare_dry_run_canary_execution(_preorder(), _state(), request)
    assert "authorization_id_mismatch" in result["blockers"]


def test_policy_version_must_match():
    request = _request()
    request["policy_version"] = "v2"
    result = prepare_dry_run_canary_execution(_preorder(), _state(), request)
    assert "policy_version_mismatch" in result["blockers"]


def test_notional_cannot_exceed_20_or_preorder_amount():
    preorder = _preorder()
    preorder["requested_notional_usd"] = 10.0
    request = _request()
    request["requested_notional_usd"] = 21.0
    result = prepare_dry_run_canary_execution(preorder, _state(), request)
    assert "requested_notional_exceeds_20_usd" in result["blockers"]
    assert "requested_notional_exceeds_preorder_notional" in result["blockers"]


def test_missing_idempotency_key_fails_closed_unknown():
    request = _request()
    del request["idempotency_key"]
    result = prepare_dry_run_canary_execution(_preorder(), _state(), request)
    assert result["status"] == "UNKNOWN"
    assert "idempotency_key" in result["missing"]


def test_execution_contamination_fails_closed_unknown():
    preorder = _preorder()
    preorder["order_submitted"] = True
    result = prepare_dry_run_canary_execution(preorder, _state(), _request())
    assert result["status"] == "UNKNOWN"
    assert "non_executing_dry_run_inputs" in result["missing"]


def test_state_version_is_required_for_compare_and_swap():
    state = _state()
    del state["version"]
    result = prepare_dry_run_canary_execution(_preorder(), state, _request())
    assert result["status"] == "UNKNOWN"
    assert "valid_authorization_state_version" in result["missing"]


def test_preorder_must_explicitly_allow_single_use_consumption():
    preorder = _preorder()
    preorder["authorization_consumable"] = False
    preorder["single_use"] = False
    result = prepare_dry_run_canary_execution(preorder, _state(), _request())
    assert result["status"] == "UNKNOWN"
    assert "authorization_consumable" in result["missing"]
    assert "single_use_preorder" in result["missing"]


def test_evidence_is_deep_copied():
    preorder = _preorder()
    result = prepare_dry_run_canary_execution(preorder, _state(), _request())
    preorder["authorization_id"] = "mutated"
    assert result["evidence"]["preorder"]["authorization_id"] == "auth-1"
