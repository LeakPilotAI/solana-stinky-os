"""Fail closed on stale active migration tracks; never manufacture completion."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post-migration-collector" / "src"))

from post_migration.config import settings
from post_migration.store import Store

RECOVERED_MINT_SAMPLE_LIMIT = 20


def bounded_recovery_evidence(mints: list[str]) -> dict[str, object]:
    """Preserve audit identity without flooding/clipping the operator terminal."""
    normalized = sorted(str(mint) for mint in mints)
    digest = hashlib.sha256(("\n".join(normalized) + ("\n" if normalized else "")).encode("utf-8")).hexdigest()
    return {
        "recovered_interrupted_tracks": len(normalized),
        "recovered_mint_sample": normalized[:RECOVERED_MINT_SAMPLE_LIMIT],
        "recovered_mint_sample_limit": RECOVERED_MINT_SAMPLE_LIMIT,
        "recovered_mint_set_sha256": digest,
        "recovered_mint_list_truncated": len(normalized) > RECOVERED_MINT_SAMPLE_LIMIT,
    }


async def main() -> int:
    store = Store()
    try:
        mints = await store.fail_stale_active_tracks(
            max_duration_sec=settings.track_max_duration_sec
        )
        evidence = bounded_recovery_evidence(mints)
        print(
            json.dumps(
                {
                    "status": "OBSERVED",
                    **evidence,
                    "new_status": "failed",
                    "completion_manufactured": False,
                    "paper_only": True,
                    "live_execution": False,
                    "trading_authority": False,
                    "rpc_contacted": False,
                    "transaction_signed": False,
                    "order_submitted": False,
                    "wallet_mutated": False,
                },
                sort_keys=True,
                indent=2,
            )
        )
    finally:
        await store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
