from datetime import datetime, timezone

import pytest

from entity_resolver.launch_history import LaunchHistoryStore


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


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
