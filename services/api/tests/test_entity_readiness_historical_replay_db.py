import pytest

from stinky_api import entity_readiness_historical_replay as replay


class _Result:
    def __init__(self, rows):
        self._rows = rows
    def mappings(self):
        return self
    def all(self):
        return self._rows


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result(self.responses.pop(0))


@pytest.mark.asyncio
async def test_db_replay_aggregates_cohort_and_clamps_bounds():
    entity_id = "00000000-0000-0000-0000-000000000001"
    session = _Session([
        [{"entity_id": entity_id, "latest_observed_at": None}],
        [
            {"observed_at": "2026-08-01T12:00:00Z", "ingested_at": "2026-08-01T12:01:00Z", "readiness": {"status": "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION", "ready": False, "blockers": ["X"]}},
            {"observed_at": "2026-08-10T12:00:00Z", "ingested_at": "2026-08-10T12:01:00Z", "readiness": {"status": "READY_FOR_DESCRIPTIVE_CALIBRATION", "ready": True, "blockers": []}},
        ],
    ])
    result = await replay.historical_entity_readiness_replay(session, entity_limit=999, snapshot_limit_per_entity=999)
    assert result["status"] == "VALIDATED"
    assert result["counts"]["validated"] == 1
    assert result["counts"]["entity_count"] == 1
    assert result["bounded"] == {"entity_limit": 500, "snapshot_limit_per_entity": 200}
    assert session.calls[0][1]["entity_limit"] == 500
    assert session.calls[1][1]["limit"] == 200


@pytest.mark.asyncio
async def test_db_replay_unavailable_table_is_insufficient_not_fabricated():
    class Broken:
        async def execute(self, statement, params=None):
            raise RuntimeError("missing")
    result = await replay.historical_entity_readiness_replay(Broken())
    assert result["status"] == "INSUFFICIENT_CAPTURED_HISTORY"
    assert result["valid"] is False
    assert result["blockers"] == ["ENTITY_READINESS_SNAPSHOTS_UNAVAILABLE"]
    assert result["historical_snapshot_reconstruction_authorized"] is False
