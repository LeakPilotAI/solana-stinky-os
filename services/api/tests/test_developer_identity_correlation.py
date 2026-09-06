from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stinky_api.developer_identity_correlation import correlate_developer_identity


class Result:
    def __init__(self, rows=None):
        self._rows = rows or []
    def mappings(self): return self
    def all(self): return self._rows


class Session:
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []
    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return Result(self.batches.pop(0) if self.batches else [])


@pytest.mark.asyncio
async def test_correlation_preserves_observed_relationships_without_authority():
    entity_id = uuid4()
    ts = datetime(2026, 9, 5, tzinfo=timezone.utc)
    session = Session([
        [{"funder_wallet": "FUNDER", "other_entity_id": str(uuid4()), "observation_count": 2,
          "first_observed_at": ts, "last_observed_at": ts}],
        [{"wallet": "W1", "other_entity_id": str(uuid4()), "role": "deployer", "link_reason": "observed",
          "first_seen_at": ts, "last_seen_at": ts}],
        [{"wallet": "W1", "buyer_entity_id": str(uuid4()), "launch_count": 2, "best_rank": 3,
          "first_observed_at": ts, "last_observed_at": ts}],
        [{"relationship_kind": "shared_counterparty", "other_entity_id": str(uuid4()), "edge_count": 2, "observation_count": 4}],
    ])
    result = await correlate_developer_identity(
        session, entity_id, graph={"wallets": [{"wallet": "W1"}]}, as_of=ts, limit=999,
    )
    assert result["status"] == "OBSERVED"
    assert result["bounded"]["limit"] == 200
    assert result["shared_funders"][0]["relationship"] == "SHARED_FUNDER_OBSERVED"
    assert result["cross_entity_wallet_reuse"][0]["relationship"] == "WALLET_REUSE_OBSERVED"
    assert result["deployer_buyer_recurrence"][0]["coordination_inferred"] is False
    assert result["shared_relationship_structures"][0]["ownership_inferred"] is False
    assert result["ownership_inferred"] is False
    assert result["coordination_inferred"] is False
    assert result["intent_inferred"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["temporal_cutoff_enforced"] is True
    assert all(call[1].get("as_of") == ts for call in session.calls)


@pytest.mark.asyncio
async def test_no_wallets_stays_new_unknown_without_queries():
    session = Session([])
    result = await correlate_developer_identity(session, uuid4(), graph={"wallets": []})
    assert result["status"] == "NEW-UNKNOWN"
    assert result["missing"] == ["entity_wallets"]
    assert session.calls == []
    assert result["ownership_inferred"] is False
    assert result["coordination_inferred"] is False


@pytest.mark.asyncio
async def test_invalid_as_of_fails_closed_unknown():
    result = await correlate_developer_identity(Session([]), uuid4(), graph={"wallets": [{"wallet": "W"}]}, as_of="not-a-date")
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["valid_as_of"]
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


@pytest.mark.asyncio
async def test_query_failures_remain_missing_not_negative_evidence():
    class Broken:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("db")
    result = await correlate_developer_identity(Broken(), uuid4(), graph={"wallets": [{"wallet": "W"}]})
    assert result["status"] == "UNKNOWN"
    assert set(result["missing"]) == {
        "shared_funder_observations", "cross_entity_wallet_reuse",
        "deployer_early_buyer_recurrence", "shared_relationship_structures",
    }
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
