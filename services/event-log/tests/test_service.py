"""Unit tests for EventLogService (mocked transport & session)."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from stinky_core.events.base import Event, EventType
from stinky_core.quality.validator import EventValidator

from event_log.service import EventLogService


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_transport():
    t = AsyncMock()
    t.publish = AsyncMock()
    return t


@pytest.mark.asyncio
async def test_ingest_valid_event(mock_session, mock_transport):
    service = EventLogService(
        session=mock_session,
        transport=mock_transport,
        validator=EventValidator(),
    )
    event = Event(
        event_type=EventType.TOKEN_LAUNCH,
        slot=100,
        block_time=datetime.now(timezone.utc),
        payload={"mint": "So1", "deployer": "Dep1", "name": "TEST"},
        producer="test",
    )
    accepted, errors = await service.ingest(event)
    assert accepted is True
    assert errors == []
    mock_transport.publish.assert_awaited()


@pytest.mark.asyncio
async def test_ingest_invalid_event(mock_session, mock_transport):
    service = EventLogService(
        session=mock_session,
        transport=mock_transport,
        validator=EventValidator(),
    )
    event = Event(
        event_type=EventType.TOKEN_LAUNCH,
        payload={"mint": "So1"},  # missing required keys + slot
        producer="test",
    )
    accepted, errors = await service.ingest(event)
    assert accepted is False
    assert len(errors) > 0
    # Should still publish a DATA_QUALITY_REJECTED event
    mock_transport.publish.assert_awaited()
