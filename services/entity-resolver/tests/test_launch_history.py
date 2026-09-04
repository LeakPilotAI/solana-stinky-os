from datetime import datetime, timezone
from uuid import uuid4

import pytest

from entity_resolver.launch_history import LaunchHistoryStore


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row

    def mappings(self):
        return self

    def all(self):
        return self._row or []


class _Session:
    def __init__(self, row):
        self.row = row
        self.committed = False
        self.rolled_back = False
        self.params = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        self.params = params
        return _Result(self.row)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class _Sessions:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


@pytest.mark.asyncio
async def test_record_outcome_updates_known_launch() -> None:
    session = _Session((123,))
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    observed = datetime(2026, 9, 4, 12, 34, 56, 123456, tzinfo=timezone.utc)
    result = await store.record_outcome(
        mint="MINT",
        status="completed",
        metadata={"peak_multiple": 3.2},
        observed_at=observed,
    )

    assert result is True
    assert session.committed is True
    assert session.rolled_back is False
    assert session.params["mint"] == "MINT"
    assert session.params["status"] == "completed"
    assert "2026-09-04T12:34:56.123456+00:00" in session.params["metadata"]


@pytest.mark.asyncio
async def test_record_outcome_does_not_create_unknown_history() -> None:
    session = _Session(None)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    result = await store.record_outcome(mint="UNKNOWN", status="completed")

    assert result is False
    assert session.committed is False
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_list_deployer_launches_returns_history_and_bounds_limit() -> None:
    rows = [
        {
            "id": 1,
            "mint": "MINT1",
            "outcome_status": "completed",
            "outcome_meta": {"peak_multiple": 2.0},
        }
    ]
    session = _Session(rows)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    result = await store.list_deployer_launches(
        deployer_wallet="DEPLOYER",
        limit=9999,
    )

    assert result == rows
    assert session.params == {"wallet": "DEPLOYER", "limit": 500}


@pytest.mark.asyncio
async def test_list_entity_launches_uses_entity_id_and_default_limit() -> None:
    rows = [{"id": 7, "mint": "MINT7", "outcome_status": None}]
    session = _Session(rows)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)
    entity_id = uuid4()

    result = await store.list_entity_launches(entity_id=entity_id)

    assert result == rows
    assert session.params == {"eid": entity_id, "limit": 100}


@pytest.mark.asyncio
async def test_deployer_history_summary_returns_evidence_counts() -> None:
    row = {
        "launch_count": 6,
        "outcomes_known": 4,
        "completed_count": 4,
        "outcomes_unknown": 2,
        "first_launch_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_launch_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
    }
    session = _Session(row)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    result = await store.get_deployer_history_summary(deployer_wallet="DEPLOYER")

    assert result == {"deployer_wallet": "DEPLOYER", **row}
    assert session.params == {"wallet": "DEPLOYER"}
