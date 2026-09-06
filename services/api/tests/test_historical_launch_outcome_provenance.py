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


@pytest.mark.asyncio
async def test_provenance_exposes_source_metrics_and_authority_boundary():
    launch = {"entity_id": "e1", "mint": "m1", "event_id": "launch-1", "launch_observed_at": datetime(2026,1,1,tzinfo=timezone.utc),
              "outcome_status": "RUNNER", "outcome_meta": {"observed_at": "2026-01-01T00:30:00+00:00", "ingested_at": "2026-01-01T00:31:00+00:00", "event_id": "outcome-1", "source_event": "post_migration.tracking_completed"},
              "launch_ingested_at": datetime(2026,1,1,tzinfo=timezone.utc)}
    observations = [{"id": 1, "horizon": "30m", "horizon_seconds": 1800, "anchor_observed_at": datetime(2026,1,1,tzinfo=timezone.utc),
                     "observed_at": datetime(2026,1,1,0,30,tzinfo=timezone.utc), "ingested_at": datetime(2026,1,1,0,30,5,tzinfo=timezone.utc),
                     "source": "dexscreener", "evidence_basis": "market_snapshot_observation", "metrics": {"price_usd": 2.0}, "event_id": "obs-1", "signature": None}]
    out = await historical_launch_outcome_provenance(_Session(launch, observations), "m1")
    assert out["outcome"] == "RUNNER"
    assert out["outcome_source_event"] == "post_migration.tracking_completed"
    assert out["observations"][0]["source"] == "dexscreener"
    assert out["observations"][0]["metrics"]["price_usd"] == 2.0
    assert out["predictive_authority"] is False and out["trade_signal"] is False


@pytest.mark.asyncio
async def test_as_of_masks_outcome_until_both_observed_and_ingested():
    launch = {"entity_id": "e1", "mint": "m1", "event_id": "launch-1", "launch_observed_at": datetime(2026,1,1,tzinfo=timezone.utc),
              "outcome_status": "FADE", "outcome_meta": {"observed_at": "2026-01-01T00:20:00+00:00", "ingested_at": "2026-01-01T00:40:00+00:00"},
              "launch_ingested_at": datetime(2026,1,1,tzinfo=timezone.utc)}
    session = _Session(launch, [])
    out = await historical_launch_outcome_provenance(session, "m1", as_of="2026-01-01T00:30:00Z")
    assert out["outcome"] == "UNKNOWN"
    assert out["temporal_cutoff_enforced"] is True
    observation_sql = session.calls[1][0]
    assert "o.observed_at <= :as_of" in observation_sql
    assert "o.ingested_at <= :as_of" in observation_sql


@pytest.mark.asyncio
async def test_legacy_missing_ingestion_fails_closed_historically():
    launch = {"entity_id": "e1", "mint": "m1", "event_id": "launch-1", "launch_observed_at": datetime(2026,1,1,tzinfo=timezone.utc),
              "outcome_status": "HELD", "outcome_meta": {"observed_at": "2026-01-01T00:20:00+00:00"}, "launch_ingested_at": datetime(2026,1,1,tzinfo=timezone.utc)}
    out = await historical_launch_outcome_provenance(_Session(launch, []), "m1", as_of="2026-01-01T01:00:00Z")
    assert out["outcome"] == "UNKNOWN"
    assert "outcome_ingested_at" in out["missing"]
