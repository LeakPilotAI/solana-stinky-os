"""Print bounded live entity-readiness cohort coverage as JSON.

Run from services/api with the normal Genesis environment:
    python scripts/live_entity_readiness_cohort.py --entity-limit 100
"""
from __future__ import annotations

import argparse
import asyncio
import json

from stinky_api.db import SessionLocal
from stinky_api.entity_readiness_live_cohort import live_entity_readiness_cohort_validation


def _args():
    parser = argparse.ArgumentParser(description="Measure captured entity-readiness replay coverage")
    parser.add_argument("--entity-limit", type=int, default=100)
    parser.add_argument("--snapshot-limit", type=int, default=100)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--include-entities", action="store_true")
    return parser.parse_args()


async def _run(args) -> int:
    async with SessionLocal() as session:
        try:
            result = await live_entity_readiness_cohort_validation(
                session,
                entity_limit=args.entity_limit,
                snapshot_limit_per_entity=args.snapshot_limit,
                as_of=args.as_of,
                include_entities=args.include_entities,
            )
        finally:
            # This command is observational by contract. Never persist transaction state.
            await session.rollback()
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 2 if result.get("status") == "TEMPORAL_VIOLATION" else 0


def main() -> int:
    return asyncio.run(_run(_args()))


if __name__ == "__main__":
    raise SystemExit(main())
