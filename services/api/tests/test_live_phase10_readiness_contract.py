from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_live_readiness_remains_descriptive_and_off_command_center():
    source = (ROOT / "src" / "stinky_api" / "live_phase10_readiness.py").read_text(encoding="utf-8")
    assert '"phase_11_authorized": False' in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
    assert '"probability_inferred": False' in source
    assert '"confidence_inferred": False' in source
    assert '"command_center_coupled": False' in source
    assert "command_center(" not in source


def test_static_readiness_route_precedes_dynamic_entity_route():
    source = (ROOT / "src" / "stinky_api" / "entity_graph.py").read_text(encoding="utf-8")
    static_route = '@router.get("/research/phase10-readiness")'
    dynamic_route = '@router.get("/{entity_id}")'
    assert static_route in source
    assert dynamic_route in source
    assert source.index(static_route) < source.index(dynamic_route)


def test_historical_replay_does_not_persist_current_evidence():
    source = (ROOT / "src" / "stinky_api" / "live_phase10_readiness.py").read_text(encoding="utf-8")
    assert "persist_current and not historical_replay" in source
    assert "SKIPPED_HISTORICAL_REPLAY" in source
    assert "await session.commit()" in source
    assert "await session.rollback()" in source
