"""Micro-benchmarks for deterministic performance math."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from post_migration.models import ObservedTrade, TradeSide
from post_migration.performance import compute_wallet_performance, match_round_trips


def _gen_trades(n_wallets: int = 50, n_tokens: int = 10) -> list[ObservedTrade]:
    base = datetime(2026, 8, 11, tzinfo=timezone.utc)
    trades: list[ObservedTrade] = []
    for w in range(n_wallets):
        wallet = f"Wallet{w:04d}"
        for t in range(n_tokens):
            mint = f"Mint{t:04d}"
            trades.append(
                ObservedTrade(
                    mint=mint,
                    wallet=wallet,
                    side=TradeSide.BUY,
                    signature=f"B-{w}-{t}",
                    traded_at=base + timedelta(seconds=t),
                    sol_amount=1.0 + (w % 5) * 0.1,
                    token_amount=1000,
                )
            )
            trades.append(
                ObservedTrade(
                    mint=mint,
                    wallet=wallet,
                    side=TradeSide.SELL,
                    signature=f"S-{w}-{t}",
                    traded_at=base + timedelta(seconds=100 + t),
                    sol_amount=1.2 + (w % 3) * 0.2,
                    token_amount=1000,
                )
            )
    return trades


def main() -> None:
    trades = _gen_trades()
    t0 = time.perf_counter()
    trips = match_round_trips(trades)
    t1 = time.perf_counter()
    wallets = {t.wallet for t in trades}
    for w in wallets:
        compute_wallet_performance(w, trades)
    t2 = time.perf_counter()
    print(
        {
            "trades": len(trades),
            "round_trips": len(trips),
            "wallets": len(wallets),
            "match_ms": round((t1 - t0) * 1000, 2),
            "perf_all_ms": round((t2 - t1) * 1000, 2),
        }
    )


if __name__ == "__main__":
    main()
