from datetime import datetime, timezone

import pytest

from stinky_api.historical_launch_outcome_provenance import historical_launch_outcome_provenance


class _Result:
    def __init__(self, *, first=None, rows=None): self._first = first; self._rows = rows or []
    def mappings(self): return self
    def first(self): return self._first
    def all(self): return self._rows


class _Session:
    def __init__(self, launch, observations): self.launch = launch; self.observations = observations; self.calls = []
    async def execute(self, statement, params):
        sql = str(statement); self.calls.append((sql, dict(params)))
        if "FROM entity_launches" in sql: return _Result(first=self.launch)
        return _Result(rows=self.observations)


def _event_fields(outcome: str, *, occurred="2026-01-01T00:30:00+00:00", ingested="2026-01-01T00:31:00+00:00"):
    return {
        "outcome_event_id": "outcome-1",
        "outcome_event_type": "post_migration.tracking_completed",
        "outcome_event_observed_at": datetime.fromisoformat(occurred),
        "outcome_event_ingested_at": datetime.fromisoformat(ingested),
        "outcome_event_signature": None,
        "outcome_event_producer": "sentinel",
        "outcome_event_payload": {"mint": "m1", "outcome_status": outcome},
    }


@pytest.mark.asyncio
async def test_provenance_exposes_source_metrics_and_authority_boundary():
    launch = {"entity_id": "e1", "mint": "m1", "event_id": "launch-1", "launch_observed_at": datetime(2026,1,1,tzinfo=timezone.utc),
              "mutable_outcome_status": "RUNNER", "outcome_meta": {}, "launch_ingested_at": datetime(2026,1,1,tzinfo=timezone.utc),
              **_event_fields("RUNNER")}
    observations = [{"id": 1, "horizon": "30m", "horizon_seconds": 1800, "anchor_observed_at": datetime(2026,1,1,tzinfo=timezone.utc),
                     "observed_at": datetime(2026,1,1,0,30,tzinfo=timezone.utc), "ingested_at": datetime(2026,1,1,0,30,5,tzinfo=timezone.utc),
                     "source": "dexscreener", "evidence_basis": "market_snapshot_observation", "metrics": {"price_usd": 2.0}, "event_id": "obs-1", "signature": None}]
    out = await historical_launch_outcome_provenance(_Session(launch, observations), "m1")
    assert out["outcome"] == "RUNNER"
    assert out["outcome_resolution_basis"] == "immutable_post_migration_tracking_completed_event"
    assert out["mutable_outcome_status_is_historical_authority"] is False
    assert out["outcome_source_event"] == "post_migration.tracking_completed"
    assert out["lifecycle_memory"]["missing_horizons"] == ["5m", "15m", "1h", "4h", "24h"]
    assert out["observations"][0]["source"] == "dexscreener"
    assert out["observations"][0]["metrics"]["price_usd"] == 2.0
    assert out["predictive_authority"] is False and out["trade_signal"] is False


@pytest.mark.asyncio
async def test_as_of_masks_outcome_until_both_observed_and_ingested():
    launch = {"entity_id": "e1", "mint": "m1", "event_id": "launch-1", "launch_observed_at": datetime(2026,1,1,tzinfo=timezone.utc),
              "mutable_outcome_status": "FADE", "outcome_meta": {}, "launch_ingested_at": datetime(2026,1,1,tzinfo=timezone.utc),
              **_event_fields("FADE", occurred="2026-01-01T00:20:00+00:00", ingested="2026-01-01T00:40:00+00:00")}
    # The SQL cutoff would prevent this event from being returned. Simulate that result.
    launch.update({"outcome_event_id": None, "outcome_event_type": None, "outcome_event_observed_at": None,
                   "outcome_event_ingested_at": None, "outcome_event_signature": None, "outcome_event_producer": None,
                   "outcome_event_payload": None})
    session = _Session(launch, [])
    out = await historical_launch_outcome_provenance(session, "m1", as_of="2026-01-01T00:30:00Z")
    assert out["outcome"] == "UNKNOWN"
    assert out["temporal_cutoff_enforced"] is True
    assert out["mutable_outcome_status"] == "FADE"
    assert out["mutable_outcome_status_is_historical_authority"] is False
    launch_sql = session.calls[0][0]
    assert "e.occurred_at <= :as_of" in launch_sql and "e.ingested_at <= :as_of" in launch_sql
    observation_sql = session.calls[1][0]
    assert "o.observed_at <= :as_of" in observation_sql
    assert "o.ingested_at <= :as_of" in observation_sql


@pytest.mark.asyncio
async def test_mutable_legacy_outcome_without_immutable_event_stays_unknown():
    launch = {"entity_id": "e1", "mint": "m1", "event_id": "launch-1", "launch_observed_at": datetime(2026,1,1,tzinfo=timezone.utc),
              "mutable_outcome_status": "HELD", "outcome_meta": {"observed_at": "2026-01-01T00:20:00+00:00"},
              "launch_ingested_at": datetime(2026,1,1,tzinfo=timezone.utc), "outcome_event_id": None}
    out = await historical_launch_outcome_provenance(_Session(launch, []), "m1", as_of="2026-01-01T01:00:00Z")
    assert out["outcome"] == "UNKNOWN"
    assert out["mutable_outcome_status"] == "HELD"
    assert out["mutable_outcome_status_is_historical_authority"] is False
    assert "outcome_event" in out["missing"]
