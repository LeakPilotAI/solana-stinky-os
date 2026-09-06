from datetime import datetime, timezone

import pytest

from stinky_api.market_pattern_calibration_memory import (
    calibration_longitudinal_memory,
    persist_rolling_calibration_snapshot,
)


class _Mappings:
    def __init__(self, rows): self.rows = rows
    def all(self): return self.rows


class _Result:
    def __init__(self, *, first=None, rows=None):
        self._first = first
        self._rows = rows or []
    def first(self): return self._first
    def mappings(self): return _Mappings(self._rows)


class PersistSession:
    def __init__(self, *, insert_row=(7,), existing_row=None):
        self.insert_row = insert_row
        self.existing_row = existing_row
        self.statements = []
        self.params = []
        self.commits = 0
        self.rollbacks = 0
    async def execute(self, statement, params):
        sql = str(statement)
        self.statements.append(sql)
        self.params.append(params)
        if "INSERT INTO market_pattern_calibration_snapshots" in sql:
            return _Result(first=self.insert_row)
        return _Result(first=self.existing_row)
    async def commit(self): self.commits += 1
    async def rollback(self): self.rollbacks += 1


class HistorySession:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None
    async def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _Result(rows=self.rows)


def _rolling():
    return {
        "status": "OBSERVED",
        "pattern_hash": "pattern-1",
        "trend_status": "STABLE",
        "window_count": 2,
        "evaluated_window_count": 2,
        "criteria": {"evaluation_window_occurrences": 2, "max_windows": 20},
        "windows": [
            {"evaluation_window": {"last_observed_at": "2026-09-01T01:00:00Z"}},
            {"evaluation_window": {"last_observed_at": "2026-09-02T01:00:00Z"}},
        ],
        "evidence_only": True,
    }


@pytest.mark.asyncio
async def test_persist_snapshot_uses_evidence_boundary_and_idempotency_key():
    session = PersistSession()
    result = await persist_rolling_calibration_snapshot(
        session,
        _rolling(),
        computed_at="2026-09-03T00:00:00Z",
    )

    assert result["snapshot_id"] == 7
    assert result["evidence_through_observed_at"] == "2026-09-02T01:00:00+00:00"
    assert len(result["criteria_hash"]) == 64
    assert "ON CONFLICT (pattern_hash, evidence_through_observed_at, criteria_hash)" in session.statements[0]
    assert session.params[0]["trend_status"] == "STABLE"
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_duplicate_snapshot_returns_existing_id_without_incrementing_history():
    session = PersistSession(insert_row=None, existing_row=(9,))
    result = await persist_rolling_calibration_snapshot(session, _rolling())

    assert result["snapshot_id"] == 9
    assert session.commits == 0
    assert session.rollbacks == 1
    assert len(session.statements) == 2


@pytest.mark.asyncio
async def test_missing_evidence_boundary_is_not_persisted():
    session = PersistSession()
    rolling = _rolling()
    rolling["windows"] = []
    assert await persist_rolling_calibration_snapshot(session, rolling) is None
    assert session.statements == []


@pytest.mark.asyncio
async def test_longitudinal_history_is_bounded_and_cutoff_safe():
    rows = [
        {
            "id": 1,
            "pattern_hash": "pattern-1",
            "evidence_through_observed_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "as_of": None,
            "computed_at": datetime(2026, 9, 1, 1, tzinfo=timezone.utc),
            "ingested_at": datetime(2026, 9, 1, 1, 1, tzinfo=timezone.utc),
            "trend_status": "STABLE",
            "window_count": 2,
            "evaluated_window_count": 2,
            "criteria_hash": "h",
            "criteria": {},
            "snapshot": {"trend_status": "STABLE"},
            "evidence_basis": "successive_chronological_reference_and_evaluation_windows",
            "created_at": datetime(2026, 9, 1, 1, 1, tzinfo=timezone.utc),
        }
    ]
    session = HistorySession(rows)
    result = await calibration_longitudinal_memory(
        session,
        "pattern-1",
        limit=999,
        as_of="2026-09-02T00:00:00Z",
    )

    assert result["status"] == "OBSERVED"
    assert result["snapshot_count"] == 1
    assert result["bounded"]["limit"] == 500
    assert result["temporal_cutoff_enforced"] is True
    assert "evidence_through_observed_at <= :as_of" in session.statement
    assert session.params["as_of"].isoformat() == "2026-09-02T00:00:00+00:00"
    assert result["records"][0]["trend_status"] == "STABLE"
    assert result["evidence_only"] is True
    assert all(k not in result for k in ("prediction", "probability", "confidence", "risk", "quality", "trade_signal"))


@pytest.mark.asyncio
async def test_invalid_history_cutoff_fails_closed_without_query():
    class ExplodingSession:
        async def execute(self, *args, **kwargs):
            raise AssertionError("query should not execute")

    result = await calibration_longitudinal_memory(ExplodingSession(), "pattern-1", as_of="not-a-time")
    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["invalid_as_of"]
