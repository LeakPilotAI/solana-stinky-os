import pytest
from uuid import uuid4

from stinky_api.historical_outcome_comparison import historical_outcomes_for_analogues


class Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class Session:
    def __init__(self, rows=None, error=False):
        self.rows = rows or []
        self.error = error

    async def execute(self, statement, params):
        if self.error:
            raise RuntimeError("query failed")
        return Result(self.rows)


@pytest.mark.asyncio
async def test_historical_outcomes_are_descriptive_and_bounded():
    analogue_id = uuid4()
    session = Session([
        {
            "entity_id": str(analogue_id),
            "mint": "mint-1",
            "event_id": "event-1",
            "observed_at": None,
            "outcome_status": "completed",
            "outcome_meta": {"observed_at": "2026-09-04T00:00:00+00:00"},
        },
        {
            "entity_id": str(analogue_id),
            "mint": "mint-2",
            "event_id": "event-2",
            "observed_at": None,
            "outcome_status": None,
            "outcome_meta": {},
        },
    ])

    result = await historical_outcomes_for_analogues(
        session,
        [{"entity_id": str(analogue_id)}],
        limit_per_entity=1,
    )

    assert result["status"] == "OBSERVED"
    assert result["evidence_only"] is True
    assert result["records"][0]["launch_count_observed"] == 1
    assert result["records"][0]["outcomes_known"] == 1
    assert result["records"][0]["completed_count"] == 1
    assert result["records"][0]["outcomes_unknown"] == 0
    assert result["records"][0]["launches"][0]["outcome_observed"] is True


@pytest.mark.asyncio
async def test_unknown_when_no_usable_analogue_ids():
    result = await historical_outcomes_for_analogues(
        Session(),
        [{"entity_id": "not-a-uuid"}],
    )

    assert result["status"] == "UNKNOWN"
    assert result["records"] == []
    assert result["missing"] == ["historical_analogue_ids"]
    assert result["evidence_only"] is True


@pytest.mark.asyncio
async def test_query_failure_stays_unknown():
    result = await historical_outcomes_for_analogues(
        Session(error=True),
        [{"entity_id": str(uuid4())}],
    )

    assert result["status"] == "UNKNOWN"
    assert result["missing"] == ["entity_launches"]
    assert result["evidence_only"] is True
