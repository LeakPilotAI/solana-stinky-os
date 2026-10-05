from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from post_migration.publisher import EventPublisher, settings
from stinky_core.events.base import Event, EventType


@pytest.mark.asyncio
@pytest.mark.parametrize("connected", [True, False])
@pytest.mark.parametrize("event_type,force_durable", [
    (EventType.POST_MIGRATION_TRACKING_STARTED, False),
    (EventType.WALLET_PERFORMANCE_UPDATED, False),
    (EventType.POST_MIGRATION_BUY, True),
])
async def test_http_delivery_preserves_original_identity(
    monkeypatch, connected, event_type, force_durable
):
    monkeypatch.setattr(settings, "event_log_url", "http://event-log.test")
    publisher = EventPublisher()
    publisher._transport = AsyncMock()
    publisher._connected = connected
    publisher._http = AsyncMock()
    publisher._http.post = AsyncMock(return_value=httpx.Response(200))
    event = Event(
        event_id=UUID("00000000-0000-4000-8000-000000000001"),
        occurred_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        event_type=event_type, payload={"mint": "fixture-mint"},
        signature="fixture-signature", producer=settings.service_name,
    )
    try:
        # Re-delivery must retain the Timescale identity pair on both paths.
        for _ in range(2):
            await publisher._emit(event, force_durable=force_durable)
        for call in publisher._http.post.await_args_list:
            body = call.kwargs["json"]
            assert body["event_id"] == str(event.event_id)
            assert datetime.fromisoformat(body["occurred_at"]) == event.occurred_at
            assert body["signature"] == event.signature
            assert body["payload"] == event.payload
        assert publisher._http.post.await_count == 2
        assert publisher._transport.publish.await_count == (2 if connected else 0)
        for call in publisher._transport.publish.await_args_list:
            assert call.args[0].event_id == event.event_id
            assert call.args[0].occurred_at == event.occurred_at
    finally:
        await publisher.close()
