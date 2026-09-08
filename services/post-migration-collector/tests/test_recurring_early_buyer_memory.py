"""PostgreSQL-backed tests for recurring early-buyer memory."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from post_migration.early_buyer_memory import EarlyBuyerMemoryStore

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
async def test_recurring_memory_counts_distinct_launches_not_capture_groups() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    store = EarlyBuyerMemoryStore(DATABASE_URL)
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

        base = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        mint_a = "MintRecurringA1111111111111111111111111111111"
        mint_b = "MintRecurringB1111111111111111111111111111111"
        track_a = await _track(conn, mint_a, base)
        track_b = await _track(conn, mint_b, base + timedelta(minutes=5))

        # WalletRepeat appears on mint A twice because A is re-captured. That must
        # still count as only one launch. The latest immutable capture is the
        # descriptive current membership projection.
        await _capture(
            conn,
            track_id=track_a,
            mint=mint_a,
            wallets=["WalletOld", "WalletRepeat"],
            suffix="old",
        )
        await _capture(
            conn,
            track_id=track_a,
            mint=mint_a,
            wallets=["WalletRepeat", "WalletNew"],
            suffix="new",
        )
        await _capture(
            conn,
            track_id=track_b,
            mint=mint_b,
            wallets=["WalletX", "WalletRepeat"],
            suffix="one",
        )

        await conn.execute(
            "INSERT INTO entity_launches (mint, observed_at, outcome_status) VALUES ($1, $2, 'RUNNER'), ($3, $4, 'FADE')",
            mint_a,
            base + timedelta(hours=1),
            mint_b,
            base + timedelta(hours=1, minutes=5),
        )

        rows = await store.list_wallet_memory(min_distinct_launches=2)
        repeat = next(row for row in rows if row["wallet"] == "WalletRepeat")
        assert repeat["distinct_launches"] == 2
        assert repeat["first5_launches"] == 2
        assert repeat["runner_outcomes"] == 1
        assert repeat["fade_outcomes"] == 1
        assert repeat["held_outcomes"] == 0
        assert repeat["attributed_outcomes"] == 2

        launches = await store.list_wallet_launches(wallet="WalletRepeat")
        assert [(row["mint"], row["rank"], row["outcome_status"]) for row in launches] == [
            (mint_a, 1, "RUNNER"),
            (mint_b, 2, "FADE"),
        ]
    finally:
        await store.close()
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_memory_remains_descriptive_when_outcome_table_is_unavailable() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    store = EarlyBuyerMemoryStore(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.execute((MIGRATIONS / "001_post_migration_schema.sql").read_text())
        base = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
        mint_a = "MintUnknownA11111111111111111111111111111111"
        mint_b = "MintUnknownB11111111111111111111111111111111"
        track_a = await _track(conn, mint_a, base)
        track_b = await _track(conn, mint_b, base + timedelta(minutes=1))
        await _capture(conn, track_id=track_a, mint=mint_a, wallets=["WalletRepeat"], suffix="a")
        await _capture(conn, track_id=track_b, mint=mint_b, wallets=["WalletRepeat"], suffix="b")

        rows = await store.list_wallet_memory(min_distinct_launches=2)
        repeat = next(row for row in rows if row["wallet"] == "WalletRepeat")
        assert repeat["distinct_launches"] == 2
        assert repeat["attributed_outcomes"] == 0
        assert repeat["unknown_outcomes"] == 2

        launches = await store.list_wallet_launches(wallet="WalletRepeat")
        assert len(launches) == 2
        assert all(row["outcome_status"] is None for row in launches)
    finally:
        await store.close()
        await conn.close()
