from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from post_migration.models import ObservedTrade, TradeSide
from post_migration.publisher import EventPublisher


def _trade(*, is_early_buyer: bool, early_rank: int | None) -> ObservedTrade:
    return ObservedTrade(
        mint="Mint111111111111111111111111111111111111111",
        wallet="Wallet1111111111111111111111111111111111111",
        side=TradeSide.BUY,
        signature=f"sig-{is_early_buyer}-{early_rank}",
        traded_at=datetime(2026, 9, 9, 2, 0, tzinfo=timezone.utc),
        sol_amount=0.1,
        is_early_buyer=is_early_buyer,
        early_rank=early_rank,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("rank", [1, 5, 10, 20])
async def test_first20_early_buys_force_durable_event(rank: int) -> None:
    publisher = EventPublisher()
    publisher._emit = AsyncMock()  # type: ignore[method-assign]
    try:
        await publisher.buy(_trade(is_early_buyer=True, early_rank=rank))
        publisher._emit.assert_awaited_once()
        assert publisher._emit.await_args.kwargs["force_durable"] is True
    finally:
        await publisher.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_early_buyer", "rank"),
    [
        (False, None),
        (False, 1),
        (True, None),
        (True, 0),
        (True, 21),
        (True, 50),
    ],
)
async def test_non_first20_buys_remain_non_durable(
    is_early_buyer: bool,
    rank: int | None,
) -> None:
    publisher = EventPublisher()
    publisher._emit = AsyncMock()  # type: ignore[method-assign]
    try:
        await publisher.buy(_trade(is_early_buyer=is_early_buyer, early_rank=rank))
        publisher._emit.assert_awaited_once()
        assert publisher._emit.await_args.kwargs["force_durable"] is False
    finally:
        await publisher.close()
