"""Deterministic wallet performance aggregates.

Pure functions – fully replayable from wallet_trades history.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Sequence

from post_migration.models import ObservedTrade, TradeSide, WalletPerformance


@dataclass(frozen=True, slots=True)
class ClosedRoundTrip:
    """A matched buy→sell cycle used for return / holding stats."""

    wallet: str
    mint: str
    buy_at: datetime
    sell_at: datetime
    sol_in: float
    sol_out: float
    usd_in: float | None
    usd_out: float | None
    return_pct: float
    holding_seconds: float
    token_amount: float | None = None


def _safe_return_pct(cost: float, proceeds: float) -> float | None:
    if cost <= 0:
        return None
    return ((proceeds - cost) / cost) * 100.0


def match_round_trips(trades: Sequence[ObservedTrade]) -> list[ClosedRoundTrip]:
    """FIFO match buys to sells per (wallet, mint).

    When token amounts are present, allocates proportional SOL across partial fills.
    Deterministic and replayable.
    """
    by_key: dict[tuple[str, str], list[ObservedTrade]] = defaultdict(list)
    for t in sorted(trades, key=lambda x: (x.traded_at, x.signature)):
        by_key[(t.wallet, t.mint)].append(t)

    closed: list[ClosedRoundTrip] = []
    for (wallet, mint), seq in by_key.items():
        # Open lots: (remaining_tokens, sol_cost, usd_cost, buy_at, original_tokens)
        open_lots: list[list[float | datetime | None]] = []
        for t in seq:
            if t.side == TradeSide.BUY:
                tok = float(t.token_amount) if t.token_amount is not None else 1.0
                sol = float(t.sol_amount or 0)
                usd = float(t.usd_amount) if t.usd_amount is not None else None
                open_lots.append([tok, sol, usd, t.traded_at, tok])
            elif t.side == TradeSide.SELL and open_lots:
                sell_tok = float(t.token_amount) if t.token_amount is not None else None
                sell_sol = float(t.sol_amount or 0)
                sell_usd = float(t.usd_amount) if t.usd_amount is not None else None
                remaining_sell = sell_tok if sell_tok is not None else open_lots[0][0]

                while remaining_sell and open_lots and float(remaining_sell) > 1e-18:
                    lot = open_lots[0]
                    lot_tok = float(lot[0] or 0)
                    if lot_tok <= 0:
                        open_lots.pop(0)
                        continue
                    take = min(lot_tok, float(remaining_sell))
                    frac = take / lot_tok if lot_tok > 0 else 1.0
                    sol_in = float(lot[1] or 0) * frac
                    usd_in = float(lot[2]) * frac if lot[2] is not None else None
                    # Allocate sell proceeds by token fraction of this sell leg
                    if sell_tok and sell_tok > 0:
                        sol_out = sell_sol * (take / sell_tok)
                        usd_out = (
                            sell_usd * (take / sell_tok) if sell_usd is not None else None
                        )
                    else:
                        sol_out = sell_sol
                        usd_out = sell_usd

                    ret = _safe_return_pct(sol_in, sol_out)
                    if ret is None and usd_in is not None and usd_out is not None:
                        ret = _safe_return_pct(usd_in, usd_out)
                    if ret is not None:
                        buy_at = lot[3]
                        assert isinstance(buy_at, datetime)
                        holding = max(0.0, (t.traded_at - buy_at).total_seconds())
                        closed.append(
                            ClosedRoundTrip(
                                wallet=wallet,
                                mint=mint,
                                buy_at=buy_at,
                                sell_at=t.traded_at,
                                sol_in=sol_in,
                                sol_out=sol_out,
                                usd_in=usd_in,
                                usd_out=usd_out,
                                return_pct=ret,
                                holding_seconds=holding,
                                token_amount=take,
                            )
                        )

                    lot[0] = lot_tok - take
                    lot[1] = float(lot[1] or 0) * (1.0 - frac)
                    if lot[2] is not None:
                        lot[2] = float(lot[2]) * (1.0 - frac)
                    remaining_sell = float(remaining_sell) - take
                    if float(lot[0] or 0) <= 1e-18:
                        open_lots.pop(0)
                    if sell_tok is None:
                        # Whole-trade FIFO without token sizes: one lot per sell
                        break
    return closed


def compute_wallet_performance(
    wallet: str,
    trades: Sequence[ObservedTrade],
    *,
    milestone_multiples: Sequence[float] = (2, 5, 10, 50, 100),
    min_qualifying_sol: float = 0.05,
) -> WalletPerformance:
    """Build reusable performance record for one wallet."""
    mine = [t for t in trades if t.wallet == wallet]
    buys = [t for t in mine if t.side == TradeSide.BUY]
    sells = [t for t in mine if t.side == TradeSide.SELL]
    early = [t for t in buys if t.is_early_buyer]
    tokens = {t.mint for t in buys}

    qualifying = [
        t
        for t in buys
        if t.sol_amount is None or abs(t.sol_amount) >= min_qualifying_sol
    ]

    trips = [rt for rt in match_round_trips(mine) if rt.wallet == wallet]
    returns = [rt.return_pct for rt in trips]
    holdings = [rt.holding_seconds for rt in trips]
    wins = sum(1 for r in returns if r > 0)
    losses = sum(1 for r in returns if r <= 0)

    realized_usd = 0.0
    realized_sol = 0.0
    for rt in trips:
        realized_sol += rt.sol_out - rt.sol_in
        if rt.usd_in is not None and rt.usd_out is not None:
            realized_usd += rt.usd_out - rt.usd_in

    milestones: dict[str, int] = {f"x{int(m)}": 0 for m in milestone_multiples}
    for r in returns:
        multiple = 1.0 + (r / 100.0)
        for m in milestone_multiples:
            if multiple >= m:
                milestones[f"x{int(m)}"] = milestones.get(f"x{int(m)}", 0) + 1

    n = len(returns)
    return WalletPerformance(
        wallet=wallet,
        total_trades=len(mine),
        total_buys=len(buys),
        total_sells=len(sells),
        tokens_purchased=len(tokens),
        early_buy_count=len(early),
        qualifying_trades=len(qualifying),
        wins=wins,
        losses=losses,
        loss_rate=(losses / n) if n else None,
        hit_rate=(wins / n) if n else None,
        avg_return_pct=(sum(returns) / n) if n else None,
        median_return_pct=float(median(returns)) if n else None,
        max_return_pct=max(returns) if n else None,
        avg_holding_seconds=(sum(holdings) / len(holdings)) if holdings else None,
        realized_pnl_usd=realized_usd,
        realized_pnl_sol=realized_sol,
        milestones_hit=milestones,
    )


def update_position_from_trade(
    *,
    tokens_bought: float,
    tokens_sold: float,
    sol_spent: float,
    sol_received: float,
    usd_spent: float,
    usd_received: float,
    trade: ObservedTrade,
) -> dict[str, float | bool | None]:
    """Apply one trade to a position accumulator. Returns new state dict."""
    tb, ts = tokens_bought, tokens_sold
    ss, sr = sol_spent, sol_received
    us, ur = usd_spent, usd_received

    amt = float(trade.token_amount or 0)
    sol = float(trade.sol_amount or 0)
    usd = float(trade.usd_amount or 0)

    if trade.side == TradeSide.BUY:
        tb += amt
        ss += sol
        us += usd
    else:
        ts += amt
        sr += sol
        ur += usd

    remaining = max(0.0, tb - ts)
    sold_frac = (ts / tb) if tb > 0 else 0.0
    realized_sol = sr - (ss * min(1.0, sold_frac))
    realized_usd = ur - (us * min(1.0, sold_frac))
    avg_entry = (us / tb) if tb > 0 else None

    return {
        "tokens_bought": tb,
        "tokens_sold": ts,
        "tokens_remaining": remaining,
        "sol_spent": ss,
        "sol_received": sr,
        "usd_spent": us,
        "usd_received": ur,
        "avg_entry_price_usd": avg_entry,
        "realized_pnl_usd": realized_usd,
        "realized_pnl_sol": realized_sol,
        "is_open": remaining > 1e-12,
    }
