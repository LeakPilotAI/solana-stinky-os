import pytest

from stinky_api import investigation_calibration_surface as surface_module
from stinky_api.investigation_calibration_surface import (
    build_investigation_calibration_surface,
    unknown_calibration_surface,
)
from stinky_api.investigation_entity_network import entity_network_for_investigation


def test_unknown_surface_is_explicit_evidence_only_and_bounded():
    surface = unknown_calibration_surface(status="NEW-UNKNOWN", pattern_hash=None, limit=999)
    assert surface["market_pattern_calibration_transitions"]["status"] == "NEW-UNKNOWN"
    assert surface["market_pattern_regime_memory"]["bounded"]["pattern_limit"] == 500
    assert surface["market_pattern_regime_memory"]["shared_cause_inferred"] is False
    assert surface["market_pattern_regime_segmentation"]["future_regime_leakage_permitted"] is False
    assert surface["market_pattern_regime_stability"]["future_evaluation_leakage_permitted"] is False
    assert all(value["evidence_only"] is True for value in surface.values())


@pytest.mark.asyncio
async def test_unknown_investigation_response_exposes_full_calibration_surface():
    class ExplodingSession:
        async def execute(self, *args, **kwargs):
            raise AssertionError("database should not be queried")

    result = await entity_network_for_investigation(ExplodingSession())
    expected = {
        "market_pattern_calibration_transitions",
        "market_pattern_regime_memory",
        "market_pattern_regime_segmentation",
        "market_pattern_conditional_performance",
        "market_pattern_regime_stability",
    }
    assert expected.issubset(result)
    assert all(result[key]["status"] == "NEW-UNKNOWN" for key in expected)
    assert all(result[key]["evidence_only"] is True for key in expected)


@pytest.mark.asyncio
async def test_surface_propagates_as_of_and_limits(monkeypatch):
    calls = {}

    def fake_transitions(memory):
        calls["memory"] = memory
        return {"status": "OBSERVED", "transitions": [], "state_runs": [], "evidence_only": True}

    async def fake_regime(session, **kwargs):
        calls["regime"] = kwargs
        return {"status": "OBSERVED", "pattern_count": 3, "state_counts": {"STABLE": 3}, "shared_cause_inferred": False, "evidence_only": True}

    async def fake_segment(session, pattern_hash, **kwargs):
        calls["segment"] = (pattern_hash, kwargs)
        return {"status": "OBSERVED", "pattern_hash": pattern_hash, "records": [], "regime_counts": {}, "evidence_only": True}

    def fake_conditional(calibration, segmentation):
        calls["conditional"] = (calibration, segmentation)
        return {"status": "OBSERVED", "pattern_hash": "p1", "regimes": {}, "evidence_only": True}

    def fake_stability(calibration, segmentation):
        calls["stability"] = (calibration, segmentation)
        return {"status": "OBSERVED", "pattern_hash": "p1", "regimes": {}, "evidence_only": True}

    monkeypatch.setattr(surface_module, "describe_calibration_state_transitions", fake_transitions)
    monkeypatch.setattr(surface_module, "calibration_regime_memory", fake_regime)
    monkeypatch.setattr(surface_module, "segment_pattern_occurrences_by_regime", fake_segment)
    monkeypatch.setattr(surface_module, "summarize_conditional_pattern_performance", fake_conditional)
    monkeypatch.setattr(surface_module, "assess_regime_conditioned_stability", fake_stability)

    memory = {"status": "OBSERVED", "records": []}
    calibration = {"status": "OBSERVED", "pattern_hash": "p1", "records": []}
    result = await build_investigation_calibration_surface(
        object(),
        pattern_hash="p1",
        calibration=calibration,
        calibration_memory=memory,
        as_of="2026-09-01T00:00:00+00:00",
        occurrence_limit=777,
        pattern_limit=9999,
        regime_lookback_hours=48,
    )

    assert calls["memory"] is memory
    assert calls["regime"] == {
        "lookback_hours": 48,
        "pattern_limit": 2000,
        "as_of": "2026-09-01T00:00:00+00:00",
    }
    assert calls["segment"] == (
        "p1",
        {
            "occurrence_limit": 500,
            "regime_lookback_hours": 48,
            "as_of": "2026-09-01T00:00:00+00:00",
        },
    )
    assert result["market_pattern_regime_memory"]["status"] == "OBSERVED"
    assert result["market_pattern_regime_segmentation"]["status"] == "OBSERVED"
    assert result["market_pattern_conditional_performance"]["status"] == "OBSERVED"
    assert result["market_pattern_regime_stability"]["status"] == "OBSERVED"


@pytest.mark.asyncio
async def test_surface_fails_soft_per_layer(monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    async def explode_async(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(surface_module, "describe_calibration_state_transitions", explode)
    monkeypatch.setattr(surface_module, "calibration_regime_memory", explode_async)
    monkeypatch.setattr(surface_module, "segment_pattern_occurrences_by_regime", explode_async)
    monkeypatch.setattr(surface_module, "summarize_conditional_pattern_performance", explode)
    monkeypatch.setattr(surface_module, "assess_regime_conditioned_stability", explode)

    result = await build_investigation_calibration_surface(
        object(),
        pattern_hash="p1",
        calibration={"status": "OBSERVED", "pattern_hash": "p1", "records": []},
        calibration_memory={"status": "UNKNOWN", "records": []},
    )

    assert all(value["status"] == "UNKNOWN" for value in result.values())
    assert all(value["evidence_only"] is True for value in result.values())
