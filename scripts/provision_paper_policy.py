"""Provision an explicit paper-only Genesis policy from operator-supplied values."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api" / "src"))

from stinky_api.db import SessionLocal
from stinky_api.paper_policy_provisioning import provision_paper_policy


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Provision a versioned Genesis PAPER-ONLY policy. No defaults are supplied.")
    p.add_argument("--policy-version", required=True)
    p.add_argument("--horizon", required=True, choices=["5m", "15m", "30m", "1h", "4h", "24h"])
    p.add_argument("--min-runner-probability", required=True, type=float)
    p.add_argument("--max-fade-probability", required=True, type=float)
    p.add_argument("--min-nonnegative-market-cap-probability", required=True, type=float)
    p.add_argument("--entry-slippage-bps", required=True, type=float)
    p.add_argument("--exit-slippage-bps", required=True, type=float)
    p.add_argument("--entry-fee-bps", required=True, type=float)
    p.add_argument("--exit-fee-bps", required=True, type=float)
    p.add_argument("--latency-ms", required=True, type=float)
    p.add_argument("--paper-notional-usd", required=True, type=float)
    p.add_argument("--provision-only", action="store_true", help="Register immutably without activating.")
    return p


async def run(args: argparse.Namespace) -> int:
    config = {
        "paper_policy": {
            "policy_version": args.policy_version,
            "horizon": args.horizon,
            "min_runner_probability": args.min_runner_probability,
            "max_fade_probability": args.max_fade_probability,
            "min_nonnegative_market_cap_probability": args.min_nonnegative_market_cap_probability,
        },
        "execution_assumptions": {
            "entry_slippage_bps": args.entry_slippage_bps,
            "exit_slippage_bps": args.exit_slippage_bps,
            "entry_fee_bps": args.entry_fee_bps,
            "exit_fee_bps": args.exit_fee_bps,
            "latency_ms": args.latency_ms,
        },
        "paper_notional_usd": args.paper_notional_usd,
    }
    async with SessionLocal() as session:
        result = await provision_paper_policy(session, config, activate=not args.provision_only)
    print(json.dumps(result, sort_keys=True, default=str))
    return 0 if result.get("status") in {"ACTIVE", "PROVISIONED"} else 2


def main() -> None:
    args = parser().parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
