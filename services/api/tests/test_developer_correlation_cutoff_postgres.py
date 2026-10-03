"""Exercise optional correlation cutoffs using PostgreSQL's actual bind inference."""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from stinky_api import developer_identity_correlation as correlation

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="requires dedicated API_TEST_DATABASE_URL")

@pytest.mark.asyncio
@pytest.mark.parametrize("offset,expected", [(None, 2), (0, 1), (-1, 0)])
async def test_optional_cutoff_preserves_observed_edges_without_transaction_failure(monkeypatch, offset, expected):
    schema = "correlation_cutoff_" + uuid4().hex
    conn = await asyncpg.connect(DB_URL)
    engine = None
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        await conn.execute("""
            CREATE TABLE wallet_funding_observations(source_wallet text,destination_wallet text,observed_at timestamptz);
            CREATE TABLE entity_wallets(wallet text,entity_id uuid,role text,link_reason text,first_seen_at timestamptz,last_seen_at timestamptz);
            CREATE TABLE entity_launches(mint text,deployer_wallet text,entity_id uuid,observed_at timestamptz);
            CREATE TABLE migration_buyers(wallet text,mint text,rank int,bought_at timestamptz);
            CREATE TABLE wallet_relationships(wallet_a text,wallet_b text,relationship_kind text,observation_count int,first_seen_at timestamptz,last_seen_at timestamptz);
        """)
        owner, other1, other2 = uuid4(), uuid4(), uuid4()
        start = datetime(2026,1,1,tzinfo=timezone.utc)
        await conn.execute("INSERT INTO entity_wallets VALUES('owner',$1,'creator','fixture',$2,$2)", owner, start)
        for wallet, other, ts in [("old",other1,start),("future",other2,start+timedelta(seconds=1))]:
            await conn.execute("INSERT INTO entity_wallets VALUES($1,$2,'buyer','fixture',$3,$3)",wallet,other,ts)
            await conn.execute("INSERT INTO wallet_relationships VALUES('owner',$1,'observed',1,$2,$2)",wallet,ts)
        for name in ("motif_outcome_context","persist_motif_outcome_snapshot","motif_outcome_audit_history"):
            monkeypatch.setattr(correlation,name,AsyncMock(return_value={}))
        engine = create_async_engine(DB_URL.replace("postgresql://","postgresql+asyncpg://",1),
            connect_args={"server_settings":{"search_path":schema,"default_transaction_read_only":"on"}})
        cutoff = None if offset is None else start+timedelta(seconds=offset)
        async with async_sessionmaker(engine)() as session:
            result = await correlation.correlate_developer_identity(session,owner,
                graph={"wallets":[{"wallet":"owner"},{"wallet":"old"},{"wallet":"future"}]},as_of=cutoff)
        assert result["missing"] == []
        assert len(result["cross_entity_wallet_reuse"]) == expected
        assert len(result["shared_relationship_structures"]) == expected
        if cutoff is not None:
            assert result["temporal_cutoff_enforced"] is True
            assert all(datetime.fromisoformat(r["first_seen_at"])<=cutoff for r in result["cross_entity_wallet_reuse"])
        assert result["ownership_inferred"] is False
        assert result["coordination_inferred"] is False
        assert result["predictive_authority"] is False
        assert result["trade_signal"] is False
    finally:
        if engine is not None: await engine.dispose()
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
