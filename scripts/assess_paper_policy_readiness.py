"""Assess Genesis prospective evidence for a reviewable paper-policy threshold proposal."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api" / "src"))

from stinky_api.db import SessionLocal
from stinky_api.evidence_paper_policy_readiness import assess_current_prospective_policy_readiness


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Evidence-only PAPER policy readiness. Criteria are explicit; no defaults exist.")
    p.add_argument("--min-closed-outcomes", required=True, type=int)
    p.add_argument("--min-market-cap-samples", required=True, type=int)
    p.add_argument("--min-outcome-classes", required=True, type=int, choices=[1, 2, 3])
    return p


async def run(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        result = await assess_current_prospective_policy_readiness(
            session,
            min_closed_outcomes=args.min_closed_outcomes,
            min_market_cap_samples=args.min_market_cap_samples,
            min_outcome_classes=args.min_outcome_classes,
        )
    print(json.dumps(result, sort_keys=True, default=str, indent=2))
    return 0 if result.get("status") == "READY_FOR_OPERATOR_REVIEW" else 2


def main() -> None:
    raise SystemExit(asyncio.run(run(parser().parse_args())))


if __name__ == "__main__":
    main()
