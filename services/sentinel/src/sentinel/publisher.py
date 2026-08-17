"""Publish detected launches and migrations into the Stinky event pipeline.

Order (durable-first):
  1. Postgres events + outbox (never lose the observation)
  2. Redis Streams (real-time consumers)
  3. Optional HTTP Event Log (compat; non-blocking)

Redis/HTTP failure must not drop chain events.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import orjson
import structlog

from stinky_core.events.base import Event, EventEnvelope, EventType
from stinky_core.transport.redis_streams import RedisStreamsTransport

from sentinel.config import settings
from sentinel.durable import DurableEventStore
from sentinel.models import DetectedLaunch, DetectedMigration

logger = structlog.get_logger(__name__)


def _envelope_to_bytes(envelope_val: object) -> bytes:
    if isinstance(envelope_val, (bytes, bytearray)):
        return bytes(envelope_val)
    if isinstance(envelope_val, str):
        return envelope_val.encode()
    return orjson.dumps(envelope_val)


class LaunchPublisher:
    """Durable-first publisher for TOKEN_LAUNCH, TOKEN_MIGRATED, alerts."""

    def __init__(self) -> None:
        self._transport = RedisStreamsTransport(
            redis_url=settings.redis_url,
            default_stream=settings.event_stream,
        )
        self._connected = False
        self._http = httpx.AsyncClient(timeout=15.0)
        self._durable = DurableEventStore()
        self._relay_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def connect(self) -> None:
        try:
            await self._durable.ensure_schema()
        except Exception as exc:
            logger.error("publisher.durable_schema_failed", error=str(exc))

        try:
            await self._transport.connect()
            self._connected = True
            logger.info("publisher.redis_connected", stream=settings.event_stream)
        except Exception as exc:
            logger.warning("publisher.redis_unavailable", error=str(exc))
            self._connected = False

        self._stop.clear()
        self._relay_task = asyncio.create_task(self._relay_loop())

    async def close(self) -> None:
        self._stop.set()
        if self._relay_task:
            self._relay_task.cancel()
            try:
                await self._relay_task
            except asyncio.CancelledError:
                pass
        if self._connected:
            await self._transport.close()
        await self._durable.close()
        await self._http.aclose()

    async def _publish_event(self, event: Event, *, kind: str, mint: str) -> bool:
        # 1) Durable first
        try:
            appended = await self._durable.append(event)
        except Exception as exc:
            logger.error(
                f"{kind}.durable_failed",
                error=str(exc),
                mint=mint,
                event_id=str(event.event_id),
            )
            appended = True  # still try live paths

        if appended is False:
            return True  # duplicate signature — treat as success

        # 2) Redis real-time
        if self._connected:
            try:
                await self._transport.publish(event)
                await self._durable.mark_published(event.event_id)
                logger.info(
                    f"{kind}.published_redis",
                    mint=mint,
                    event_id=str(event.event_id),
                    event_type=event.event_type.value,
                )
            except Exception as exc:
                logger.error(f"{kind}.redis_publish_failed", error=str(exc))
                await self._durable.mark_publish_failed(event.event_id, str(exc))
        else:
            await self._durable.mark_publish_failed(
                event.event_id, "redis_not_connected"
            )

        # 3) Optional HTTP (compat) — never required for durability
        if settings.event_log_url:
            try:
                body = {
                    "event_id": str(event.event_id),
                    "event_type": event.event_type.value,
                    "payload": event.payload,
                    "slot": event.slot,
                    "block_time": (
                        event.block_time or datetime.now(timezone.utc)
                    ).isoformat(),
                    "signature": event.signature,
                    "producer": event.producer or "sentinel",
                }
                resp = await self._http.post(
                    f"{settings.event_log_url.rstrip('/')}/v1/events",
                    json=body,
                )
                if resp.status_code < 300:
                    logger.info(
                        f"{kind}.published_http",
                        mint=mint,
                        status=resp.status_code,
                    )
                else:
                    logger.debug(
                        f"{kind}.http_rejected",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
            except Exception as exc:
                logger.debug(f"{kind}.http_publish_failed", error=str(exc))

        return True

    async def publish(self, launch: DetectedLaunch) -> bool:
        event = Event(
            event_type=EventType.TOKEN_LAUNCH,
            slot=launch.slot,
            block_time=launch.block_time or datetime.now(timezone.utc),
            signature=launch.signature,
            payload=launch.to_event_payload(),
            producer="sentinel",
        )
        return await self._publish_event(event, kind="launch", mint=launch.mint)

    async def publish_migration(self, migration: DetectedMigration) -> bool:
        event = Event(
            event_type=EventType.TOKEN_MIGRATED,
            slot=migration.slot,
            block_time=migration.block_time or datetime.now(timezone.utc),
            signature=migration.signature,
            payload=migration.to_event_payload(),
            producer="sentinel",
        )
        return await self._publish_event(
            event, kind="migration", mint=migration.mint
        )

    async def publish_raw_event(self, event: Event, *, kind: str) -> bool:
        mint = str(event.payload.get("mint") or "")
        return await self._publish_event(event, kind=kind, mint=mint)

    async def _relay_loop(self) -> None:
        """Retry unpublished outbox rows every 15s."""
        while not self._stop.is_set():
            try:
                await asyncio.sleep(15.0)
                if not self._connected:
                    try:
                        await self._transport.connect()
                        self._connected = True
                    except Exception:
                        continue
                rows = await self._durable.drain_unpublished(limit=30)
                for row in rows:
                    try:
                        env = EventEnvelope.from_bytes(
                            _envelope_to_bytes(row["envelope"])
                        )
                        await self._transport.publish(env.event)
                        await self._durable.mark_published(env.event.event_id)
                        logger.info(
                            "outbox.relayed",
                            event_id=str(env.event.event_id),
                            event_type=env.event.event_type.value,
                        )
                    except Exception as exc:
                        eid = row.get("event_id")
                        if eid:
                            from uuid import UUID

                            await self._durable.mark_publish_failed(
                                UUID(str(eid)), str(exc)
                            )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("outbox.relay_error", error=str(exc))
