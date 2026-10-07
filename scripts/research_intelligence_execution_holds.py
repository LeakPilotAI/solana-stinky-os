#!/usr/bin/env python3
"""Historical fixed-hold research over immutable execution-v1 plans.

This is retrospective hypothesis research. Comparing historical hold durations
does not make any duration prospective, validated, or authorized for trading.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import timedelta
from statistics import median

import asyncpg


POLICY = "genesis-paper-execution-v1"
ENTRY_LATENCY_SEC = 30
COST_PCT = 0.02
MIN_ENTRY_LIQUIDITY_USD = 1000.0

# Small predeclared research family. These are historical diagnostics only.
HOLD_SECONDS = (60, 120, 180, 300, 600, 900)


ROWS = """
SELECT p.id AS plan_id, p.mint, d.decided_at
FROM intelligence_paper_execution_plans p
JOIN intelligence_paper_decisions d
  ON d.id = p.paper_decision_id
WHERE p.execution_policy_version = $1
ORDER BY p.id
"""


def dsn():
    return os.getenv(
        "STINKY_DATABASE_URL",
        "postgresql://stinky:stinky@127.0.0.1:5433/stinky",
    ).replace("postgresql+asyncpg://", "postgresql://", 1)


def quantile(values, p):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] + (values[hi] - values[lo]) * frac


def summarize(values):
    if not values:
        return {"n": 0}

    wins = sum(v > 1.0 for v in values)

    return {
        "n": len(values),
        "mean_net_multiple": sum(values) / len(values),
        "median_net_multiple": median(values),
        "p25_net_multiple": quantile(values, 0.25),
        "p75_net_multiple": quantile(values, 0.75),
        "min_net_multiple": min(values),
        "max_net_multiple": max(values),
        "wins": wins,
        "win_rate": wins / len(values),
    }


async def v1_entry(conn, mint, entry_target):
    """Reproduce frozen V1 reporter entry semantics exactly."""
    v1_exit_target = entry_target + timedelta(seconds=900)

    snaps = await conn.fetch(
        """
        SELECT captured_at, price_usd, liquidity_usd
        FROM market_snapshots
        WHERE mint=$1
          AND captured_at >= $2
          AND price_usd > 0
        ORDER BY captured_at
        """,
        mint,
        entry_target,
    )

    return next(
        (
            row for row in snaps
            if row["captured_at"] <= v1_exit_target
        ),
        None,
    )


async def first_exit_at_or_after(conn, mint, target):
    return await conn.fetchrow(
        """
        SELECT captured_at, price_usd, liquidity_usd
        FROM market_snapshots
        WHERE mint=$1
          AND captured_at >= $2
          AND price_usd > 0
        ORDER BY captured_at
        LIMIT 1
        """,
        mint,
        target,
    )

async def run():
    conn = await asyncpg.connect(dsn())

    try:
        plans = await conn.fetch(ROWS, POLICY)

        results = {
            hold: {
                "filled": [],
                "no_fill": 0,
                "pending_exit": 0,
                "rows": [],
            }
            for hold in HOLD_SECONDS
        }

        for plan in plans:
            entry_target = plan["decided_at"] + timedelta(
                seconds=ENTRY_LATENCY_SEC
            )

            entry = await v1_entry(
                conn,
                plan["mint"],
                entry_target,
            )

            if entry is None:
                for hold in HOLD_SECONDS:
                    results[hold]["no_fill"] += 1
                    results[hold]["rows"].append({
                        "plan_id": plan["plan_id"],
                        "status": "NO_FILL",
                    })
                continue

            entry_liq = (
                float(entry["liquidity_usd"])
                if entry["liquidity_usd"] is not None
                else None
            )

            if (
                entry_liq is None
                or entry_liq < MIN_ENTRY_LIQUIDITY_USD
            ):
                for hold in HOLD_SECONDS:
                    results[hold]["no_fill"] += 1
                    results[hold]["rows"].append({
                        "plan_id": plan["plan_id"],
                        "status": "NO_FILL",
                    })
                continue

            entry_price = float(entry["price_usd"])

            for hold in HOLD_SECONDS:
                exit_target = entry_target + timedelta(
                    seconds=hold
                )

                exit_row = await first_exit_at_or_after(
                    conn,
                    plan["mint"],
                    exit_target,
                )

                if exit_row is None:
                    results[hold]["pending_exit"] += 1
                    results[hold]["rows"].append({
                        "plan_id": plan["plan_id"],
                        "status": "PENDING_EXIT",
                    })
                    continue

                gross = float(exit_row["price_usd"]) / entry_price
                net = gross * (1.0 - COST_PCT)

                results[hold]["filled"].append(net)
                results[hold]["rows"].append({
                    "plan_id": plan["plan_id"],
                    "status": "FILLED",
                    "entry_at": entry["captured_at"].isoformat(),
                    "exit_at": exit_row["captured_at"].isoformat(),
                    "gross_multiple": gross,
                    "net_multiple": net,
                })

        scenarios = {}

        for hold in HOLD_SECONDS:
            bucket = results[hold]
            scenarios[str(hold)] = {
                "hold_sec": hold,
                "filled": len(bucket["filled"]),
                "no_fill": bucket["no_fill"],
                "pending_exit": bucket["pending_exit"],
                "performance": summarize(bucket["filled"]),
                "rows": bucket["rows"],
            }

        return {
            "version": "genesis-execution-hold-research-v1",
            "source_execution_policy": POLICY,
            "classification": "retrospective_hypothesis_research",
            "assumptions": {
                "entry_latency_sec": ENTRY_LATENCY_SEC,
                "round_trip_cost_pct": COST_PCT,
                "min_entry_liquidity_usd": MIN_ENTRY_LIQUIDITY_USD,
                "hold_seconds": list(HOLD_SECONDS),
            },
            "warning": (
                "Hold durations are compared on historical execution-v1 paths. "
                "Results are hypothesis-generating only and must not be called "
                "prospective validation or used to grant trading authority."
            ),
            "scenarios": scenarios,
            "read_only": True,
            "policy_retuning_permitted": False,
            "prospective_validation": False,
            "live_trading_authority": False,
        }

    finally:
        await conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output")
    args = ap.parse_args()

    payload = json.dumps(
        asyncio.run(run()),
        indent=2,
        sort_keys=True,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload + "\n")

    print(payload)


if __name__ == "__main__":
    main()
