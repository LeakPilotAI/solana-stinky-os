from copy import deepcopy
from pathlib import Path

import pytest

from stinky_api.dry_run_execution_persistence import persist_dry_run_canary_execution


class _Mappings:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Result:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return _Mappings(self._row)


class _FakeSession:
    def __init__(self, *, cas_row=None, fail_audit=False):
        self.cas_row = cas_row
        self.fail_audit = fail_audit
        self.calls = []
        self.commit_calls = 0
        self.rollback_calls = 0

    async def execute(self, statement, params):
        self.calls.append((str(statement), deepcopy(params)))
        if len(self.calls) == 1:
            return _Result(self.cas_row)
        if self.fail_audit:
            raise RuntimeError("audit insert failed")
        return _Result()

    async def commit(self):
        self.commit_calls += 1

    async def rollback(self):
        self.rollback_calls += 1


def _prepared():
    return {
        "status": "OBSERVED",
        "adapter_result": "DRY_RUN_READY",
        "dry_run_ready": True,
        "authorization_transition_prepared": True,
        "authorization_id": "auth-1",
        "attempt_id": "attempt-1",
        "policy_version": "v1",
        "requested_notional_usd": 20.0,
        "maximum_canary_notional_usd": 20.0,
        "max_loss_usd": 5.0,
        "idempotency_key": "idem-1",
        "authorization_transition": {
            "operation": "COMPARE_AND_SWAP_AUTHORIZATION_CONSUMPTION",
            "authorization_id": "auth-1",
            "expected": {"consumed": False, "use_count": 0, "version": 7},
            "proposed": {
                "consumed": True,
                "use_count": 1,
                "version": 8,
                "consumed_by_attempt_id": "attempt-1",
                "consumed_at": "2026-09-10T01:35:00+00:00",
                "idempotency_key": "idem-1",
            },
            "must_be_atomic_before_external_side_effect": True,
            "applied": False,
        },
        "post_order_audit_record": {
            "event": "CANARY_EXECUTION_ADAPTER_DRY_RUN_PREPARED",
            "attempt_id": "attempt-1",
            "authorization_id": "auth-1",
            "policy_version": "v1",
            "requested_at": "2026-09-10T01:35:00+00:00",
            "requested_notional_usd": 20.0,
            "max_loss_usd": 5.0,
            "adapter_mode": "DRY_RUN",
            "idempotency_key": "idem-1",
            "external_side_effects": False,
            "rpc_contacted": False,
            "transaction_signed": False,
            "order_submitted": False,
            "authorization_transition_applied": False,
        },
        "adapter_mode": "DRY_RUN",
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
        "rpc_contacted": False,
        "transaction_signed": False,
        "order_submitted": False,
        "wallet_mutated": False,
        "persistence_mutated": False,
        "automatic_execution": False,
    }


def _cas_row():
    return {
        "authorization_id": "auth-1",
        "policy_version": "v1",
        "consumed": True,
        "use_count": 1,
        "version": 8,
    }


@pytest.mark.asyncio
async def test_success_stages_exact_cas_then_immutable_audit_without_external_effects():
    session = _FakeSession(cas_row=_cas_row())
    result = await persist_dry_run_canary_execution(session, _prepared())

    assert result["persistence_result"] == "TRANSACTION_STAGED"
    assert result["authorization_consumed_in_transaction"] is True
    assert result["audit_inserted_in_transaction"] is True
    assert result["authorization_version_before"] == 7
    assert result["authorization_version_after"] == 8
    assert result["live_execution"] is False
    assert result["rpc_contacted"] is False
    assert result["transaction_signed"] is False
    assert result["order_submitted"] is False
    assert len(session.calls) == 2

    cas_sql, cas_params = session.calls[0]
    assert "UPDATE canary_authorization_state" in cas_sql
    assert "consumed = FALSE" in cas_sql
    assert "use_count = 0" in cas_sql
    assert "version = :expected_version" in cas_sql
    assert cas_params["expected_version"] == 7
    assert cas_params["proposed_version"] == 8

    audit_sql, audit_params = session.calls[1]
    assert "INSERT INTO dry_run_execution_audit" in audit_sql
    assert audit_params["attempt_id"] == "attempt-1"
    assert audit_params["idempotency_key"] == "idem-1"
    assert '"authorization_transition_applied":true' in audit_params["audit_payload"]
    assert '"external_side_effects":false' in audit_params["audit_payload"]


