from __future__ import annotations

import pytest

from stinky_api.developer_correlation_audit import persist_developer_correlation_snapshot
from stinky_api.developer_longitudinal_audit import persist_developer_snapshot


ENTITY_ID = "11111111-1111-1111-1111-111111111111"


class _Session:
    """Minimal session that models PostgreSQL's aborted-transaction behavior."""

    def __init__(self, *, fail_attempts: int = 1):
        self.fail_attempts = fail_attempts
        self.execute_calls = 0
        self.rollback_calls = 0
        self.insert_calls = 0

    async def execute(self, statement, params=None):
        self.execute_calls += 1
        sql = str(statement)
        if self.fail_attempts:
            self.fail_attempts -= 1
            raise RuntimeError("current transaction is aborted")
        if "INSERT INTO" in sql:
            self.insert_calls += 1
        return None

    async def rollback(self):
        self.rollback_calls += 1


def _developer_evidence():
    return {
        "status": "OBSERVED",
        "entity_id": ENTITY_ID,
        "reference_mint": "mint-1",
        "history_state": "NEW-UNKNOWN",
        "fresh_entity_interpretation": "NEW-UNKNOWN",
        "launch_history": {"historical_launch_count": 0, "records": [], "outcome_counts": {}},
        "associated_wallets": {"count": 1, "records": [{"wallet": "wallet-1"}]},
        "funding_relationships": {"observation_count": 0, "counterparties": []},
        "recurring_early_buyers": {"status": "NOT_APPLICABLE", "count": 0, "records": []},
        "missing": ["prior_developer_launch_history"],
        "risk_inferred": False,
        "quality_inferred": False,
        "predictive_authority": False,
        "trade_signal": False,
        "evidence_only": True,
    }


def _correlation_evidence():
    return {
        "status": "UNKNOWN",
        "entity_id": ENTITY_ID,
        "wallets": ["wallet-1"],
        "shared_funders": [],
        "cross_entity_wallet_reuse": [],
        "deployer_buyer_recurrence": [],
        "shared_relationship_structures": [],
        "missing": ["cross_entity_wallet_reuse"],
        "ownership_inferred": False,
        "coordination_inferred": False,
        "intent_inferred": False,
        "risk_inferred": False,
        "quality_inferred": False,
        "predictive_authority": False,
        "trade_signal": False,
        "evidence_only": True,
    }


@pytest.mark.asyncio
async def test_developer_snapshot_recovers_from_poisoned_read_transaction():
    session = _Session(fail_attempts=1)
    digest = await persist_developer_snapshot(session, _developer_evidence())

    assert digest
    assert session.rollback_calls == 1
    assert session.insert_calls == 1


@pytest.mark.asyncio
async def test_correlation_snapshot_recovers_from_poisoned_read_transaction_and_preserves_unknown():
    session = _Session(fail_attempts=1)
    evidence = _correlation_evidence()
    digest = await persist_developer_correlation_snapshot(session, evidence)

    assert digest
    assert evidence["status"] == "UNKNOWN"
    assert session.rollback_calls == 1
    assert session.insert_calls == 1
    assert evidence["ownership_inferred"] is False
    assert evidence["coordination_inferred"] is False
    assert evidence["risk_inferred"] is False
    assert evidence["quality_inferred"] is False
    assert evidence["predictive_authority"] is False
    assert evidence["trade_signal"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("persist", "evidence"),
    [
        (persist_developer_snapshot, _developer_evidence),
        (persist_developer_correlation_snapshot, _correlation_evidence),
    ],
)
async def test_snapshot_retry_failure_leaves_session_reusable_and_propagates(persist, evidence):
    session = _Session(fail_attempts=2)

    with pytest.raises(RuntimeError, match="transaction is aborted"):
        await persist(session, evidence())

    assert session.rollback_calls == 2
    assert session.insert_calls == 0
