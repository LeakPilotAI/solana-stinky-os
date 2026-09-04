"""POST /v1/track — queue a mint for Sentinel manual track + collector."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog
from pydantic import BaseModel, Field

from stinky_api.config import settings

logger = structlog.get_logger(__name__)

MANUAL_QUEUE = "stinky.manual_tracks"


class TrackRequest(BaseModel):
    mint: str = Field(..., min_length=32, max_length=64)
    pool: str | None = None
    note: str | None = Field(default="manual", max_length=120)


async def enqueue_manual_track(body: TrackRequest) -> dict[str, Any]:
    mint = body.mint.strip()
    if not mint.lower().endswith("pump"):
        return {
            "ok": False,
            "error": "mint_must_end_with_pump",
            "mint": mint,
        }
    payload = {
        "mint": mint,
        "pool": (body.pool or "").strip() or None,
        "note": (body.note or "manual").strip()[:120],
    }
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.lpush(MANUAL_QUEUE, json.dumps(payload))
        qlen = await r.llen(MANUAL_QUEUE)
    finally:
        await r.aclose()
    logger.info("api.manual_track_queued", mint=mint, queue_len=qlen)
    return {
        "ok": True,
        "mint": mint,
        "queued": True,
        "queue": MANUAL_QUEUE,
        "queue_len": qlen,
        "note": payload["note"],
        "hint": "Sentinel will publish token.migrated + start volume watch within a few seconds",
    }
