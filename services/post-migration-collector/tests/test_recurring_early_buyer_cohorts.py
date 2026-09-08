"""PostgreSQL-backed tests for recurring early-buyer cohort memory."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from post_migration.early_buyer_cohorts import EarlyBuyerCohortStore

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
DATABASE_URL = os.getenv("POST_MIGRATION_TEST_DATABASE_URL")


async def _track(conn: asyncpg.Connection, mint: str, when: datetime):
    track_id = uuid4()
    await conn.execute(
        "INSERT INTO migration_tracks (track_id, mint, migration_at) VALUES ($1, $2, $3)",
        track_id,
        mint,
        when,
    )
    return track_id


async def _capture(
    conn: asyncpg.Connection,
    *,
    track_id,
    mint: str,
    wallets: list[str],
    suffix: str,
) -> None:
    async with conn.transaction():
        await conn.execute("DELETE FROM migration_buyers WHERE mint = $1", mint)
        for rank, wallet in enumerate(wallets, start=1):
            await conn.execute(
                """
                INSERT INTO migration_buyers (
                    track_id, mint, wallet, rank, signature, bought_at,
                    is_meaningful, meta
                ) VALUES ($1, $2, $3, $4, $5, $6, TRUE, '{}'::jsonb)
                """,
                track_id,
                mint,
                wallet,
                rank,
                f"{mint}-{suffix}-{rank}",
                datetime.now(timezone.utc),
            )


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_pair_recurrence_counts_distinct_launches_not_recaptures() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    store = EarlyBuyerCohortStore(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.execute((MIGRATIONS / "001_post_migration_schema.sql").read_text())
        await conn.execute(
            """
            CREATE TABLE entity_launches (
                id BIGSERIAL PRIMARY KEY,
                mint TEXT,
                observed_at TIMESTAMPTZ NOT NULL,
                outcome_status TEXT
            );
            """
        )

        base = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
        mint_a = "MintPairA111111111111111111111111111111111111"
        mint_b = "MintPairB111111111111111111111111111111111111"
        track_a = await _track(conn, mint_a, base)
        track_b = await _track(conn, mint_b, base + timedelta(minutes=3))

        # First capture contains WalletStale, but the latest capture does not.
        # Historical evidence remains immutable, while current pair membership
        # must use only the latest capture and must not inflate recurrence.
        await _capture(
            conn,
            track_id=track_a,
            mint=mint_a,
            wallets=["WalletA", "WalletB", "WalletStale"],
            suffix="old",
        )
        await _capture(
            conn,
            track_id=track_a,
            mint=mint_a,
            wallets=["WalletA", "WalletB", "WalletNew"],
            suffix="new",
        )
        await _capture(
            conn,
            track_id=track_b,
            mint=mint_b,
            wallets=["WalletX", "WalletA", "WalletB"],
            suffix="one",
        )

        await conn.execute(
            "INSERT INTO entity_launches (mint, observed_at, outcome_status) VALUES ($1, $2, 'RUNNER'), ($3, $4, 'FADE')",
            mint_a,
            base + timedelta(hours=1),
            mint_b,
            base + timedelta(hours=1, minutes=3),
        )

        rows = await store.list_recurring_pairs(min_distinct_launches=2)
        pair = next(
            row
            for row in rows
            if {row["wallet_a"], row["wallet_b"]} == {"WalletA", "WalletB"}
        )
        assert pair["distinct_launches"] == 2
        assert pair["first5_together"] == 2
        assert pair["first10_together"] == 2
        assert pair["first20_together"] == 2
        assert pair["best_pair_rank"] == 2
        assert pair["runner_outcomes"] == 1
        assert pair["fade_outcomes"] == 1
        assert pair["attributed_outcomes"] == 2

        assert not any(
            "WalletStale" in {row["wallet_a"], row["wallet_b"]}
            for row in rows
        )

        launches = await store.list_pair_launches(
            wallet_a="WalletB", wallet_b="WalletA"
        )
        assert [(row["mint"], row["outcome_status"]) for row in launches] == [
            (mint_a, "RUNNER"),
            (mint_b, "FADE"),
        ]
        assert len({row["mint"] for row in launches}) == 2
    finally:
        await store.close()
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_pair_memory_remains_unknown_without_outcome_table() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    store = EarlyBuyerCohortStore(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.execute((MIGRATIONS / "001_post_migration_schema.sql").read_text())

        base = datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc)
        mint_a = "MintPairUnknownA1111111111111111111111111111111"
        mint_b = "MintPairUnknownB1111111111111111111111111111111"
        track_a = await _track(conn, mint_a, base)
        track_b = await _track(conn, mint_b, base + timedelta(minutes=1))
        await _capture(
            conn,
            track_id=track_a,
            mint=mint_a,
            wallets=["WalletA", "WalletB"],
            suffix="a",
        )
        await _capture(
            conn,
            track_id=track_b,
            mint=mint_b,
            wallets=["WalletA", "WalletB"],
            suffix="b",
        )

        rows = await store.list_recurring_pairs(min_distinct_launches=2)
        pair = rows[0]
        assert pair["distinct_launches"] == 2
        assert pair["attributed_outcomes"] == 0
        assert pair["unknown_outcomes"] == 2

        launches = await store.list_pair_launches(
            wallet_a="WalletA", wallet_b="WalletB"
        )
        assert len(launches) == 2
        assert all(row["outcome_status"] is None for row in launches)
    finally:
        await store.close()
        await conn.close()
