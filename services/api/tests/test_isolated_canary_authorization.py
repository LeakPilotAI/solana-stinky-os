from copy import deepcopy

from stinky_api.isolated_canary_authorization import (
    MAX_CANARY_NOTIONAL_USD,
    evaluate_isolated_canary_authorization,
)


def release_gate():
    return {
        "status": "OBSERVED",
        "release_gate_result": "PASS",
        "eligible_for_isolated_canary_review": True,
        "live_canary_unlocked": False,
        "automatic_canary_activation": False,
        "policy_version": "release-v1",
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
    }


def controls():
    return {
        "canary_notional_usd": 20.0,
        "max_loss_usd": 5.0,
        "max_open_positions": 1,
        "isolated_funds": True,
        "isolated_account_or_wallet": True,
        "kill_switch_armed": True,
        "no_borrowing": True,
        "no_leverage": True,
    }


def infrastructure():
    return {
        "status": "HEALTHY",
        "critical_services_healthy": True,
        "unresolved_critical_incidents": 0,
        "revalidated_for_canary": True,
        "checked_at": "2026-09-09T14:00:00+00:00",
    }


def authorization():
    return {
        "human_authorized": True,
        "authorization_id": "canary-001",
        "authorized_at": "2026-09-09T14:01:00+00:00",
        "authorized_notional_usd": 20.0,
        "policy_version": "release-v1",
    }


def test_pass_marks_only_execution_eligibility_not_live_authority():
    result = evaluate_isolated_canary_authorization(
        release_gate(), controls(), infrastructure(), authorization()
    )
    assert result["status"] == "OBSERVED"
    assert result["canary_authorization_result"] == "PASS"
    assert result["canary_execution_eligible"] is True
    assert result["canary_notional_usd"] == 20.0
    assert result["maximum_canary_notional_usd"] == MAX_CANARY_NOTIONAL_USD
    assert result["live_execution"] is False
    assert result["trading_authority"] is False
    assert result["order_submission_allowed"] is False
    assert result["transaction_signing_allowed"] is False
    assert result["rpc_contact_allowed"] is False


def test_release_gate_not_passed_is_observed_block():
    gate = release_gate()
    gate["release_gate_result"] = "BLOCKED"
    gate["eligible_for_isolated_canary_review"] = False
    result = evaluate_isolated_canary_authorization(
        gate, controls(), infrastructure(), authorization()
    )
    assert result["status"] == "OBSERVED"
    assert result["canary_authorization_result"] == "BLOCKED"
    assert "release_gate_not_passed" in result["blockers"]


def test_notional_above_20_is_blocked():
    cfg = controls()
    cfg["canary_notional_usd"] = 20.01
    result = evaluate_isolated_canary_authorization(
        release_gate(), cfg, infrastructure(), authorization()
    )
    assert result["canary_authorization_result"] == "BLOCKED"
    assert "canary_notional_exceeds_20_usd" in result["blockers"]


def test_loss_cap_must_not_exceed_notional():
    cfg = controls()
    cfg["max_loss_usd"] = 21.0
    result = evaluate_isolated_canary_authorization(
        release_gate(), cfg, infrastructure(), authorization()
    )
    assert "loss_cap_exceeds_canary_notional" in result["blockers"]


def test_kill_switch_and_isolation_are_required():
    cfg = controls()
    cfg["kill_switch_armed"] = False
    cfg["isolated_funds"] = False
    cfg["isolated_account_or_wallet"] = False
    result = evaluate_isolated_canary_authorization(
        release_gate(), cfg, infrastructure(), authorization()
    )
    assert result["canary_authorization_result"] == "BLOCKED"
    assert "kill_switch_not_armed" in result["blockers"]
    assert "funds_not_isolated" in result["blockers"]
    assert "account_or_wallet_not_isolated" in result["blockers"]


def test_single_position_no_borrowing_no_leverage_are_required():
    cfg = controls()
    cfg["max_open_positions"] = 2
    cfg["no_borrowing"] = False
    cfg["no_leverage"] = False
    result = evaluate_isolated_canary_authorization(
        release_gate(), cfg, infrastructure(), authorization()
    )
    assert "single_position_isolation_required" in result["blockers"]
    assert "borrowing_not_prohibited" in result["blockers"]
    assert "leverage_not_prohibited" in result["blockers"]


def test_infrastructure_must_be_revalidated_and_healthy():
    infra = infrastructure()
    infra["critical_services_healthy"] = False
    infra["unresolved_critical_incidents"] = 1
    result = evaluate_isolated_canary_authorization(
        release_gate(), controls(), infra, authorization()
    )
    assert result["canary_authorization_result"] == "BLOCKED"
    assert "critical_services_unhealthy" in result["blockers"]
    assert "unresolved_critical_incidents" in result["blockers"]


def test_missing_revalidation_evidence_fails_closed_unknown():
    infra = infrastructure()
    infra.pop("checked_at")
    result = evaluate_isolated_canary_authorization(
        release_gate(), controls(), infra, authorization()
    )
    assert result["status"] == "UNKNOWN"
    assert "canary_infrastructure_checked_at" in result["missing"]


def test_human_authorization_and_matching_policy_are_required():
    auth = authorization()
    auth["human_authorized"] = False
    auth["policy_version"] = "other"
    result = evaluate_isolated_canary_authorization(
        release_gate(), controls(), infrastructure(), auth
    )
    assert result["canary_authorization_result"] == "BLOCKED"
    assert "human_authorization_missing" in result["blockers"]
    assert "authorization_policy_version_mismatch" in result["blockers"]


def test_authorized_notional_caps_requested_notional():
    auth = authorization()
    auth["authorized_notional_usd"] = 10.0
    result = evaluate_isolated_canary_authorization(
        release_gate(), controls(), infrastructure(), auth
    )
    assert result["canary_authorization_result"] == "BLOCKED"
    assert "requested_notional_exceeds_authorized_notional" in result["blockers"]


def test_authority_contamination_fails_closed_unknown():
    gate = release_gate()
    gate["trading_authority"] = True
    result = evaluate_isolated_canary_authorization(
        gate, controls(), infrastructure(), authorization()
    )
    assert result["status"] == "UNKNOWN"
    assert result["canary_execution_eligible"] is False
    assert "non_authoritative_canary_evidence" in result["missing"]


def test_evidence_is_deep_copied():
    gate = release_gate()
    cfg = controls()
    infra = infrastructure()
    auth = authorization()
    result = evaluate_isolated_canary_authorization(gate, cfg, infra, auth)
    before = deepcopy(result["evidence"])
    gate["release_gate_result"] = "BLOCKED"
    cfg["canary_notional_usd"] = 999
    infra["critical_services_healthy"] = False
    auth["human_authorized"] = False
    assert result["evidence"] == before
