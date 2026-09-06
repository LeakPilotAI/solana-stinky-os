"""Read-only operator audit for exact Phase-10 research cohort provenance."""
from __future__ import annotations

import argparse
import asyncio
import json

from stinky_api.db import SessionLocal
from stinky_api.phase10_cohort_provenance import audit_phase10_cohort_provenance


async def _run(limit: int, feature_horizon_seconds: int) -> None:
    async with SessionLocal() as session:
        result = await audit_phase10_cohort_provenance(
            session,
            limit=limit,
            feature_horizon_seconds=feature_horizon_seconds,
        )
        print(json.dumps(result, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit label and feature provenance for the exact Phase-10 research cohort."
    )
    parser.add_argument("--limit", type=int, default=200, help="Cohort rows (1..500).")
    parser.add_argument(
        "--feature-horizon-seconds",
        type=int,
        default=300,
        help="Feature cutoff after launch (0..1800 seconds).",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.limit, args.feature_horizon_seconds))


if __name__ == "__main__":
    main()
