"""Unit tests for trade parsing and early-buyer ranking."""

from __future__ import annotations

import json
from pathlib import Path

from post_migration.models import TradeSide
from post_migration.trade_parser import (
    classify_side,
    dedupe_trades,
    parse_helius_swap,
    parse_normalized_trade,
    parse_pump_v2_trade,
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
    buyer = "BuyerAAA111111111111111111111111111111111"
    pool = "PoolXYZ1111111111111111111111111111111111"
    tx = {
        "signature": "HeliusSig1",
        "timestamp": 1690000000,
        "slot": 42,
        "feePayer": buyer,
        "tokenTransfers": [
            {
                "mint": MINT,
                "fromUserAccount": pool,
                "toUserAccount": buyer,
                "tokenAmount": 12345,
            }
        ],
        "nativeTransfers": [
            {"fromUserAccount": buyer, "toUserAccount": pool, "amount": 1_500_000_000}
        ],
    }
    trades = parse_helius_swap(tx, mint=MINT)
    assert len(trades) == 1
    assert trades[0].side == TradeSide.BUY
    assert trades[0].wallet == buyer
    assert trades[0].sol_amount == 1.5


def test_parse_pump_v2_buy_and_sell():
    buy = parse_pump_v2_trade(
        {
            "tx": "SigBuy111",
            "timestamp": "2026-08-17T08:00:00.000Z",
            "userAddress": "BuyerWallet1111111111111111111111111111111",
            "type": "buy",
            "program": "pump_amm",
            "amountSol": "0.9",
            "amountUsd": "95.2",
            "baseAmount": "14492.3",
            "quoteAmount": "0.9",
            "priceUsd": "0.000006",
        },
        mint=MINT,
    )
    assert buy is not None
    assert buy.side == TradeSide.BUY
    assert buy.wallet.startswith("BuyerWallet111")
    assert buy.sol_amount == 0.9
    assert buy.meta.get("source") == "pump.v2"

    sell = parse_pump_v2_trade(
        {
            "tx": "SigSell111",
            "timestamp": "2026-08-17T08:01:00.000Z",
            "userAddress": "SellerWallet111111111111111111111111111111",
            "type": "sell",
            "program": "pump_amm",
            "amountSol": "0.4",
            "baseAmount": "8000",
        },
        mint=MINT,
    )
    assert sell is not None
    assert sell.side == TradeSide.SELL
    assert sell.sol_amount == 0.4


def test_parse_pump_v2_rejects_program_accounts():
    t = parse_pump_v2_trade(
        {
            "tx": "SigProg",
            "timestamp": "2026-08-17T08:00:00.000Z",
            "userAddress": "11111111111111111111111111111111",
            "type": "buy",
            "amountSol": "1.0",
        },
        mint=MINT,
    )
    assert t is None


def test_unknown_side_not_guessed():
    assert classify_side(None) is None
    assert classify_side("swap") is None
    assert classify_side("unknown") is None
    assert classify_side("") is None
    t = parse_pump_v2_trade(
        {
            "tx": "SigAmbiguous",
            "timestamp": "2026-08-17T08:00:00.000Z",
            "userAddress": "BuyerWallet1111111111111111111111111111111",
            "type": "swap",
            "amountSol": "1.0",
        },
        mint=MINT,
    )
    assert t is None
    t2 = parse_normalized_trade(
        {"wallet": "BuyerWallet1111111111111111111111111111111", "side": "maybe", "signature": "s1"},
        mint=MINT,
    )
    assert t2 is None


def test_duplicate_signature_one_trade():
    raw = {
        "tx": "SigDup",
        "timestamp": "2026-08-17T08:00:00.000Z",
        "userAddress": "BuyerWallet1111111111111111111111111111111",
        "type": "buy",
        "amountSol": "1.0",
    }
    a = parse_pump_v2_trade(raw, mint=MINT)
    b = parse_pump_v2_trade(raw, mint=MINT)
    assert a is not None and b is not None
    unique = dedupe_trades([a, b])
    assert len(unique) == 1


def test_pool_and_program_wallets_excluded():
    pool = parse_pump_v2_trade(
        {
            "tx": "SigPool",
            "timestamp": "2026-08-17T08:00:00.000Z",
            "userAddress": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
            "type": "buy",
            "amountSol": "5.0",
        },
        mint=MINT,
    )
    prog = parse_pump_v2_trade(
        {
            "tx": "SigProg2",
            "timestamp": "2026-08-17T08:00:00.000Z",
            "userAddress": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "type": "buy",
            "amountSol": "5.0",
        },
        mint=MINT,
    )
    assert pool is None
    assert prog is None

