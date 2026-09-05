import pytest
from uuid import uuid4

from stinky_api import investigation_entity_network as adapter
from stinky_api.investigation_entity_network import entity_network_for_investigation


class ExplodingSession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("database should not be queried without an entity id or creator wallet")


@pytest.mark.asyncio
async def test_unknown_investigation_entity_is_explicit_and_bounded():
    result = await entity_network_for_investigation(
        ExplodingSession(),
        wallet_limit=0,
        relationship_limit=999,
    )

    assert result["status"] == "NEW-UNKNOWN"
    assert result["evidence_only"] is True
    assert result["missing"] == ["entity_history"]
    assert result["funding_history"] == []
    assert result["historical_analogues"]["status"] == "NEW-UNKNOWN"
    assert result["historical_outcome_comparison"]["status"] == "NEW-UNKNOWN"
    assert result["bounded"] == {
        "wallet_limit": 1,
        "relationship_limit": 500,
        "funding_observation_limit": 500,
        "analogue_limit": 10,
        "analogue_candidate_limit": 500,
        "outcome_launch_limit_per_analogue": 20,
    }


@pytest.mark.asyncio
async def test_invalid_entity_id_falls_back_to_creator_wallet():
    class Session:
        def __init__(self):
            self.queried = False

        async def execute(self, *args, **kwargs):
            self.queried = True
            class Result:
                def first(self):
                    return None
            return Result()

    session = Session()
    result = await entity_network_for_investigation(
        session,
        entity_id="not-a-uuid",
        creator_wallet="creator-wallet",
    )

    assert session.queried is True
    assert result["status"] == "NEW-UNKNOWN"
    assert result["evidence_only"] is True


@pytest.mark.asyncio
async def test_known_entity_includes_historical_outcomes(monkeypatch):
    entity_id = uuid4()

    class Session:
        async def execute(self, *args, **kwargs):
            class Result:
                def first(self):
                    return (entity_id,)
            return Result()

    async def fake_assemble(*args):
        return {
            "entity": {"entity_id": str(entity_id)},
            "wallets": [],
            "relationships": [],
            "bounded": {"wallet_limit": 10, "relationship_limit": 20},
            "evidence_only": True,
        }

    async def fake_funding(*args, **kwargs):
        return [{"signature": "sig-1", "amount_lamports": 42}]

    async def fake_history(*args, **kwargs):
        return {"status": "KNOWN_ENTITY", "sources": {}, "evidence_only": True}

    async def fake_analogues(*args, **kwargs):
        return {
            "status": "OBSERVED",
            "records": [{"entity_id": str(uuid4()), "similarity_distance": 0.0}],
            "evidence_basis": "entity_behavior_fingerprints",
            "bounded": {"limit": 10, "candidate_limit": 500},
            "evidence_only": True,
        }

    async def fake_outcomes(*args, **kwargs):
        assert kwargs["limit_per_entity"] == 20
        return {
            "status": "OBSERVED",
            "records": [{
                "entity_id": "analogue-1",
                "launch_count_observed": 2,
                "outcomes_known": 1,
                "completed_count": 1,
                "outcomes_unknown": 1,
                "evidence_basis": "entity_launches",
            }],
            "evidence_basis": "entity_launches",
            "bounded": {"limit_per_entity": 20},
            "evidence_only": True,
        }

    monkeypatch.setattr(adapter, "_assemble", fake_assemble)
    monkeypatch.setattr(adapter, "funding_history_for_entity", fake_funding)
    monkeypatch.setattr(adapter, "synthesize_entity_history", fake_history)
    monkeypatch.setattr(adapter, "find_historical_analogues", fake_analogues)
    monkeypatch.setattr(adapter, "historical_outcomes_for_analogues", fake_outcomes)

    result = await entity_network_for_investigation(
        Session(),
        creator_wallet="creator-wallet",
        wallet_limit=10,
        relationship_limit=20,
    )

    assert result["status"] == "KNOWN_ENTITY"
    assert result["evidence_only"] is True
    assert result["historical_outcome_comparison"]["status"] == "OBSERVED"
    assert result["historical_outcome_comparison"]["records"][0]["completed_count"] == 1
    assert result["historical_outcome_comparison"]["records"][0]["outcomes_unknown"] == 1
    assert result["bounded"]["outcome_launch_limit_per_analogue"] == 20
    assert result["historical_outcome_comparison"]["evidence_only"] is True
