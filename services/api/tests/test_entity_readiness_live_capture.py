import pytest

from stinky_api import investigation_entity_network
from stinky_api.entity_graph import investigation_calibration_evidence


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, entity_id):
        self.entity_id = entity_id

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM entity_launches" in sql:
            return _Result((self.entity_id,))
        return _Result(None)


def _network(entity_id):
    return {
        "history": {
            "sources": {
                "developer_longitudinal": {
                    "status": "OBSERVED",
                    "entity_id": entity_id,
                    "history_state": "KNOWN_HISTORY",
                    "risk_inferred": False,
                    "quality_inferred": False,
                    "predictive_authority": False,
                    "trade_signal": False,
                    "evidence_only": True,
                }
            }
        },
        "developer_identity_correlation": {
            "status": "OBSERVED",
            "entity_id": entity_id,
            "wallets": [],
            "shared_funders": [],
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
        "historical_outcome_calibration": {
            "status": "OBSERVED",
            "launch_count_observed": 7,
            "outcomes_known": 5,
            "outcome_coverage": 5 / 7,
            "evidence_basis": "entity_launches",
            "evidence_only": True,
        },
    }


@pytest.mark.asyncio
async def test_current_investigation_persists_combined_readiness_snapshot(monkeypatch):
    entity_id = "11111111-1111-1111-1111-111111111111"
    captured = {"developer": 0, "correlation": 0, "readiness": 0}

    async def fake_network(session, **kwargs):
        return _network(entity_id)

    async def fake_persist_developer(session, evidence):
        captured["developer"] += 1
        return "dev-hash"

    async def fake_persist_correlation(session, evidence):
        captured["correlation"] += 1
        return "corr-hash"

    async def fake_component_history(*args, **kwargs):
        return {"status": "OBSERVED", "records": [], "changes": [], "latest_change": None}

    async def fake_readiness(session, got_entity_id, outcome, **kwargs):
        assert got_entity_id == entity_id
        assert outcome["launch_count_observed"] == 7
        assert kwargs["as_of"] is None
        return {
            "status": "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION",
            "ready": False,
            "blockers": ["RELATIONSHIP_HISTORY_NOT_STABLE"],
            "entity_id": entity_id,
            "calibration_scope": "ENTITY_INTELLIGENCE_DESCRIPTIVE_ONLY",
            "predictive_authority": False,
            "risk_inferred": False,
            "quality_inferred": False,
            "trade_signal": False,
            "evidence_only": True,
        }

    async def fake_persist_readiness(session, got_entity_id, readiness, **kwargs):
        captured["readiness"] += 1
        assert got_entity_id == entity_id
        assert readiness["ready"] is False
        return "ready-hash"

    async def fake_readiness_history(session, got_entity_id, **kwargs):
        assert got_entity_id == entity_id
        return {
            "status": "OBSERVED",
            "snapshot_count": 1,
            "regression_count": 0,
            "latest_transition": {"transition": "INITIAL_STATE"},
            "records": [{}],
            "transitions": [{}],
        }

    monkeypatch.setattr(investigation_entity_network, "entity_network_for_investigation", fake_network)
    monkeypatch.setattr("stinky_api.entity_graph.persist_developer_snapshot", fake_persist_developer)
    monkeypatch.setattr("stinky_api.entity_graph.persist_developer_correlation_snapshot", fake_persist_correlation)
    monkeypatch.setattr("stinky_api.entity_graph.developer_audit_history", fake_component_history)
    monkeypatch.setattr("stinky_api.entity_graph.developer_correlation_audit_history", fake_component_history)
    monkeypatch.setattr("stinky_api.entity_intelligence_calibration_readiness.entity_intelligence_calibration_readiness", fake_readiness)
    monkeypatch.setattr("stinky_api.entity_readiness_transition_audit.persist_entity_readiness_snapshot", fake_persist_readiness)
    monkeypatch.setattr("stinky_api.entity_readiness_transition_audit.entity_readiness_history", fake_readiness_history)

    result = await investigation_calibration_evidence("mint-live", _Session(entity_id), as_of=None)

    assert captured == {"developer": 1, "correlation": 1, "readiness": 1}
    assert result["entity_readiness"]["status"] == "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["entity_readiness_snapshot_hash"] == "ready-hash"
    assert result["entity_readiness_snapshot_count"] == 1
    assert result["entity_readiness_latest_transition"]["transition"] == "INITIAL_STATE"
    assert result["predictive_authority"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["trade_signal"] is False


@pytest.mark.asyncio
async def test_historical_as_of_computes_readiness_but_never_persists_snapshot(monkeypatch):
    entity_id = "22222222-2222-2222-2222-222222222222"
    persisted = []
    cutoff = "2026-08-15T00:00:00+00:00"

    async def fake_network(session, **kwargs):
        return _network(entity_id)

    async def fake_component_history(*args, **kwargs):
        return {"status": "OBSERVED", "records": [], "changes": [], "latest_change": None}

    async def fake_readiness(session, got_entity_id, outcome, **kwargs):
        assert kwargs["as_of"] == cutoff
        return {
            "status": "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION",
            "ready": False,
            "blockers": ["DEVELOPER_HISTORY_NOT_STABLE"],
            "entity_id": got_entity_id,
            "calibration_scope": "ENTITY_INTELLIGENCE_DESCRIPTIVE_ONLY",
            "predictive_authority": False,
            "risk_inferred": False,
            "quality_inferred": False,
            "trade_signal": False,
            "evidence_only": True,
        }

    async def should_not_persist(*args, **kwargs):
        persisted.append(True)
        raise AssertionError("historical readiness must never be persisted")

    async def fake_readiness_history(session, got_entity_id, **kwargs):
        assert kwargs["as_of"] == cutoff
        return {"status": "UNKNOWN", "snapshot_count": 0, "regression_count": 0, "latest_transition": None, "records": [], "transitions": []}

    monkeypatch.setattr(investigation_entity_network, "entity_network_for_investigation", fake_network)
    monkeypatch.setattr("stinky_api.entity_graph.developer_audit_history", fake_component_history)
    monkeypatch.setattr("stinky_api.entity_graph.developer_correlation_audit_history", fake_component_history)
    monkeypatch.setattr("stinky_api.entity_intelligence_calibration_readiness.entity_intelligence_calibration_readiness", fake_readiness)
    monkeypatch.setattr("stinky_api.entity_readiness_transition_audit.persist_entity_readiness_snapshot", should_not_persist)
    monkeypatch.setattr("stinky_api.entity_readiness_transition_audit.entity_readiness_history", fake_readiness_history)

    result = await investigation_calibration_evidence("mint-historical", _Session(entity_id), as_of=cutoff)

    assert persisted == []
    assert result["entity_readiness_snapshot_hash"] is None
    assert result["entity_readiness"]["ready"] is False
    assert result["entity_readiness_snapshot_count"] == 0


def test_endpoint_contract_exposes_readiness_without_predictive_authority():
    import inspect
    from stinky_api import entity_graph

    source = inspect.getsource(entity_graph.investigation_calibration_evidence)
    assert '"entity_readiness"' in source
    assert '"entity_readiness_snapshot_hash"' in source
    assert '"entity_readiness_regression_count"' in source
    assert '"predictive_authority": False' in source
    assert '"risk_inferred": False' in source
    assert '"quality_inferred": False' in source
    assert '"trade_signal": False' in source
