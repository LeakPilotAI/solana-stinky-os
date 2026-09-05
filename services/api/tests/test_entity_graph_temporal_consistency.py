from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stinky_api.entity_graph import _assemble


class Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows


class Session:
    def __init__(self, entity, wallets, relationships):
        self.results = [Result(row=entity), Result(rows=wallets), Result(rows=relationships)]

    async def execute(self, *args, **kwargs):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_as_of_does_not_expose_future_entity_counters_or_relationship_counts():
    cutoff = datetime(2026, 9, 4, tzinfo=timezone.utc)
    future = datetime(2026, 9, 5, tzinfo=timezone.utc)
    entity_id = uuid4()
    session = Session(
        {
            "entity_id": str(entity_id), "entity_type": "deployer", "display_label": None,
            "primary_wallet": "DEPLOYER", "wallet_count": 9, "launch_count": 12,
            "early_buy_count": 7, "confidence": 1.0, "created_at": cutoff,
            "updated_at": future, "meta": {},
        },
        [{
            "wallet": "DEPLOYER", "entity_id": str(entity_id), "role": "deployer",
            "link_reason": "observed", "confidence": 1.0, "first_seen_at": cutoff,
            "last_seen_at": future, "evidence": {"basis": "direct"},
        }],
        [{
            "wallet_a": "DEPLOYER", "wallet_b": "BUYER", "relationship_kind": "deployer_buyer_association",
            "observation_count": 9, "first_seen_at": cutoff, "last_seen_at": future,
            "confidence": 1.0, "evidence": {"basis": "entity_launches+migration_buyers"},
            "entity_a_id": str(entity_id), "entity_b_id": "other",
        }],
    )

    result = await _assemble(session, entity_id, 10, 10, as_of=cutoff)

    assert result["entity"]["launch_count"] is None
    assert result["entity"]["wallet_count"] is None
    assert result["entity"]["early_buy_count"] is None
    assert result["entity"]["historical_aggregate_status"] == "UNKNOWN"
    assert result["wallets"][0]["last_seen_at"] is None
    assert result["wallets"][0]["historical_last_seen_status"] == "UNKNOWN"
    assert result["relationships"][0]["observation_count"] is None
    assert result["relationships"][0]["last_seen_at"] is None
    assert result["relationships"][0]["historical_observation_status"] == "UNKNOWN"
    assert result["temporal_cutoff_enforced"] is True


@pytest.mark.asyncio
async def test_entity_created_after_cutoff_is_not_projected_into_history():
    cutoff = datetime(2026, 9, 4, tzinfo=timezone.utc)
    entity_id = uuid4()
    session = Session(
        {
            "entity_id": str(entity_id), "entity_type": "deployer", "display_label": None,
            "primary_wallet": "DEPLOYER", "wallet_count": 1, "launch_count": 1,
            "early_buy_count": 0, "confidence": 1.0,
            "created_at": datetime(2026, 9, 5, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 9, 5, tzinfo=timezone.utc), "meta": {},
        },
        [], [],
    )

    assert await _assemble(session, entity_id, 10, 10, as_of=cutoff) is None
