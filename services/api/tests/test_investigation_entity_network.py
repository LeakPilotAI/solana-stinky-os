import pytest
from uuid import uuid4

from stinky_api import investigation_entity_network as adapter
from stinky_api.investigation_entity_network import entity_network_for_investigation


class ExplodingSession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("database should not be queried without an entity id or creator wallet")


@pytest.mark.asyncio
async def test_unknown_investigation_entity_is_explicit_and_bounded():
    result = await entity_network_for_investigation(ExplodingSession(), wallet_limit=0, relationship_limit=999)
    assert result["status"] == "NEW-UNKNOWN"
    assert result["evidence_only"] is True
    assert result["missing"] == ["entity_history"]
    assert result["funding_history"] == []
    assert result["market_lifecycle"]["status"] == "NEW-UNKNOWN"
    assert result["market_outcome_analysis"]["status"] == "NEW-UNKNOWN"
    assert result["market_pattern_history"]["status"] == "NEW-UNKNOWN"
    assert result["market_pattern_outcome_calibration"]["status"] == "NEW-UNKNOWN"
    assert result["market_pattern_outcome_distribution"]["status"] == "NEW-UNKNOWN"
    assert result["market_pattern_calibration_readiness"]["status"] == "NEW-UNKNOWN"
    assert result["market_pattern_rolling_calibration"]["status"] == "NEW-UNKNOWN"
    assert result["market_pattern_calibration_memory"]["status"] == "NEW-UNKNOWN"
    assert result["historical_analogues"]["status"] == "NEW-UNKNOWN"
    assert result["historical_outcome_comparison"]["status"] == "NEW-UNKNOWN"
    assert result["historical_outcome_calibration"]["status"] == "NEW-UNKNOWN"
    assert result["bounded"] == {
        "wallet_limit": 1,
        "relationship_limit": 500,
        "funding_observation_limit": 500,
        "market_lifecycle_limit": 500,
        "market_pattern_history_limit": 500,
        "market_pattern_outcome_occurrence_limit": 500,
        "market_pattern_calibration_memory_limit": 500,
        "analogue_limit": 10,
        "analogue_candidate_limit": 500,
        "outcome_launch_limit_per_analogue": 20,
    }


@pytest.mark.asyncio
async def test_invalid_entity_id_falls_back_to_creator_wallet():
    class Session:
        def __init__(self): self.queried = False
        async def execute(self, *args, **kwargs):
            self.queried = True
            class Result:
                def first(self): return None
            return Result()
    session = Session()
    result = await entity_network_for_investigation(session, entity_id="not-a-uuid", creator_wallet="creator-wallet")
    assert session.queried is True
    assert result["status"] == "NEW-UNKNOWN"
    assert result["evidence_only"] is True


