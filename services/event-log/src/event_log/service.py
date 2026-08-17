"""Core Event Log service – ingest, validate, persist, publish."""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_core.events.base import Event, EventType
from stinky_core.quality.validator import EventValidator
from stinky_core.transport.base import EventTransport

from event_log.repository import EventRepository

logger = structlog.get_logger(__name__)


class EventLogService:
    """Orchestrates validation → persistence → re-publish for downstream consumers."""

    def __init__(
        self,
        session: AsyncSession,
        transport: EventTransport,
        validator: EventValidator | None = None,
    ) -> None:
        self._repo = EventRepository(session)
        self._transport = transport
        self._validator = validator or EventValidator()

    async def ingest(self, event: Event) -> tuple[bool, list[str]]:
        """
        Validate and append an event.

        Returns (accepted, errors).
        Accepted events are persisted and re-published on the main stream
        so that Feature Engineering and other services can consume them.
        """
        result = self._validator.validate(event)
        if not result.is_valid:
            logger.warning(
                "event.rejected",
                event_id=str(event.event_id),
                event_type=event.event_type,
                errors=result.errors,
            )
            await self._repo.insert_rejected(
                raw_payload=event.model_dump(mode="json"),
                errors=result.errors,
                source=event.producer,
            )
            await self._repo.commit()
            # Also emit a quality event for observability
            quality_event = Event(
                event_type=EventType.DATA_QUALITY_REJECTED,
                payload={
                    "original_event_id": str(event.event_id),
                    "errors": result.errors,
                },
                producer="event-log",
                correlation_id=event.event_id,
            )
            await self._transport.publish(quality_event)
            return False, result.errors

        await self._repo.insert_event_raw(event)
        await self._repo.commit()
        await self._transport.publish(event)

        logger.info(
            "event.accepted",
            event_id=str(event.event_id),
            event_type=event.event_type,
            producer=event.producer,
        )
        return True, []
