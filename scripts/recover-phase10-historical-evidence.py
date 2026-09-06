"""Operator command for Phase-10 historical evidence audit and conservative recovery."""
from __future__ import annotations

import argparse
import asyncio
import json

from stinky_api.db import SessionLocal
from stinky_api.historical_evidence_reconstruction import (
    historical_reconstruction_audit,
    initialize_phase10_snapshot_memory,
    recover_direct_migration_launches,
)


async def _run(*, limit: int, initialize_snapshots: bool, recover_launches: bool) -> None:
    async with SessionLocal() as session:
        if recover_launches:
            result = await recover_direct_migration_launches(session, limit=limit)
        elif initialize_snapshots:
            initialized = await initialize_phase10_snapshot_memory(session)
            audit = await historical_reconstruction_audit(session)
            result = {"initialization": initialized, "audit": audit}
        else:
            result = await historical_reconstruction_audit(session)
        print(json.dumps(result, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit or conservatively recover Phase-10 historical evidence."
    )
    parser.add_argument("--limit", type=int, default=500, help="Maximum launch identities to recover (1..5000).")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--initialize-snapshots", action="store_true", help="Create empty prospective developer/correlation snapshot memory. Does not backfill snapshots.")
    actions.add_argument("--recover-launches", action="store_true", help="Recover direct migration creator/mint launch identities. Derived snapshots are not backdated.")
    args = parser.parse_args()
    asyncio.run(_run(limit=args.limit, initialize_snapshots=args.initialize_snapshots, recover_launches=args.recover_launches))


if __name__ == "__main__":
    main()
