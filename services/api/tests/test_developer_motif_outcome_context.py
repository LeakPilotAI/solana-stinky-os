from datetime import datetime, timezone
from uuid import UUID

import pytest

from stinky_api.developer_motif_outcome_context import motif_outcome_context


class _Mappings:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return _Mappings(self._rows)


class _Session:
    def __init__(self, rows): self.rows = rows; self.calls = []
    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result(self.rows)


def _motifs():
    return {"status": "OBSERVED", "records": [{
        "motif_kind": "CROSS_ENTITY_RELATIONSHIP_MOTIF",
        "motif_state": "MULTI_COMPONENT_CONSTELLATION",
        "component_kinds": ["SHARED_FUNDER", "WALLET_REUSE"],
        "other_entity_ids": ["22222222-2222-2222-2222-222222222222"],
    }]}


def _assert_no_scoring_or_probability_keys(result):
    serialized = str(result).lower()
    for forbidden in ("risk_score", "quality_score", "ownership_probability", "coordination_probability", "expected_return_score", "confidence_score"):
        assert forbidden not in serialized
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False


@pytest.mark.asyncio
async def test_historical_motif_outcomes_are_descriptive_and_counted():
    session = _Session([
        {"entity_id": "22222222-2222-2222-2222-222222222222", "mint": "M1", "deployer_wallet": "D1",
         "observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "outcome_status": "RUNNER",
         "outcome_meta": {"observed_at": "2026-09-02T00:00:00+00:00"}, "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
        {"entity_id": "22222222-2222-2222-2222-222222222222", "mint": "M2", "deployer_wallet": "D2",
         "observed_at": datetime(2026, 9, 2, tzinfo=timezone.utc), "outcome_status": "FADE",
         "outcome_meta": {"observed_at": "2026-09-03T00:00:00+00:00"}, "created_at": datetime(2026, 9, 2, tzinfo=timezone.utc)},
    ])
    result = await motif_outcome_context(session, UUID("11111111-1111-1111-1111-111111111111"), network_motifs=_motifs(), launch_limit=20)
    assert result["status"] == "OBSERVED"
    assert result["motif_analogue_count"] == 1
    assert result["launch_analogue_count"] == 2
    assert result["outcome_counts"] == {"RUNNER": 1, "HELD": 0, "FADE": 1, "UNKNOWN": 0}
    assert result["analogue_history_is_not_prediction"] is True
    _assert_no_scoring_or_probability_keys(result)


@pytest.mark.asyncio
async def test_outcome_learned_after_cutoff_is_masked_unknown():
    session = _Session([
        {"entity_id": "22222222-2222-2222-2222-222222222222", "mint": "M1", "deployer_wallet": "D1",
         "observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "outcome_status": "RUNNER",
         "outcome_meta": {"observed_at": "2026-09-05T00:00:00+00:00"}, "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
    ])
    result = await motif_outcome_context(
        session, UUID("11111111-1111-1111-1111-111111111111"), network_motifs=_motifs(),
        as_of=datetime(2026, 9, 3, tzinfo=timezone.utc), launch_limit=20,
    )
    launch = result["records"][0]["launches"][0]
    assert launch["outcome"] == "UNKNOWN"
    assert launch["outcome_observed_at"] == "2026-09-05T00:00:00+00:00"
    assert result["outcome_counts"]["UNKNOWN"] == 1
    assert result["temporal_cutoff_enforced"] is True
    sql, params = session.calls[0]
    assert "l.observed_at <= :as_of" in sql
    assert params["as_of"] == datetime(2026, 9, 3, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_known_outcome_without_observation_time_is_unknown_at_historical_cutoff():
    session = _Session([
        {"entity_id": "22222222-2222-2222-2222-222222222222", "mint": "M1", "deployer_wallet": "D1",
         "observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "outcome_status": "HELD",
         "outcome_meta": {}, "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)},
    ])
    result = await motif_outcome_context(
        session, UUID("11111111-1111-1111-1111-111111111111"), network_motifs=_motifs(),
        as_of=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    assert result["records"][0]["launches"][0]["outcome"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_no_motif_stays_new_unknown_without_fabricated_analogues():
    result = await motif_outcome_context(_Session([]), UUID("11111111-1111-1111-1111-111111111111"), network_motifs={"status": "NEW-UNKNOWN", "records": []})
    assert result["status"] == "NEW-UNKNOWN"
    assert result["motif_analogue_count"] == 0
    assert result["launch_analogue_count"] == 0
    assert result["records"] == []
    _assert_no_scoring_or_probability_keys(result)
