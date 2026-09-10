import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api.canary_authorization_provisioning import provision_canary_authorization_state
from stinky_api.dry_run_canary_lifecycle import prepare_and_persist_dry_run_canary_lifecycle
from stinky_api.isolated_canary_authorization import evaluate_isolated_canary_authorization

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="real PostgreSQL test requires API_TEST_DATABASE_URL")


def release_gate():
    return {
        "status": "OBSERVED",
        "release_gate_result": "PASS",
        "eligible_for_isolated_canary_review": True,
        "live_canary_unlocked": False,
        "automatic_canary_activation": False,
        "policy_version": "release-v1",
        "live_execution": False,
        "trading_authority": False,
        "trade_signal": False,
        "recommendation_authority": False,
    }


def controls():
    return {
        "canary_notional_usd": 20.0,
        "max_loss_usd": 5.0,
        "max_open_positions": 1,
        "isolated_funds": True,
        "isolated_account_or_wallet": True,
        "kill_switch_armed": True,
        "no_borrowing": True,
        "no_leverage": True,
    }


def authorization_infrastructure():
    return {
        "status": "HEALTHY",
        "critical_services_healthy": True,
        "unresolved_critical_incidents": 0,
        "revalidated_for_canary": True,
        "checked_at": "2026-09-10T01:00:00+00:00",
    }


def human_authorization():
    return {
        "human_authorized": True,
        "authorization_id": "auth-lifecycle",
        "authorized_at": "2026-09-10T01:00:30+00:00",
        "authorized_notional_usd": 20.0,
        "policy_version": "release-v1",
    }


def runtime():
    return {
        "requested_notional_usd": 20.0,
        "realized_loss_usd": 0.0,
        "open_positions": 0,
        "kill_switch_armed": True,
        "isolated_funds": True,
        "isolated_account_or_wallet": True,
        "no_borrowing": True,
        "no_leverage": True,
        "evaluated_at": "2026-09-10T01:01:10+00:00",
        "max_infrastructure_age_seconds": 300,
    }


def runtime_infrastructure():
    return {
        "status": "HEALTHY",
        "critical_services_healthy": True,
        "unresolved_critical_incidents": 0,
        "checked_at": "2026-09-10T01:01:00+00:00",
    }


def request(attempt_id: str = "attempt-lifecycle", idempotency_key: str = "idem-lifecycle"):
    return {
        "attempt_id": attempt_id,
        "requested_at": "2026-09-10T01:01:20+00:00",
        "authorization_id": "auth-lifecycle",
        "policy_version": "release-v1",
        "requested_notional_usd": 20.0,
        "adapter_mode": "DRY_RUN",
        "idempotency_key": idempotency_key,
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
async def test_full_persisted_dry_run_lifecycle_survives_fresh_engine_and_blocks_replay():
    await apply_migrations()
    assert DB_URL
    sqlalchemy_url = DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

    canary_authorization = evaluate_isolated_canary_authorization(
        release_gate(), controls(), authorization_infrastructure(), human_authorization()
    )
    assert canary_authorization["canary_authorization_result"] == "PASS"
    assert canary_authorization["live_execution"] is False
    assert canary_authorization["order_submission_allowed"] is False

    first_engine = create_async_engine(sqlalchemy_url)
    first_sessions = async_sessionmaker(first_engine, expire_on_commit=False)
    try:
        async with first_sessions() as session:
            provisioned = await provision_canary_authorization_state(session, canary_authorization)
            assert provisioned["provisioning_result"] == "TRANSACTION_STAGED"
            await session.commit()

        async with first_sessions() as session:
            lifecycle = await prepare_and_persist_dry_run_canary_lifecycle(
                session,
                canary_authorization,
                runtime(),
                runtime_infrastructure(),
                request(),
            )
            assert lifecycle["lifecycle_result"] == "TRANSACTION_STAGED"
            assert lifecycle["preorder_passed"] is True
            assert lifecycle["adapter_prepared"] is True
            assert lifecycle["persistence_staged"] is True
            assert lifecycle["authorization_version_before"] == 0
            assert lifecycle["authorization_version_after"] == 1
            assert lifecycle["live_execution"] is False
            assert lifecycle["rpc_contacted"] is False
            assert lifecycle["transaction_signed"] is False
            assert lifecycle["order_submitted"] is False
            assert lifecycle["wallet_mutated"] is False
            await session.commit()
    finally:
        await first_engine.dispose()

    # Simulate a process restart / fresh connection pool. Durable state must still
    # be consumed and must block any later replay before adapter persistence.
    second_engine = create_async_engine(sqlalchemy_url)
    second_sessions = async_sessionmaker(second_engine, expire_on_commit=False)
    try:
        async with second_sessions() as session:
            state = (await session.execute(text(
                "SELECT consumed, use_count, version, consumed_by_attempt_id, idempotency_key "
                "FROM canary_authorization_state WHERE authorization_id='auth-lifecycle'"
            ))).mappings().one()
            audit = (await session.execute(text(
                "SELECT adapter_mode, rpc_contacted, transaction_signed, order_submitted, "
                "wallet_mutated, external_side_effects FROM dry_run_execution_audit "
                "WHERE authorization_id='auth-lifecycle'"
            ))).mappings().one()
            provision_count = (await session.execute(text(
                "SELECT count(*) FROM canary_authorization_provision_audit "
                "WHERE authorization_id='auth-lifecycle'"
            ))).scalar_one()

            assert state == {
                "consumed": True,
                "use_count": 1,
                "version": 1,
                "consumed_by_attempt_id": "attempt-lifecycle",
                "idempotency_key": "idem-lifecycle",
            }
            assert audit == {
                "adapter_mode": "DRY_RUN",
                "rpc_contacted": False,
                "transaction_signed": False,
                "order_submitted": False,
                "wallet_mutated": False,
                "external_side_effects": False,
            }
            assert provision_count == 1

            replay = await prepare_and_persist_dry_run_canary_lifecycle(
                session,
                canary_authorization,
                runtime(),
                runtime_infrastructure(),
                request("attempt-replay", "idem-replay"),
            )
            assert replay["lifecycle_result"] == "BLOCKED"
            assert replay["stopped_at"] == "preorder"
            assert "authorization_already_consumed" in replay["stage_result"]["blockers"]
            assert replay["adapter_prepared"] is False
            assert replay["persistence_staged"] is False

            audit_count = (await session.execute(text(
                "SELECT count(*) FROM dry_run_execution_audit WHERE authorization_id='auth-lifecycle'"
            ))).scalar_one()
            assert audit_count == 1
    finally:
        await second_engine.dispose()
