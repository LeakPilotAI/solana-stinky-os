import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api.paper_policy_provisioning import load_active_paper_configuration, provision_paper_policy

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="real PostgreSQL test requires API_TEST_DATABASE_URL")


def config(version="paper-v1", runner=0.6):
    return {
        "paper_policy": {
            "policy_version": version, "horizon": "15m",
            "min_runner_probability": runner, "max_fade_probability": 0.25,
            "min_nonnegative_market_cap_probability": 0.7,
        },
        "execution_assumptions": {
            "entry_slippage_bps": 100, "exit_slippage_bps": 100,
            "entry_fee_bps": 50, "exit_fee_bps": 50, "latency_ms": 500,
        },
        "paper_notional_usd": 20,
    }


async def reset_db():
    assert DB_URL
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("DROP TABLE IF EXISTS paper_policy_activation_audit CASCADE")
        await conn.execute("DROP TABLE IF EXISTS paper_policy_active CASCADE")
        await conn.execute("DROP TABLE IF EXISTS paper_policy_registry CASCADE")
        root = Path(__file__).resolve().parents[1] / "migrations"
        await conn.execute((root / "007_paper_policy_registry.sql").read_text())
    finally:
        await conn.close()


def factory():
    assert DB_URL
    engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_active_policy_survives_fresh_engine_and_registry_is_immutable():
    await reset_db()
    engine1, Session1 = factory()
    async with Session1() as session:
        result = await provision_paper_policy(session, config())
        assert result["status"] == "ACTIVE"
        assert result["live_execution"] is False
    await engine1.dispose()

    engine2, Session2 = factory()
    async with Session2() as session:
        loaded = await load_active_paper_configuration(session)
        assert loaded["configured"] is True
        assert loaded["paper_policy"]["policy_version"] == "paper-v1"
        assert loaded["paper_notional_usd"] == 20.0
        with pytest.raises(Exception):
            await session.execute(__import__("sqlalchemy").text("UPDATE paper_policy_registry SET horizon='30m' WHERE policy_version='paper-v1'"))
        await session.rollback()
    await engine2.dispose()


@pytest.mark.asyncio
async def test_same_version_cannot_be_rebound_to_different_thresholds():
    await reset_db()
    engine, Session = factory()
    async with Session() as session:
        assert (await provision_paper_policy(session, config()))["status"] == "ACTIVE"
        blocked = await provision_paper_policy(session, config(runner=0.61))
        assert blocked["status"] == "BLOCKED"
        assert blocked["reason"] == "policy_version_already_bound_to_different_payload"
    await engine.dispose()
