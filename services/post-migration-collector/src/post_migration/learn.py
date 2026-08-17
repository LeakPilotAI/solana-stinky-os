"""Orchestrate success learning against Postgres (replayable)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import orjson
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from post_migration.config import settings
from post_migration.learner import (
    TokenOutcome,
    aggregate_wallet_early_success,
    label_token_from_peaks,
)

logger = structlog.get_logger(__name__)


class SuccessLearner:
    def __init__(self) -> None:
        self._engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, pool_size=5
        )
        self._sessions = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def close(self) -> None:
        await self._engine.dispose()

    async def ensure_schema(self) -> None:
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "002_success_learning.sql"
        )
        async with self._sessions() as session:
            exists = (
                await session.execute(
                    text(
                        """
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'token_outcomes'
                        """
                    )
                )
            ).first()
            if exists:
                logger.info("learn.schema_present")
                # still ensure wallet_performance columns
                await session.execute(
                    text(
                        """
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'wallet_performance'
                                  AND column_name = 'early_success_rate'
                            ) THEN
                                ALTER TABLE wallet_performance
                                    ADD COLUMN early_success_rate NUMERIC,
                                    ADD COLUMN early_on_runner INT NOT NULL DEFAULT 0,
                                    ADD COLUMN early_on_mega INT NOT NULL DEFAULT 0,
                                    ADD COLUMN early_success_sample INT NOT NULL DEFAULT 0;
                            END IF;
                        END $$;
                        """
                    )
                )
                await session.commit()
                return
            if path.exists():
                sql = path.read_text(encoding="utf-8")
                # execute statement-by-statement skipping empty
                for stmt in sql.split(";"):
                    s = stmt.strip()
                    if not s or s.startswith("--"):
                        continue
                    try:
                        await session.execute(text(s))
                    except Exception as exc:
                        logger.warning("learn.schema_stmt_failed", error=str(exc)[:200])
                await session.commit()
                logger.info("learn.schema_applied")
            else:
                # inline minimal
                await session.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS token_outcomes (
                            mint TEXT PRIMARY KEY,
                            evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            migration_at TIMESTAMPTZ,
                            snapshots_n INT NOT NULL DEFAULT 0,
                            peak_volume_m5_usd NUMERIC,
                            peak_liquidity_usd NUMERIC,
                            peak_market_cap_usd NUMERIC,
                            peak_price_usd NUMERIC,
                            label TEXT NOT NULL,
                            hours_observed NUMERIC,
                            notes TEXT,
                            meta JSONB NOT NULL DEFAULT '{}'
                        )
                        """
                    )
                )
                await session.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS wallet_early_success (
                            wallet TEXT PRIMARY KEY,
                            early_entries INT NOT NULL DEFAULT 0,
                            early_on_mega INT NOT NULL DEFAULT 0,
                            early_on_runner INT NOT NULL DEFAULT 0,
                            early_on_mid INT NOT NULL DEFAULT 0,
                            early_on_fade INT NOT NULL DEFAULT 0,
                            early_on_unknown INT NOT NULL DEFAULT 0,
                            success_rate NUMERIC,
                            sample_size INT NOT NULL DEFAULT 0,
                            last_success_at TIMESTAMPTZ,
                            last_fade_at TIMESTAMPTZ,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                        """
                    )
                )
                await session.commit()
                logger.info("learn.schema_inline")

    async def evaluate_all_tokens(self, *, limit: int = 2000) -> dict[str, int]:
        """Label every tracked mint from market_snapshots peaks."""
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT
                            t.mint,
                            t.started_at AS migration_at,
                            COUNT(s.snapshot_id)::int AS snapshots_n,
                            MAX(s.volume_m5_usd) AS peak_vol,
                            MAX(s.liquidity_usd) AS peak_liq,
                            MAX(s.market_cap_usd) AS peak_mcap,
                            MAX(s.price_usd) AS peak_price
                        FROM migration_tracks t
                        LEFT JOIN market_snapshots s ON s.mint = t.mint
                        GROUP BY t.mint, t.started_at
                        ORDER BY t.started_at DESC NULLS LAST
                        LIMIT :lim
                        """
                    ),
                    {"lim": limit},
                )
            ).mappings().all()

            counts: dict[str, int] = {}
            now = datetime.now(timezone.utc)
            for r in rows:
                outcome = label_token_from_peaks(
                    mint=str(r["mint"]),
                    peak_volume_m5=float(r["peak_vol"]) if r["peak_vol"] is not None else None,
                    peak_liquidity=float(r["peak_liq"]) if r["peak_liq"] is not None else None,
                    peak_mcap=float(r["peak_mcap"]) if r["peak_mcap"] is not None else None,
                    peak_price=float(r["peak_price"]) if r["peak_price"] is not None else None,
                    snapshots_n=int(r["snapshots_n"] or 0),
                    migration_at=r["migration_at"],
                    evaluated_at=now,
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO token_outcomes (
                            mint, evaluated_at, migration_at, snapshots_n,
                            peak_volume_m5_usd, peak_liquidity_usd,
                            peak_market_cap_usd, peak_price_usd,
                            label, hours_observed, notes, meta
                        ) VALUES (
                            :mint, now(), :migration_at, :snap,
                            :vol, :liq, :mcap, :price,
                            :label, :hours, :notes, CAST(:meta AS jsonb)
                        )
                        ON CONFLICT (mint) DO UPDATE SET
                            evaluated_at = now(),
                            snapshots_n = EXCLUDED.snapshots_n,
                            peak_volume_m5_usd = EXCLUDED.peak_volume_m5_usd,
                            peak_liquidity_usd = EXCLUDED.peak_liquidity_usd,
                            peak_market_cap_usd = EXCLUDED.peak_market_cap_usd,
                            peak_price_usd = EXCLUDED.peak_price_usd,
                            label = EXCLUDED.label,
                            hours_observed = EXCLUDED.hours_observed,
                            notes = EXCLUDED.notes
                        """
                    ),
                    {
                        "mint": outcome.mint,
                        "migration_at": outcome.migration_at,
                        "snap": outcome.snapshots_n,
                        "vol": outcome.peak_volume_m5_usd,
                        "liq": outcome.peak_liquidity_usd,
                        "mcap": outcome.peak_market_cap_usd,
                        "price": outcome.peak_price_usd,
                        "label": outcome.label,
                        "hours": outcome.hours_observed,
                        "notes": outcome.notes,
                        "meta": "{}",
                    },
                )
                counts[outcome.label] = counts.get(outcome.label, 0) + 1
            await session.commit()
            logger.info("learn.tokens_evaluated", **counts, total=sum(counts.values()))
            return counts

    async def attribute_early_buyers(self) -> int:
        """Credit migration_buyers on labeled token_outcomes → wallet_early_success."""
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT mb.wallet, o.label, mb.bought_at
                        FROM migration_buyers mb
                        INNER JOIN token_outcomes o ON o.mint = mb.mint
                        WHERE mb.wallet IS NOT NULL
                        """
                    )
                )
            ).mappings().all()
            stats = aggregate_wallet_early_success([dict(r) for r in rows])
            for s in stats:
                await session.execute(
                    text(
                        """
                        INSERT INTO wallet_early_success (
                            wallet, early_entries, early_on_mega, early_on_runner,
                            early_on_mid, early_on_fade, early_on_unknown,
                            success_rate, sample_size, last_success_at, last_fade_at,
                            updated_at
                        ) VALUES (
                            :w, :ee, :mega, :runner, :mid, :fade, :unk,
                            :rate, :sample, :ls, :lf, now()
                        )
                        ON CONFLICT (wallet) DO UPDATE SET
                            early_entries = EXCLUDED.early_entries,
                            early_on_mega = EXCLUDED.early_on_mega,
                            early_on_runner = EXCLUDED.early_on_runner,
                            early_on_mid = EXCLUDED.early_on_mid,
                            early_on_fade = EXCLUDED.early_on_fade,
                            early_on_unknown = EXCLUDED.early_on_unknown,
                            success_rate = EXCLUDED.success_rate,
                            sample_size = EXCLUDED.sample_size,
                            last_success_at = EXCLUDED.last_success_at,
                            last_fade_at = EXCLUDED.last_fade_at,
                            updated_at = now()
                        """
                    ),
                    {
                        "w": s.wallet,
                        "ee": s.early_entries,
                        "mega": s.early_on_mega,
                        "runner": s.early_on_runner,
                        "mid": s.early_on_mid,
                        "fade": s.early_on_fade,
                        "unk": s.early_on_unknown,
                        "rate": s.success_rate,
                        "sample": s.sample_size,
                        "ls": s.last_success_at,
                        "lf": s.last_fade_at,
                    },
                )
                # Mirror into wallet_performance for score engine
                await session.execute(
                    text(
                        """
                        INSERT INTO wallet_performance (
                            wallet, early_success_rate, early_on_runner,
                            early_on_mega, early_success_sample, updated_at
                        ) VALUES (
                            :w, :rate, :runner, :mega, :sample, now()
                        )
                        ON CONFLICT (wallet) DO UPDATE SET
                            early_success_rate = EXCLUDED.early_success_rate,
                            early_on_runner = EXCLUDED.early_on_runner,
                            early_on_mega = EXCLUDED.early_on_mega,
                            early_success_sample = EXCLUDED.early_success_sample,
                            updated_at = now()
                        """
                    ),
                    {
                        "w": s.wallet,
                        "rate": s.success_rate,
                        "runner": s.early_on_runner + s.early_on_mega,
                        "mega": s.early_on_mega,
                        "sample": s.sample_size,
                    },
                )
            await session.commit()
            logger.info("learn.wallets_attributed", wallets=len(stats))
            return len(stats)

    async def run_full(self, *, token_limit: int = 2000) -> dict[str, Any]:
        await self.ensure_schema()
        labels = await self.evaluate_all_tokens(limit=token_limit)
        wallets = await self.attribute_early_buyers()
        return {"token_labels": labels, "wallets_updated": wallets}
