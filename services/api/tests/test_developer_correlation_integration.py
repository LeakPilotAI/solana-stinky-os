from datetime import datetime, timezone
from uuid import uuid4

import pytest

from stinky_api import investigation_entity_network
from stinky_api.entity_graph import developer_correlation_for_entity
from stinky_api.investigation_entity_network import entity_network_for_investigation


class ExplodingSession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("database should not be queried without an entity")


@pytest.mark.asyncio
async def test_unknown_investigation_exposes_nonconclusive_correlation():
    result = await entity_network_for_investigation(ExplodingSession(), relationship_limit=999)
    correlation = result["developer_identity_correlation"]
    assert correlation["status"] == "NEW-UNKNOWN"
    assert correlation["shared_funders"] == []
    assert correlation["cross_entity_wallet_reuse"] == []
    assert correlation["deployer_buyer_recurrence"] == []
    assert correlation["shared_relationship_structures"] == []
    assert correlation["ownership_inferred"] is False
    assert correlation["coordination_inferred"] is False
    assert correlation["intent_inferred"] is False
    assert correlation["risk_inferred"] is False
    assert correlation["quality_inferred"] is False
    assert correlation["predictive_authority"] is False
    assert correlation["trade_signal"] is False
    assert correlation["bounded"]["limit"] == 500


@pytest.mark.asyncio
async def test_entity_correlation_route_reuses_canonical_investigation(monkeypatch):
    entity_id = uuid4()
    cutoff = datetime(2026, 9, 5, 20, 0, tzinfo=timezone.utc)
    captured = {}

    async def fake_network(session, **kwargs):
        captured.update(kwargs)
        return {
            "developer_identity_correlation": {
                "status": "OBSERVED",
                "entity_id": str(entity_id),
                "shared_funders": [{"other_entity_id": str(uuid4()), "relationship": "SHARED_FUNDER_OBSERVED"}],
                "cross_entity_wallet_reuse": [],
                "deployer_buyer_recurrence": [],
                "shared_relationship_structures": [],
                "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
                "ownership_inferred": False,
                "coordination_inferred": False,
                "intent_inferred": False,
                "risk_inferred": False,
                "quality_inferred": False,
                "predictive_authority": False,
                "trade_signal": False,
                "evidence_only": True,
            }
        }

    monkeypatch.setattr(investigation_entity_network, "entity_network_for_investigation", fake_network)
    result = await developer_correlation_for_entity(entity_id, object(), as_of=cutoff, limit=75)

    assert captured["entity_id"] == str(entity_id)
    assert captured["wallet_limit"] == 75
    assert captured["relationship_limit"] == 75
    assert captured["as_of"] == cutoff
    assert result["status"] == "OBSERVED"
    assert result["shared_funders"][0]["relationship"] == "SHARED_FUNDER_OBSERVED"
    assert result["ownership_inferred"] is False
    assert result["coordination_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
