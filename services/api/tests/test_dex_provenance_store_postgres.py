"""Real append-only storage upgrade behavior in an isolated test schema."""
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest


DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="real PostgreSQL requires API_TEST_DATABASE_URL")


@pytest.mark.asyncio
async def test_provenance_upgrade_blocks_truncate_and_preserves_append_behavior():
    schema = "test_provenance_" + uuid4().hex
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        await conn.execute((migrations / "008_dex_provenance_evidence.sql").read_text())
        insert = """INSERT INTO dex_provenance_evidence_snapshots
            (chain, pool_address, evidence_block, evidence_key, record_payload, sources_payload)
            VALUES ('base', 'fixture-pool', $1, $2, '{"evidence":"original"}', '[]')
            ON CONFLICT (chain, pool_address, evidence_block, evidence_key) DO NOTHING
            RETURNING id"""
        first_id = await conn.fetchval(insert, 123, "fixture-key")
        original = await conn.fetch("SELECT * FROM dex_provenance_evidence_snapshots")
        upgrade = (migrations / "011_dex_provenance_truncate_guard.sql").read_text()
        await conn.execute(upgrade)
        await conn.execute(upgrade)  # Safe startup replay.
        assert await conn.fetch("SELECT * FROM dex_provenance_evidence_snapshots") == original

        for statement in (
            "UPDATE dex_provenance_evidence_snapshots SET evidence_block = 124",
            "DELETE FROM dex_provenance_evidence_snapshots",
            "TRUNCATE dex_provenance_evidence_snapshots",
            "TRUNCATE dex_provenance_evidence_snapshots RESTART IDENTITY CASCADE",
        ):
            with pytest.raises(asyncpg.RaiseError, match="append-only"):
                await conn.execute(statement)
            assert await conn.fetch("SELECT * FROM dex_provenance_evidence_snapshots") == original

        await conn.execute("CREATE TABLE transaction_fixture (value INTEGER)")
        with pytest.raises(asyncpg.RaiseError, match="append-only"):
            async with conn.transaction():
                await conn.execute("INSERT INTO transaction_fixture VALUES (1)")
                await conn.execute("TRUNCATE transaction_fixture, dex_provenance_evidence_snapshots")
        assert await conn.fetchval("SELECT count(*) FROM transaction_fixture") == 0
        assert await conn.fetch("SELECT * FROM dex_provenance_evidence_snapshots") == original
        assert await conn.fetchval(insert, 123, "fixture-key") is None
        later_id = await conn.fetchval(insert, 124, "later-key")
        assert later_id > first_id
        assert await conn.fetchval("SELECT count(*) FROM dex_provenance_evidence_snapshots") == 2
        assert await conn.fetchval("SELECT evidence_block FROM dex_provenance_evidence_snapshots ORDER BY evidence_block DESC LIMIT 1") == 124
    finally:
        await conn.execute("SET search_path TO public")
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
