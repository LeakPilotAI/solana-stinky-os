"""Redis Streams concrete implementation of EventTransport (ADR-004).

Business logic must never import this module directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

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
        self._since_trim = 0

    def _new_client(self) -> Redis:
        return Redis.from_url(
            self._redis_url,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=3,
            retry_on_timeout=True,
            health_check_interval=15,
            socket_keepalive=True,
        )

    async def connect(self) -> None:
        if self._redis is not None:
            return
        self._redis = self._new_client()
        await asyncio.wait_for(self._redis.ping(), timeout=3)
        logger.info("redis_streams.connected", url=self._redis_url)

    async def close(self) -> None:
        await self._reset()
        logger.info("redis_streams.closed")

    async def _reset(self) -> None:
        client = self._redis
        self._redis = None
        if client is None:
            return
        try:
            await client.aclose()
        except Exception:
            pass

    def _client(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("Transport not connected. Call connect() first.")
        return self._redis

    async def publish(self, event: Event, *, stream: str | None = None) -> str:
        envelope = EventEnvelope(event=event)
        target = stream or self._default_stream
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                if self._redis is None:
                    await self.connect()
                kwargs: dict[str, Any] = {}
                self._since_trim += 1
                if self._since_trim >= 200:
                    kwargs = {"maxlen": self._maxlen, "approximate": True}
                    self._since_trim = 0
                message_id: bytes = await asyncio.wait_for(
                    self._client().xadd(target, {"data": envelope.to_bytes()}, **kwargs),
                    timeout=4,
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
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "redis_streams.publish_retry",
                    attempt=attempt,
                    error=f"{type(exc).__name__}: {exc}"[:200],
                )
                await self._reset()
                if attempt < 3:
                    await asyncio.sleep(0.25 * attempt)
        assert last_exc is not None
        raise last_exc

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
        """Fast, non-destructive. Never drop the live client from a probe."""
        if self._redis is None:
            return False

        async def _ping() -> bool:
            pong = await self._client().ping()
            return bool(pong)

        try:
            return bool(await asyncio.wait_for(_ping(), timeout=0.4))
        except Exception:
            return False