from datetime import datetime, timezone

import pytest

from stinky_api.cross_investigation_calibration_change_feed import calibration_change_feed


class _Mappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _Mappings(self._rows)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = None

    async def execute(self, statement, params=None):
        self.sql = str(statement)
        self.params = params
        return _Result(self.rows)


def _summary(state, missing=None):
    return {
        "pattern_hash": "p1",
        "evidence_status": "PARTIAL_EVIDENCE",
        "observed_layer_count": 4,
        "layer_count": 7,
        "current_calibration_state": state,
        "transition_count": 1,
        "regime_memory": {"state_counts": {"STABLE": 2}},
        "conditional_evidence": {"sufficient_regimes": []},
        "chronological_generalization": {
            "stable_regimes": [],
            "unstable_regimes": [],
            "insufficient_regimes": [],
        },
        "missing": missing or [],
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "predictive_authority": False,
        "trade_signal": False,
        "shared_cause_inferred": False,
        "evidence_only": True,
    }


@pytest.mark.asyncio
async def test_feed_describes_latest_cross_pattern_delta_and_maps_mint():
    now = datetime(2026, 9, 6, 3, 0, tzinfo=timezone.utc)
    rows = [{
        "pattern_hash": "p1",
        "current_synthesis": _summary("STABLE"),
        "previous_synthesis": _summary("INSUFFICIENT_EVIDENCE", ["followup"]),
        "current_observed_at": now,
        "current_ingested_at": now,
        "previous_observed_at": now,
        "mint": "mint1",
        "occurrence_observed_at": now,
    }]
    session = FakeSession(rows)
    feed = await calibration_change_feed(session, limit=25)

    assert feed["status"] == "OBSERVED"
    assert feed["count"] == 1
    assert feed["items"][0]["mint"] == "mint1"
    assert "FIELD_CHANGED" in feed["items"][0]["change_kinds"]
    assert "UNKNOWN_RESOLVED" in feed["items"][0]["change_kinds"]
    assert feed["predictive_authority"] is False
    assert feed["trade_signal"] is False
    assert feed["shared_cause_inferred"] is False
    assert "ROW_NUMBER() OVER" in session.sql
    assert "PARTITION BY s.pattern_hash" in session.sql


@pytest.mark.asyncio
async def test_feed_as_of_is_applied_before_snapshot_ranking():
    session = FakeSession([])
    cutoff = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    feed = await calibration_change_feed(session, as_of=cutoff)

    assert "s.observed_at <= :as_of" in session.sql
    assert "s.ingested_at <= :as_of" in session.sql
    assert session.params["as_of"] == cutoff
    assert feed["as_of"] == cutoff.isoformat()
    assert feed["temporal_cutoff_enforced"] is True


@pytest.mark.asyncio
async def test_feed_invalid_as_of_fails_closed_without_query():
    session = FakeSession([])
    feed = await calibration_change_feed(session, as_of="not-a-time")

    assert feed["status"] == "UNKNOWN"
    assert feed["items"] == []
    assert feed["missing"] == ["valid_as_of"]
    assert session.sql == ""


@pytest.mark.asyncio
async def test_unchanged_is_hidden_by_default():
    now = datetime(2026, 9, 6, 3, 0, tzinfo=timezone.utc)
    same = _summary("STABLE")
    rows = [{
        "pattern_hash": "p1",
        "current_synthesis": same,
        "previous_synthesis": same,
        "current_observed_at": now,
        "current_ingested_at": now,
        "previous_observed_at": now,
        "mint": "mint1",
        "occurrence_observed_at": now,
    }]
    session = FakeSession(rows)
    feed = await calibration_change_feed(session)
    assert feed["items"] == []
    assert feed["count"] == 0
