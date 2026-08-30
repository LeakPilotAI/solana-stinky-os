"""Durable event persistence: Postgres first, stream second (outbox).

Never lose a blockchain observation because Redis or HTTP Event Log is down.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import orjson
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stinky_core.events.base import Event, EventEnvelope

from sentinel.config import settings

logger = structlog.get_logger(__name__)


class DurableEventStore:
    """Append-only events + outbox in the same transaction."""

    def __init__(self) -> None:
        self._engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, pool_size=5
        )
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )
        self._ready = False

    async def close(self) -> None:
        await self._engine.dispose()

    async def ensure_schema(self) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS event_idempotency (
                        idem_key   TEXT PRIMARY KEY,
                        event_id   UUID NOT NULL,
                        event_type TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS event_outbox (
                        id           BIGSERIAL PRIMARY KEY,
                        event_id     UUID NOT NULL,
                        occurred_at  TIMESTAMPTZ NOT NULL,
                        stream       TEXT NOT NULL DEFAULT 'stinky.events',
                        envelope     JSONB NOT NULL,
                        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                        published_at TIMESTAMPTZ,
                        attempts     INT NOT NULL DEFAULT 0,
                        last_error   TEXT
                    )
                    """
                )
            )
            await session.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_event_outbox_event_id
                    ON event_outbox (event_id)
                    """
                )
            )
            try:
                from stinky_core.fees import FEE_OBSERVATIONS_DDL, FEE_OBSERVATIONS_INDEXES
            except ImportError:
                FEE_OBSERVATIONS_DDL = None
                FEE_OBSERVATIONS_INDEXES = ()
            if FEE_OBSERVATIONS_DDL:
                await session.execute(text(FEE_OBSERVATIONS_DDL))
                for idx in FEE_OBSERVATIONS_INDEXES:
                    await session.execute(text(idx))
            try:
                from stinky_core.intelligence import MARKET_INSPECTIONS_DDL, MARKET_INSPECTIONS_INDEXES
            except ImportError:
                MARKET_INSPECTIONS_DDL = None
                MARKET_INSPECTIONS_INDEXES = ()
            if MARKET_INSPECTIONS_DDL:
                await session.execute(text(MARKET_INSPECTIONS_DDL))
                for idx in MARKET_INSPECTIONS_INDEXES:
                    await session.execute(text(idx))
            try:
                from stinky_core.memory import MEMORY_ALTERS, MEMORY_DDL, MEMORY_INDEXES
            except ImportError:
                MEMORY_DDL = None
                MEMORY_INDEXES = ()
                MEMORY_ALTERS = ()
            if MEMORY_DDL:
                for stmt in MEMORY_DDL.split(";"):
                    s = stmt.strip()
                    if s:
                        await session.execute(text(s))
                for idx in MEMORY_INDEXES:
                    await session.execute(text(idx))
                for alt in MEMORY_ALTERS or ():
                    try:
                        await session.execute(text(alt))
                    except Exception:
                        pass
            await session.commit()
        self._ready = True
        logger.info("durable.schema_ready")

    def _idem_key(self, event: Event) -> str | None:
        """Deterministic dedupe for chain events with a signature."""
        if not event.signature:
            return None
        return f"{event.event_type.value}:{event.signature}"

    async def append(self, event: Event, *, stream: str | None = None) -> bool:
        """Persist event + outbox row. Returns False if duplicate idem_key.

        Always writes when no signature (e.g. derived alerts).
        """
        if not self._ready:
            await self.ensure_schema()

        stream_name = stream or settings.event_stream
        envelope = EventEnvelope(event=event)
        env_bytes = envelope.to_bytes().decode()
        idem = self._idem_key(event)

        async with self._sessions() as session:
            if idem:
                existing = (
                    await session.execute(
                        text(
                            "SELECT event_id FROM event_idempotency WHERE idem_key = :k"
                        ),
                        {"k": idem},
                    )
                ).first()
                if existing:
                    logger.info(
                        "durable.duplicate_skipped",
                        idem_key=idem,
                        event_type=event.event_type.value,
                    )
                    return False

            await session.execute(
                text(
                    """
                    INSERT INTO events (
                        event_id, event_type, occurred_at, slot, block_time,
                        signature, payload, schema_version, correlation_id,
                        causation_id, producer
                    ) VALUES (
                        :event_id, :event_type, :occurred_at, :slot, :block_time,
                        :signature, CAST(:payload AS jsonb), :schema_version,
                        :correlation_id, :causation_id, :producer
                    )
                    ON CONFLICT (event_id, occurred_at) DO NOTHING
                    """
                ),
                {
                    "event_id": str(event.event_id),
                    "event_type": event.event_type.value,
                    "occurred_at": event.occurred_at,
                    "slot": event.slot,
                    "block_time": event.block_time,
                    "signature": event.signature,
                    "payload": orjson.dumps(event.payload).decode(),
                    "schema_version": event.schema_version,
                    "correlation_id": (
                        str(event.correlation_id) if event.correlation_id else None
                    ),
                    "causation_id": (
                        str(event.causation_id) if event.causation_id else None
                    ),
                    "producer": event.producer,
                },
            )

            if idem:
                await session.execute(
                    text(
                        """
                        INSERT INTO event_idempotency (idem_key, event_id, event_type)
                        VALUES (:k, :eid, :et)
                        ON CONFLICT (idem_key) DO NOTHING
                        """
                    ),
                    {
                        "k": idem,
                        "eid": str(event.event_id),
                        "et": event.event_type.value,
                    },
                )

            await session.execute(
                text(
                    """
                    INSERT INTO event_outbox (event_id, occurred_at, stream, envelope)
                    VALUES (:eid, :oa, :stream, CAST(:env AS jsonb))
                    ON CONFLICT (event_id) DO NOTHING
                    """
                ),
                {
                    "eid": str(event.event_id),
                    "oa": event.occurred_at,
                    "stream": stream_name,
                    "env": env_bytes,
                },
            )
            await session.commit()

        logger.info(
            "durable.appended",
            event_id=str(event.event_id),
            event_type=event.event_type.value,
            mint=(event.payload or {}).get("mint"),
        )
        return True

    async def mark_published(self, event_id: UUID) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    UPDATE event_outbox
                    SET published_at = now()
                    WHERE event_id = :eid AND published_at IS NULL
                    """
                ),
                {"eid": str(event_id)},
            )
            await session.commit()

    async def mark_publish_failed(self, event_id: UUID, error: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                text(
                    """
                    UPDATE event_outbox
                    SET attempts = attempts + 1,
                        last_error = :err
                    WHERE event_id = :eid
                    """
                ),
                {"eid": str(event_id), "err": error[:500]},
            )
            await session.commit()

    async def drain_unpublished(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch unpublished outbox rows for relay retry."""
        async with self._sessions() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, event_id, stream, envelope
                    FROM event_outbox
                    WHERE published_at IS NULL
                    ORDER BY created_at ASC
                    LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
            return [dict(r) for r in result.mappings()]
