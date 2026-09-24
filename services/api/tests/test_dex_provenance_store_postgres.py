"""Real append-only storage upgrade behavior in an isolated test schema."""
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api.dex_provenance_store import append_dex_provenance_evidence, load_latest_dex_provenance_evidence


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


@pytest.mark.asyncio
async def test_duplicate_append_distinguishes_idempotence_from_conflicting_evidence():
    schema = "test_provenance_" + uuid4().hex
    conn = await asyncpg.connect(DB_URL)
    engine = None
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for name in ("008_dex_provenance_evidence.sql", "011_dex_provenance_truncate_guard.sql"):
            await conn.execute((migrations / name).read_text())
        await conn.execute("CREATE TABLE transaction_fixture (value INTEGER)")
        engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1),
            connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine)
        record = {"value": 1, "nested": {"a": "original", "b": 2}}
        sources = ({"provider": "one"}, {"provider": "two"})
        async def append(session, rec=record, src=sources, key="legacy-generic-key"):
            return await append_dex_provenance_evidence(session, chain="base", pool_address="fixture",
                evidence_block=123, evidence_key=key, record_payload=rec, sources_payload=src)
        async with sessions() as session:
            original_id = await append(session)
            await session.commit()
            reordered = {"nested": {"b": 2, "a": "original"}, "value": 1}
            assert await append(session, reordered) == original_id
            await session.commit()
            for rec, src in (
                ({**record, "value": True}, sources),  # JSONB Boolean differs from number.
                ({**record, "value": "SYNTHETIC_SECRET"}, sources),
                (record, ({"provider": "other"},)),
                (record, tuple(reversed(sources))),
            ):
                await session.execute(text("INSERT INTO transaction_fixture VALUES (1)"))
                with pytest.raises(ValueError, match="^DEX provenance evidence key conflicts with stored payload$"):
                    await append(session, rec, src)
                await session.rollback()
                assert await conn.fetchval("SELECT count(*) FROM transaction_fixture") == 0
                loaded = await load_latest_dex_provenance_evidence(session, chain="base", pool_address="fixture")
                assert loaded.id == original_id
                assert loaded.record_payload == record
                assert loaded.sources_payload == sources
            # Distinct keys still preserve distinct evidence; no overwritten history.
            assert await append(session, {"value": "different"}, key="different-key") != original_id
            await session.commit()
        assert await conn.fetchval("SELECT count(*) FROM dex_provenance_evidence_snapshots") == 2
    finally:
        if engine is not None:
            await engine.dispose()
        await conn.execute("SET search_path TO public")
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
