"""Manual CA track queue — operator injects mints Redis missed.

Redis list: stinky.manual_tracks
Payload: plain mint string OR JSON {"mint":"...","pool":"...","note":"..."}

On each item:
  1) publish token.migrated (collector starts buyer capture)
  2) volume.watch (DexScreener polls; free-tier vol gate emits alert.candidate)
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis
import structlog

from sentinel.config import settings
from sentinel.models import DetectedMigration

if TYPE_CHECKING:
    from sentinel.publisher import LaunchPublisher
    from sentinel.volume import VolumeMonitor

logger = structlog.get_logger(__name__)

MANUAL_QUEUE = "stinky.manual_tracks"


def _parse_item(raw: bytes | str) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    raw = (raw or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"mint": raw}


class ManualTrackConsumer:
    def __init__(
        self,
        volume: "VolumeMonitor",
        publisher: "LaunchPublisher",
        *,
        queue: str = MANUAL_QUEUE,
    ) -> None:
        self._volume = volume
        self._publisher = publisher
        self._queue = queue
        self._stop = asyncio.Event()
        self._redis: aioredis.Redis | None = None

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        url = settings.redis_url
        self._redis = aioredis.from_url(url, decode_responses=False)
        logger.info("manual_track.starting", queue=self._queue, redis=url)
        try:
            while not self._stop.is_set():
                try:
                    item = await self._redis.brpop(self._queue, timeout=5)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("manual_track.brpop_error", error=str(exc)[:200])
                    await asyncio.sleep(2.0)
                    continue
                if not item:
                    continue
                _key, raw = item
                data = _parse_item(raw)
                mint = str(data.get("mint") or "").strip()
                if not mint:
                    continue
                try:
                    await self._handle(mint, data)
                except Exception as exc:
                    logger.warning(
                        "manual_track.handle_failed",
                        mint=mint,
                        error=str(exc)[:300],
                    )
        finally:
            if self._redis is not None:
                await self._redis.aclose()
            logger.info("manual_track.stopped")

    async def _handle(self, mint: str, data: dict[str, Any]) -> None:
        mint_l = mint.lower()
        if not mint_l.endswith("pump"):
            logger.info("manual_track.rejected_not_pump", mint=mint)
            return

        pool = str(data.get("pool") or data.get("pair") or "").strip()
        note = str(data.get("note") or "manual")[:120]
        sig = str(data.get("signature") or f"manual-{mint[:16]}-{int(time.time())}")

        migration = DetectedMigration(
            mint=mint,
            pool=pool or mint,  # non-empty for downstream joins
            creator=data.get("creator"),
            signature=sig,
            block_time=datetime.now(timezone.utc),
            destination="pumpswap",
            source="manual",
            raw={"note": note, "manual": True},
        )

        logger.info("manual_track.accepted", mint=mint, note=note)

        # Collector + event log path
        try:
            await self._publisher.publish_migration(migration)
        except Exception as exc:
            logger.warning("manual_track.publish_failed", mint=mint, error=str(exc)[:200])

        # Volume / discovery quality path (free-tier: vol >= 50k can emit)
        self._volume.watch(migration)
