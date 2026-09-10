"""Read-only local report for Genesis prospective paper-policy readiness.

This script does not provision or activate a policy. Sufficiency criteria are
explicit command-line inputs; Genesis supplies no hidden defaults.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api" / "src"))

from stinky_api.db import SessionLocal
from stinky_api.evidence_paper_policy_readiness import assess_current_prospective_policy_readiness

AUTHORITY = {
    "paper_only": True,
    "read_only_report": True,
    "automatic_activation": False,
    "live_execution": False,
    "trading_authority": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only Genesis local paper readiness report. Criteria are required; no defaults exist.")
    p.add_argument("--min-closed-outcomes", required=True, type=int)
    p.add_argument("--min-market-cap-samples", required=True, type=int)
    p.add_argument("--min-outcome-classes", required=True, type=int, choices=[1, 2, 3])
    p.add_argument("--json", action="store_true", help="Print the complete machine-readable report.")
    return p


def _positive(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def summarize(result: dict[str, Any], *, min_closed: int, min_market: int, min_classes: int) -> dict[str, Any]:
    closed = _positive(result.get("prospective_closed_outcomes", result.get("closed_outcomes", 0)))
    counts = result.get("prospective_outcome_counts") if isinstance(result.get("prospective_outcome_counts"), dict) else {}
    represented = sum(1 for key in ("RUNNER", "HELD", "FADE") if _positive(counts.get(key)) > 0)
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    market_samples = _positive(evidence.get("market_cap_samples"))
    missing = list(result.get("missing") or [])
    return {
        "status": result.get("status", "UNKNOWN"),
        "criteria": {
            "min_closed_outcomes": min_closed,
            "min_market_cap_samples": min_market,
            "min_outcome_classes": min_classes,
        },
        "observed": {
            "closed_outcomes": closed,
            "outcome_counts": {k: _positive(counts.get(k)) for k in ("RUNNER", "HELD", "FADE")},
            "represented_outcome_classes": represented,
            "market_cap_samples": market_samples,
        },
        "deficits": {
            "closed_outcomes_needed": max(0, min_closed - closed),
            "outcome_classes_needed": max(0, min_classes - represented),
            "market_cap_samples_needed": max(0, min_market - market_samples),
        },
        "missing": missing,
        "threshold_proposal": result.get("threshold_proposal") if result.get("status") == "READY_FOR_OPERATOR_REVIEW" else None,
        "point_estimates": result.get("point_estimates") if result.get("status") == "READY_FOR_OPERATOR_REVIEW" else None,
        "as_of": result.get("as_of"),
        "prospective_started_at": result.get("prospective_started_at"),
        **AUTHORITY,
    }


async def run(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        raw = await assess_current_prospective_policy_readiness(
            session,
            min_closed_outcomes=args.min_closed_outcomes,
            min_market_cap_samples=args.min_market_cap_samples,
            min_outcome_classes=args.min_outcome_classes,
        )
    report = summarize(
        raw,
        min_closed=args.min_closed_outcomes,
        min_market=args.min_market_cap_samples,
        min_classes=args.min_outcome_classes,
    )
    if args.json:
        print(json.dumps({"report": report, "raw_readiness": raw}, sort_keys=True, default=str, indent=2))
    else:
        print("GENESIS PAPER READINESS")
        print(f"Status: {report['status']}")
        print(f"Prospective epoch: {report.get('prospective_started_at') or 'UNKNOWN'}")
        print(f"Closed outcomes: {report['observed']['closed_outcomes']} / {args.min_closed_outcomes}")
        oc = report['observed']['outcome_counts']
        print(f"Outcome classes: RUNNER={oc['RUNNER']} HELD={oc['HELD']} FADE={oc['FADE']} ({report['observed']['represented_outcome_classes']} / {args.min_outcome_classes} represented)")
        print(f"Market-cap samples: {report['observed']['market_cap_samples']} / {args.min_market_cap_samples}")
        deficits = report["deficits"]
        print(f"Still needed: closed={deficits['closed_outcomes_needed']} classes={deficits['outcome_classes_needed']} market_cap={deficits['market_cap_samples_needed']}")
        print("Missing: " + (", ".join(report["missing"]) if report["missing"] else "none"))
        if report["threshold_proposal"] is not None:
            print("Threshold proposal (review only; NOT activated):")
            print(json.dumps(report["threshold_proposal"], sort_keys=True, indent=2))
        print("Authority: PAPER ONLY / READ ONLY / LIVE LOCKED / NO AUTOMATIC ACTIVATION")
    return 0 if report.get("status") == "READY_FOR_OPERATOR_REVIEW" else 2


def main() -> None:
    raise SystemExit(asyncio.run(run(parser().parse_args())))


if __name__ == "__main__":
    main()
