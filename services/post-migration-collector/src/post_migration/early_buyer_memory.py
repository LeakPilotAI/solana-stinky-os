"""Descriptive recurring early-buyer memory derived from immutable captures.

This module deliberately does not assign quality, risk, coordination, insider
status, prediction, or trade authority. It collapses repeated capture groups for
one mint to the latest immutable observation, then counts recurrence only across
distinct launches and attributes measured launch outcomes when available.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from post_migration.config import settings


LATEST_MEMBERSHIP_CTE = """
WITH capture_groups AS (
    SELECT mint, capture_txid, MIN(observed_at) AS captured_at
    FROM migration_buyer_history
    GROUP BY mint, capture_txid
),
latest_capture AS (
    SELECT mint, capture_txid, captured_at
    FROM (
        SELECT mint, capture_txid, captured_at,
               ROW_NUMBER() OVER (
                   PARTITION BY mint
                   ORDER BY captured_at DESC, capture_txid DESC
               ) AS rn
        FROM capture_groups
    ) ranked
    WHERE rn = 1
),
latest_membership AS (
    SELECT h.mint,
           h.wallet,
           MIN(h.rank) AS rank,
           lc.captured_at,
           lc.capture_txid
    FROM migration_buyer_history h
    JOIN latest_capture lc
      ON lc.mint = h.mint
     AND lc.capture_txid = h.capture_txid
    GROUP BY h.mint, h.wallet, lc.captured_at, lc.capture_txid
)
"""


class EarlyBuyerMemoryStore:
    """Read-only recurrence and outcome attribution over persistent evidence."""

    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or settings.database_url
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
        self._engine = create_async_engine(url, pool_pre_ping=True, pool_size=3)
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def _has_entity_launches(self, session: AsyncSession) -> bool:
        row = (
            await session.execute(
                text("SELECT to_regclass('public.entity_launches') IS NOT NULL")
            )
        ).first()
        return bool(row and row[0])

    async def list_wallet_memory(
        self,
        *,
        min_distinct_launches: int = 2,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return wallets recurring across distinct launches.

        Repeated immutable captures of the same mint never increase the launch
        count. The latest immutable capture is the current descriptive membership
        projection; prior captures remain preserved in migration_buyer_history.
        """
        min_launches = max(1, int(min_distinct_launches))
        bounded_limit = max(1, min(int(limit), 500))
        async with self._sessions() as session:
            has_outcomes = await self._has_entity_launches(session)
            if has_outcomes:
                outcome_cte = """,
launch_evidence AS (
    SELECT lm.mint,
           lm.wallet,
           lm.rank,
           lm.captured_at,
           lm.capture_txid,
           mt.migration_at,
           outcome.outcome_status
    FROM latest_membership lm
    LEFT JOIN migration_tracks mt ON mt.mint = lm.mint
    LEFT JOIN LATERAL (
        SELECT el.outcome_status
        FROM entity_launches el
        WHERE el.mint = lm.mint
        ORDER BY el.observed_at DESC, el.id DESC
        LIMIT 1
    ) outcome ON TRUE
)
"""
            else:
                outcome_cte = """,
launch_evidence AS (
    SELECT lm.mint,
           lm.wallet,
           lm.rank,
           lm.captured_at,
           lm.capture_txid,
           mt.migration_at,
           NULL::TEXT AS outcome_status
    FROM latest_membership lm
    LEFT JOIN migration_tracks mt ON mt.mint = lm.mint
)
"""

            sql = LATEST_MEMBERSHIP_CTE + outcome_cte + """
SELECT wallet,
       COUNT(*) AS distinct_launches,
       COUNT(*) FILTER (WHERE rank <= 5) AS first5_launches,
       COUNT(*) FILTER (WHERE rank <= 10) AS first10_launches,
       COUNT(*) FILTER (WHERE rank <= 20) AS first20_launches,
       MIN(rank) AS best_rank,
       MIN(migration_at) AS first_launch_at,
       MAX(migration_at) AS last_launch_at,
       COUNT(*) FILTER (WHERE outcome_status IS NOT NULL) AS attributed_outcomes,
       COUNT(*) FILTER (WHERE UPPER(outcome_status) = 'RUNNER') AS runner_outcomes,
       COUNT(*) FILTER (WHERE UPPER(outcome_status) = 'HELD') AS held_outcomes,
       COUNT(*) FILTER (WHERE UPPER(outcome_status) = 'FADE') AS fade_outcomes,
       COUNT(*) FILTER (
           WHERE outcome_status IS NULL OR UPPER(outcome_status) = 'UNKNOWN'
       ) AS unknown_outcomes
FROM launch_evidence
GROUP BY wallet
HAVING COUNT(*) >= :min_launches
ORDER BY distinct_launches DESC, first5_launches DESC, wallet ASC
LIMIT :limit
"""
            rows = (
                await session.execute(
                    text(sql),
                    {"min_launches": min_launches, "limit": bounded_limit},
                )
            ).mappings().all()
            return [dict(row) for row in rows]

    async def list_wallet_launches(
        self,
        *,
        wallet: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the distinct launches supporting one wallet's recurrence."""
        wallet = str(wallet or "").strip()
        if not wallet:
            return []
        bounded_limit = max(1, min(int(limit), 500))
        async with self._sessions() as session:
            has_outcomes = await self._has_entity_launches(session)
            if has_outcomes:
                outcome_select = """
       outcome.outcome_status,
"""
                outcome_join = """
LEFT JOIN LATERAL (
    SELECT el.outcome_status
    FROM entity_launches el
    WHERE el.mint = lm.mint
    ORDER BY el.observed_at DESC, el.id DESC
    LIMIT 1
) outcome ON TRUE
"""
            else:
                outcome_select = "       NULL::TEXT AS outcome_status,\n"
                outcome_join = ""

            sql = LATEST_MEMBERSHIP_CTE + f"""
SELECT lm.mint,
       lm.rank,
       lm.captured_at,
       lm.capture_txid,
       mt.migration_at,
{outcome_select}       CASE WHEN lm.rank <= 5 THEN TRUE ELSE FALSE END AS first5,
       CASE WHEN lm.rank <= 10 THEN TRUE ELSE FALSE END AS first10,
       CASE WHEN lm.rank <= 20 THEN TRUE ELSE FALSE END AS first20
FROM latest_membership lm
LEFT JOIN migration_tracks mt ON mt.mint = lm.mint
{outcome_join}WHERE lm.wallet = :wallet
ORDER BY mt.migration_at ASC NULLS LAST, lm.mint ASC
LIMIT :limit
"""
            rows = (
                await session.execute(
                    text(sql), {"wallet": wallet, "limit": bounded_limit}
                )
            ).mappings().all()
            return [dict(row) for row in rows]
