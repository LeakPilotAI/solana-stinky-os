from datetime import datetime, timezone

import pytest

from stinky_api.developer_history_calibration_stability import developer_history_calibration_stability


class _Mappings:
    def __init__(self, rows):
        self._rows = rows
    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []
    def mappings(self):
        return _Mappings(self._rows)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "SELECT id, entity_id::text" in sql:
            return _Result(self.rows)
        return _Result([])


def _rows():
    launches = [
        {"mint": "M1", "observed_at": "2026-08-01T00:00:00+00:00", "outcome_status": "RUNNER"},
        {"mint": "M2", "observed_at": "2026-08-05T00:00:00+00:00", "outcome_status": "FADE"},
        {"mint": "M3", "observed_at": "2026-08-09T00:00:00+00:00", "outcome_status": "HELD"},
        {"mint": "M4", "observed_at": "2026-08-13T00:00:00+00:00", "outcome_status": "RUNNER"},
        {"mint": "M5", "observed_at": "2026-08-17T00:00:00+00:00", "outcome_status": "FADE"},
        {"mint": "M6", "observed_at": "2026-08-21T00:00:00+00:00", "outcome_status": "HELD"},
    ]
    evidence = {"history_state": "KNOWN_HISTORY", "launch_history": {"historical_launch_count": 6, "records": launches}}
    eid = "11111111-1111-1111-1111-111111111111"
    return [
        {"id": 3, "entity_id": eid, "evidence_hash": "h3", "evidence": evidence, "observed_at": datetime(2026, 8, 27, tzinfo=timezone.utc), "ingested_at": datetime(2026, 8, 27, tzinfo=timezone.utc)},
        {"id": 2, "entity_id": eid, "evidence_hash": "h2", "evidence": evidence, "observed_at": datetime(2026, 8, 26, tzinfo=timezone.utc), "ingested_at": datetime(2026, 8, 26, tzinfo=timezone.utc)},
        {"id": 1, "entity_id": eid, "evidence_hash": "h1", "evidence": evidence, "observed_at": datetime(2026, 8, 25, tzinfo=timezone.utc), "ingested_at": datetime(2026, 8, 25, tzinfo=timezone.utc)},
    ]


@pytest.mark.asyncio
async def test_db_entry_point_reads_immutable_history_and_returns_stability():
    entity_id = "11111111-1111-1111-1111-111111111111"
    session = FakeSession(_rows())
    result = await developer_history_calibration_stability(session, entity_id)
    assert result["entity_id"] == entity_id
    assert result["source"] == "developer_longitudinal_snapshots"
    assert result["source_status"] == "OBSERVED"
    assert result["stability_status"] == "STABLE_FOR_DESCRIPTIVE_CALIBRATION"
    assert result["predictive_authority"] is False
    assert any("developer_longitudinal_snapshots" in sql for sql, _ in session.calls)


@pytest.mark.asyncio
async def test_db_entry_point_passes_as_of_to_audit_query():
    entity_id = "11111111-1111-1111-1111-111111111111"
    session = FakeSession(_rows())
    cutoff = datetime(2026, 9, 1, tzinfo=timezone.utc)
    result = await developer_history_calibration_stability(session, entity_id, as_of=cutoff)
    select_params = next(params for sql, params in session.calls if "SELECT id, entity_id::text" in sql)
    assert select_params["as_of"] == cutoff
    assert result["temporal_cutoff_enforced"] is True
