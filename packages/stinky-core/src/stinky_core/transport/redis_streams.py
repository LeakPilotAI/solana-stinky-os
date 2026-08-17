"""Redis Streams concrete implementation of EventTransport (ADR-004).

Business logic must never import this module directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import orjson
import structlog
from redis.asyncio import Redis

from stinky_core.events.base import Event, EventEnvelope
from stinky_core.transport.base import EventTransport

logger = structlog.get_logger(__name__)


class RedisStreamsTransport(EventTransport):
    """Production-ready Redis Streams transport."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        default_stream: str = "stinky.events",
        maxlen: int = 10_000_000,
    ) -> None:
        self._redis_url = redis_url
        self._default_stream = default_stream
        self._maxlen = maxlen
        self._redis: Redis | None = None

    async def connect(self) -> None:
        if self._redis is not None:
            return
        self._redis = Redis.from_url(self._redis_url, decode_responses=False)
        await self._redis.ping()
        logger.info("redis_streams.connected", url=self._redis_url)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            logger.info("redis_streams.closed")

    def _client(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("Transport not connected. Call connect() first.")
        return self._redis

    async def publish(self, event: Event, *, stream: str | None = None) -> str:
        envelope = EventEnvelope(event=event)
        target = stream or self._default_stream
        message_id: bytes = await self._client().xadd(
            target,
            {"data": envelope.to_bytes()},
            maxlen=self._maxlen,
            approximate=True,
        )
        mid = message_id.decode() if isinstance(message_id, bytes) else str(message_id)
        logger.debug(
            "event.published",
            stream=target,
            event_type=event.event_type,
            event_id=str(event.event_id),
            message_id=mid,
        )
        return mid

    async def publish_batch(
        self, events: Sequence[Event], *, stream: str | None = None
    ) -> list[str]:
        ids: list[str] = []
        for event in events:
            mid = await self.publish(event, stream=stream)
            ids.append(mid)
        return ids

    async def consume(
        self,
        stream: str,
        group: str,
        consumer_name: str,
        *,
        count: int = 10,
        block_ms: int = 5000,
    ) -> AsyncIterator[tuple[str, EventEnvelope]]:
        client = self._client()
        # Ensure group exists (idempotent)
        try:
            await client.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:  # group already exists
            pass

        while True:
            results: list[Any] = await client.xreadgroup(
                groupname=group,
                consumername=consumer_name,
                streams={stream: ">"},
                count=count,
                block=block_ms,
            )
            if not results:
                continue
            for _stream_name, messages in results:
                for message_id, fields in messages:
                    mid = (
                        message_id.decode()
                        if isinstance(message_id, bytes)
                        else str(message_id)
                    )
                    raw = fields.get(b"data") or fields.get("data")
                    if raw is None:
                        logger.warning("message.missing_data", message_id=mid)
                        await self.ack(stream, group, mid)
                        continue
                    try:
                        envelope = EventEnvelope.from_bytes(raw)
                        yield mid, envelope
                    except Exception as exc:
                        logger.exception(
                            "message.deserialize_failed",
                            message_id=mid,
                            error=str(exc),
                        )
                        # Dead-letter path would go here; for now we ack to avoid poison
                        await self.ack(stream, group, mid)

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        await self._client().xack(stream, group, message_id)

    async def create_consumer_group(
        self, stream: str, group: str, *, start_id: str = "0"
    ) -> None:
        try:
            await self._client().xgroup_create(
                stream, group, id=start_id, mkstream=True
            )
            logger.info("consumer_group.created", stream=stream, group=group)
        except Exception as exc:
            # BUSYGROUP = already exists
            if "BUSYGROUP" not in str(exc):
                raise
            logger.debug("consumer_group.exists", stream=stream, group=group)

    async def health_check(self) -> bool:
        try:
            pong = await self._client().ping()
            return bool(pong)
        except Exception:
            return False
