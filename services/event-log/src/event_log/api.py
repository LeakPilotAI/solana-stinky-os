"""FastAPI surface for the Event Log service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_core.events.base import Event, EventType
from stinky_core.transport.redis_streams import RedisStreamsTransport

from event_log.config import settings
from event_log.db import get_session
from event_log.service import EventLogService

logger = structlog.get_logger(__name__)

transport = RedisStreamsTransport(
    redis_url=settings.redis_url,
    default_stream=settings.event_stream,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis may still be loading RDB after docker compose start (BusyLoadingError).
    last_err: Exception | None = None
    for attempt in range(1, 31):
        try:
            await transport.connect()
            last_err = None
            break
        except Exception as exc:
            last_err = exc
            msg = str(exc).lower()
            retryable = (
                "loading" in msg
                or "busy" in msg
                or "refused" in msg
                or "connect" in msg
                or "timed out" in msg
                or "timeout" in msg
            )
            logger.warning(
                "event_log.redis_connect_retry",
                attempt=attempt,
                error=f"{type(exc).__name__}: {exc}"[:200],
            )
            if not retryable or attempt >= 30:
                raise
            await asyncio.sleep(2)
    if last_err is not None:
        raise last_err
    logger.info("event_log.started", service=settings.service_name)
    yield
    await transport.close()
    logger.info("event_log.stopped")


app = FastAPI(
    title="Stinky OS – Event Log",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)


class IngestRequest(BaseModel):
    event_type: EventType
    payload: dict = Field(default_factory=dict)
    slot: int | None = None
    block_time: str | None = None  # ISO
    signature: str | None = None
    producer: str = "api"
    schema_version: str = "1.0.0"


class IngestResponse(BaseModel):
    accepted: bool
    event_id: str | None = None
    errors: list[str] = Field(default_factory=list)


@app.get("/health")
async def health() -> dict:
    healthy = await transport.health_check()
    return {
        "status": "ok" if healthy else "degraded",
        "service": settings.service_name,
        "transport": healthy,
    }


@app.post("/v1/events", response_model=IngestResponse)
async def ingest_event(
    body: IngestRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IngestResponse:
    from datetime import datetime

    block_time = None
    if body.block_time:
        block_time = datetime.fromisoformat(body.block_time.replace("Z", "+00:00"))

    event = Event(
        event_type=body.event_type,
        payload=body.payload,
        slot=body.slot,
        block_time=block_time,
        signature=body.signature,
        producer=body.producer,
        schema_version=body.schema_version,
    )

    service = EventLogService(session=session, transport=transport)
    try:
        accepted, errors = await service.ingest(event)
    except Exception as exc:
        msg = str(exc)
        blip = (
            isinstance(exc, (TimeoutError, ConnectionError, OSError))
            or "timeout" in msg.lower()
            or "6380" in msg
        )
        if blip:
            logger.error("ingest.redis_unavailable", error=msg[:200])
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"accepted": False, "errors": ["redis unavailable"]},
            ) from exc
        logger.exception("ingest.failed", error=msg)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"accepted": False, "errors": [msg]},
        ) from exc

    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"accepted": False, "errors": errors},
        )

    return IngestResponse(accepted=True, event_id=str(event.event_id))


@app.get("/ready")
async def ready() -> dict:
    return {"ready": True}
