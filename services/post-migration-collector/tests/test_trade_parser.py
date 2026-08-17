"""Unit tests for trade parsing and early-buyer ranking."""

from __future__ import annotations

import json
from pathlib import Path

from post_migration.models import TradeSide
from post_migration.trade_parser import (
    parse_helius_swap,
    parse_normalized_trade,
    rank_early_buyers,
)

MINT = "Mint111111111111111111111111111111111111111"
FIXTURE = Path(__file__).parent / "fixtures" / "sample_trades.json"


def test_parse_normalized_fixture():
    raw = json.loads(FIXTURE.read_text())
    trades = [parse_normalized_trade(r, mint=MINT) for r in raw]
    trades = [t for t in trades if t is not None]
    assert len(trades) == 5
    assert trades[0].side == TradeSide.BUY
    assert trades[0].sol_amount == 1.5


def test_rank_early_buyers_skips_dust_and_dedupes():
    raw = json.loads(FIXTURE.read_text())
    trades = [parse_normalized_trade(r, mint=MINT) for r in raw]
    buys = [t for t in trades if t and t.side == TradeSide.BUY]
    ranked = rank_early_buyers(buys, max_buyers=20, min_sol=0.01)
    assert len(ranked) == 2  # dust filtered
    assert ranked[0].early_rank == 1
    assert ranked[0].is_early_buyer is True
    assert ranked[0].wallet.startswith("BuyerWallet111")
    assert ranked[1].early_rank == 2


def test_parse_helius_token_transfers():
    tx = {
        "signature": "HeliusSig1",
        "timestamp": 1690000000,
        "slot": 42,
        "feePayer": "BuyerAAA",
        "tokenTransfers": [
            {
                "mint": MINT,
                "fromUserAccount": "PoolXYZ",
                "toUserAccount": "BuyerAAA",
                "tokenAmount": 12345,
            }
        ],
        "nativeTransfers": [
            {"fromUserAccount": "BuyerAAA", "toUserAccount": "PoolXYZ", "amount": 1_500_000_000}
        ],
    }
    trades = parse_helius_swap(tx, mint=MINT)
    assert len(trades) == 1
    assert trades[0].side == TradeSide.BUY
    assert trades[0].wallet == "BuyerAAA"
    assert trades[0].sol_amount == 1.5
