"""Emit immutable post-migration events to Redis + Event Log."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from stinky_core.events.base import Event, EventType
from stinky_core.transport.redis_streams import RedisStreamsTransport

from post_migration.config import settings
from post_migration.metrics import metrics
from post_migration.models import MarketSnapshot, ObservedTrade, WalletPerformance

logger = structlog.get_logger(__name__)

# High-frequency ticks already live in wallet_trades / market_snapshots.
# Putting every tick on Redis + HTTP fills the stream until the 512m Redis OOM
# at the default hourly RDB snapshot (~1 hour). Sparse Phase-10 feature snapshots
# explicitly bypass these sets through _emit(..., force_durable=True).
_SKIP_STREAM = {
    EventType.POST_MIGRATION_BUY,
    EventType.POST_MIGRATION_SELL,
    EventType.POST_MIGRATION_MARKET_SNAPSHOT,
}
_SKIP_HTTP = _SKIP_STREAM


class EventPublisher:
    def __init__(self) -> None:
        self._transport = RedisStreamsTransport(
            redis_url=settings.redis_url,
            default_stream=settings.event_stream,
        )
        self._connected = False
        self._http = httpx.AsyncClient(timeout=2.0)

    async def connect(self) -> None:
        try:
            await self._transport.connect()
            self._connected = True
        except Exception as exc:
            logger.warning("publisher.redis_unavailable", error=str(exc))
            self._connected = False

    async def close(self) -> None:
        if self._connected:
            await self._transport.close()
        await self._http.aclose()

    async def _emit(self, event: Event, *, force_durable: bool = False) -> None:
        stream_allowed = force_durable or event.event_type not in _SKIP_STREAM
        http_allowed = force_durable or event.event_type not in _SKIP_HTTP

        if self._connected and stream_allowed:
            try:
                await self._transport.publish(event)
                metrics.inc("events_emitted")
            except Exception as exc:
                logger.error("publisher.redis_failed", error=str(exc))
                metrics.inc("errors")

        if settings.event_log_url and http_allowed:
            try:
                body = {
                    "event_type": event.event_type.value,
                    "payload": event.payload,
                    "slot": event.slot,
                    "block_time": (
                        event.block_time or datetime.now(timezone.utc)
                    ).isoformat(),
                    "signature": event.signature,
                    "producer": settings.service_name,
                }
                resp = await self._http.post(
                    f"{settings.event_log_url.rstrip('/')}/v1/events",
                    json=body,
                )
                if resp.status_code >= 300:
                    logger.warning(
                        "publisher.http_rejected",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
            except Exception as exc:
                logger.warning("publisher.http_failed", error=str(exc))

    async def tracking_started(self, payload: dict[str, Any], *, signature: str | None = None) -> None:
        await self._emit(
            Event(
                event_type=EventType.POST_MIGRATION_TRACKING_STARTED,
                signature=signature,
                block_time=datetime.now(timezone.utc),
                payload=payload,
                producer=settings.service_name,
            )
        )

    async def buy(self, trade: ObservedTrade) -> None:
        await self._emit(
            Event(
                event_type=EventType.POST_MIGRATION_BUY,
                signature=trade.signature,
                slot=trade.slot,
                block_time=trade.traded_at,
                payload={
                    "mint": trade.mint,
                    "wallet": trade.wallet,
                    "signature": trade.signature,
                    "token_amount": trade.token_amount,
                    "sol_amount": trade.sol_amount,
                    "usd_amount": trade.usd_amount,
                    "price_usd": trade.price_usd,
                    "is_early_buyer": trade.is_early_buyer,
                    "early_rank": trade.early_rank,
                },
                producer=settings.service_name,
            )
        )

    async def sell(self, trade: ObservedTrade) -> None:
        await self._emit(
            Event(
                event_type=EventType.POST_MIGRATION_SELL,
                signature=trade.signature,
                slot=trade.slot,
                block_time=trade.traded_at,
                payload={
                    "mint": trade.mint,
                    "wallet": trade.wallet,
                    "signature": trade.signature,
                    "token_amount": trade.token_amount,
                    "sol_amount": trade.sol_amount,
                    "usd_amount": trade.usd_amount,
                    "price_usd": trade.price_usd,
                },
                producer=settings.service_name,
            )
        )

    @staticmethod
    def _market_payload(snap: MarketSnapshot) -> dict[str, Any]:
        return {
            "mint": snap.mint,
            "price_usd": snap.price_usd,
            "liquidity_usd": snap.liquidity_usd,
            "volume_m5_usd": snap.volume_m5_usd,
            "volume_h1_usd": snap.volume_h1_usd,
            "volume_h24_usd": snap.volume_h24_usd,
            "fdv_usd": snap.fdv_usd,
            "market_cap_usd": snap.market_cap_usd,
            "pair_address": snap.pair_address,
            "dex_id": snap.dex_id,
            "source": snap.source,
        }

    async def market_snapshot(self, snap: MarketSnapshot) -> None:
        """Handle ordinary high-frequency snapshots without durable stream fanout."""
        await self._emit(
            Event(
                event_type=EventType.POST_MIGRATION_MARKET_SNAPSHOT,
                block_time=snap.captured_at,
                payload=self._market_payload(snap),
                producer=settings.service_name,
            )
        )

    async def phase10_feature_snapshot(
        self,
        snap: MarketSnapshot,
        *,
        feature_horizon: str,
        horizon_seconds: int,
        anchor_observed_at: datetime,
    ) -> None:
        """Emit one sparse research-grade snapshot for a Phase-10 feature cutoff.

        Unlike ordinary market ticks, this event is intentionally durable in both
        Redis and Event Log so downstream ingestion time is independently recorded.
        The actual observation time remains snap.captured_at.
        """
        payload = {
            **self._market_payload(snap),
            "phase10_feature": True,
            "feature_horizon": feature_horizon,
            "horizon_seconds": int(horizon_seconds),
            "anchor_observed_at": anchor_observed_at.isoformat(),
        }
        await self._emit(
            Event(
                event_type=EventType.POST_MIGRATION_MARKET_SNAPSHOT,
                block_time=snap.captured_at,
                payload=payload,
                producer=settings.service_name,
            ),
            force_durable=True,
        )

    async def performance_updated(self, perf: WalletPerformance) -> None:
        await self._emit(
            Event(
                event_type=EventType.WALLET_PERFORMANCE_UPDATED,
                block_time=datetime.now(timezone.utc),
                payload=perf.model_dump(),
                producer=settings.service_name,
            )
        )

    async def tracking_completed(self, mint: str, summary: dict[str, Any]) -> None:
        await self._emit(
            Event(
                event_type=EventType.POST_MIGRATION_TRACKING_COMPLETED,
                block_time=datetime.now(timezone.utc),
                payload={"mint": mint, **summary},
                producer=settings.service_name,
            )
        )
