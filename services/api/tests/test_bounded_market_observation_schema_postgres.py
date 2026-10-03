"""Bounded API hydration against the real persisted market-observation schema."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from stinky_api import queries
from stinky_core.memory import MEMORY_ALTERS, IntelligenceMemory

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="requires dedicated API_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[3]

@pytest.mark.asyncio
@pytest.mark.parametrize("loader,limit", [(queries.load_observation_snapshot, 50), (queries.load_quality_snapshot, 20)])
@pytest.mark.parametrize("missing_table", [False, True])
async def test_bounded_ticks_use_persisted_schema_and_preserve_failure(loader, limit, missing_table):
    schema = "bounded_ticks_" + uuid4().hex
    conn = await asyncpg.connect(DB_URL)
    engine = None
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        for name in ("008_market_observations.sql", "009_observations.sql", "010_quality_states.sql"):
            await conn.execute((ROOT / "services/sentinel/migrations" / name).read_text())
        for sql in MEMORY_ALTERS:
            if sql.startswith("ALTER TABLE market_observations "):
                await conn.execute(sql)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await conn.execute("INSERT INTO intelligence_investigations(mint,gate1_at,discovered_at,row) VALUES('selected',$1,$1,'{}')", start)
        await conn.executemany("""INSERT INTO market_observations
            (mint,observed_at,volume_m5_usd,price_usd,liquidity_usd,source,market_cap_usd,
             buys,sells,txns,unique_buyers,unique_sellers,volume_since_gate,pair_address,dex_id)
            VALUES($1,$2,33000,2,10000,'fixture',50000,3,1,4,2,1,40000,'pair','dex')""",
            [(mint, start + timedelta(seconds=i)) for mint in ("selected", "unrelated") for i in range(60)])
        if missing_table:
            await conn.execute("DROP TABLE market_observations")
        engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1),
            connect_args={"server_settings": {"search_path": schema, "default_transaction_read_only": "on"}})
        async with async_sessionmaker(engine)() as session:
            result = await loader(session)
        if missing_table:
            assert result["market_ticks"] == []
            assert "market_ticks" in result["_hydration_failed_layers"]
            return
        assert result["_hydration_failed_layers"] == []
        ticks = result["market_ticks"]
        assert len(ticks) == limit
        assert {t["mint"] for t in ticks} == {"selected"}
        assert [t["observed_at"] for t in ticks] == [(start + timedelta(seconds=i)).isoformat() for i in range(60-limit, 60)]
        assert ticks[0]["pair_address"] == "pair"
        assert ticks[0]["dex_id"] == "dex"
        assert ticks[0]["buys"] == 3 and ticks[0]["sells"] == 1
        assert ticks[0]["unique_buyers"] == 2 and ticks[0]["unique_sellers"] == 1
        assert ticks[0]["volume_since_gate"] == 40000
        memory = IntelligenceMemory()
        assert memory.load_market_ticks(ticks) == limit
        assert memory.market_ticks[0].buy_sell_ratio == 0.75
        assert await conn.fetchval("SELECT count(*) FROM market_observations") == 120
    finally:
        if engine is not None:
            await engine.dispose()
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
