"""Stinky OS Core – shared events, transport, quality, and models."""

__version__ = "0.1.0"

from stinky_core.events.base import Event, EventType, EventEnvelope
from stinky_core.transport.base import EventTransport, EventProducer, EventConsumer

__all__ = [
    "__version__",
    "Event",
    "EventType",
    "EventEnvelope",
    "EventTransport",
    "EventProducer",
    "EventConsumer",
]
