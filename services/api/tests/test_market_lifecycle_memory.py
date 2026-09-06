from datetime import datetime, timezone

from stinky_api.market_lifecycle_memory import build_market_lifecycle_memory, canonical_outcome_from_event


def _obs(horizon: str, seconds: int, at_minute: int):
    return {
        "horizon": horizon,
        "horizon_seconds": seconds,
        "anchor_observed_at": "2026-01-01T00:00:00+00:00",
        "observed_at": f"2026-01-01T00:{at_minute:02d}:00+00:00" if at_minute < 60 else "2026-01-01T01:00:00+00:00",
        "ingested_at": f"2026-01-01T00:{at_minute:02d}:05+00:00" if at_minute < 60 else "2026-01-01T01:00:05+00:00",
        "source": "market_snapshots",
        "evidence_basis": "market_snapshot_observation",
        "metrics": {"price_usd": 1.0},
    }


def test_canonical_outcome_requires_immutable_completion_event():
    assert canonical_outcome_from_event({"event_type": "other", "payload": {"outcome_status": "RUNNER"}}) == "UNKNOWN"
    assert canonical_outcome_from_event({"event_type": "post_migration.tracking_completed", "payload": {"outcome_status": "RUNNER"}}) == "RUNNER"
    assert canonical_outcome_from_event({"event_type": "post_migration.tracking_completed", "payload": {"outcome_status": "completed"}}) == "UNKNOWN"


def test_lifecycle_memory_has_six_explicit_horizon_slots_and_unknowns():
    memory = build_market_lifecycle_memory(mint="m1", observations=[_obs("5m", 300, 5), _obs("30m", 1800, 30)])
    assert len(memory["horizons"]) == 6
    assert memory["observed_horizon_count"] == 2
    assert memory["missing_horizons"] == ["15m", "1h", "4h", "24h"]
    assert memory["complete_through_24h"] is False
    assert memory["outcome"] == "UNKNOWN"


def test_lifecycle_cutoff_requires_observed_and_ingested_times():
    observations = [{
        "horizon": "5m", "horizon_seconds": 300,
        "observed_at": datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        "ingested_at": datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc),
        "metrics": {},
    }]
    event = {
        "event_id": "e1", "event_type": "post_migration.tracking_completed",
        "occurred_at": datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc),
        "ingested_at": datetime(2026, 1, 1, 0, 25, tzinfo=timezone.utc),
        "payload": {"outcome_status": "FADE"},
    }
    memory = build_market_lifecycle_memory(mint="m1", observations=observations, outcome_event=event, as_of="2026-01-01T00:15:00Z")
    assert memory["observed_horizon_count"] == 0
    assert memory["outcome"] == "UNKNOWN"
    assert memory["temporal_cutoff_enforced"] is True


def test_visible_completion_event_resolves_factual_outcome_without_prediction():
    event = {
        "event_id": "e1", "event_type": "post_migration.tracking_completed",
        "occurred_at": "2026-01-01T00:30:00+00:00", "ingested_at": "2026-01-01T00:31:00+00:00",
        "payload": {"outcome_status": "HELD"},
    }
    memory = build_market_lifecycle_memory(mint="m1", observations=[], outcome_event=event)
    assert memory["outcome"] == "HELD"
    assert memory["outcome_resolution_basis"] == "immutable_post_migration_tracking_completed_event"
    assert memory["predictive_authority"] is False
    assert memory["trade_signal"] is False
