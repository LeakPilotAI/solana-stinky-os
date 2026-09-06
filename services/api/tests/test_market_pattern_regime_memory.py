from datetime import datetime, timezone

import pytest

from stinky_api.market_pattern_regime_memory import calibration_regime_memory


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


@pytest.mark.asyncio
async def test_regime_memory_counts_latest_visible_independent_patterns():
    rows = [
        {"pattern_hash": "a", "trend_status": "DEGRADING", "evidence_through_observed_at": datetime(2026, 9, 5, 10, tzinfo=timezone.utc), "computed_at": datetime(2026, 9, 5, 11, tzinfo=timezone.utc), "ingested_at": datetime(2026, 9, 5, 11, tzinfo=timezone.utc)},
        {"pattern_hash": "b", "trend_status": "DEGRADING", "evidence_through_observed_at": datetime(2026, 9, 5, 9, tzinfo=timezone.utc), "computed_at": datetime(2026, 9, 5, 10, tzinfo=timezone.utc), "ingested_at": datetime(2026, 9, 5, 10, tzinfo=timezone.utc)},
        {"pattern_hash": "c", "trend_status": "STABLE", "evidence_through_observed_at": datetime(2026, 9, 5, 8, tzinfo=timezone.utc), "computed_at": datetime(2026, 9, 5, 9, tzinfo=timezone.utc), "ingested_at": datetime(2026, 9, 5, 9, tzinfo=timezone.utc)},
    ]
    session = Session(rows)
    result = await calibration_regime_memory(session, as_of="2026-09-05T12:00:00Z", lookback_hours=12, pattern_limit=9999)

    assert result["status"] == "OBSERVED"
    assert result["pattern_count"] == 3
    assert result["degrading_pattern_count"] == 2
    assert result["stable_pattern_count"] == 1
    assert result["shared_cause_inferred"] is False
    assert result["bounded"]["pattern_limit"] == 2000
    assert "DISTINCT ON (pattern_hash)" in session.statement
    assert "evidence_through_observed_at <= :as_of" in session.statement
    assert "computed_at <= :as_of" in session.statement
    assert "ingested_at <= :as_of" in session.statement
    assert session.params["window_start"].isoformat() == "2026-09-05T00:00:00+00:00"
    assert all(k not in result for k in ("prediction", "probability", "confidence", "risk", "quality", "trade_signal"))


@pytest.mark.asyncio
async def test_invalid_cutoff_fails_closed_without_query():
    class ExplodingSession:
        async def execute(self, *args, **kwargs):
            raise AssertionError("query should not execute")
    result = await calibration_regime_memory(ExplodingSession(), as_of="bad-time")
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["invalid_as_of"]
