from datetime import datetime, timezone

import pytest

from stinky_api.market_pattern_outcome_calibration import calibrate_market_pattern_outcomes


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


class Session:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None

    async def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _Result(self.rows)


@pytest.mark.asyncio
async def test_pattern_followup_coverage_is_descriptive_and_horizon_specific():
    rows = [
        {
            "occurrence_id": 1,
            "mint": "A",
            "pattern_observed_at": datetime(2026, 9, 1, 0, 15, tzinfo=timezone.utc),
            "horizon": "30m",
            "horizon_seconds": 1800,
            "followup_observed_at": datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc),
            "followup_ingested_at": datetime(2026, 9, 1, 0, 31, tzinfo=timezone.utc),
            "source": "market_snapshot",
            "evidence_basis": "market_snapshot_observation",
            "metrics": {"price_usd": 2.0},
        },
        {
            "occurrence_id": 1,
            "mint": "A",
            "pattern_observed_at": datetime(2026, 9, 1, 0, 15, tzinfo=timezone.utc),
            "horizon": "1h",
            "horizon_seconds": 3600,
            "followup_observed_at": datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
            "followup_ingested_at": datetime(2026, 9, 1, 1, 1, tzinfo=timezone.utc),
            "source": "market_snapshot",
            "evidence_basis": "market_snapshot_observation",
            "metrics": {"price_usd": 1.5},
        },
        {
            "occurrence_id": 2,
            "mint": "B",
            "pattern_observed_at": datetime(2026, 9, 2, 0, 15, tzinfo=timezone.utc),
            "horizon": None,
            "horizon_seconds": None,
            "followup_observed_at": None,
            "followup_ingested_at": None,
            "source": None,
            "evidence_basis": None,
            "metrics": None,
        },
    ]
    session = Session(rows)
    result = await calibrate_market_pattern_outcomes(session, "hash-1")

    assert result["status"] == "OBSERVED"
    assert result["occurrence_count"] == 2
    assert result["occurrences_with_followup"] == 1
    assert result["occurrences_without_followup"] == 1
    assert result["followup_coverage"] == 0.5
    assert result["horizon_coverage"]["30m"]["coverage"] == 0.5
    assert result["horizon_coverage"]["1h"]["coverage"] == 0.5
    assert result["horizon_coverage"]["24h"]["coverage"] == 0.0
    assert result["records"][1]["followup_records"] == []
    assert result["evidence_only"] is True
    assert all(k not in result for k in ("prediction", "probability", "risk", "quality", "trade_signal"))


@pytest.mark.asyncio
async def test_pattern_followup_query_enforces_strict_after_boundary_and_as_of():
    session = Session([])
    result = await calibrate_market_pattern_outcomes(
        session,
        "hash-2",
        as_of="2026-09-03T00:00:00Z",
    )

    assert "mo.observed_at > o.observed_at" in session.statement
    assert "observed_at <= :as_of" in session.statement
    assert "mo.observed_at <= :as_of" in session.statement
    assert session.params["as_of"].isoformat() == "2026-09-03T00:00:00+00:00"
    assert result["status"] == "UNKNOWN"
    assert result["temporal_cutoff_enforced"] is True


@pytest.mark.asyncio
async def test_invalid_as_of_fails_closed_without_query():
    class ExplodingSession:
        async def execute(self, *args, **kwargs):
            raise AssertionError("query must not run")

    result = await calibrate_market_pattern_outcomes(
        ExplodingSession(),
        "hash-3",
        as_of="not-a-time",
    )

    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["invalid_as_of"]
    assert result["followup_coverage"] is None
