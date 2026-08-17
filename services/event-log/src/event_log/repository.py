"""Persistence of immutable events and rejected events."""

from __future__ import annotations

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from stinky_core.events.base import Event


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_event_raw(self, event: Event) -> None:
        """Append-only insert. Conflict target matches Timescale PK."""
        await self._session.execute(
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

    async def insert_rejected(
        self, raw_payload: dict, errors: list[str], source: str | None = None
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO rejected_events (raw_payload, errors, source)
                VALUES (CAST(:raw AS jsonb), :errors, :source)
                """
            ),
            {
                "raw": orjson.dumps(raw_payload).decode(),
                "errors": errors,
                "source": source,
            },
        )

    async def commit(self) -> None:
        await self._session.commit()
