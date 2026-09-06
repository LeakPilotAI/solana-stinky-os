"""Explicit operator command for conservative Phase-10 historical bridge recovery."""
from __future__ import annotations

import argparse
import asyncio
import json

from stinky_api.db import SessionLocal
from stinky_api.historical_research_bridge import (
    historical_research_bridge_preflight,
    recover_historical_research_bridge,
)


async def _run(limit: int, dry_run: bool) -> None:
    async with SessionLocal() as session:
        if dry_run:
            result = await historical_research_bridge_preflight(session)
        else:
            result = await recover_historical_research_bridge(session, limit=limit)
        print(json.dumps(result, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover historically defensible migration→entity launch rows for Phase 10 research."
    )
    parser.add_argument("--limit", type=int, default=500, help="Maximum rows to bridge (1..5000).")
    parser.add_argument("--dry-run", action="store_true", help="Show bridge inventory without writing.")
    args = parser.parse_args()
    asyncio.run(_run(args.limit, args.dry_run))


if __name__ == "__main__":
    main()
