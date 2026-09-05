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
    assert result["bounded"] == {
        "wallet_limit": 1,
        "relationship_limit": 500,
        "funding_observation_limit": 500,
        "analogue_limit": 10,
        "analogue_candidate_limit": 500,
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
async def test_known_entity_includes_bounded_funding_history(monkeypatch):
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
        assert kwargs["wallet_limit"] == 10
        assert kwargs["observation_limit"] == 20
        return [{
            "source_wallet": "SOURCE",
            "destination_wallet": "DESTINATION",
            "amount_lamports": 42,
            "signature": "sig-1",
            "observed_at": "2026-09-04T00:00:00+00:00",
            "evidence": {"evidence_basis": "direct_transfer_observation"},
        }]

    async def fake_history(*args, **kwargs):
        return {"status": "KNOWN_ENTITY", "sources": {}, "evidence_only": True}

    async def fake_analogues(*args, **kwargs):
        assert kwargs["limit"] == 10
        assert kwargs["candidate_limit"] == 500
        return {
            "status": "OBSERVED",
            "records": [{
                "entity_id": "analogue-1",
                "similarity_distance": 0.0,
                "matched_dimension_count": 5,
                "matched_dimensions": ["launch_count"],
                "candidate_fingerprint_computed_at": "2026-09-04T00:00:00+00:00",
                "evidence_basis": "entity_behavior_fingerprints",
            }],
            "evidence_basis": "entity_behavior_fingerprints",
            "bounded": {"limit": 10, "candidate_limit": 500},
            "evidence_only": True,
        }

    monkeypatch.setattr(adapter, "_assemble", fake_assemble)
    monkeypatch.setattr(adapter, "funding_history_for_entity", fake_funding)
    monkeypatch.setattr(adapter, "synthesize_entity_history", fake_history)
    monkeypatch.setattr(adapter, "find_historical_analogues", fake_analogues)

    result = await entity_network_for_investigation(
        Session(),
        creator_wallet="creator-wallet",
        wallet_limit=10,
        relationship_limit=20,
    )

    assert result["status"] == "KNOWN_ENTITY"
    assert result["evidence_only"] is True
    assert result["funding_history"][0]["signature"] == "sig-1"
    assert result["funding_history"][0]["amount_lamports"] == 42
    assert result["bounded"]["funding_observation_limit"] == 20
    assert result["historical_analogues"]["status"] == "OBSERVED"
    assert result["historical_analogues"]["records"][0]["entity_id"] == "analogue-1"
    assert result["bounded"]["analogue_limit"] == 10
    assert result["bounded"]["analogue_candidate_limit"] == 500
    assert result["historical_analogues"]["evidence_only"] is True
