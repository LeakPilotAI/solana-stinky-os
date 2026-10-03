from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from post_migration.config import settings
from post_migration.service import CollectorService

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_expired_migration_is_rejected_before_tracker_task_is_spawned():
    service = CollectorService()
    service._store = AsyncMock()
    service._publisher = AsyncMock()
    service._chain = AsyncMock()

    started = await service.track_mint(
        "ExpiredMint111111111111111111111111111111111",
        migration_at=datetime.now(timezone.utc)
        - timedelta(seconds=settings.track_max_duration_sec + 60),
    )

    assert started is False
    assert service._active_tracks == set()
    assert service._tasks == set()
    service._store.start_track.assert_not_awaited()
    service._chain.fetch_trades_for_mint.assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_passes_factual_tracking_horizon_to_store_query():
    service = CollectorService()
    service._store = AsyncMock()
    service._store.migrations_needing_buyers.return_value = []

    started = await service.backfill_from_events(limit=12)

    assert started == 0
    service._store.migrations_needing_buyers.assert_awaited_once_with(
        limit=12,
        max_age_sec=settings.track_max_duration_sec,
    )


@pytest.mark.asyncio
async def test_backfill_overfetches_by_in_memory_active_count():
    service = CollectorService()
    service._store = AsyncMock()
    service._store.migrations_needing_buyers.return_value = []
    service._active_tracks.update({"A", "B", "C"})

    started = await service.backfill_from_events(limit=12)

    assert started == 0
    service._store.migrations_needing_buyers.assert_awaited_once_with(
        limit=15,
        max_age_sec=settings.track_max_duration_sec,
    )


def test_store_backfill_sql_is_bounded_to_current_observation_horizon():
    source = (
        ROOT / "services" / "post-migration-collector" / "src"
        / "post_migration" / "store.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def migrations_needing_buyers(")
    end = source.index("    async def recompute_all_performance(", start) if "    async def recompute_all_performance(" in source[start:] else len(source)
    block = source[start:end]

    assert "max_age_sec: float" in block
    assert "e.occurred_at >= CAST(:cutoff AS timestamptz)" in block
    assert '{"lim": limit, "cutoff": cutoff}' in block
    assert "mt.status = 'active'" in block
    assert "CASE WHEN mt.status = 'active' THEN 0 ELSE 1 END" in block


def test_unrelated_wallet_listing_does_not_reference_backfill_cutoff():
    source = (
        ROOT / "services" / "post-migration-collector" / "src"
        / "post_migration" / "store.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def list_wallets_with_trades(")
    end = source.index("    async def recompute_all_performance(", start)
    block = source[start:end]

    assert '{"lim": limit}' in block
    assert "cutoff" not in block


def test_service_has_second_line_of_defense_for_stale_stream_events():
    source = (
        ROOT / "services" / "post-migration-collector" / "src"
        / "post_migration" / "service.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def track_mint(")
    end = source.index("    async def _on_migration(", start)
    block = source[start:end]

    assert "age_sec >= settings.track_max_duration_sec" in block
    assert '"collector.expired_migration_ignored"' in block
    assert 'metrics.inc("expired_migrations_ignored")' in block
    assert block.index("age_sec >= settings.track_max_duration_sec") < block.index("tracker = MintTracker(")