@pytest.mark.asyncio
async def test_failed_cas_blocks_replay_and_does_not_insert_audit():
    session = _FakeSession(cas_row=None)
    result = await persist_dry_run_canary_execution(session, _prepared())

    assert result["persistence_result"] == "BLOCKED"
    assert "authorization_compare_and_swap_failed" in result["blockers"]
    assert result["authorization_consumed_in_transaction"] is False
    assert result["audit_inserted_in_transaction"] is False
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_persistence_function_never_commits_or_rolls_back_outer_transaction():
    session = _FakeSession(cas_row=_cas_row())
    await persist_dry_run_canary_execution(session, _prepared())
    assert session.commit_calls == 0
    assert session.rollback_calls == 0


@pytest.mark.asyncio
async def test_audit_insert_failure_propagates_for_outer_transaction_rollback():
    session = _FakeSession(cas_row=_cas_row(), fail_audit=True)
    with pytest.raises(RuntimeError, match="audit insert failed"):
        await persist_dry_run_canary_execution(session, _prepared())
    assert len(session.calls) == 2
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_prepared_transition_must_be_unapplied():
    prepared = _prepared()
    prepared["authorization_transition"]["applied"] = True
    session = _FakeSession(cas_row=_cas_row())
    result = await persist_dry_run_canary_execution(session, prepared)
    assert result["persistence_result"] == "BLOCKED"
    assert "transition_must_be_unapplied_before_persistence" in result["blockers"]
    assert session.calls == []


@pytest.mark.asyncio
async def test_single_use_transition_shape_is_required():
    prepared = _prepared()
    prepared["authorization_transition"]["proposed"]["use_count"] = 2
    session = _FakeSession(cas_row=_cas_row())
    result = await persist_dry_run_canary_execution(session, prepared)
    assert "invalid_proposed_single_use_state" in result["blockers"]
    assert session.calls == []


@pytest.mark.asyncio
async def test_exact_version_increment_is_required():
    prepared = _prepared()
    prepared["authorization_transition"]["proposed"]["version"] = 9
    session = _FakeSession(cas_row=_cas_row())
    result = await persist_dry_run_canary_execution(session, prepared)
    assert "invalid_version_increment" in result["blockers"]
    assert session.calls == []


@pytest.mark.asyncio
async def test_attempt_and_idempotency_must_match_transition_and_audit():
    prepared = _prepared()
    prepared["authorization_transition"]["proposed"]["idempotency_key"] = "other"
    prepared["post_order_audit_record"]["attempt_id"] = "other-attempt"
    session = _FakeSession(cas_row=_cas_row())
    result = await persist_dry_run_canary_execution(session, prepared)
    assert "transition_idempotency_key_mismatch" in result["blockers"]
    assert "audit_identity_mismatch" in result["blockers"]
    assert session.calls == []


@pytest.mark.asyncio
async def test_external_execution_contamination_fails_closed_unknown():
    prepared = _prepared()
    prepared["order_submitted"] = True
    session = _FakeSession(cas_row=_cas_row())
    result = await persist_dry_run_canary_execution(session, prepared)
    assert result["status"] == "UNKNOWN"
    assert "non_executing_dry_run_prepared_evidence" in result["missing"]
    assert session.calls == []


@pytest.mark.asyncio
async def test_roadmap_20_dollar_cap_remains_enforced():
    prepared = _prepared()
    prepared["requested_notional_usd"] = 20.01
    session = _FakeSession(cas_row=_cas_row())
    result = await persist_dry_run_canary_execution(session, prepared)
    assert "requested_notional_exceeds_20_usd" in result["blockers"]
    assert session.calls == []


@pytest.mark.asyncio
async def test_returned_prepared_evidence_is_mutation_isolated():
    prepared = _prepared()
    session = _FakeSession(cas_row=_cas_row())
    result = await persist_dry_run_canary_execution(session, prepared)
    prepared["authorization_id"] = "mutated"
    assert result["prepared_evidence"]["authorization_id"] == "auth-1"


def test_migration_enforces_single_use_replay_protection_and_immutable_audit():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "002_dry_run_execution_persistence.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS canary_authorization_state" in migration
    assert "CREATE TABLE IF NOT EXISTS dry_run_execution_audit" in migration
    assert "canary_authorization_single_use_state" in migration
    assert "idempotency_key                 TEXT NOT NULL UNIQUE" in migration
    assert "dry_run_notional_max_20" in migration
    assert "dry_run_no_external_side_effects" in migration
    assert "BEFORE UPDATE OR DELETE ON dry_run_execution_audit" in migration
    assert "reject_dry_run_execution_audit_mutation" in migration