@pytest.mark.asyncio
async def test_known_entity_includes_historical_outcomes_and_calibration(monkeypatch):
    entity_id = uuid4()

    class Session:
        async def execute(self, *args, **kwargs):
            class Result:
                def first(self): return (entity_id,)
            return Result()

    async def fake_assemble(*args):
        return {"entity": {"entity_id": str(entity_id)}, "wallets": [], "relationships": [], "bounded": {"wallet_limit": 10, "relationship_limit": 20}, "evidence_only": True}
    async def fake_funding(*args, **kwargs): return [{"signature": "sig-1", "amount_lamports": 42}]
    async def fake_history(*args, **kwargs): return {"status": "KNOWN_ENTITY", "sources": {}, "evidence_only": True}
    async def fake_lifecycle(*args, **kwargs):
        assert kwargs["limit"] == 20
        return {"status": "OBSERVED", "mint": "MINT", "records": [{"horizon": "5m", "horizon_seconds": 300, "observed_at": "2026-09-04T00:05:00+00:00", "metrics": {"price_usd": 1.0}}], "missing": [], "bounded": {"limit": 20}, "evidence_basis": "market_snapshot_observation", "evidence_only": True}
    async def fake_persist(*args, **kwargs):
        assert kwargs["mint"] == "MINT"
        assert kwargs["observed_at"] == "2026-09-04T00:05:00+00:00"
        return "pattern-hash"
    async def fake_pattern_history(*args, **kwargs):
        assert args[1] == "pattern-hash"
        assert kwargs["limit"] == 20
        return {"status": "OBSERVED", "pattern_hash": "pattern-hash", "occurrence_count": 2, "distinct_market_count": 2, "records": [{"mint": "MINT"}, {"mint": "OTHER"}], "missing": [], "bounded": {"limit": 20}, "evidence_only": True}
    async def fake_pattern_calibration(*args, **kwargs):
        assert args[1] == "pattern-hash"
        assert kwargs["occurrence_limit"] == 20
        return {"status": "OBSERVED", "pattern_hash": "pattern-hash", "occurrence_count": 2, "occurrences_with_followup": 1, "occurrences_without_followup": 1, "followup_coverage": 0.5, "horizon_coverage": {"1h": {"occurrences_observed": 1, "occurrence_count": 2, "coverage": 0.5}}, "records": [], "missing": [], "bounded": {"occurrence_limit": 20}, "evidence_only": True}
    async def fake_analogues(*args, **kwargs):
        return {"status": "OBSERVED", "records": [{"entity_id": str(uuid4()), "similarity_distance": 0.0}], "evidence_basis": "entity_behavior_fingerprints", "bounded": {"limit": 10, "candidate_limit": 500}, "evidence_only": True}
    async def fake_outcomes(*args, **kwargs):
        assert kwargs["limit_per_entity"] == 20
        return {"status": "OBSERVED", "records": [{"entity_id": "analogue-1", "launches": [{"outcome_observed": True, "outcome_status": "completed"}, {"outcome_observed": False, "outcome_status": None}], "launch_count_observed": 2, "outcomes_known": 1, "completed_count": 1, "outcomes_unknown": 1, "evidence_basis": "entity_launches"}], "evidence_basis": "entity_launches", "bounded": {"limit_per_entity": 20}, "evidence_only": True}

    monkeypatch.setattr(adapter, "_assemble", fake_assemble)
    monkeypatch.setattr(adapter, "funding_history_for_entity", fake_funding)
    monkeypatch.setattr(adapter, "synthesize_entity_history", fake_history)
    monkeypatch.setattr(adapter, "market_lifecycle_for_mint", fake_lifecycle)
    monkeypatch.setattr(adapter, "persist_market_pattern_occurrence", fake_persist)
    monkeypatch.setattr(adapter, "market_pattern_history", fake_pattern_history)
    monkeypatch.setattr(adapter, "calibrate_market_pattern_outcomes", fake_pattern_calibration)
    monkeypatch.setattr(adapter, "find_historical_analogues", fake_analogues)
    monkeypatch.setattr(adapter, "historical_outcomes_for_analogues", fake_outcomes)

    result = await entity_network_for_investigation(Session(), creator_wallet="creator-wallet", mint="MINT", wallet_limit=10, relationship_limit=20)
    assert result["status"] == "KNOWN_ENTITY"
    assert result["evidence_only"] is True
    assert result["market_lifecycle"]["status"] == "OBSERVED"
    assert result["market_lifecycle"]["mint"] == "MINT"
    assert result["market_lifecycle"]["records"][0]["horizon"] == "5m"
    assert result["market_outcome_analysis"]["status"] == "OBSERVED"
    assert result["market_outcome_analysis"]["metrics"]["price_usd"]["first"] == {"horizon": "5m", "value": 1.0}
    assert result["market_outcome_analysis"]["evidence_only"] is True
    assert result["market_pattern_history"]["status"] == "OBSERVED"
    assert result["market_pattern_history"]["occurrence_count"] == 2
    assert result["market_pattern_history"]["distinct_market_count"] == 2
    assert result["market_pattern_outcome_calibration"]["status"] == "OBSERVED"
    assert result["market_pattern_outcome_calibration"]["followup_coverage"] == 0.5
    assert result["market_pattern_outcome_calibration"]["occurrences_without_followup"] == 1
    assert result["market_pattern_outcome_distribution"]["status"] == "OBSERVED"
    assert result["market_pattern_outcome_distribution"]["horizons"]["1h"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["market_pattern_calibration_readiness"]["readiness_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["market_pattern_rolling_calibration"]["trend_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["market_pattern_calibration_memory"]["status"] == "UNKNOWN"
    assert result["historical_outcome_comparison"]["status"] == "OBSERVED"
    assert result["historical_outcome_comparison"]["records"][0]["completed_count"] == 1
    assert result["historical_outcome_comparison"]["records"][0]["outcomes_unknown"] == 1
    assert result["historical_outcome_calibration"]["status"] == "OBSERVED"
    assert result["historical_outcome_calibration"]["analogue_count"] == 1
    assert result["historical_outcome_calibration"]["launch_count_observed"] == 2
    assert result["historical_outcome_calibration"]["outcomes_known"] == 1
    assert result["historical_outcome_calibration"]["outcomes_unknown"] == 1
    assert result["historical_outcome_calibration"]["completed_count"] == 1
    assert result["historical_outcome_calibration"]["outcome_coverage"] == 0.5
    assert result["bounded"]["outcome_launch_limit_per_analogue"] == 20
    assert result["bounded"]["market_pattern_history_limit"] == 20
    assert result["bounded"]["market_pattern_outcome_occurrence_limit"] == 20
    assert result["bounded"]["market_pattern_calibration_memory_limit"] == 20
    assert result["historical_outcome_comparison"]["evidence_only"] is True
    assert result["historical_outcome_calibration"]["evidence_only"] is True
