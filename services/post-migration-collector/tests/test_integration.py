"""Integration-style tests without live chain/DB (in-memory pipeline)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from post_migration.models import ObservedTrade, TradeSide
from post_migration.performance import compute_wallet_performance, update_position_from_trade
from post_migration.trade_parser import parse_normalized_trade, rank_early_buyers
from stinky_core.events.base import Event, EventType
from stinky_core.quality.validator import EventValidator

MINT = "Mint111111111111111111111111111111111111111"
FIXTURE = Path(__file__).parent / "fixtures" / "sample_trades.json"


def test_event_validation_for_new_types():
    v = EventValidator()
    buy = Event(
        event_type=EventType.POST_MIGRATION_BUY,
        payload={"mint": MINT, "wallet": "W1", "signature": "S1"},
        producer="test",
    )
    assert v.validate(buy).is_valid

    started = Event(
        event_type=EventType.POST_MIGRATION_TRACKING_STARTED,
        payload={"mint": MINT, "pool": "Pool1"},
        producer="test",
    )
    assert v.validate(started).is_valid

    bad = Event(
        event_type=EventType.POST_MIGRATION_BUY,
        payload={"mint": MINT},
        producer="test",
    )
    assert not v.validate(bad).is_valid


def test_full_fixture_pipeline_replay():
    """Replay fixture: rank early buyers → match sells → performance."""
    raw = json.loads(FIXTURE.read_text())
    trades = [t for t in (parse_normalized_trade(r, mint=MINT) for r in raw) if t]
    buys = [t for t in trades if t.side == TradeSide.BUY]
    ranked = rank_early_buyers(buys, max_buyers=20, min_sol=0.01)
    assert [r.early_rank for r in ranked] == [1, 2]

    # Simulate continuous tracking (same wallets later sell)
    for r in ranked:
        assert r.is_early_buyer

    w1 = ranked[0].wallet
    perf = compute_wallet_performance(w1, trades)
    assert perf.tokens_purchased == 1
    assert perf.total_buys == 1
    assert perf.total_sells == 1
    assert perf.realized_pnl_sol > 0


def test_position_accumulator():
    buy = ObservedTrade(
        mint=MINT,
        wallet="W",
        side=TradeSide.BUY,
        signature="b1",
        traded_at=datetime.now(timezone.utc),
        token_amount=100,
        sol_amount=2.0,
        usd_amount=300,
    )
    state = update_position_from_trade(
        tokens_bought=0,
        tokens_sold=0,
        sol_spent=0,
        sol_received=0,
        usd_spent=0,
        usd_received=0,
        trade=buy,
    )
    assert state["tokens_bought"] == 100
    assert state["is_open"] is True

    sell = ObservedTrade(
        mint=MINT,
        wallet="W",
        side=TradeSide.SELL,
        signature="s1",
        traded_at=datetime.now(timezone.utc),
        token_amount=100,
        sol_amount=5.0,
        usd_amount=750,
    )
    state2 = update_position_from_trade(
        tokens_bought=float(state["tokens_bought"]),  # type: ignore[arg-type]
        tokens_sold=float(state["tokens_sold"]),  # type: ignore[arg-type]
        sol_spent=float(state["sol_spent"]),  # type: ignore[arg-type]
        sol_received=float(state["sol_received"]),  # type: ignore[arg-type]
        usd_spent=float(state["usd_spent"]),  # type: ignore[arg-type]
        usd_received=float(state["usd_received"]),  # type: ignore[arg-type]
        trade=sell,
    )
    assert state2["tokens_remaining"] == 0
    assert state2["is_open"] is False
