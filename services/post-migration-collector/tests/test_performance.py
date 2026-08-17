"""Deterministic wallet performance tests (replay fixtures)."""

from __future__ import annotations

import json
from pathlib import Path

from post_migration.performance import compute_wallet_performance, match_round_trips
from post_migration.trade_parser import parse_normalized_trade

MINT = "Mint111111111111111111111111111111111111111"
FIXTURE = Path(__file__).parent / "fixtures" / "sample_trades.json"


def _load():
    raw = json.loads(FIXTURE.read_text())
    return [t for t in (parse_normalized_trade(r, mint=MINT) for r in raw) if t]


def test_round_trip_matching():
    trades = _load()
    trips = match_round_trips(trades)
    assert len(trips) == 2
    # Buyer1: 1.5 SOL in → 4.5 SOL out = +200%
    w1 = [t for t in trips if t.wallet.startswith("BuyerWallet111")][0]
    assert abs(w1.return_pct - 200.0) < 0.01
    assert w1.holding_seconds == 599.0  # 03:00:01 → 03:10:00


def test_wallet_performance_win_loss():
    trades = _load()
    w1 = "BuyerWallet1111111111111111111111111111111"
    w2 = "BuyerWallet2222222222222222222222222222222"
    p1 = compute_wallet_performance(w1, trades, milestone_multiples=(2, 5, 10))
    p2 = compute_wallet_performance(w2, trades, milestone_multiples=(2, 5, 10))

    assert p1.wins == 1
    assert p1.losses == 0
    assert p1.hit_rate == 1.0
    assert p1.max_return_pct and p1.max_return_pct > 100
    assert p1.milestones_hit.get("x2", 0) == 1

    assert p2.wins == 0
    assert p2.losses == 1
    assert p2.loss_rate == 1.0
    assert p2.hit_rate == 0.0


def test_performance_replay_is_deterministic():
    trades = _load()
    w = "BuyerWallet1111111111111111111111111111111"
    a = compute_wallet_performance(w, trades)
    b = compute_wallet_performance(w, trades)
    assert a.model_dump() == b.model_dump()
