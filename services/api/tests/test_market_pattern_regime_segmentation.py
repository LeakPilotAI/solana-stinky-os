from datetime import datetime, timezone

import pytest

from stinky_api.market_pattern_regime_segmentation import (
    classify_regime_state,
    segment_pattern_occurrences_by_regime,
)


class _Mappings:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Result:
    def __init__(self, rows): self.rows = rows
    def mappings(self): return _Mappings(self.rows)


class Session:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None
    async def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _Result(self.rows)


def test_regime_classifier_requires_independent_sample_and_unique_dominance():
    assert classify_regime_state({"STABLE": 1, "IMPROVING": 1, "DEGRADING": 0}, min_independent_patterns=3) == "INSUFFICIENT_EVIDENCE"
    assert classify_regime_state({"STABLE": 2, "IMPROVING": 2, "DEGRADING": 0}, min_independent_patterns=3) == "MIXED"
    assert classify_regime_state({"STABLE": 1, "IMPROVING": 0, "DEGRADING": 3}, min_independent_patterns=3) == "DEGRADING_DOMINANT"
    assert classify_regime_state({"STABLE": 4, "IMPROVING": 1, "DEGRADING": 0}, min_independent_patterns=3) == "STABLE_DOMINANT"


@pytest.mark.asyncio
async def test_segmentation_uses_only_snapshots_visible_by_occurrence_time_and_excludes_target_pattern():
    observed = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    rows = [
        {"occurrence_id": 1, "mint": "M1", "pattern_observed_at": observed, "regime_pattern_hash": "other-a", "trend_status": "DEGRADING", "evidence_through_observed_at": observed, "computed_at": observed, "ingested_at": observed},
        {"occurrence_id": 1, "mint": "M1", "pattern_observed_at": observed, "regime_pattern_hash": "other-b", "trend_status": "DEGRADING", "evidence_through_observed_at": observed, "computed_at": observed, "ingested_at": observed},
        {"occurrence_id": 1, "mint": "M1", "pattern_observed_at": observed, "regime_pattern_hash": "other-c", "trend_status": "STABLE", "evidence_through_observed_at": observed, "computed_at": observed, "ingested_at": observed},
    ]
    session = Session(rows)
    result = await segment_pattern_occurrences_by_regime(
        session,
        "target-pattern",
        occurrence_limit=999,
        regime_lookback_hours=99999,
        min_independent_patterns=3,
        as_of="2026-09-06T00:00:00Z",
    )

    assert result["status"] == "OBSERVED"
    assert result["occurrence_count"] == 1
    assert result["segmented_occurrence_count"] == 1
    assert result["records"][0]["regime_state"] == "DEGRADING_DOMINANT"
    assert result["records"][0]["state_counts"]["DEGRADING"] == 2
    assert result["target_pattern_excluded_from_regime"] is True
    assert result["future_regime_leakage_permitted"] is False
    assert result["bounded"]["occurrence_limit"] == 500
    assert result["bounded"]["regime_lookback_hours"] == 720
    assert "s.pattern_hash <> :pattern_hash" in session.statement
    assert "s.evidence_through_observed_at <= occ.observed_at" in session.statement
    assert "s.computed_at <= occ.observed_at" in session.statement
    assert "s.ingested_at <= occ.observed_at" in session.statement
    assert "s.evidence_through_observed_at >= occ.observed_at - :lookback" in session.statement
    assert "o.observed_at <= :as_of" in session.statement
    assert result["temporal_cutoff_enforced"] is True


@pytest.mark.asyncio
async def test_invalid_as_of_fails_closed_before_query():
    class Exploding:
        async def execute(self, *args, **kwargs):
            raise AssertionError("query should not execute")

    result = await segment_pattern_occurrences_by_regime(Exploding(), "pattern-1", as_of="not-a-time")
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["invalid_as_of"]
