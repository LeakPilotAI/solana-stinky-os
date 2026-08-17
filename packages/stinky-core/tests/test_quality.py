"""Unit tests for Data Quality Layer."""

from datetime import datetime, timezone

import pytest

from stinky_core.events.base import Event, EventType
from stinky_core.quality.validator import EventValidator


@pytest.fixture
def validator() -> EventValidator:
    return EventValidator()


def test_valid_launch(validator: EventValidator):
    event = Event(
        event_type=EventType.TOKEN_LAUNCH,
        slot=123456,
        block_time=datetime.now(timezone.utc),
        payload={"mint": "So111...", "deployer": "Abc...", "name": "STINKY"},
    )
    result = validator.validate(event)
    assert result.is_valid
    assert result.errors == []


def test_missing_payload_keys(validator: EventValidator):
    event = Event(
        event_type=EventType.TOKEN_LAUNCH,
        slot=1,
        block_time=datetime.now(timezone.utc),
        payload={"mint": "So111..."},
    )
    result = validator.validate(event)
    assert not result.is_valid
    assert any("missing required payload keys" in e for e in result.errors)


def test_missing_slot_for_chain_event(validator: EventValidator):
    event = Event(
        event_type=EventType.TOKEN_LAUNCH,
        payload={"mint": "x", "deployer": "y", "name": "z"},
    )
    result = validator.validate(event)
    assert not result.is_valid
    assert any("slot is required" in e for e in result.errors)


def test_score_out_of_range(validator: EventValidator):
    event = Event(
        event_type=EventType.SCORE_UPDATED,
        payload={
            "entity_id": "e1",
            "score": 150.0,
            "confidence": 0.9,
            "model_version": "v1",
        },
    )
    result = validator.validate(event)
    assert not result.is_valid
    assert any("score must be in [0, 100]" in e for e in result.errors)


def test_validate_or_raise(validator: EventValidator):
    event = Event(event_type=EventType.TOKEN_LAUNCH, payload={})
    with pytest.raises(ValueError, match="validation failed"):
        validator.validate_or_raise(event)
