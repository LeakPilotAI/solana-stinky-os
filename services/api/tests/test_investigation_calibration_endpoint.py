import pytest

from stinky_api import investigation_entity_network
from stinky_api.entity_graph import investigation_calibration_evidence


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, *, entity_id=None, creator="creator-wallet"):
        self.calls = []
        self.entity_id = entity_id
        self.creator = creator

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "FROM entity_launches" in sql:
            return _Result((self.entity_id,) if self.entity_id else None)
        if "FROM migration_tracks" in sql:
            return _Result((self.creator,) if self.creator else None)
        return _Result(None)


@pytest.mark.asyncio
async def test_calibration_endpoint_resolves_creator_and_returns_compact_synthesis(monkeypatch):
    captured = {}

    async def fake_network(session, **kwargs):
        captured.update(kwargs)
        return {
            "market_pattern_calibration_synthesis": {
                "status": "OBSERVED",
                "pattern_hash": "p1",
                "evidence_status": "PARTIAL_EVIDENCE",
                "current_calibration_state": "STABLE",
                "predictive_authority": False,
                "trade_signal": False,
                "evidence_only": True,
            },
            "developer_identity_correlation": {
                "status": "OBSERVED",
                "entity_id": "entity-1",
                "shared_funders": [{"other_entity_id": "entity-2"}],
                "cross_entity_wallet_reuse": [],
                "deployer_buyer_recurrence": [],
                "shared_relationship_structures": [],
                "ownership_inferred": False,
                "coordination_inferred": False,
                "intent_inferred": False,
                "risk_inferred": False,
                "quality_inferred": False,
                "predictive_authority": False,
                "trade_signal": False,
                "evidence_only": True,
            },
            "history": {
                "sources": {
                    "developer_longitudinal": {
                        "status": "OBSERVED",
                        "entity_id": "entity-1",
                        "history_state": "KNOWN_HISTORY",
                        "launch_history": {"historical_launch_count": 3},
                        "associated_wallets": {"count": 2},
                        "funding_relationships": {"observation_count": 4},
                        "recurring_early_buyers": {"count": 1},
                        "risk_inferred": False,
                        "quality_inferred": False,
                        "predictive_authority": False,
                        "trade_signal": False,
                        "evidence_only": True,
                    }
                }
            },
        }

    monkeypatch.setattr(investigation_entity_network, "entity_network_for_investigation", fake_network)
    session = _Session()
    result = await investigation_calibration_evidence("mint-1", session)

    assert captured["creator_wallet"] == "creator-wallet"
    assert captured["entity_id"] is None
    assert captured["mint"] == "mint-1"
    assert captured["wallet_limit"] == 100
    assert captured["relationship_limit"] == 500
    assert result["mint"] == "mint-1"
    assert result["calibration"]["evidence_status"] == "PARTIAL_EVIDENCE"
    assert result["developer"]["history_state"] == "KNOWN_HISTORY"
    assert result["developer"]["launch_history"]["historical_launch_count"] == 3
    assert result["developer_correlation"]["status"] == "OBSERVED"
    assert result["developer_correlation"]["shared_funders"][0]["other_entity_id"] == "entity-2"
    assert result["developer_correlation"]["ownership_inferred"] is False
    assert result["developer_correlation"]["coordination_inferred"] is False
    assert result["developer"]["risk_inferred"] is False
    assert result["developer"]["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["evidence_only"] is True


@pytest.mark.asyncio
async def test_calibration_endpoint_prefers_persisted_migration_entity(monkeypatch):
    captured = {}
    persisted = []
    entity_id = "11111111-1111-1111-1111-111111111111"

    async def fake_network(session, **kwargs):
        captured.update(kwargs)
        return {
            "history": {
                "sources": {
                    "developer_longitudinal": {
                        "status": "NEW-UNKNOWN",
                        "entity_id": entity_id,
                        "history_state": "NEW-UNKNOWN",
                        "fresh_entity_interpretation": "NEW-UNKNOWN",
                        "missing": ["prior_launch_history"],
                        "risk_inferred": False,
                        "quality_inferred": False,
                        "predictive_authority": False,
                        "trade_signal": False,
                        "evidence_only": True,
                    }
                }
            },
            "developer_identity_correlation": {
                "status": "UNKNOWN",
                "entity_id": entity_id,
                "wallets": [],
                "shared_funders": [],
                "cross_entity_wallet_reuse": [],
                "deployer_buyer_recurrence": [],
                "shared_relationship_structures": [],
                "missing": ["correlation_evidence"],
                "ownership_inferred": False,
                "coordination_inferred": False,
                "intent_inferred": False,
                "risk_inferred": False,
                "quality_inferred": False,
                "predictive_authority": False,
                "trade_signal": False,
                "evidence_only": True,
            },
        }

    async def fake_persist_developer(session, evidence):
        persisted.append(("developer", evidence["entity_id"]))
        return "dev-hash"

    async def fake_persist_correlation(session, evidence):
        persisted.append(("correlation", evidence["entity_id"]))
        return "corr-hash"

    async def fake_history(*args, **kwargs):
        return {"status": "OBSERVED", "records": [], "changes": [], "latest_change": None}

    monkeypatch.setattr(investigation_entity_network, "entity_network_for_investigation", fake_network)
    monkeypatch.setattr("stinky_api.entity_graph.persist_developer_snapshot", fake_persist_developer)
    monkeypatch.setattr("stinky_api.entity_graph.persist_developer_correlation_snapshot", fake_persist_correlation)
    monkeypatch.setattr("stinky_api.entity_graph.developer_audit_history", fake_history)
    monkeypatch.setattr("stinky_api.entity_graph.developer_correlation_audit_history", fake_history)

    session = _Session(entity_id=entity_id, creator="should-not-be-used")
    result = await investigation_calibration_evidence("mint-new", session, as_of=None)

    assert captured["entity_id"] == entity_id
    assert captured["creator_wallet"] is None
    assert captured["mint"] == "mint-new"
    assert persisted == [("developer", entity_id), ("correlation", entity_id)]
    assert result["developer"]["history_state"] == "NEW-UNKNOWN"
    assert result["developer_correlation"]["status"] == "UNKNOWN"
    assert all("FROM migration_tracks" not in sql for sql, _ in session.calls)
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


@pytest.mark.asyncio
async def test_calibration_endpoint_preserves_unknown_synthesis_and_fresh_developer(monkeypatch):
    async def fake_network(session, **kwargs):
        return {}

    monkeypatch.setattr(investigation_entity_network, "entity_network_for_investigation", fake_network)
    result = await investigation_calibration_evidence("mint-2", _Session())

    assert result["status"] == "UNKNOWN"
    assert result["calibration"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["calibration"]["predictive_authority"] is False
    assert result["calibration"]["trade_signal"] is False
    assert result["developer"]["history_state"] == "NEW-UNKNOWN"
    assert result["developer"]["fresh_entity_interpretation"] == "NEW-UNKNOWN"
    assert result["developer_correlation"]["status"] == "UNKNOWN"
    assert result["developer_correlation"]["ownership_inferred"] is False
    assert result["developer_correlation"]["coordination_inferred"] is False
    assert result["developer"]["risk_inferred"] is False
    assert result["developer"]["quality_inferred"] is False
    assert result["developer"]["predictive_authority"] is False
    assert result["developer"]["trade_signal"] is False
