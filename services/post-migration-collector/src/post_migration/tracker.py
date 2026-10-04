"""Per-mint post-migration tracking session."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.exc import DBAPIError

from stinky_core.measured_outcomes import (
    CLASSIFIED_OUTCOMES,
    classify_completed_market_path,
)

from post_migration.chain import ChainClient, last_trade_source_status
from post_migration.config import settings
from post_migration.metrics import metrics
from post_migration.models import ObservedTrade, TradeSide, TrackStatus
from post_migration.performance import compute_wallet_performance
from post_migration.publisher import EventPublisher
from post_migration.store import Store
from post_migration.trade_parser import rank_early_buyers

logger = structlog.get_logger(__name__)

_PHASE10_FEATURE_HORIZONS: tuple[tuple[str, int], ...] = (
    ("5m", 300),
    ("15m", 900),
    ("30m", 1800),
)

# Keep lifecycle completion aligned with the canonical measured-outcome classifier.
# This is evidence-completeness tolerance, not a trading or policy threshold.
_COMPLETION_EDGE_TOLERANCE_SEC = 120.0


def _is_transient_database_disconnect(exc: BaseException) -> bool:
    """Recognize connection loss without treating evidence/query errors as transient."""
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ConnectionError):
            return True
        if isinstance(current, DBAPIError) and bool(current.connection_invalidated):
            return True
        for related in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(related, BaseException):
                pending.append(related)
    return False


def _completion_outcome_summary(classification: dict[str, Any]) -> dict[str, Any]:
    """Expose only measured canonical labels; UNKNOWN remains unlabeled evidence."""
    label = str(classification.get("label") or "UNKNOWN").upper()
    if label not in CLASSIFIED_OUTCOMES:
        return {}
    return {
        "outcome_status": label,
        "outcome_evidence": classification,
    }


def _is_forward_outcome_eligible(
    migration_at: datetime,
    measured_outcome_epoch: datetime | None,
) -> bool:
    """Require the measured observation window to begin after this process boundary."""
    if measured_outcome_epoch is None:
        return False
    migration = migration_at if migration_at.tzinfo else migration_at.replace(tzinfo=timezone.utc)
    epoch = (
        measured_outcome_epoch
        if measured_outcome_epoch.tzinfo
        else measured_outcome_epoch.replace(tzinfo=timezone.utc)
    )
    return migration >= epoch


def _completion_coverage_evidence(
    *,
    migration_at: datetime,
    coverage: dict[str, Any],
    required_window_sec: float,
) -> dict[str, Any]:
    first_at = coverage.get("first_snapshot_at")
    final_at = coverage.get("final_snapshot_at")
    count = int(coverage.get("valid_price_snapshot_count") or 0)
    if isinstance(first_at, datetime) and first_at.tzinfo is None:
        first_at = first_at.replace(tzinfo=timezone.utc)
    if isinstance(final_at, datetime) and final_at.tzinfo is None:
        final_at = final_at.replace(tzinfo=timezone.utc)
    anchor = migration_at if migration_at.tzinfo else migration_at.replace(tzinfo=timezone.utc)
    first_delay = (
        (first_at - anchor).total_seconds()
        if isinstance(first_at, datetime)
        else None
    )
    final_coverage = (
        (final_at - anchor).total_seconds()
        if isinstance(final_at, datetime)
        else None
    )
    required_final = max(0.0, float(required_window_sec) - _COMPLETION_EDGE_TOLERANCE_SEC)
    complete = bool(
        count >= 2
        and first_delay is not None
        and first_delay <= _COMPLETION_EDGE_TOLERANCE_SEC
        and final_coverage is not None
        and final_coverage >= required_final
    )
    return {
        "complete": complete,
        "valid_price_snapshot_count": count,
        "first_snapshot_at": first_at.isoformat() if isinstance(first_at, datetime) else None,
        "final_snapshot_at": final_at.isoformat() if isinstance(final_at, datetime) else None,
        "first_snapshot_delay_sec": first_delay,
        "final_snapshot_coverage_sec": final_coverage,
        "required_final_snapshot_coverage_sec": required_final,
        "edge_tolerance_sec": _COMPLETION_EDGE_TOLERANCE_SEC,
    }


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
        measured_outcome_epoch: datetime | None = None,
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
        self.measured_outcome_epoch = measured_outcome_epoch
        self.payload = payload or {}
        self.track_id: UUID | None = None
        self._seen_trade_keys: set[tuple[str, str, str]] = set()
        self._wallets_touched: set[str] = set()
        self._phase10_horizons_emitted: set[str] = set()
        self._early_buyer_events_published: set[tuple[str, str, str]] = set()

    async def _capture_phase10_feature_snapshot(self, snap: Any) -> None:
        """Durably emit one pre-cutoff snapshot for each research horizon.

        The feature represents evidence Genesis genuinely possessed by the horizon,
        not an interpolated measurement at the exact horizon. A bounded lead window
        ensures the durable event can be ingested before feature_as_of. If tracking
        starts late or misses the window, the feature remains absent/UNKNOWN.
        """
        captured_at = getattr(snap, "captured_at", None)
        if not isinstance(captured_at, datetime):
            return
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        anchor = self.migration_at
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        age_seconds = (captured_at - anchor).total_seconds()
        if age_seconds < 0:
            return

        lead_window = max(
            30.0,
            float(settings.market_snapshot_interval_sec)
            + float(settings.track_poll_interval_sec),
        )
        for horizon, target_seconds in _PHASE10_FEATURE_HORIZONS:
            if horizon in self._phase10_horizons_emitted:
                continue
            seconds_remaining = float(target_seconds) - age_seconds
            if 0.0 <= seconds_remaining <= lead_window:
                await self._publisher.phase10_feature_snapshot(
                    snap,
                    feature_horizon=horizon,
                    horizon_seconds=target_seconds,
                    anchor_observed_at=anchor,
                )
                self._phase10_horizons_emitted.add(horizon)
                metrics.inc("phase10_feature_snapshots")
                logger.info(
                    "track.phase10_feature_snapshot",
                    mint=self.mint,
                    horizon=horizon,
                    captured_at=captured_at.isoformat(),
                    feature_as_of=(anchor.timestamp() + target_seconds),
                    seconds_remaining=round(seconds_remaining, 3),
                )

    async def _publish_ranked_early_buyers(
        self, ranked: list[ObservedTrade]
    ) -> None:
        """Persist early flags/ranks and emit one sparse durable event per ranked buy.

        Ordinary trade ingest intentionally happens before early-buyer ranking and
        records the trade key as seen. Ranking must therefore revisit that same trade
        to enrich its persisted early-buyer fields and trigger the bounded first-20
        durable event. A separate publication set prevents duplicate durable events.
        """
        for trade in ranked:
            early_trade = trade.model_copy(update={"is_early_buyer": True})
            key = (
                early_trade.signature,
                early_trade.wallet,
                early_trade.side.value,
            )
            await self._store.upsert_trade(early_trade)
            if key in self._early_buyer_events_published:
                continue
            await self._publisher.buy(early_trade)
            self._early_buyer_events_published.add(key)

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
            durable_status = await self._store.get_track_status(self.mint)
            if durable_status in {TrackStatus.COMPLETED, TrackStatus.FAILED}:
                logger.info("track.terminal_replay_ignored", mint=self.mint, status=durable_status.value)
                return
            tracking_anchor = self.migration_at
            if tracking_anchor.tzinfo is None:
                tracking_anchor = tracking_anchor.replace(tzinfo=timezone.utc)
            elapsed_at_start = (datetime.now(timezone.utc) - tracking_anchor).total_seconds()
            if elapsed_at_start >= settings.track_max_duration_sec:
                await self._store.complete_track(self.mint, status=TrackStatus.FAILED)
                logger.warning("track.interrupted_window_failed", mint=self.mint, elapsed=int(elapsed_at_start), required_window=settings.track_max_duration_sec)
                metrics.inc("tracks_failed_interrupted_window")
                return
            metrics.inc("tracks_started")
            self._early_buyer_events_published.update(
                await self._store.load_early_buyer_event_keys(self.mint)
            )
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

            last_market = 0.0
            early_done = False

            while True:
                elapsed = (
                    datetime.now(timezone.utc) - tracking_anchor
                ).total_seconds()
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
                        await self._publish_ranked_early_buyers(ranked)
                        n = await self._store.save_early_buyers(
                            self.track_id, self.mint, ranked
                        )
                        metrics.inc("early_buyers_captured", n)
                        source_status = last_trade_source_status()
                        coverage_complete = source_status.trade_source_coverage == 1.0
                        logger.info(
                            "track.early_buyers",
                            mint=self.mint,
                            captured=n,
                            candidates=len(ranked),
                            buys_seen=len(buys),
                            trade_source=source_status.trade_source,
                            trade_source_coverage=source_status.trade_source_coverage,
                            coverage_complete=coverage_complete,
                        )
                        if n > 0 and coverage_complete:
                            await self._store.set_buyer_capture_complete(self.mint, True)
                            early_done = True
                        elif n > 0:
                            logger.warning(
                                "track.early_buyers_partial",
                                mint=self.mint,
                                captured=n,
                                trade_source=source_status.trade_source,
                                trade_source_coverage=source_status.trade_source_coverage,
                            )
                    else:
                        if elapsed > settings.early_buyer_window_sec:
                            await self._store.set_buyer_capture_complete(self.mint, False)
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
                        await self._capture_phase10_feature_snapshot(snap)
                        metrics.inc("market_snapshots")
                    last_market = elapsed

                if new_trades:
                    await self._refresh_performance(milestones)

                await asyncio.sleep(settings.track_poll_interval_sec)

            await self._refresh_performance(milestones)
            coverage = await self._store.market_snapshot_coverage(
                self.mint,
                start_at=tracking_anchor,
                end_at=tracking_anchor + timedelta(seconds=settings.track_max_duration_sec),
            )
            completion_evidence = _completion_coverage_evidence(
                migration_at=tracking_anchor,
                coverage=coverage,
                required_window_sec=settings.track_max_duration_sec,
            )
            if not completion_evidence["complete"]:
                await self._store.fail_track_for_incomplete_market_path(
                    self.mint,
                    coverage=completion_evidence,
                )
                metrics.inc("tracks_failed_incomplete_market_path")
                logger.warning(
                    "track.incomplete_market_path_failed",
                    mint=self.mint,
                    **completion_evidence,
                )
                return

            completed_at = datetime.now(timezone.utc)
            measured_path = await self._store.load_market_snapshots(
                self.mint,
                start_at=tracking_anchor,
                end_at=completed_at,
            )
            classification = classify_completed_market_path(
                {
                    "migration_at": tracking_anchor,
                    "completed_at": completed_at,
                },
                measured_path,
            )
            forward_outcome_eligible = _is_forward_outcome_eligible(
                tracking_anchor,
                self.measured_outcome_epoch,
            )
            outcome_summary = (
                _completion_outcome_summary(classification)
                if forward_outcome_eligible
                else {}
            )
            if outcome_summary:
                await self._store.complete_track_with_measured_outcome(
                    self.mint,
                    completed_at=completed_at,
                    canonical_measured_outcome=classification,
                )
            else:
                await self._store.complete_track(
                    self.mint,
                    status=TrackStatus.COMPLETED,
                )
            await self._publisher.tracking_completed(
                self.mint,
                {
                    "wallets_touched": len(self._wallets_touched),
                    "trades_seen": len(self._seen_trade_keys),
                    "duration_sec": settings.track_max_duration_sec,
                    **outcome_summary,
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
            if _is_transient_database_disconnect(exc):
                metrics.inc("database_disconnects")
                logger.warning(
                    "track.database_disconnect_deferred",
                    mint=self.mint,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                # Do not retry an uncertain write in-place. Leave durable state
                # active so the existing bounded periodic backfill can resume
                # this still-current observation window from persisted evidence.
                return
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
            self._seen_trade_keys.add(key)
            self._wallets_touched.add(t.wallet)
            if not inserted:
                continue
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
