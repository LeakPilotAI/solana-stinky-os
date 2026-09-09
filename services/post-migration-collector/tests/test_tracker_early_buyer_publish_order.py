from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from post_migration.models import ObservedTrade, TradeSide
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
