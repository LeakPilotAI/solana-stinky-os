"""Event Transport Interface (ADR-004).

Business logic must depend only on this abstraction.
Concrete implementations (Redis Streams, Kafka, NATS, …) live in adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from stinky_core.events.base import Event, EventEnvelope


class EventProducer(Protocol):
    """Protocol for publishing events."""

    async def publish(self, event: Event, *, stream: str | None = None) -> None: ...
    async def publish_batch(
        self, events: Sequence[Event], *, stream: str | None = None
    ) -> None: ...


class EventConsumer(Protocol):
    """Protocol for consuming events."""

    async def consume(
        self,
        stream: str,
        group: str,
        consumer_name: str,
        *,
        count: int = 10,
        block_ms: int = 5000,
    ) -> AsyncIterator[EventEnvelope]: ...

    async def ack(self, stream: str, group: str, message_id: str) -> None: ...


class EventTransport(ABC):
    """Abstract transport that both produces and consumes.

    Implementations must be fully async and idempotent where possible.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the underlying broker."""

    @abstractmethod
    async def close(self) -> None:
        """Gracefully close connections."""

    @abstractmethod
    async def publish(self, event: Event, *, stream: str | None = None) -> str:
        """Publish a single event. Returns transport message id."""

    @abstractmethod
    async def publish_batch(
        self, events: Sequence[Event], *, stream: str | None = None
    ) -> list[str]:
        """Publish multiple events. Returns list of message ids."""

    @abstractmethod
    async def consume(
        self,
        stream: str,
        group: str,
        consumer_name: str,
        *,
        count: int = 10,
        block_ms: int = 5000,
    ) -> AsyncIterator[tuple[str, EventEnvelope]]:
        """Yield (message_id, envelope) pairs.

        Caller is responsible for calling ack after successful processing.
        """

    @abstractmethod
    async def ack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge successful processing of a message."""

    @abstractmethod
    async def create_consumer_group(
        self, stream: str, group: str, *, start_id: str = "0"
    ) -> None:
        """Idempotently create a consumer group."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the transport is healthy."""
