from datetime import datetime, timezone

import pytest

from stinky_api.developer_correlation_audit import persist_developer_correlation_snapshot


class _Result:
    pass


class _Session:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_correlation_snapshot_uses_one_authoritative_utc_timestamp_for_observed_and_ingested():
    session = _Session()
    explicit = datetime(2026, 9, 8, 2, 30, 0)
    evidence = {
        "entity_id": "00000000-0000-0000-0000-000000000001",
        "status": "OBSERVED",
        "wallets": ["WalletA"],
        "shared_funders": [],
        "cross_entity_wallet_reuse": [],
        "deployer_buyer_recurrence": [],
        "shared_relationship_structures": [],
        "missing": [],
    }

    digest = await persist_developer_correlation_snapshot(
        session,
        evidence,
        observed_at=explicit,
    )

    assert digest
    insert_calls = [
        (sql, params)
        for sql, params in session.calls
        if "INSERT INTO developer_correlation_snapshots" in sql
    ]
    assert len(insert_calls) == 1
    params = insert_calls[0][1]
    assert params["observed_at"] == params["ingested_at"]
    assert params["observed_at"].tzinfo == timezone.utc
    assert params["observed_at"] == explicit.replace(tzinfo=timezone.utc)
    assert session.commits == 1
    assert session.rollbacks == 0
