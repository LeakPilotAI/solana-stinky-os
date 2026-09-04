"""Entity resolver service – batch + optional event-driven hooks."""

from __future__ import annotations

import asyncio
import json

import redis.asyncio as redis
import structlog

from entity_resolver.config import settings
from entity_resolver.resolver import EntityResolver
from entity_resolver.store import EntityStore

logger = structlog.get_logger(__name__)


class EntityService:
    def __init__(self) -> None:
        self._store = EntityStore()
        self._resolver = EntityResolver(self._store)
        self._redis: redis.Redis | None = None
        self._running = False

    async def start(self) -> None:
        await self._store.ensure_schema()
        self._redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
            retry_on_timeout=False,
            health_check_interval=30,
            socket_keepalive=True,
        )
        try:
            await self._redis.xgroup_create(
                settings.event_stream,
                settings.entity_consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception:
            pass
        self._running = True
        logger.info(
            "entity_service.started",
            stream=settings.event_stream,
            group=settings.entity_consumer_group,
        )
        await self._resolver.run_batch()

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()
        await self._resolver.close()

    async def run_forever(self) -> None:
        await self.start()
        assert self._redis is not None
        consumer = f"entity-{id(self)}"
        last_batch = asyncio.get_event_loop().time()
        backoff = 1.0
        while self._running:
            try:
                rows = await self._redis.xreadgroup(
                    groupname=settings.entity_consumer_group,
                    consumername=consumer,
                    streams={settings.event_stream: ">"},
                    count=20,
                    block=5000,
                )
                backoff = 1.0
                if rows:
                    for _stream, messages in rows:
                        for msg_id, fields in messages:
                            await self._handle(msg_id, fields)

                now = asyncio.get_event_loop().time()
                if now - last_batch >= settings.batch_interval_sec:
                    await self._resolver.run_batch()
                    last_batch = now
            except Exception as exc:
                logger.warning("entity_service.loop_error", error=str(exc)[:240], backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _handle(self, msg_id: str, fields: dict[str, str]) -> None:
        assert self._redis is not None
        try:
            raw = fields.get("data") or fields.get("payload") or ""
            if not raw:
                for v in fields.values():
                    if isinstance(v, str) and v.startswith("{"):
                        raw = v
                        break
            if raw:
                event = json.loads(raw)
                et = event.get("event_type") or event.get("type")
                payload = event.get("payload") or {}
                if et == "token.launch":
                    deployer = payload.get("deployer")
                    if deployer:
                        await self._resolver.on_deployer_observed(deployer)
                elif et == "token.migrated":
                    creator = payload.get("creator") or payload.get("deployer")
                    if creator:
                        await self._resolver.on_deployer_observed(creator)
            await self._redis.xack(
                settings.event_stream, settings.entity_consumer_group, msg_id
            )
        except Exception as exc:
            logger.error("entity_service.handle_failed", error=str(exc))
            try:
                await self._redis.xack(
                    settings.event_stream, settings.entity_consumer_group, msg_id
                )
            except Exception:
                pass
