import pytest

from stinky_api import db


class _FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


@pytest.mark.asyncio
async def test_request_session_commits_after_success(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(db, "SessionLocal", lambda: session)

    dependency = db.get_session()
    yielded = await anext(dependency)
    assert yielded is session

    with pytest.raises(StopAsyncIteration):
        await anext(dependency)

    assert session.commit_calls == 1
    assert session.rollback_calls == 0


@pytest.mark.asyncio
async def test_request_session_rolls_back_when_handler_raises(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(db, "SessionLocal", lambda: session)

    dependency = db.get_session()
    yielded = await anext(dependency)
    assert yielded is session

    with pytest.raises(RuntimeError, match="boom"):
        await dependency.athrow(RuntimeError("boom"))

    assert session.commit_calls == 0
    assert session.rollback_calls == 1
