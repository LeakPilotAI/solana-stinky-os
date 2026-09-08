from datetime import datetime, timezone

import pytest

from stinky_api.entity_readiness_historical_depth import (
    entity_readiness_historical_depth,
    summarize_historical_depth,
)


def test_historical_depth_summarizes_prior_launch_and_relationship_thresholds():
    result = summarize_historical_depth(
        [
            {
                "total_launches": 7,
                "prior_launches": 6,
                "prior_classified_outcomes": 4,
                "prior_history_span_days": 9.0,
            },
            {
                "total_launches": 2,
                "prior_launches": 1,
                "prior_classified_outcomes": 1,
                "prior_history_span_days": 0.0,
            },
        ],
        [
            {"distinct_snapshot_count": 5},
            {"distinct_snapshot_count": 2},
        ],
        entity_count=2,
    )

    dev = result["developer_history_depth"]
    rel = result["relationship_history_depth"]
    assert result["status"] == "MEASURED"
    assert dev["entities_with_multiple_total_launches"] == 2
    assert dev["entities_meeting_min_prior_launches"] == 1
    assert dev["entities_meeting_min_prior_known_outcomes"] == 1
    assert dev["entities_meeting_min_prior_outcome_coverage"] == 2
    assert dev["entities_meeting_min_prior_history_span"] == 1
    assert dev["entities_meeting_prior_outcome_gate"] == 1
    assert dev["max_total_launches"] == 7
    assert dev["max_prior_launches"] == 6
    assert dev["max_prior_classified_outcomes"] == 4
    assert rel["entities_with_relationship_snapshots"] == 2
    assert rel["entities_with_two_distinct_relationship_snapshots"] == 2
    assert rel["entities_meeting_min_relationship_snapshots"] == 1
    assert rel["max_distinct_relationship_snapshots"] == 5
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False


class _MappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, result_sets):
        self._result_sets = list(result_sets)
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _MappingsResult(self._result_sets.pop(0))


@pytest.mark.asyncio
async def test_live_historical_depth_reads_prior_launches_and_distinct_relationship_snapshots():
    session = _Session([
        [{
            "entity_id": "00000000-0000-0000-0000-000000000001",
            "total_launches": 6,
            "prior_launches": 5,
            "prior_classified_outcomes": 3,
            "prior_history_span_days": 8.0,
        }],
        [{
            "entity_id": "00000000-0000-0000-0000-000000000001",
            "distinct_snapshot_count": 4,
        }],
    ])

    result = await entity_readiness_historical_depth(
        session,
        entity_ids=["00000000-0000-0000-0000-000000000001"],
        not_before=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )

    assert result["developer_history_depth"]["entities_meeting_prior_outcome_gate"] == 1
    assert result["developer_history_depth"]["entities_meeting_min_prior_history_span"] == 1
    assert result["relationship_history_depth"]["entities_meeting_min_relationship_snapshots"] == 1
    assert "ROW_NUMBER() OVER" in session.calls[0][0]
    assert "COUNT(DISTINCT evidence_hash)" in session.calls[1][0]
    assert result["release_authority"] is False


@pytest.mark.asyncio
async def test_historical_as_of_fails_closed_for_mutable_outcome_depth():
    session = _Session([])
    cutoff = datetime(2026, 9, 8, tzinfo=timezone.utc)

    result = await entity_readiness_historical_depth(
        session,
        entity_ids=["00000000-0000-0000-0000-000000000001"],
        not_before=datetime(2026, 9, 7, tzinfo=timezone.utc),
        as_of=cutoff,
    )

    assert result["status"] == "HISTORICAL_DEPTH_STATE_UNAVAILABLE"
    assert result["historical_as_of_supported"] is False
    assert session.calls == []
    assert result["predictive_authority"] is False
