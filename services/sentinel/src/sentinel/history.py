"""Creator wallet historical activity from our event store + RPC bootstrap."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sentinel.config import settings
from sentinel.models import WalletSummary
from sentinel.rate_limit import gate
from sentinel.rpc import SolanaRPC

logger = structlog.get_logger(__name__)


class WalletHistory:
    def __init__(self, rpc: SolanaRPC) -> None:
        self._rpc = rpc
        self._engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=3,
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def _from_event_store(self, address: str) -> dict[str, Any]:
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT
                            COUNT(*)::int AS launch_count,
                            MIN(occurred_at) AS first_seen,
                            ARRAY(
                                SELECT payload->>'mint'
                                FROM events e2
                                WHERE e2.event_type = 'token.launch'
                                  AND e2.payload->>'deployer' = :addr
                                  AND e2.payload->>'mint' IS NOT NULL
                                ORDER BY e2.occurred_at DESC
                                LIMIT 10
                            ) AS recent_mints
                        FROM events
                        WHERE event_type = 'token.launch'
                          AND payload->>'deployer' = :addr
                        """
                    ),
                    {"addr": address},
                )
                row = result.mappings().first()
                if not row:
                    return {"launch_count": 0, "first_seen": None, "recent_mints": []}
                return {
                    "launch_count": int(row["launch_count"] or 0),
                    "first_seen": row["first_seen"],
                    "recent_mints": [m for m in (row["recent_mints"] or []) if m],
                }
        except Exception as exc:
            logger.warning("history.event_store_failed", error=str(exc))
            return {"launch_count": 0, "first_seen": None, "recent_mints": []}

    async def _from_rpc(self, address: str, *, limit: int = 25) -> dict[str, Any]:
        if gate.tripped and settings.skip_rpc_history_when_throttled:
            return {"tx_count": 0, "first_seen": None, "skipped": True}
        try:
            sigs = await self._rpc.get_signatures_for_address(address, limit=limit)
        except Exception as exc:
            logger.warning("history.rpc_failed", address=address, error=str(exc))
            return {"tx_count": 0, "first_seen": None}

        first_seen = None
        if sigs:
            oldest = sigs[-1]
            bt = oldest.get("blockTime")
            if bt:
                first_seen = datetime.fromtimestamp(bt, tz=timezone.utc)
        return {"tx_count": len(sigs), "first_seen": first_seen}

    async def summarize(self, address: str, *, limit: int = 25) -> WalletSummary:
        stored = await self._from_event_store(address)
        rpc = await self._from_rpc(address, limit=limit)

        first_seen = stored["first_seen"] or rpc.get("first_seen")
        launch_count = stored["launch_count"]
        if rpc.get("skipped"):
            note = (
                f"stored_launches={launch_count}; rpc history skipped (helius cooldown)"
                if launch_count
                else "rpc history skipped (helius cooldown); no stored launches yet"
            )
        elif launch_count == 0:
            note = f"rpc_recent_txs={rpc.get('tx_count', 0)}; no stored launches yet"
        else:
            note = f"stored_launches={launch_count}"

        return WalletSummary(
            address=address,
            first_seen=first_seen,
            launch_count=launch_count,
            recent_mints=stored["recent_mints"],
            note=note,
        )
