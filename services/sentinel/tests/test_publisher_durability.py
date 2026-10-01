import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from sentinel import publisher as module
from sentinel.durable import DurableEventStore
from sentinel.migration_watcher import MigrationWatcher
from sentinel.models import DetectedMigration
from sentinel.models import DetectedLaunch, WalletSummary
from sentinel.watcher import PumpFunWatcher
from stinky_core.events.base import Event, EventType


def publisher(append_result=True, append_error=None, connected=True):
    instance = object.__new__(module.LaunchPublisher)
    instance._connected = connected
    instance._durable = Mock(
        append=AsyncMock(return_value=append_result, side_effect=append_error),
        mark_published=AsyncMock(), mark_publish_failed=AsyncMock(),
    )
    instance._transport = Mock(publish=AsyncMock())
    instance._http = Mock(post=AsyncMock(return_value=Mock(status_code=200)))
    return instance


@pytest.mark.parametrize("connected", [True, False])
def test_failed_durable_append_blocks_all_live_delivery(monkeypatch, connected):
    monkeypatch.setattr(module.settings, "event_log_url", "https://events.example")
    instance = publisher(append_error=RuntimeError("synthetic database failure"), connected=connected)
    event = Event(event_type=EventType.TOKEN_MIGRATED, payload={"mint": "synthetic"})
    with pytest.raises(RuntimeError, match="durable event persistence failed"):
        asyncio.run(instance._publish_event(event, kind="migration", mint="synthetic"))
    instance._transport.publish.assert_not_awaited()
    instance._http.post.assert_not_awaited()
    instance._durable.mark_published.assert_not_awaited()
    instance._durable.mark_publish_failed.assert_not_awaited()


@pytest.mark.parametrize("duplicate,connected", [(False, True), (False, False), (True, True)])
def test_successful_append_and_duplicate_preserve_outbox_contract(monkeypatch, duplicate, connected):
    monkeypatch.setattr(module.settings, "event_log_url", "https://events.example")
    instance = publisher(append_result=not duplicate, connected=connected)
    event = Event(event_type=EventType.TOKEN_MIGRATED, payload={"mint": "synthetic"})
    assert asyncio.run(instance._publish_event(event, kind="migration", mint="synthetic")) is True
    if duplicate:
        instance._transport.publish.assert_not_awaited()
        instance._http.post.assert_not_awaited()
    elif connected:
        instance._transport.publish.assert_awaited_once_with(event)
        instance._durable.mark_published.assert_awaited_once_with(event.event_id)
    else:
        instance._transport.publish.assert_not_awaited()
        instance._durable.mark_publish_failed.assert_awaited_once_with(event.event_id, "redis_not_connected")
    if not duplicate:
        body = instance._http.post.await_args.kwargs["json"]
        assert body["event_id"] == str(event.event_id)
        assert body["occurred_at"] == event.occurred_at.isoformat()


@pytest.mark.parametrize("failure", [RuntimeError("durable event persistence failed"), asyncio.CancelledError()])
def test_migration_retry_after_publish_failure_is_not_deduplicated(failure):
    pub = Mock(publish_migration=AsyncMock(side_effect=[failure, True]))
    volume = Mock()
    watcher = MigrationWatcher(pub, volume_monitor=volume, rpc=Mock())
    migration = DetectedMigration(mint="synthetic-mint", pool="synthetic-pool", signature="synthetic-signature")

    async def scenario():
        with pytest.raises(type(failure)):
            await watcher._handle(migration)
        assert watcher._cnt_published == 0
        volume.watch.assert_not_called()
        await watcher._handle(migration)
        await watcher._handle(migration)

    asyncio.run(scenario())
    assert pub.publish_migration.await_count == 2
    assert watcher._cnt_published == 1
    volume.watch.assert_called_once_with(migration)


@pytest.mark.parametrize("failure", [RuntimeError("durable event persistence failed"), asyncio.CancelledError()])
def test_launch_retry_after_publish_failure_is_not_deduplicated(failure):
    pub = Mock(publish=AsyncMock(side_effect=[failure, True]))
    history = Mock(summarize=AsyncMock(return_value=WalletSummary(address="synthetic-deployer")))
    watcher = PumpFunWatcher(pub, rpc=Mock(), history=history)
    launch = DetectedLaunch(mint="synthetic-mint", deployer="synthetic-deployer", signature="synthetic-signature")

    async def scenario():
        with pytest.raises(type(failure)):
            await watcher._handle_launch(launch)
        await watcher._handle_launch(launch)
        await watcher._handle_launch(launch)

    asyncio.run(scenario())
    assert pub.publish.await_count == 2


def test_redis_failure_after_persistence_retains_outbox_retry(monkeypatch):
    monkeypatch.setattr(module.settings, "event_log_url", "")
    instance = publisher()
    instance._transport.publish.side_effect = RuntimeError("synthetic redis failure")
    event = Event(event_type=EventType.TOKEN_MIGRATED, payload={"mint": "synthetic"})
    assert asyncio.run(instance._publish_event(event, kind="migration", mint="synthetic")) is True
    instance._durable.append.assert_awaited_once_with(event)
    instance._durable.mark_published.assert_not_awaited()
    instance._durable.mark_publish_failed.assert_awaited_once_with(event.event_id, "synthetic redis failure")


class _ExecuteResult:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class _DurableSession:
    def __init__(self, *, reservation_won: bool):
        self.reservation_won = reservation_won
        self.statements = []
        self.commits = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params or {}))
        if "INSERT INTO event_idempotency" in sql:
            return _ExecuteResult(("reserved",) if self.reservation_won else None)
        return _ExecuteResult()

    async def commit(self):
        self.commits += 1


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _durable_store_with_session(session):
    store = object.__new__(DurableEventStore)
    store._ready = True
    store._sessions = lambda: _SessionContext(session)
    return store


def test_atomic_idempotency_loser_never_persists_event_or_outbox():
    session = _DurableSession(reservation_won=False)
    store = _durable_store_with_session(session)
    event = Event(
        event_type=EventType.ALERT_CANDIDATE,
        signature="same-chain-signature",
        payload={"mint": "synthetic"},
    )

    assert asyncio.run(store.append(event)) is False

    sql = "\n".join(statement for statement, _ in session.statements)
    assert "INSERT INTO event_idempotency" in sql
    assert "ON CONFLICT (idem_key) DO NOTHING" in sql
    assert "RETURNING event_id" in sql
    assert "SELECT event_id FROM event_idempotency" not in sql
    assert "INSERT INTO events" not in sql
    assert "INSERT INTO event_outbox" not in sql
    assert session.commits == 0


def test_atomic_idempotency_winner_reserves_before_event_and_outbox():
    session = _DurableSession(reservation_won=True)
    store = _durable_store_with_session(session)
    event = Event(
        event_type=EventType.ALERT_CANDIDATE,
        signature="same-chain-signature",
        payload={"mint": "synthetic"},
    )

    assert asyncio.run(store.append(event)) is True

    sql = [statement for statement, _ in session.statements]
    reserve_i = next(i for i, statement in enumerate(sql) if "INSERT INTO event_idempotency" in statement)
    event_i = next(i for i, statement in enumerate(sql) if "INSERT INTO events" in statement)
    outbox_i = next(i for i, statement in enumerate(sql) if "INSERT INTO event_outbox" in statement)
    assert reserve_i < event_i < outbox_i
    assert session.commits == 1
