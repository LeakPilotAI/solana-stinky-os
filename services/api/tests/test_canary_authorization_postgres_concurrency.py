import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api.canary_authorization_provisioning import provision_canary_authorization_state
from stinky_api.dry_run_execution_persistence import persist_dry_run_canary_execution

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="real PostgreSQL test requires API_TEST_DATABASE_URL")


def authorization():
    return {
        "status": "OBSERVED", "canary_authorization_result": "PASS",
        "canary_execution_eligible": True, "canary_notional_usd": 20.0,
        "max_loss_usd": 5.0, "max_open_positions": 1,
        "kill_switch_armed": True, "isolated_funds": True,
        "isolated_account_or_wallet": True, "human_authorized": True,
        "authorization_id": "auth-concurrency", "authorized_at": "2026-09-09T20:00:00+00:00",
        "policy_version": "release-v1", "live_execution": False,
        "trading_authority": False, "trade_signal": False,
        "recommendation_authority": False, "order_submission_allowed": False,
        "transaction_signing_allowed": False, "rpc_contact_allowed": False,
        "automatic_canary_activation": False,
    }


def prepared(attempt_id: str):
    key = f"idem-{attempt_id}"
    requested_at = "2026-09-09T20:01:00+00:00"
    return {
        "status": "OBSERVED", "adapter_result": "DRY_RUN_READY", "dry_run_ready": True,
        "authorization_transition_prepared": True, "adapter_mode": "DRY_RUN",
        "authorization_id": "auth-concurrency", "attempt_id": attempt_id,
        "policy_version": "release-v1", "idempotency_key": key,
        "requested_notional_usd": 20.0, "max_loss_usd": 5.0,
        "live_execution": False, "trading_authority": False, "trade_signal": False,
        "recommendation_authority": False, "rpc_contacted": False,
        "transaction_signed": False, "order_submitted": False, "wallet_mutated": False,
        "automatic_execution": False,
        "authorization_transition": {
            "operation": "COMPARE_AND_SWAP_AUTHORIZATION_CONSUMPTION",
            "authorization_id": "auth-concurrency",
            "expected": {"consumed": False, "use_count": 0, "version": 0},
            "proposed": {"consumed": True, "use_count": 1, "version": 1,
                         "consumed_by_attempt_id": attempt_id, "consumed_at": requested_at,
                         "idempotency_key": key},
            "must_be_atomic_before_external_side_effect": True, "applied": False,
        },
        "post_order_audit_record": {
            "event": "CANARY_EXECUTION_ADAPTER_DRY_RUN_PREPARED", "attempt_id": attempt_id,
            "authorization_id": "auth-concurrency", "policy_version": "release-v1",
            "requested_at": requested_at, "requested_notional_usd": 20.0,
            "max_loss_usd": 5.0, "adapter_mode": "DRY_RUN", "idempotency_key": key,
            "external_side_effects": False, "rpc_contacted": False,
            "transaction_signed": False, "order_submitted": False,
            "authorization_transition_applied": False,
        },
    }


async def apply_migrations():
    assert DB_URL
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("DROP TABLE IF EXISTS dry_run_execution_audit CASCADE")
        await conn.execute("DROP TABLE IF EXISTS canary_authorization_provision_audit CASCADE")
        await conn.execute("DROP TABLE IF EXISTS canary_authorization_state CASCADE")
        root = Path(__file__).resolve().parents[1] / "migrations"
        await conn.execute((root / "002_dry_run_execution_persistence.sql").read_text())
        await conn.execute((root / "003_canary_authorization_provisioning.sql").read_text())
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_real_postgres_allows_exactly_one_concurrent_consumption_and_audit():
    await apply_migrations()
    assert DB_URL
    engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            provisioned = await provision_canary_authorization_state(session, authorization())
            assert provisioned["provisioning_result"] == "TRANSACTION_STAGED"
            await session.commit()

        async def consume(attempt_id: str):
            async with sessions() as session:
                result = await persist_dry_run_canary_execution(session, prepared(attempt_id))
                await session.commit()
                return result

        first, second = await asyncio.gather(consume("attempt-a"), consume("attempt-b"))
        results = [first["persistence_result"], second["persistence_result"]]
        assert results.count("TRANSACTION_STAGED") == 1
        assert results.count("BLOCKED") == 1

        async with sessions() as session:
            state = (await session.execute(text(
                "SELECT consumed, use_count, version FROM canary_authorization_state "
                "WHERE authorization_id='auth-concurrency'"
            ))).mappings().one()
            audit_count = (await session.execute(text(
                "SELECT count(*) FROM dry_run_execution_audit WHERE authorization_id='auth-concurrency'"
            ))).scalar_one()
            provision_count = (await session.execute(text(
                "SELECT count(*) FROM canary_authorization_provision_audit WHERE authorization_id='auth-concurrency'"
            ))).scalar_one()
        assert state == {"consumed": True, "use_count": 1, "version": 1}
        assert audit_count == 1
        assert provision_count == 1
    finally:
        await engine.dispose()
