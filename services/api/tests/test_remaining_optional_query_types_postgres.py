"""Exercise remaining optional SQL parameters using PostgreSQL bind inference."""
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api import developer_motif_outcome_context as motif_module
from stinky_api.market_pattern_outcome_calibration import calibrate_market_pattern_outcomes

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="requires dedicated API_TEST_DATABASE_URL")


async def _engine_for(schema: str):
    return create_async_engine(
        DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1),
        connect_args={"server_settings": {"search_path": schema, "default_transaction_read_only": "on"}},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("as_of", [None, datetime(2026, 1, 2, tzinfo=timezone.utc)])
async def test_pattern_baseline_optional_cutoff_has_concrete_postgres_type(as_of):
    schema = "optional_pattern_" + uuid4().hex
    conn = await asyncpg.connect(DB_URL)
    engine = None
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        await conn.execute(
            "CREATE TABLE market_path_pattern_occurrences("
            "id bigserial primary key, pattern_hash text, mint text, observed_at timestamptz)"
        )
        await conn.execute(
            "CREATE TABLE market_outcome_observations("
            "id bigserial primary key, mint text, horizon text, horizon_seconds int, "
            "anchor_observed_at timestamptz, observed_at timestamptz, ingested_at timestamptz, "
            "source text, evidence_basis text, metrics jsonb)"
        )
        observed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await conn.execute(
            "INSERT INTO market_path_pattern_occurrences(pattern_hash,mint,observed_at) VALUES('p','M',$1)",
            observed,
        )
        await conn.execute(
            "INSERT INTO market_outcome_observations(mint,horizon,horizon_seconds,anchor_observed_at,"
            "observed_at,ingested_at,source,evidence_basis,metrics) "
            "VALUES('M','5m',300,$1,$1,$1,'fixture','fixture','{\"price_usd\":1}'::jsonb)",
            observed,
        )
        engine = await _engine_for(schema)
        async with async_sessionmaker(engine)() as session:
            result = await calibrate_market_pattern_outcomes(session, "p", as_of=as_of)
        assert result["status"] == "OBSERVED"
    finally:
        if engine is not None:
            await engine.dispose()
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("current_mint,expected", [(None, 2), ("CURRENT", 1)])
async def test_motif_optional_current_mint_has_concrete_postgres_type(monkeypatch, current_mint, expected):
    schema = "optional_motif_" + uuid4().hex
    conn = await asyncpg.connect(DB_URL)
    engine = None
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        await conn.execute(
            "CREATE TABLE entity_launches("
            "id bigserial primary key, entity_id uuid, mint text, deployer_wallet text, "
            "observed_at timestamptz, created_at timestamptz)"
        )
        entity = UUID("22222222-2222-2222-2222-222222222222")
        observed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await conn.execute(
            "INSERT INTO entity_launches(entity_id,mint,deployer_wallet,observed_at,created_at) "
            "VALUES($1,'OLD','D1',$2,$2),($1,'CURRENT','D2',$2,$2)",
            entity, observed,
        )
        monkeypatch.setattr(
            motif_module,
            "historical_launch_outcome_provenance",
            AsyncMock(return_value={"status": "UNKNOWN", "outcome": "UNKNOWN"}),
        )
        monkeypatch.setattr(
            motif_module,
            "load_lifecycle_memories_for_mints",
            AsyncMock(return_value={
                "memories": [],
                "distribution": motif_module._empty_distribution(),
                "bounded": {"mint_limit": 100, "query_count": 0},
            }),
        )
        engine = await _engine_for(schema)
        motifs = {"status": "OBSERVED", "records": [{
            "motif_kind": "fixture",
            "motif_state": "fixture",
            "component_kinds": [],
            "other_entity_ids": [str(entity)],
        }]}
        async with async_sessionmaker(engine)() as session:
            result = await motif_module.motif_outcome_context(
                session,
                UUID("11111111-1111-1111-1111-111111111111"),
                network_motifs=motifs,
                current_mint=current_mint,
            )
        assert result["status"] == "OBSERVED"
        assert result["launch_analogue_count"] == expected
        assert result["predictive_authority"] is False
        assert result["trade_signal"] is False
    finally:
        if engine is not None:
            await engine.dispose()
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
