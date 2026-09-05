from datetime import datetime, timezone
from uuid import uuid4

import pytest

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
        self.params = []

    async def execute(self, statement, params):
        self.params.append(params)
        if self.error:
            raise RuntimeError("query failed")
        cutoff = params.get("as_of")
        rows = self.rows
        if cutoff is not None:
            rows = [row for row in rows if row.get("observed_at") is None or row["observed_at"] <= cutoff]
        return Result(rows)


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
async def test_historical_outcomes_respect_as_of_cutoff():
    analogue_id = uuid4()
    cutoff = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    session = Session([
        {
            "entity_id": str(analogue_id),
            "mint": "before",
            "event_id": "before-event",
            "observed_at": datetime(2026, 9, 4, 11, tzinfo=timezone.utc),
            "outcome_status": "completed",
            "outcome_meta": {},
        },
        {
            "entity_id": str(analogue_id),
            "mint": "future",
            "event_id": "future-event",
            "observed_at": datetime(2026, 9, 4, 13, tzinfo=timezone.utc),
            "outcome_status": "completed",
            "outcome_meta": {},
        },
    ])

    result = await historical_outcomes_for_analogues(
        session,
        [{"entity_id": str(analogue_id)}],
        as_of=cutoff,
    )

    launches = result["records"][0]["launches"]
    assert [launch["mint"] for launch in launches] == ["before"]
    assert result["as_of"] == cutoff.isoformat()
    assert result["temporal_cutoff_enforced"] is True
    assert session.params[0]["as_of"] == cutoff


@pytest.mark.asyncio
async def test_invalid_outcome_cutoff_is_unknown():
    result = await historical_outcomes_for_analogues(
        Session(),
        [{"entity_id": str(uuid4())}],
        as_of="not-a-timestamp",
    )

    assert result["status"] == "UNKNOWN"
    assert result["records"] == []
    assert result["missing"] == ["invalid_as_of"]
    assert result["evidence_only"] is True


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
