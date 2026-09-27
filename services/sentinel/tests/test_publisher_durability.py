import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from sentinel import publisher as module
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
