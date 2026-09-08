"""Descriptive recurring early-buyer cohort memory.

This module derives wallet-pair co-occurrence only from the latest immutable
buyer capture for each mint. Repeated captures of one mint never inflate
recurrence. Results are descriptive evidence only: no insider, coordination,
ownership, quality, prediction, risk, or trade authority is inferred.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from post_migration.config import settings
from post_migration.early_buyer_memory import LATEST_MEMBERSHIP_CTE


class EarlyBuyerCohortStore:
    """Read-only recurring pair/cohort intelligence over immutable evidence."""

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

    @staticmethod
    def _pair_cte(*, has_outcomes: bool) -> str:
        outcome_select = "outcome.outcome_status" if has_outcomes else "NULL::TEXT AS outcome_status"
        outcome_join = (
            """
    LEFT JOIN LATERAL (
        SELECT el.outcome_status
        FROM entity_launches el
        WHERE el.mint = a.mint
        ORDER BY el.observed_at DESC, el.id DESC
        LIMIT 1
    ) outcome ON TRUE
"""
            if has_outcomes
            else ""
        )
        return f"""
,
bounded_membership AS (
    SELECT mint, wallet, rank, captured_at, capture_txid
    FROM latest_membership
    WHERE rank <= :max_rank
),
pair_launches AS (
    SELECT a.mint,
           a.wallet AS wallet_a,
           b.wallet AS wallet_b,
           a.rank AS rank_a,
           b.rank AS rank_b,
           GREATEST(a.rank, b.rank) AS pair_max_rank,
           ABS(a.rank - b.rank) AS rank_gap,
           a.captured_at,
           a.capture_txid,
           mt.migration_at,
           {outcome_select}
    FROM bounded_membership a
    JOIN bounded_membership b
      ON b.mint = a.mint
     AND b.wallet > a.wallet
    LEFT JOIN migration_tracks mt ON mt.mint = a.mint
{outcome_join})
"""

    async def list_recurring_pairs(
        self,
        *,
        min_distinct_launches: int = 2,
        max_rank: int = 20,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return wallet pairs recurring together across distinct launches."""
        min_launches = max(2, int(min_distinct_launches))
        bounded_rank = max(2, min(int(max_rank), 20))
        bounded_limit = max(1, min(int(limit), 500))

        async with self._sessions() as session:
            has_outcomes = await self._has_entity_launches(session)
            sql = LATEST_MEMBERSHIP_CTE + self._pair_cte(has_outcomes=has_outcomes) + """
SELECT wallet_a,
       wallet_b,
       COUNT(*) AS distinct_launches,
       COUNT(*) FILTER (WHERE pair_max_rank <= 5) AS first5_together,
       COUNT(*) FILTER (WHERE pair_max_rank <= 10) AS first10_together,
       COUNT(*) FILTER (WHERE pair_max_rank <= 20) AS first20_together,
       MIN(pair_max_rank) AS best_pair_rank,
       ROUND(AVG(rank_gap)::numeric, 3) AS avg_rank_gap,
       MIN(migration_at) AS first_launch_at,
       MAX(migration_at) AS last_launch_at,
       COUNT(*) FILTER (WHERE outcome_status IS NOT NULL) AS attributed_outcomes,
       COUNT(*) FILTER (WHERE UPPER(outcome_status) = 'RUNNER') AS runner_outcomes,
       COUNT(*) FILTER (WHERE UPPER(outcome_status) = 'HELD') AS held_outcomes,
       COUNT(*) FILTER (WHERE UPPER(outcome_status) = 'FADE') AS fade_outcomes,
       COUNT(*) FILTER (
           WHERE outcome_status IS NULL OR UPPER(outcome_status) = 'UNKNOWN'
       ) AS unknown_outcomes
FROM pair_launches
GROUP BY wallet_a, wallet_b
HAVING COUNT(*) >= :min_launches
ORDER BY distinct_launches DESC,
         first5_together DESC,
         first10_together DESC,
         best_pair_rank ASC,
         wallet_a ASC,
         wallet_b ASC
LIMIT :limit
"""
            rows = (
                await session.execute(
                    text(sql),
                    {
                        "min_launches": min_launches,
                        "max_rank": bounded_rank,
                        "limit": bounded_limit,
                    },
                )
            ).mappings().all()
            return [dict(row) for row in rows]

    async def list_pair_launches(
        self,
        *,
        wallet_a: str,
        wallet_b: str,
        max_rank: int = 20,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return distinct launches supporting one observable recurring pair."""
        first = str(wallet_a or "").strip()
        second = str(wallet_b or "").strip()
        if not first or not second or first == second:
            return []
        if first > second:
            first, second = second, first
        bounded_rank = max(2, min(int(max_rank), 20))
        bounded_limit = max(1, min(int(limit), 500))

        async with self._sessions() as session:
            has_outcomes = await self._has_entity_launches(session)
            sql = LATEST_MEMBERSHIP_CTE + self._pair_cte(has_outcomes=has_outcomes) + """
SELECT mint,
       rank_a,
       rank_b,
       pair_max_rank,
       rank_gap,
       captured_at,
       capture_txid,
       migration_at,
       outcome_status,
       CASE WHEN pair_max_rank <= 5 THEN TRUE ELSE FALSE END AS first5_together,
       CASE WHEN pair_max_rank <= 10 THEN TRUE ELSE FALSE END AS first10_together,
       CASE WHEN pair_max_rank <= 20 THEN TRUE ELSE FALSE END AS first20_together
FROM pair_launches
WHERE wallet_a = :wallet_a
  AND wallet_b = :wallet_b
ORDER BY migration_at ASC NULLS LAST, mint ASC
LIMIT :limit
"""
            rows = (
                await session.execute(
                    text(sql),
                    {
                        "wallet_a": first,
                        "wallet_b": second,
                        "max_rank": bounded_rank,
                        "limit": bounded_limit,
                    },
                )
            ).mappings().all()
            return [dict(row) for row in rows]
