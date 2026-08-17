"""Orchestrates Redis consumption of token.migrated â†’ MintTracker sessions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
import structlog

from post_migration.chain import ChainClient
from post_migration.config import settings
from post_migration.metrics import metrics
from post_migration.publisher import EventPublisher
from post_migration.store import Store
from post_migration.tracker import MintTracker

logger = structlog.get_logger(__name__)


class CollectorService:
    def __init__(self) -> None:
        self._store = Store()
        self._publisher = EventPublisher()
        self._chain = ChainClient()
        self._redis: redis.Redis | None = None
        self._running = False
        self._active_tracks: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        await self._store.ensure_schema()
        await self._publisher.connect()
        self._redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=None,
        )
        try:
            await self._redis.xgroup_create(
                settings.event_stream,
                settings.collector_consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception:
            pass
        self._running = True
        logger.info(
            "collector.started",
            stream=settings.event_stream,
            group=settings.collector_consumer_group,
            max_early_buyers=settings.max_early_buyers,
        )

    async def stop(self) -> None:
        self._running = False
        for t in list(self._tasks):
            t.cancel()
        await self._publisher.close()
        await self._chain.close()
        await self._store.close()
        if self._redis:
            await self._redis.aclose()
        logger.info("collector.stopped", metrics=metrics.snapshot())

    async def run_forever(self) -> None:
        await self.start()
        assert self._redis is not None
        consumer = f"collector-{id(self)}"
        try:
            while self._running:
                try:
                    rows = await self._redis.xreadgroup(
                        groupname=settings.collector_consumer_group,
                        consumername=consumer,
                        streams={settings.event_stream: ">"},
                        count=20,
                        block=5000,
                    )
                    if not rows:
                        continue
                    for _stream, messages in rows:
                        for msg_id, fields in messages:
                            await self._handle_message(msg_id, fields)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("collector.loop_error", error=str(exc))
                    metrics.inc("errors")
                    await asyncio.sleep(2)
        finally:
            await self.stop()

    async def _handle_message(self, msg_id: str, fields: dict[str, str]) -> None:
        assert self._redis is not None
        try:
            raw = fields.get("data") or fields.get("payload") or ""
            if not raw:
                for v in fields.values():
                    if isinstance(v, str) and (
                        v.startswith("{") or v.startswith("\x7b")
                    ):
                        raw = v
                        break
            if not raw:
                await self._redis.xack(
                    settings.event_stream, settings.collector_consumer_group, msg_id
                )
                return

            event = self._parse_event(raw)
            if event is None:
                await self._redis.xack(
                    settings.event_stream, settings.collector_consumer_group, msg_id
                )
                return

            event_type = event.get("event_type") or event.get("type")
            if event_type != "token.migrated":
                await self._redis.xack(
                    settings.event_stream, settings.collector_consumer_group, msg_id
                )
                return

            metrics.inc("migrations_received")
            payload = event.get("payload") or {}
            await self._on_migration(event, payload)
            await self._redis.xack(
                settings.event_stream, settings.collector_consumer_group, msg_id
            )
        except Exception as exc:
            logger.error("collector.handle_failed", error=str(exc))
            metrics.inc("errors")
            try:
                await self._redis.xack(
                    settings.event_stream, settings.collector_consumer_group, msg_id
                )
            except Exception:
                pass

    def _parse_event(self, raw: str | bytes) -> dict[str, Any] | None:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except Exception:
                return None
        try:
            data = json.loads(raw)
        except Exception:
            return None
        if (
            isinstance(data, dict)
            and "event" in data
            and isinstance(data["event"], dict)
        ):
            return data["event"]
        if isinstance(data, dict) and "event_type" in data:
            return data
        return None

    async def track_mint(
        self,
        mint: str,
        *,
        pool: str | None = None,
        creator: str | None = None,
        destination: str | None = None,
        signature: str | None = None,
        slot: int | None = None,
        migration_at: datetime | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Start a tracking session for a mint (live event or manual backfill)."""
        if mint in self._active_tracks:
            logger.info("collector.track_already_active", mint=mint)
            return False
        if len(self._active_tracks) >= settings.max_concurrent_tracks:
            logger.warning(
                "collector.track_capacity",
                active=len(self._active_tracks),
                mint=mint,
            )
            return False

        mat = migration_at or datetime.now(timezone.utc)
        if mat.tzinfo is None:
            mat = mat.replace(tzinfo=timezone.utc)

        tracker = MintTracker(
            store=self._store,
            publisher=self._publisher,
            chain=self._chain,
            mint=mint,
            pool=pool,
            creator=creator,
            destination=destination,
            migration_signature=signature,
            migration_slot=slot,
            migration_at=mat,
            payload=payload or {},
        )

        async def _run() -> None:
            self._active_tracks.add(mint)
            try:
                await tracker.run()
            finally:
                self._active_tracks.discard(mint)

        task = asyncio.create_task(_run(), name=f"track-{mint[:8]}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        logger.info("collector.track_spawned", mint=mint, pool=pool)
        return True

    async def _on_migration(
        self, event: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        mint = payload.get("mint")
        if not mint:
            logger.warning(
                "collector.migration_missing_mint", keys=list(payload.keys())
            )
            return

        migration_at = event.get("block_time") or event.get("occurred_at")
        if isinstance(migration_at, str):
            migration_at = datetime.fromisoformat(migration_at.replace("Z", "+00:00"))
        if not isinstance(migration_at, datetime):
            migration_at = datetime.now(timezone.utc)

        await self.track_mint(
            mint,
            pool=payload.get("pool"),
            creator=payload.get("creator"),
            destination=payload.get("destination"),
            signature=event.get("signature"),
            slot=event.get("slot"),
            migration_at=migration_at,
            payload=payload,
        )

    async def backfill_from_events(self, *, limit: int = 20) -> int:
        """Spawn tracks for recent token.migrated rows that have zero buyers."""
        rows = await self._store.migrations_needing_buyers(limit=limit)
        started = 0
        for row in rows:
            mint = row.get("mint")
            if not mint:
                continue
            ok = await self.track_mint(
                mint,
                pool=row.get("pool"),
                creator=row.get("creator"),
                destination=row.get("destination"),
                signature=row.get("signature"),
                migration_at=row.get("occurred_at"),
                payload=row.get("payload") or {},
            )
            if ok:
                started += 1
        logger.info("collector.backfill_started", tracks=started, candidates=len(rows))
        return started

    @property
    def health(self) -> dict[str, Any]:
        return {
            "service": settings.service_name,
            "running": self._running,
            "active_tracks": len(self._active_tracks),
            "metrics": metrics.snapshot(),
        }

