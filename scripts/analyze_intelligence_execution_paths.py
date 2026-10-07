#!/usr/bin/env python3
"""Read-only execution-path diagnostics for prospective execution-v1.

Descriptive post-outcome research only. Path extrema are hindsight diagnostics,
not executable rules and must not be interpreted as prospective exit policies.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from datetime import timedelta
from statistics import median

import asyncpg

POLICY = "genesis-paper-execution-v1"
ENTRY_LATENCY_SEC = 30
HOLD_SEC = 900
COST_PCT = 0.02
MIN_ENTRY_LIQUIDITY_USD = 1000.0

ROWS = """
SELECT p.id AS plan_id, p.mint, d.decided_at
FROM intelligence_paper_execution_plans p
JOIN intelligence_paper_decisions d
  ON d.id = p.paper_decision_id
WHERE p.execution_policy_version = $1
ORDER BY p.id
"""

SNAPS = """
SELECT captured_at, price_usd, liquidity_usd,
       volume_m5_usd, market_cap_usd
FROM market_snapshots
WHERE mint = $1
  AND captured_at >= $2
  AND captured_at <= $3
ORDER BY captured_at
"""


def dsn():
    return os.getenv(
        "STINKY_DATABASE_URL",
        "postgresql://stinky:stinky@127.0.0.1:5433/stinky",
    ).replace("postgresql+asyncpg://", "postgresql://", 1)


def q(values, p):
    if not values:
        return None
    a = sorted(values)
    pos = (len(a) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(a) - 1)
    frac = pos - lo
    return a[lo] + (a[hi] - a[lo]) * frac


def stats(values):
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": sum(values) / len(values),
        "median": median(values),
        "p25": q(values, 0.25),
        "p75": q(values, 0.75),
        "min": min(values),
        "max": max(values),
    }


def first_valid_after(snaps, target):
    return next(
        (
            s for s in snaps
            if s["captured_at"] >= target
            and s["price_usd"] is not None
            and float(s["price_usd"]) > 0
        ),
        None,
    )


def gap_stats(snaps):
    if len(snaps) < 2:
        return {"intervals": 0}

    gaps = [
        (b["captured_at"] - a["captured_at"]).total_seconds()
        for a, b in zip(snaps, snaps[1:])
    ]

    return {
        "intervals": len(gaps),
        "median_sec": median(gaps),
        "p90_sec": q(gaps, 0.90),
        "max_sec": max(gaps),
    }


async def run():
    conn = await asyncpg.connect(dsn())
    results = []

    try:
        rows = await conn.fetch(ROWS, POLICY)

        for row in rows:
            entry_target = row["decided_at"] + timedelta(
                seconds=ENTRY_LATENCY_SEC
            )
            exit_target = entry_target + timedelta(seconds=HOLD_SEC)

            # Diagnostic window ends at the frozen V1 exit target.
            snaps = await conn.fetch(
                SNAPS,
                row["mint"],
                row["decided_at"],
                exit_target,
            )

            valid = [
                s for s in snaps
                if s["price_usd"] is not None
                and float(s["price_usd"]) > 0
            ]

            base = {
                "plan_id": row["plan_id"],
                "snapshot_count": len(snaps),
                "valid_price_snapshots": len(valid),
                                "coverage": gap_stats(snaps),
                "coverage_quality": (
                    "NONE" if len(snaps) == 0
                    else "SPARSE" if len(snaps) < 10
                    else "DEGRADED" if gap_stats(snaps).get("p90_sec", 0) > 60
                    else "GOOD"
                ),
            }

            if not valid:
                results.append({
                    **base,
                    "status": "NO_MARKET_PATH",
                })
                continue

            entry = first_valid_after(valid, entry_target)

            if entry is None or entry["captured_at"] > exit_target:
                results.append({
                    **base,
                    "status": "NO_ENTRY_OBSERVATION",
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
                results.append({
                    **base,
                    "status": "ENTRY_LIQUIDITY_REJECT",
                    "entry_at": entry["captured_at"].isoformat(),
                    "entry_liquidity_usd": entry_liq,
                })
                continue

            entry_price = float(entry["price_usd"])

            post_entry = [
                s for s in valid
                if s["captured_at"] >= entry["captured_at"]
                and s["captured_at"] <= exit_target
            ]

            if not post_entry:
                results.append({
                    **base,
                    "status": "NO_POST_ENTRY_PATH",
                })
                continue

            peak = max(post_entry, key=lambda s: float(s["price_usd"]))
            trough = min(post_entry, key=lambda s: float(s["price_usd"]))

            peak_multiple = float(peak["price_usd"]) / entry_price
            trough_multiple = float(trough["price_usd"]) / entry_price

            exitrow = first_valid_after(valid, exit_target)

            # Because query window ends at exit_target, an observation exactly
            # at the target is rare. Query the first valid post-target point
            # separately to preserve V1 reporter semantics.
            if exitrow is None:
                exitrow = await conn.fetchrow(
                    """
                    SELECT captured_at, price_usd, liquidity_usd,
                           volume_m5_usd, market_cap_usd
                    FROM market_snapshots
                    WHERE mint=$1
                      AND captured_at >= $2
                      AND price_usd > 0
                    ORDER BY captured_at
                    LIMIT 1
                    """,
                    row["mint"],
                    exit_target,
                )

            below_entry = [
                s for s in post_entry[1:]
                if float(s["price_usd"]) < entry_price
            ]
            if below_entry:
                first_below_at = below_entry[0]["captured_at"]
                recovered_after_drawdown = any(
                    float(s["price_usd"]) >= entry_price
                    for s in post_entry
                    if s["captured_at"] > first_below_at
                )
            else:
                recovered_after_drawdown = None

            result = {
                **base,
                "status": "PATH_OBSERVED",
                "entry_at": entry["captured_at"].isoformat(),
                "entry_liquidity_usd": entry_liq,
                "entry_price_usd": entry_price,
                "peak_multiple": peak_multiple,
                "max_favorable_excursion_pct": peak_multiple - 1.0,
                "time_to_peak_sec": (
                    peak["captured_at"] - entry["captured_at"]
                ).total_seconds(),
                "trough_multiple": trough_multiple,
                "max_adverse_excursion_pct": trough_multiple - 1.0,
                "time_to_trough_sec": (
                    trough["captured_at"] - entry["captured_at"]
                ).total_seconds(),
                "recovered_after_drawdown": recovered_after_drawdown,
                "peak_liquidity_usd": (
                    float(peak["liquidity_usd"])
                    if peak["liquidity_usd"] is not None else None
                ),
                "trough_liquidity_usd": (
                    float(trough["liquidity_usd"])
                    if trough["liquidity_usd"] is not None else None
                ),
            }

            if exitrow is None:
                result["fixed_exit_status"] = "PENDING_EXIT"
            else:
                gross = float(exitrow["price_usd"]) / entry_price
                result.update({
                    "fixed_exit_status": "OBSERVED",
                    "exit_at": exitrow["captured_at"].isoformat(),
                    "gross_multiple": gross,
                    "net_multiple": gross * (1.0 - COST_PCT),
                })

            results.append(result)

        statuses = Counter(r["status"] for r in results)
        paths = [r for r in results if r["status"] == "PATH_OBSERVED"]
        exited = [
            r for r in paths
            if r.get("fixed_exit_status") == "OBSERVED"
        ]

        return {
            "version": "genesis-execution-path-diagnostic-v1",
            "source_execution_policy": POLICY,
            "assumptions": {
                "entry_latency_sec": ENTRY_LATENCY_SEC,
                "hold_sec": HOLD_SEC,
                "round_trip_cost_pct": COST_PCT,
                "min_entry_liquidity_usd": MIN_ENTRY_LIQUIDITY_USD,
            },
            "classification": "descriptive_post_outcome_diagnostic",
            "warning": (
                "Path extrema use hindsight and are not executable exit rules. "
                "This report must not be treated as prospective strategy evidence."
            ),
            "counts": dict(statuses),
            "summary": {
                "path_observed": len(paths),
                "fixed_exit_observed": len(exited),
                "peak_multiple": stats([
                    r["peak_multiple"] for r in paths
                ]),
                "trough_multiple": stats([
                    r["trough_multiple"] for r in paths
                ]),
                "time_to_peak_sec": stats([
                    r["time_to_peak_sec"] for r in paths
                ]),
                "time_to_trough_sec": stats([
                    r["time_to_trough_sec"] for r in paths
                ]),
                "fixed_exit_net_multiple": stats([
                    r["net_multiple"] for r in exited
                ]),
                "drawdown_recovery": {
                    "experienced_drawdown": sum(
                        r["recovered_after_drawdown"] is not None
                        for r in paths
                    ),
                    "recovered_after_drawdown": sum(
                        r["recovered_after_drawdown"] is True
                        for r in paths
                    ),
                },
            },
            "results": results,
            "read_only": True,
            "policy_retuning_permitted": False,
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
            f.write(payload + "`n")

    print(payload)


if __name__ == "__main__":
    main()

