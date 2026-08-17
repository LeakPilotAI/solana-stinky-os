"""Per-mint post-migration tracking session."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog

from post_migration.chain import ChainClient
from post_migration.config import settings
from post_migration.metrics import metrics
from post_migration.models import ObservedTrade, TradeSide, TrackStatus
from post_migration.performance import compute_wallet_performance
from post_migration.publisher import EventPublisher
from post_migration.store import Store
from post_migration.trade_parser import rank_early_buyers

logger = structlog.get_logger(__name__)


class MintTracker:
    """Tracks one migrated mint: early buyers, continuous trades, market snapshots."""

    def __init__(
        self,
        *,
        store: Store,
        publisher: EventPublisher,
        chain: ChainClient,
        mint: str,
        pool: str | None,
        creator: str | None,
        destination: str | None,
        migration_signature: str | None,
        migration_slot: int | None,
        migration_at: datetime,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._chain = chain
        self.mint = mint
        self.pool = pool
        self.creator = creator
        self.destination = destination
        self.migration_signature = migration_signature
        self.migration_slot = migration_slot
        self.migration_at = migration_at
        self.payload = payload or {}
        self.track_id: UUID | None = None
        self._seen_trade_keys: set[tuple[str, str, str]] = set()
        self._wallets_touched: set[str] = set()

    async def run(self) -> None:
        milestones = [
            float(x.strip())
            for x in settings.milestone_multiples.split(",")
            if x.strip()
        ]
        try:
            self.track_id = await self._store.start_track(
                mint=self.mint,
                pool=self.pool,
                creator=self.creator,
                destination=self.destination,
                migration_signature=self.migration_signature,
                migration_slot=self.migration_slot,
                migration_at=self.migration_at,
                meta=self.payload,
            )
            metrics.inc("tracks_started")
            await self._publisher.tracking_started(
                {
                    "mint": self.mint,
                    "pool": self.pool,
                    "creator": self.creator,
                    "destination": self.destination,
                    "track_id": str(self.track_id),
                    "migration_signature": self.migration_signature,
                },
                signature=self.migration_signature,
            )
            logger.info(
                "track.started",
                mint=self.mint,
                pool=self.pool,
                track_id=str(self.track_id),
            )

            started = datetime.now(timezone.utc)
            last_market = 0.0
            early_done = False

            while True:
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if elapsed >= settings.track_max_duration_sec:
                    break

                trades = await self._chain.fetch_trades_for_mint(
                    self.mint, pool=self.pool
                )
                new_trades = await self._ingest_trades(trades)

                if not early_done:
                    buys = [t for t in trades if t.side == TradeSide.BUY]
                    exclude: set[str] = set()
                    if self.pool:
                        exclude.add(self.pool)
                    if self.destination:
                        exclude.add(self.destination)
                    for part in settings.buyer_exclude_addresses.split(","):
                        a = part.strip()
                        if a:
                            exclude.add(a)
                    ranked = rank_early_buyers(
                        buys,
                        max_buyers=settings.max_early_buyers,
                        min_sol=settings.min_meaningful_sol,
                        exclude=exclude,
                    )
                    if ranked and self.track_id:
                        for r in ranked:
                            key = (r.signature, r.wallet, r.side.value)
                            if key not in self._seen_trade_keys:
                                r = r.model_copy(
                                    update={"is_early_buyer": True}
                                )
                                inserted = await self._store.upsert_trade(r)
                                if inserted:
                                    self._seen_trade_keys.add(key)
                                    self._wallets_touched.add(r.wallet)
                                    await self._publisher.buy(r)
                        n = await self._store.save_early_buyers(
                            self.track_id, self.mint, ranked
                        )
                        metrics.inc("early_buyers_captured", n)
                        logger.info(
                            "track.early_buyers",
                            mint=self.mint,
                            captured=n,
                            candidates=len(ranked),
                            buys_seen=len(buys),
                        )
                        # Only stop once we actually persist buyers
                        if n > 0:
                            early_done = True
                    else:
                        # Keep trying for early_buyer_window_sec (default 15m)
                        if elapsed > settings.early_buyer_window_sec:
                            early_done = True
                            logger.warning(
                                "track.early_buyers_timeout",
                                mint=self.mint,
                                elapsed=int(elapsed),
                                trades=len(trades),
                                buys=len(buys),
                            )
                        elif int(elapsed) % 60 < settings.track_poll_interval_sec:
                            logger.info(
                                "track.early_buyers_waiting",
                                mint=self.mint,
                                elapsed=int(elapsed),
                                trades=len(trades),
                                buys=len(buys),
                            )

                if elapsed - last_market >= settings.market_snapshot_interval_sec:
                    snap = await self._chain.fetch_market_snapshot(self.mint)
                    if snap:
                        await self._store.save_market_snapshot(snap)
                        await self._publisher.market_snapshot(snap)
                        metrics.inc("market_snapshots")
                    last_market = elapsed

                if new_trades:
                    await self._refresh_performance(milestones)

                await asyncio.sleep(settings.track_poll_interval_sec)

            await self._refresh_performance(milestones)
            await self._store.complete_track(self.mint, status=TrackStatus.COMPLETED)
            await self._publisher.tracking_completed(
                self.mint,
                {
                    "wallets_touched": len(self._wallets_touched),
                    "trades_seen": len(self._seen_trade_keys),
                    "duration_sec": settings.track_max_duration_sec,
                },
            )
            metrics.inc("tracks_completed")
            sells = sum(
                1 for k in self._seen_trade_keys if len(k) > 2 and k[2] == "sell"
            )
            logger.info(
                "track.completed",
                mint=self.mint,
                wallets=len(self._wallets_touched),
                trades=len(self._seen_trade_keys),
                sells=sells,
            )
        except Exception as exc:
            metrics.inc("errors")
            logger.error("track.failed", mint=self.mint, error=str(exc))
            try:
                await self._store.complete_track(self.mint, status=TrackStatus.FAILED)
            except Exception:
                pass

    async def _ingest_trades(self, trades: list[ObservedTrade]) -> int:
        new_count = 0
        for t in trades:
            key = (t.signature, t.wallet, t.side.value)
            if key in self._seen_trade_keys:
                continue
            inserted = await self._store.upsert_trade(t)
            if not inserted:
                self._seen_trade_keys.add(key)
                continue
            self._seen_trade_keys.add(key)
            self._wallets_touched.add(t.wallet)
            new_count += 1
            metrics.inc("trades_observed")
            if t.side == TradeSide.BUY:
                await self._publisher.buy(t)
            else:
                await self._publisher.sell(t)
        return new_count

    async def _refresh_performance(self, milestones: list[float]) -> None:
        for wallet in list(self._wallets_touched):
            trades = await self._store.load_trades_for_wallet(wallet)
            perf = compute_wallet_performance(
                wallet,
                trades,
                milestone_multiples=milestones,
                min_qualifying_sol=settings.min_meaningful_sol,
            )
            await self._store.upsert_wallet_performance(perf)
            await self._publisher.performance_updated(perf)
            metrics.inc("performance_updates")
