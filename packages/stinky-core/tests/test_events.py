"""Unit tests for immutable events and envelopes."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from stinky_core.events.base import Event, EventEnvelope, EventType


def test_event_is_frozen():
    event = Event(event_type=EventType.TOKEN_LAUNCH, payload={"mint": "abc"})
    with pytest.raises(Exception):
        event.payload = {"mint": "def"}  # type: ignore[misc]


def test_event_defaults():
    event = Event(event_type=EventType.TOKEN_LAUNCH)
    assert isinstance(event.event_id, UUID)
    assert event.schema_version == "1.0.0"
    assert event.occurred_at.tzinfo is not None


def test_event_utc_normalization():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    event = Event(
        event_type=EventType.TOKEN_LAUNCH,
        occurred_at=naive,
        block_time=naive,
    )
    assert event.occurred_at.tzinfo == timezone.utc
    assert event.block_time is not None
    assert event.block_time.tzinfo == timezone.utc


def test_envelope_roundtrip():
    event = Event(
        event_type=EventType.SCORE_UPDATED,
        payload={"entity_id": "e1", "score": 91.5, "confidence": 0.97, "model_version": "v1.0"},
        producer="score-engine",
    )
    envelope = EventEnvelope(event=event)
    raw = envelope.to_bytes()
    restored = EventEnvelope.from_bytes(raw)
    assert restored.event.event_id == event.event_id
    assert restored.event.event_type == EventType.SCORE_UPDATED
    assert restored.event.payload["score"] == 91.5
