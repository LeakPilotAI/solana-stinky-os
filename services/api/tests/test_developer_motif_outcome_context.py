from datetime import datetime, timezone
from uuid import UUID

import pytest

from stinky_api.developer_motif_outcome_context import motif_outcome_context


class _Mappings:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows
    def first(self): return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return _Mappings(self._rows)


class _Session:
    def __init__(self, launch_rows, observations=None, events=None):
        self.launch_rows = launch_rows; self.observations = observations or []; self.events = events or []; self.calls = []
    async def execute(self, statement, params):
        sql = str(statement); self.calls.append((sql, params))
        if "FROM market_outcome_observations" in sql: return _Result(self.observations)
        if "FROM events e" in sql: return _Result(self.events)
        return _Result(self.launch_rows)


def _motifs():
    return {"status": "OBSERVED", "records": [{
        "motif_kind": "CROSS_ENTITY_RELATIONSHIP_MOTIF",
        "motif_state": "MULTI_COMPONENT_CONSTELLATION",
        "component_kinds": ["SHARED_FUNDER", "WALLET_REUSE"],
        "other_entity_ids": ["22222222-2222-2222-2222-222222222222"],
    }]}


def _event(mint, outcome, occurred="2026-09-03T00:00:00+00:00", ingested="2026-09-03T00:01:00+00:00"):
    return {"event_id": f"event-{mint}", "event_type": "post_migration.tracking_completed", "occurred_at": occurred,
            "ingested_at": ingested, "signature": None, "producer": "tracker", "payload": {"mint": mint, "outcome_status": outcome}}


def _assert_no_scoring_or_probability_keys(result):
    serialized = str(result).lower()
    for forbidden in ("risk_score", "quality_score", "ownership_probability", "coordination_probability", "expected_return_score", "confidence_score"):
        assert forbidden not in serialized
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False


@pytest.mark.asyncio
async def test_historical_motif_outcomes_use_immutable_events_and_lifecycle_distribution():
    session = _Session([
        {"entity_id": "22222222-2222-2222-2222-222222222222", "mint": "M1", "deployer_wallet": "D1", "observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
        {"entity_id": "22222222-2222-2222-2222-222222222222", "mint": "M2", "deployer_wallet": "D2", "observed_at": datetime(2026, 9, 2, tzinfo=timezone.utc), "created_at": datetime(2026, 9, 2, tzinfo=timezone.utc)},
    ], observations=[
        {"mint": "M1", "horizon": "5m", "horizon_seconds": 300, "anchor_observed_at": "2026-09-01T00:00:00+00:00", "observed_at": "2026-09-01T00:05:00+00:00", "ingested_at": "2026-09-01T00:05:05+00:00", "source": "dex", "evidence_basis": "market_snapshot_observation", "metrics": {"price_usd": 2.0}, "event_id": "o1", "signature": None},
        {"mint": "M2", "horizon": "5m", "horizon_seconds": 300, "anchor_observed_at": "2026-09-02T00:00:00+00:00", "observed_at": "2026-09-02T00:05:00+00:00", "ingested_at": "2026-09-02T00:05:05+00:00", "source": "dex", "evidence_basis": "market_snapshot_observation", "metrics": {"price_usd": 1.0}, "event_id": "o2", "signature": None},
    ], events=[_event("M1", "RUNNER"), _event("M2", "FADE")])
    result = await motif_outcome_context(session, UUID("11111111-1111-1111-1111-111111111111"), network_motifs=_motifs(), launch_limit=20)
    assert result["status"] == "OBSERVED"
    assert result["motif_analogue_count"] == 1
    assert result["launch_analogue_count"] == 2
    assert result["outcome_counts"] == {"RUNNER": 1, "HELD": 0, "FADE": 1, "UNKNOWN": 0}
    five = result["lifecycle_distribution"]["horizons"][0]
    assert five["observed_count"] == 2 and five["unknown_count"] == 0
    assert five["metrics"]["price_usd"]["median"] == 1.5
    assert result["bounded"]["lifecycle_query_count"] == 2
    assert result["analogue_history_is_not_prediction"] is True
    _assert_no_scoring_or_probability_keys(result)


@pytest.mark.asyncio
async def test_outcome_event_after_cutoff_is_unknown_and_observation_ingestion_is_cutoff_safe():
    session = _Session([
        {"entity_id": "22222222-2222-2222-2222-222222222222", "mint": "M1", "deployer_wallet": "D1", "observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
    ], events=[])
    result = await motif_outcome_context(session, UUID("11111111-1111-1111-1111-111111111111"), network_motifs=_motifs(), as_of=datetime(2026, 9, 3, tzinfo=timezone.utc), launch_limit=20)
    launch = result["records"][0]["launches"][0]
    assert launch["outcome"] == "UNKNOWN"
    assert result["outcome_counts"]["UNKNOWN"] == 1
    assert result["temporal_cutoff_enforced"] is True
    sql = "\n".join(call[0] for call in session.calls)
    assert "o.observed_at <= :as_of AND o.ingested_at <= :as_of" in sql
    assert "e.occurred_at <= :as_of AND e.ingested_at <= :as_of" in sql


@pytest.mark.asyncio
async def test_no_immutable_event_means_unknown_even_if_launch_storage_would_have_mutable_outcome():
    session = _Session([
        {"entity_id": "22222222-2222-2222-2222-222222222222", "mint": "M1", "deployer_wallet": "D1", "observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "outcome_status": "RUNNER"},
    ])
    result = await motif_outcome_context(session, UUID("11111111-1111-1111-1111-111111111111"), network_motifs=_motifs())
    assert result["records"][0]["launches"][0]["outcome"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_no_motif_stays_new_unknown_without_fabricated_analogues():
    result = await motif_outcome_context(_Session([]), UUID("11111111-1111-1111-1111-111111111111"), network_motifs={"status": "NEW-UNKNOWN", "records": []})
    assert result["status"] == "NEW-UNKNOWN"
    assert result["motif_analogue_count"] == 0
    assert result["launch_analogue_count"] == 0
    assert result["records"] == []
    assert result["lifecycle_distribution"]["analogue_count"] == 0
    _assert_no_scoring_or_probability_keys(result)
