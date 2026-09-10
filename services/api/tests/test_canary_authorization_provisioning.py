from copy import deepcopy

import pytest

from stinky_api.canary_authorization_provisioning import provision_canary_authorization_state


def passed_authorization():
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
        "authorization_id": "auth-1",
        "authorized_at": "2026-09-09T20:00:00+00:00",
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


class _Mappings:
    def __init__(self, row): self.row = row
    def first(self): return self.row


class _Result:
    def __init__(self, row): self.row = row
    def mappings(self): return _Mappings(self.row)


class _Session:
    def __init__(self, first_row=True, fail_audit=False):
        self.calls = []
        self.first_row = first_row
        self.fail_audit = fail_audit
        self.commit_calls = 0
    async def execute(self, statement, params):
        self.calls.append((str(statement), deepcopy(params)))
        if len(self.calls) == 1:
            return _Result({"authorization_id": "auth-1"} if self.first_row else None)
        if self.fail_audit:
            raise RuntimeError("audit insert failed")
        return _Result(None)
    async def commit(self):
        self.commit_calls += 1


@pytest.mark.asyncio
async def test_passed_authorization_stages_state_and_immutable_audit_without_commit():
    session = _Session()
    result = await provision_canary_authorization_state(session, passed_authorization())
    assert result["provisioning_result"] == "TRANSACTION_STAGED"
    assert result["authorization_state_staged"] is True
    assert result["provision_audit_staged"] is True
    assert result["version"] == 0 and result["consumed"] is False and result["use_count"] == 0
    assert len(session.calls) == 2
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_duplicate_authorization_id_blocks_without_audit_insert():
    session = _Session(first_row=False)
    result = await provision_canary_authorization_state(session, passed_authorization())
    assert result["provisioning_result"] == "BLOCKED"
    assert "authorization_id_already_provisioned" in result["blockers"]
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_audit_failure_propagates_for_outer_transaction_rollback():
    session = _Session(fail_audit=True)
    with pytest.raises(RuntimeError, match="audit insert failed"):
        await provision_canary_authorization_state(session, passed_authorization())
    assert session.commit_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["status", "canary_authorization_result", "canary_execution_eligible", "human_authorized"])
async def test_non_pass_evidence_fails_closed(field):
    evidence = passed_authorization()
    evidence[field] = None
    result = await provision_canary_authorization_state(_Session(), evidence)
    assert result["provisioning_result"] == "UNKNOWN"
    assert result["authorization_state_staged"] is False


@pytest.mark.asyncio
async def test_execution_authority_contamination_fails_closed():
    evidence = passed_authorization()
    evidence["live_execution"] = True
    result = await provision_canary_authorization_state(_Session(), evidence)
    assert result["provisioning_result"] == "UNKNOWN"
    assert "non_authoritative_canary_authorization" in result["missing"]


@pytest.mark.asyncio
async def test_over_20_and_invalid_loss_cap_are_blocked():
    evidence = passed_authorization()
    evidence["canary_notional_usd"] = 20.01
    evidence["max_loss_usd"] = 21.0
    result = await provision_canary_authorization_state(_Session(), evidence)
    assert result["provisioning_result"] == "BLOCKED"
    assert "canary_notional_exceeds_20_usd" in result["blockers"]
    assert "loss_cap_exceeds_canary_notional" in result["blockers"]


@pytest.mark.asyncio
async def test_invalid_authorized_timestamp_fails_closed():
    evidence = passed_authorization()
    evidence["authorized_at"] = "not-a-time"
    result = await provision_canary_authorization_state(_Session(), evidence)
    assert result["provisioning_result"] == "UNKNOWN"
    assert "valid_authorized_at" in result["missing"]


@pytest.mark.asyncio
async def test_input_evidence_is_not_mutated():
    evidence = passed_authorization()
    original = deepcopy(evidence)
    await provision_canary_authorization_state(_Session(), evidence)
    assert evidence == original
