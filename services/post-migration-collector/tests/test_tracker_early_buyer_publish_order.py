from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from post_migration.models import ObservedTrade, TradeSide, TrackStatus
from post_migration.tracker import MintTracker


@pytest.mark.asyncio
async def test_ranked_early_buyer_revisits_already_seen_trade_and_publishes_once() -> None:
    store = AsyncMock()
    publisher = AsyncMock()
    chain = AsyncMock()

    tracker = MintTracker(
        store=store,
        publisher=publisher,
        chain=chain,
        mint="Mint111111111111111111111111111111111111111",
        pool=None,
        creator=None,
        destination=None,
        migration_signature=None,
        migration_slot=None,
        migration_at=datetime(2026, 9, 9, 2, 0, tzinfo=timezone.utc),
    )

    trade = ObservedTrade(
        mint=tracker.mint,
        wallet="Wallet1111111111111111111111111111111111111",
        side=TradeSide.BUY,
        signature="sig-early-1",
        traded_at=datetime(2026, 9, 9, 2, 1, tzinfo=timezone.utc),
        sol_amount=0.25,
        early_rank=1,
    )
    key = (trade.signature, trade.wallet, trade.side.value)

    # Reproduce the live failure: ordinary ingest has already marked this key seen.
    tracker._seen_trade_keys.add(key)

    await tracker._publish_ranked_early_buyers([trade])

    store.upsert_trade.assert_awaited_once()
    persisted = store.upsert_trade.await_args.args[0]
    assert persisted.is_early_buyer is True
    assert persisted.early_rank == 1

    publisher.buy.assert_awaited_once()
    emitted = publisher.buy.await_args.args[0]
    assert emitted.is_early_buyer is True
    assert emitted.early_rank == 1

    # A repeated ranking pass must not duplicate the sparse durable event.
    await tracker._publish_ranked_early_buyers([trade])
    assert publisher.buy.await_count == 1


def test_partial_buyer_capture_cannot_finalize_early_cohort():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "post_migration" / "tracker.py"
    ).read_text(encoding="utf-8")
    assert "coverage_complete = source_status.trade_source_coverage == 1.0" in source
    assert "if n > 0 and coverage_complete:" in source
    assert '"track.early_buyers_partial"' in source


def test_restart_hydrates_durable_early_buyer_event_dedupe_keys():
    from pathlib import Path

    tracker = (
        Path(__file__).parents[1] / "src" / "post_migration" / "tracker.py"
    ).read_text(encoding="utf-8")
    store = (
        Path(__file__).parents[1] / "src" / "post_migration" / "store.py"
    ).read_text(encoding="utf-8")

    assert "load_early_buyer_event_keys(self.mint)" in tracker
    assert "self._early_buyer_events_published.update(" in tracker
    assert "SELECT signature, wallet" in store
    assert "FROM migration_buyers" in store


def test_backfill_includes_interrupted_active_tracks_with_partial_buyers():
    from pathlib import Path

    store = (
        Path(__file__).parents[1] / "src" / "post_migration" / "store.py"
    ).read_text(encoding="utf-8")

    start = store.index("    async def migrations_needing_buyers(")
    block = store[start:]
    assert "NOT EXISTS (" in block
    assert "FROM migration_buyers mb" not in block
    assert "OR EXISTS (" in block
    assert "FROM migration_tracks mt" in block
    assert "mt.status = 'active'" in block


def test_existing_trade_after_restart_still_marks_wallet_for_performance_refresh():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "post_migration" / "tracker.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def _ingest_trades(")
    end = source.index("    async def _refresh_performance(", start)
    block = source[start:end]

    touched = block.index("self._wallets_touched.add(t.wallet)")
    duplicate_exit = block.index("if not inserted:")
    assert touched < duplicate_exit
    assert block.index("new_count += 1") > duplicate_exit


def test_tracking_and_early_buyer_windows_are_anchored_to_migration_time():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "post_migration" / "tracker.py"
    ).read_text(encoding="utf-8")
    run = source[source.index("    async def run("):source.index("    async def _ingest_trades(")]

    assert "tracking_anchor = self.migration_at" in run
    assert "datetime.now(timezone.utc) - tracking_anchor" in run
    assert "started = datetime.now(timezone.utc)" not in run
    assert "elapsed >= settings.track_max_duration_sec" in run
    assert "elapsed > settings.early_buyer_window_sec" in run


def test_start_track_does_not_resurrect_terminal_durable_status():
    from pathlib import Path

    store = (
        Path(__file__).parents[1] / "src" / "post_migration" / "store.py"
    ).read_text(encoding="utf-8")
    start = store.index("    async def start_track(")
    end = store.index("    async def complete_track(", start)
    block = store[start:end]

    assert "status = migration_tracks.status" in block
    assert "status = 'active'" not in block.split("ON CONFLICT (mint) DO UPDATE SET", 1)[1]


def test_tracker_persists_buyer_capture_completeness_for_downstream_evidence():
    from pathlib import Path

    tracker = (
        Path(__file__).parents[1] / "src" / "post_migration" / "tracker.py"
    ).read_text(encoding="utf-8")
    store = (
        Path(__file__).parents[1] / "src" / "post_migration" / "store.py"
    ).read_text(encoding="utf-8")

    assert "set_buyer_capture_complete(self.mint, True)" in tracker
    assert "set_buyer_capture_complete(self.mint, False)" in tracker
    assert "buyer_capture_complete" in store


@pytest.mark.asyncio
async def test_interrupted_track_past_horizon_fails_closed_without_completion_event():
    store, publisher, chain = AsyncMock(), AsyncMock(), AsyncMock()
    store.start_track.return_value = __import__("uuid").uuid4()
    store.get_track_status.return_value = TrackStatus.ACTIVE
    tracker = MintTracker(
        store=store, publisher=publisher, chain=chain,
        mint="StaleMint11111111111111111111111111111111111",
        pool=None, creator=None, destination=None,
        migration_signature=None, migration_slot=None,
        migration_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    await tracker.run()
    store.complete_track.assert_awaited_once_with(tracker.mint, status=TrackStatus.FAILED)
    publisher.tracking_completed.assert_not_awaited()
    publisher.tracking_started.assert_not_awaited()
    chain.fetch_trades_for_mint.assert_not_awaited()


def test_store_recovery_never_promotes_interrupted_active_track_to_completed():
    from pathlib import Path
    store = (Path(__file__).parents[1] / "src" / "post_migration" / "store.py").read_text()
    block = store[store.index("    async def fail_stale_active_tracks("):store.index("    async def set_buyer_capture_complete(")]
    assert "WHERE status='active'" in block
    assert "status='failed'" in block
    assert "interrupted_observation_window" in block
    assert "status='completed'" not in block
