"""PostgreSQL-backed temporal/provenance tests for cohort relationship evidence."""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
import asyncpg
import pytest
from post_migration.cohort_relationships import CohortRelationshipStore

DATABASE_URL = os.getenv("POST_MIGRATION_TEST_DATABASE_URL")

async def _schema(conn: asyncpg.Connection) -> None:
    await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await conn.execute("""
      CREATE TABLE wallet_relationships (
        wallet_a TEXT NOT NULL, wallet_b TEXT NOT NULL, relationship_kind TEXT NOT NULL,
        observation_count INTEGER NOT NULL, first_seen_at TIMESTAMPTZ NOT NULL,
        last_seen_at TIMESTAMPTZ NOT NULL, confidence DOUBLE PRECISION, evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        PRIMARY KEY(wallet_a,wallet_b,relationship_kind));
      CREATE TABLE wallet_funding_observations (
        signature TEXT PRIMARY KEY, source_wallet TEXT NOT NULL, destination_wallet TEXT NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL, amount_lamports BIGINT, evidence JSONB NOT NULL DEFAULT '{}'::jsonb);
    """)

@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_pair_relationship_evidence_excludes_future_funding() -> None:
    conn = await asyncpg.connect(DATABASE_URL); store = CohortRelationshipStore(DATABASE_URL)
    try:
        await _schema(conn)
        base = datetime(2026,9,8,14,0,tzinfo=timezone.utc)
        await conn.execute("INSERT INTO wallet_relationships VALUES ('A','B','funding_observation',2,$1,$2,1.0,'{\"future\":true}'::jsonb)", base-timedelta(minutes=5), base+timedelta(minutes=5))
        await conn.execute("INSERT INTO wallet_funding_observations VALUES ('past','A','B',$1,100,'{}'),('future','B','A',$2,200,'{}')", base-timedelta(minutes=2), base+timedelta(minutes=2))
        result = await store.list_pair_relationship_evidence(wallet_a='B', wallet_b='A', as_of=base)
        assert [r['signature'] for r in result['funding_observations']] == ['past']
        aggregate = result['relationships'][0]
        assert aggregate['point_in_time_aggregate_unknown'] is True
        assert aggregate['observation_count'] is None
        assert aggregate['last_seen_at'] is None
        assert aggregate['confidence'] is None
        assert aggregate['evidence'] == {}
    finally:
        await store.close(); await conn.close()

@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_common_funder_requires_same_source_before_cutoff() -> None:
    conn = await asyncpg.connect(DATABASE_URL); store = CohortRelationshipStore(DATABASE_URL)
    try:
        await _schema(conn)
        base = datetime(2026,9,8,14,0,tzinfo=timezone.utc)
        await conn.execute("""
          INSERT INTO wallet_funding_observations VALUES
          ('fa1','FUNDER','A',$1,100,'{}'),
          ('fb1','FUNDER','B',$2,200,'{}'),
          ('other','OTHER','A',$3,300,'{}'),
          ('future','FUTURE','B',$4,400,'{}')
        """, base-timedelta(minutes=10), base-timedelta(minutes=8), base-timedelta(minutes=5), base+timedelta(minutes=1))
        rows = await store.list_common_funders(wallet_a='A', wallet_b='B', as_of=base)
        assert len(rows) == 1
        row = rows[0]
        assert row['funder_wallet'] == 'FUNDER'
        assert row['wallet_a_observations'] == 1
        assert row['wallet_b_observations'] == 1
        assert row['wallet_a_lamports'] == 100
        assert row['wallet_b_lamports'] == 200
        summary = await store.summarize_pair_relationship_evidence(wallet_a='A', wallet_b='B', as_of=base)
        assert summary['common_funder_count'] == 1
        assert summary['common_funders'][0]['funder_wallet'] == 'FUNDER'
        assert summary['has_observable_relationship_evidence'] is True
    finally:
        await store.close(); await conn.close()

@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_common_funder_does_not_count_pair_funding_each_other() -> None:
    conn = await asyncpg.connect(DATABASE_URL); store = CohortRelationshipStore(DATABASE_URL)
    try:
        await _schema(conn)
        base = datetime(2026,9,8,14,0,tzinfo=timezone.utc)
        await conn.execute("INSERT INTO wallet_funding_observations VALUES ('ab','A','B',$1,100,'{}'),('ba','B','A',$2,100,'{}')", base-timedelta(minutes=2), base-timedelta(minutes=1))
        assert await store.list_common_funders(wallet_a='A', wallet_b='B', as_of=base) == []
    finally:
        await store.close(); await conn.close()

@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_pair_relationship_evidence_uses_known_past_aggregate() -> None:
    conn = await asyncpg.connect(DATABASE_URL); store = CohortRelationshipStore(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.execute("CREATE TABLE wallet_relationships (wallet_a TEXT NOT NULL,wallet_b TEXT NOT NULL,relationship_kind TEXT NOT NULL,observation_count INTEGER NOT NULL,first_seen_at TIMESTAMPTZ NOT NULL,last_seen_at TIMESTAMPTZ NOT NULL,confidence DOUBLE PRECISION,evidence JSONB NOT NULL DEFAULT '{}'::jsonb,PRIMARY KEY(wallet_a,wallet_b,relationship_kind));")
        base=datetime(2026,9,8,14,0,tzinfo=timezone.utc)
        await conn.execute("INSERT INTO wallet_relationships VALUES ('A','B','deployer_buyer_association',3,$1,$2,1.0,'{\"observed_mints\":3}'::jsonb)",base-timedelta(hours=1),base-timedelta(minutes=1))
        result=await store.summarize_pair_relationship_evidence(wallet_a='A',wallet_b='B',as_of=base)
        assert result['relationship_table_available'] is True
        assert result['funding_table_available'] is False
        assert result['relationship_kinds']==['deployer_buyer_association']
        assert result['direct_funding_observations']==0
        assert result['common_funder_count']==0
        assert result['has_observable_relationship_evidence'] is True
    finally:
        await store.close(); await conn.close()

@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="requires POST_MIGRATION_TEST_DATABASE_URL")
async def test_missing_relationship_infrastructure_is_unknown_not_inferred() -> None:
    conn=await asyncpg.connect(DATABASE_URL); store=CohortRelationshipStore(DATABASE_URL)
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        result=await store.summarize_pair_relationship_evidence(wallet_a='A',wallet_b='B',as_of=datetime.now(timezone.utc))
        assert result['relationship_table_available'] is False
        assert result['funding_table_available'] is False
        assert result['relationship_kinds']==[]
        assert result['direct_funding_observations']==0
        assert result['common_funder_count']==0
        assert result['has_observable_relationship_evidence'] is False
    finally:
        await store.close(); await conn.close()
