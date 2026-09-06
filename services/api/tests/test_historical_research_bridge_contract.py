from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "stinky_api" / "historical_research_bridge.py"
LIVE = ROOT / "src" / "stinky_api" / "live_phase10_readiness.py"
MAIN = ROOT / "src" / "stinky_api" / "main.py"


def test_bridge_requires_past_observed_entity_link_before_historical_insert():
    text = MODULE.read_text(encoding="utf-8")
    assert "x.first_seen_at <= mt.migration_at" in text
    assert "e.created_at <= mt.migration_at" in text
    assert "migration_at" in text
    assert "observed_at" in text
    assert "future_entity_inference_forbidden" in text


def test_bridge_is_idempotent_and_does_not_rewrite_entity_aggregates():
    text = MODULE.read_text(encoding="utf-8")
    assert "NOT EXISTS" in text
    assert "ON CONFLICT DO NOTHING" in text
    assert "UPDATE entities" not in text
    assert "entity_launch_count_aggregate_modified" in text


def test_bridge_has_no_predictive_or_trading_authority():
    text = MODULE.read_text(encoding="utf-8")
    for field in (
        '"predictive_authority": False',
        '"trade_signal": False',
        '"risk_inferred": False',
        '"quality_inferred": False',
        '"probability_inferred": False',
        '"confidence_inferred": False',
    ):
        assert field in text


def test_command_center_does_not_import_research_bridge():
    text = MAIN.read_text(encoding="utf-8")
    assert "historical_research_bridge" not in text
