from datetime import datetime, timezone
from unittest.mock import AsyncMock
import os

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from event_log import api
from stinky_core.events.base import Event, EventType


def original_event():
    return Event(event_type=EventType.TOKEN_LAUNCH, slot=100,
                 block_time=datetime.now(timezone.utc),
                 payload={"mint": "fixture-mint", "deployer": "fixture-deployer", "name": "TEST"},
                 signature="fixture-signature", producer="test")


@pytest.mark.asyncio
async def test_http_copy_retains_original_identity(monkeypatch):
    event = original_event()
    session = AsyncMock()
    monkeypatch.setattr(api, "transport", AsyncMock())
    body = api.IngestRequest.model_validate(event.model_dump(mode="json"))
    response = await api.ingest_event(body, session)
    stored = session.execute.await_args.args[1]
    assert response.event_id == str(event.event_id)
    assert stored["event_id"] == str(event.event_id)
    assert stored["occurred_at"] == event.occurred_at
    assert stored["signature"] == event.signature


@pytest.mark.parametrize("change", ["missing_id", "missing_time", "bad_id", "bad_time", "naive_time"])
def test_partial_or_malformed_identity_is_rejected(change):
    body = original_event().model_dump(mode="json")
    if change == "missing_id": body.pop("event_id")
    elif change == "missing_time": body.pop("occurred_at")
    elif change == "bad_id": body["event_id"] = "not-a-uuid"
    elif change == "bad_time": body["occurred_at"] = "not-a-time"
    else: body["occurred_at"] = "2026-10-01T12:00:00"
    with pytest.raises(ValidationError):
        api.IngestRequest.model_validate(body)


@pytest.mark.asyncio
async def test_legacy_request_without_identity_still_creates_new_event(monkeypatch):
    event = original_event()
    body = event.model_dump(mode="json")
    body.pop("event_id")
    body.pop("occurred_at")
    monkeypatch.setattr(api, "transport", AsyncMock())
    session = AsyncMock()
    response = await api.ingest_event(api.IngestRequest.model_validate(body), session)
    assert response.accepted
    assert response.event_id != str(event.event_id)


@pytest.mark.asyncio
async def test_repeated_http_copy_does_not_add_durable_source_rows(monkeypatch):
    url = os.environ.get("API_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires isolated CI PostgreSQL")
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://", 1))
    monkeypatch.setattr(api, "transport", AsyncMock())
    event = original_event()
    try:
        async with engine.connect() as connection:
            # Connection-private fixture; never modify the real events table.
            await connection.execute(text("""CREATE TEMP TABLE events (
                event_id uuid, event_type text, occurred_at timestamptz,
                slot bigint, block_time timestamptz, signature text, payload jsonb,
                schema_version text, correlation_id uuid, causation_id uuid, producer text,
                PRIMARY KEY(event_id, occurred_at))"""))
            await connection.commit()
            async with AsyncSession(bind=connection) as session:
                from event_log.repository import EventRepository
                await EventRepository(session).insert_event_raw(event)
                await session.commit()
                body = api.IngestRequest.model_validate(event.model_dump(mode="json"))
                for _ in range(2):
                    result = await api.ingest_event(body, session)
                    assert result.event_id == str(event.event_id)
                assert (await session.execute(text("SELECT count(*) FROM events"))).scalar_one() == 1
    finally:
        await engine.dispose()
