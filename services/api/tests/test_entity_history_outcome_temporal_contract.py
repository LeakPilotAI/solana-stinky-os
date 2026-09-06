from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_entity_history_uses_immutable_completion_event_for_outcome():
    source = (ROOT / "src" / "stinky_api" / "entity_history_synthesis.py").read_text(encoding="utf-8")
    assert "post_migration.tracking_completed" in source
    assert "e.occurred_at <= :as_of AND e.ingested_at <= :as_of" in source
    assert "canonical_outcome_from_event" in source
    assert '"mutable_outcome_status_is_historical_authority"] = False' in source
    assert 'resolved_outcome = canonical_outcome_from_event(event)' in source
    assert 'item["outcome_state"] = resolved_outcome' in source
    assert 'item["outcome_status"] = None if resolved_outcome == "UNKNOWN" else resolved_outcome' in source


def test_lifecycle_memory_keeps_all_canonical_horizons_explicit():
    source = (ROOT / "src" / "stinky_api" / "market_lifecycle_memory.py").read_text(encoding="utf-8")
    for horizon in ('"5m", 300', '"15m", 900', '"30m", 1800', '"1h", 3600', '"4h", 14400', '"24h", 86400'):
        assert horizon in source
    assert '"complete_through_24h"' in source
    assert '"missing_horizons"' in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
