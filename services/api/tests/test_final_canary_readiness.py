from copy import deepcopy

from stinky_api.final_canary_readiness import evaluate_final_canary_readiness


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


def authorization():
    return {
        "status": "OBSERVED",
        "canary_authorization_result": "PASS",
        "canary_execution_eligible": True,
        "canary_notional_usd": 20.0,
        "maximum_canary_notional_usd": 20.0,
        "max_loss_usd": 5.0,
        "max_open_positions": 1,
        "kill_switch_armed": True,
        "isolated_funds": True,
        "isolated_account_or_wallet": True,
        "human_authorized": True,
        "authorization_id": "auth-final-review",
        "authorized_at": "2026-09-10T03:10:00+00:00",
        "policy_version": "release-v1",
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
        "order_submission_allowed": False,
        "transaction_signing_allowed": False,
        "rpc_contact_allowed": False,
        "automatic_canary_activation": False,
    }


def verification():
    return {
        "status": "OBSERVED",
        "policy_version": "release-v1",
        "tested_main_sha": "5b53c8cae71ca43b9a3cc5f1f46ba48812f69e84",
        "proof_source": "github-actions-and-real-postgres-integration-suite",
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
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
        "rpc_contacted": False,
        "transaction_signed": False,
        "order_submitted": False,
        "wallet_mutated": False,
    }


def infrastructure():
    return {
        "status": "HEALTHY",
        "critical_services_healthy": True,
        "unresolved_critical_incidents": 0,
        "revalidated_for_canary": True,
        "checked_at": "2026-09-10T03:10:30+00:00",
    }


def safety():
    return {
        "status": "OBSERVED",
        "safety_checks_complete": True,
        "unresolved_safety_failures": [],
    }


def evaluate(**overrides):
    values = {
        "release_gate": release_gate(),
        "canary_authorization": authorization(),
        "verification": verification(),
        "infrastructure": infrastructure(),
        "safety": safety(),
    }
    values.update(overrides)
    return evaluate_final_canary_readiness(**values, policy_version="release-v1")


def test_all_proofs_pass_only_unlocks_live_executor_review():
    result = evaluate()
    assert result["status"] == "OBSERVED"
    assert result["operational_readiness_result"] == "PASS"
    assert result["eligible_for_live_executor_review"] is True
    assert result["live_canary_unlocked"] is False
    assert result["live_executor_implemented"] is False
    assert result["live_execution"] is False
    assert result["rpc_contact_allowed"] is False
    assert result["transaction_signing_allowed"] is False
    assert result["order_submission_allowed"] is False
    assert result["automatic_execution"] is False


def test_missing_verification_field_is_unknown_not_pass():
    proof = verification()
    proof.pop("rollback_before_commit_verified")
    result = evaluate(verification=proof)
    assert result["operational_readiness_result"] == "UNKNOWN"
    assert result["eligible_for_live_executor_review"] is False
    assert "rollback_before_commit_verified" in result["missing"]


def test_explicit_failed_verification_is_blocked():
    proof = verification()
    proof["real_postgres_concurrency_verified"] = False
    result = evaluate(verification=proof)
    assert result["operational_readiness_result"] == "BLOCKED"
    assert "real_postgres_concurrency_verified" in result["blockers"]


def test_paper_walk_forward_integration_is_mandatory():
    proof = verification()
    proof["paper_walk_forward_integration_verified"] = False
    result = evaluate(verification=proof)
    assert result["operational_readiness_result"] == "BLOCKED"
    assert "paper_walk_forward_integration_verified" in result["blockers"]


def test_policy_versions_must_match_every_evidence_family():
    proof = verification()
    proof["policy_version"] = "old-v1"
    result = evaluate(verification=proof)
    assert result["operational_readiness_result"] == "BLOCKED"
    assert "policy_version_mismatch" in result["blockers"]


def test_authority_contamination_fails_unknown():
    proof = verification()
    proof["order_submitted"] = True
    result = evaluate(verification=proof)
    assert result["operational_readiness_result"] == "UNKNOWN"
    assert "non_authoritative_operational_evidence" in result["missing"]
    assert "verification" in result["authority_contamination"]


def test_canary_notional_remains_hard_capped_at_20_usd():
    auth = authorization()
    auth["canary_notional_usd"] = 20.01
    result = evaluate(canary_authorization=auth)
    assert result["operational_readiness_result"] == "BLOCKED"
    assert "canary_notional_exceeds_20_usd" in result["blockers"]


def test_loss_cap_cannot_exceed_canary_notional():
    auth = authorization()
    auth["max_loss_usd"] = 20.01
    result = evaluate(canary_authorization=auth)
    assert result["operational_readiness_result"] == "BLOCKED"
    assert "loss_cap_exceeds_canary_notional" in result["blockers"]


def test_kill_switch_and_isolation_remain_required():
    auth = authorization()
    auth["kill_switch_armed"] = False
    auth["isolated_funds"] = False
    result = evaluate(canary_authorization=auth)
    assert result["operational_readiness_result"] == "BLOCKED"
    assert "kill_switch_armed_required" in result["blockers"]
    assert "isolated_funds_required" in result["blockers"]


def test_unhealthy_infrastructure_blocks_review():
    infra = infrastructure()
    infra["critical_services_healthy"] = False
    infra["unresolved_critical_incidents"] = 1
    result = evaluate(infrastructure=infra)
    assert result["operational_readiness_result"] == "BLOCKED"
    assert "critical_services_unhealthy" in result["blockers"]
    assert "unresolved_critical_incidents" in result["blockers"]


def test_unresolved_safety_failure_blocks_review():
    evidence = safety()
    evidence["unresolved_safety_failures"] = ["example-critical-failure"]
    result = evaluate(safety=evidence)
    assert result["operational_readiness_result"] == "BLOCKED"
    assert "unresolved_safety_failures" in result["blockers"]


def test_inputs_are_frozen_in_pass_evidence():
    proof = verification()
    original = deepcopy(proof)
    result = evaluate(verification=proof)
    proof["real_postgres_concurrency_verified"] = False
    assert result["evidence"]["verification"] == original
