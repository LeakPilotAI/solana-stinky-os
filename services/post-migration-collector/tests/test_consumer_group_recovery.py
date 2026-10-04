import asyncio

import pytest
from redis.exceptions import ResponseError

from post_migration.service import CollectorService
from post_migration.config import settings


class FakeRedis:
    def __init__(self, *, read_error=None, create_error=None):
        self.read_error = read_error
        self.create_error = create_error
        self.read_calls = 0
        self.create_calls = 0

    async def xreadgroup(self, **kwargs):
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        return []

    async def xgroup_create(self, *args, **kwargs):
        self.create_calls += 1
        if self.create_error is not None:
            raise self.create_error
        return True


def service_with(redis):
    service = object.__new__(CollectorService)
    service._redis = redis
    return service


def test_startup_database_probe_times_out_before_any_write():
    service = object.__new__(CollectorService)

    class StuckStore:
        async def health(self):
            await asyncio.Event().wait()

    service._store = StuckStore()

    async def exercise():
        with pytest.raises(TimeoutError):
            await service._require_startup_database(timeout_sec=0.01)

    asyncio.run(exercise())


def test_startup_database_probe_fails_closed_when_unavailable():
    service = object.__new__(CollectorService)

    class UnhealthyStore:
        async def health(self):
            return False

    service._store = UnhealthyStore()

    with pytest.raises(ConnectionError, match="startup database health probe failed"):
        asyncio.run(service._require_startup_database(timeout_sec=0.1))


def test_startup_database_probe_allows_healthy_transport():
    service = object.__new__(CollectorService)

    class HealthyStore:
        async def health(self):
            return True

    service._store = HealthyStore()
    asyncio.run(service._require_startup_database(timeout_sec=0.1))


def test_startup_database_probe_precedes_schema_and_recovery_writes():
    source = __import__("pathlib").Path(
        __import__("post_migration.service", fromlist=["__file__"]).__file__
    ).read_text(encoding="utf-8")
    start = source[source.index("    async def start(self) -> None:"):source.index("    async def _ensure_consumer_group")]
    probe = start.index("await self._require_startup_database()")
    schema = start.index("await self._store.ensure_schema()")
    recovery = start.index("await self._store.fail_stale_active_tracks")
    assert probe < schema < recovery


def test_missing_group_is_recreated_before_next_read():
    redis = FakeRedis(read_error=ResponseError("NOGROUP No such key or consumer group"))
    service = service_with(redis)

    rows = asyncio.run(service._read_group("collector-test"))

    assert rows == []
    assert redis.read_calls == 1
    assert redis.create_calls == 1


def test_existing_group_is_an_idempotent_success():
    redis = FakeRedis(create_error=ResponseError("BUSYGROUP Consumer Group name already exists"))
    service = service_with(redis)

    created = asyncio.run(service._ensure_consumer_group())

    assert created is False
    assert redis.create_calls == 1


def test_group_creation_does_not_hide_real_redis_errors():
    redis = FakeRedis(create_error=ResponseError("WRONGTYPE Operation against a key"))
    service = service_with(redis)

    with pytest.raises(ResponseError, match="WRONGTYPE"):
        asyncio.run(service._ensure_consumer_group())


def test_read_does_not_reclassify_unrelated_redis_errors_as_missing_group():
    redis = FakeRedis(read_error=ResponseError("WRONGTYPE Operation against a key"))
    service = service_with(redis)

    with pytest.raises(ResponseError, match="WRONGTYPE"):
        asyncio.run(service._read_group("collector-test"))

    assert redis.create_calls == 0


def test_recovery_uses_configured_stream_and_group():
    class CaptureRedis(FakeRedis):
        async def xgroup_create(self, stream, group, **kwargs):
            self.create_calls += 1
            assert stream == settings.event_stream
            assert group == settings.collector_consumer_group
            assert kwargs == {"id": "0", "mkstream": True}
            return True

    redis = CaptureRedis()
    service = service_with(redis)
    assert asyncio.run(service._ensure_consumer_group()) is True
