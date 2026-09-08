"""Regression tests for immutable first-5/10/20 buyer evidence."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
DATABASE_URL = os.getenv("POST_MIGRATION_TEST_DATABASE_URL")


async def _insert_buyer(
    conn: asyncpg.Connection,
    *,
    track_id,
    mint: str,
    wallet: str,
    rank: int,
    signature: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO migration_buyers (
            track_id, mint, wallet, rank, signature, bought_at,
            slot, token_amount, sol_spent, usd_spent, entry_price_usd,
            is_meaningful, meta
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, TRUE, '{}'::jsonb)
        """,
        track_id,
        mint,
        wallet,
        rank,
        signature,
        datetime.now(timezone.utc),
        1000 + rank,
        100.0 + rank,
        1.0 + rank,
        150.0 + rank,
        0.01 + rank,
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_retrack_preserves_prior_ranked_buyer_capture() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.execute((MIGRATIONS / "001_post_migration_schema.sql").read_text())
        # Existing databases receive the additive migration. It must be idempotent
        # against the clean-install baseline schema.
        await conn.execute((MIGRATIONS / "003_immutable_early_buyer_memory.sql").read_text())

        track_id = uuid4()
        mint = "MintImmutableBuyerEvidence111111111111111111111"
        await conn.execute(
            """
            INSERT INTO migration_tracks (track_id, mint, migration_at)
            VALUES ($1, $2, $3)
            """,
            track_id,
            mint,
            datetime.now(timezone.utc),
        )

        async with conn.transaction():
            await _insert_buyer(
                conn,
                track_id=track_id,
                mint=mint,
                wallet="WalletA",
                rank=1,
                signature="sig-a",
            )
            await _insert_buyer(
                conn,
                track_id=track_id,
                mint=mint,
                wallet="WalletB",
                rank=2,
                signature="sig-b",
            )

        first_capture = await conn.fetch(
            """
            SELECT rank, wallet, capture_txid, observed_at, ingested_at, evidence_hash
            FROM migration_buyer_history
            WHERE mint = $1
            ORDER BY rank
            """,
            mint,
        )
        assert [(r["rank"], r["wallet"]) for r in first_capture] == [
            (1, "WalletA"),
            (2, "WalletB"),
        ]
        assert len({r["capture_txid"] for r in first_capture}) == 1
        assert all(r["observed_at"] == r["ingested_at"] for r in first_capture)
        assert all(len(r["evidence_hash"]) == 64 for r in first_capture)

        # Mirror Store.save_early_buyers re-track semantics: replace the mutable
        # current projection with a changed ranking in one transaction.
        async with conn.transaction():
            await conn.execute("DELETE FROM migration_buyers WHERE mint = $1", mint)
            await _insert_buyer(
                conn,
                track_id=track_id,
                mint=mint,
                wallet="WalletB",
                rank=1,
                signature="sig-b2",
            )
            await _insert_buyer(
                conn,
                track_id=track_id,
                mint=mint,
                wallet="WalletC",
                rank=2,
                signature="sig-c",
            )

        current_projection = await conn.fetch(
            "SELECT rank, wallet FROM migration_buyers WHERE mint = $1 ORDER BY rank",
            mint,
        )
        assert [(r["rank"], r["wallet"]) for r in current_projection] == [
            (1, "WalletB"),
            (2, "WalletC"),
        ]

        history = await conn.fetch(
            """
            SELECT rank, wallet, capture_txid, observed_at, ingested_at
            FROM migration_buyer_history
            WHERE mint = $1
            ORDER BY observed_at, capture_txid, rank
            """,
            mint,
        )
        assert len(history) == 4
        capture_ids = list(dict.fromkeys(r["capture_txid"] for r in history))
        assert len(capture_ids) == 2

        old_rows = [r for r in history if r["capture_txid"] == capture_ids[0]]
        new_rows = [r for r in history if r["capture_txid"] == capture_ids[1]]
        assert [(r["rank"], r["wallet"]) for r in old_rows] == [
            (1, "WalletA"),
            (2, "WalletB"),
        ]
        assert [(r["rank"], r["wallet"]) for r in new_rows] == [
            (1, "WalletB"),
            (2, "WalletC"),
        ]
        assert all(r["observed_at"] == r["ingested_at"] for r in history)
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_one_capture_supports_frozen_first_5_10_20_cohorts() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.execute((MIGRATIONS / "001_post_migration_schema.sql").read_text())

        track_id = uuid4()
        mint = "MintFirstTwentyEvidence1111111111111111111111111"
        await conn.execute(
            "INSERT INTO migration_tracks (track_id, mint, migration_at) VALUES ($1, $2, $3)",
            track_id,
            mint,
            datetime.now(timezone.utc),
        )

        async with conn.transaction():
            for rank in range(1, 21):
                await _insert_buyer(
                    conn,
                    track_id=track_id,
                    mint=mint,
                    wallet=f"Wallet{rank:02d}",
                    rank=rank,
                    signature=f"sig-{rank:02d}",
                )

        capture = await conn.fetchrow(
            """
            SELECT capture_txid, count(*) AS n,
                   count(*) FILTER (WHERE rank <= 5) AS first5,
                   count(*) FILTER (WHERE rank <= 10) AS first10,
                   count(*) FILTER (WHERE rank <= 20) AS first20,
                   min(observed_at) = max(observed_at) AS one_observed_boundary,
                   bool_and(observed_at = ingested_at) AS temporal_integrity
            FROM migration_buyer_history
            WHERE mint = $1
            GROUP BY capture_txid
            """,
            mint,
        )
        assert capture is not None
        assert capture["n"] == 20
        assert capture["first5"] == 5
        assert capture["first10"] == 10
        assert capture["first20"] == 20
        assert capture["one_observed_boundary"] is True
        assert capture["temporal_integrity"] is True
    finally:
        await conn.close()
