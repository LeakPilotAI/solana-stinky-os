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
        "status": "OBSERVED", "release_gate_result": "PASS",
        "eligible_for_isolated_canary_review": True,
        "live_canary_unlocked": False, "automatic_canary_activation": False,
        "policy_version": "release-v1", "live_execution": False,
        "trading_authority": False, "trade_signal": False,
        "recommendation_authority": False,
    }


def controls():
    return {
        "canary_notional_usd": 20.0, "max_loss_usd": 5.0,
        "max_open_positions": 1, "isolated_funds": True,
        "isolated_account_or_wallet": True, "kill_switch_armed": True,
        "no_borrowing": True, "no_leverage": True,
    }


def authorization_infrastructure():
    return {
        "status": "HEALTHY", "critical_services_healthy": True,
        "unresolved_critical_incidents": 0, "revalidated_for_canary": True,
        "checked_at": "2026-09-10T02:00:00+00:00",
    }


def human_authorization():
    return {
        "human_authorized": True, "authorization_id": "auth-recovery",
        "authorized_at": "2026-09-10T02:00:30+00:00",
        "authorized_notional_usd": 20.0, "policy_version": "release-v1",
    }


def runtime(*, kill_switch_armed: bool = True):
    return {
        "requested_notional_usd": 20.0, "realized_loss_usd": 0.0,
        "open_positions": 0, "kill_switch_armed": kill_switch_armed,
        "isolated_funds": True, "isolated_account_or_wallet": True,
        "no_borrowing": True, "no_leverage": True,
        "evaluated_at": "2026-09-10T02:01:10+00:00",
        "max_infrastructure_age_seconds": 300,
    }


def runtime_infrastructure():
    return {
        "status": "HEALTHY", "critical_services_healthy": True,
        "unresolved_critical_incidents": 0,
        "checked_at": "2026-09-10T02:01:00+00:00",
    }


def request(attempt_id: str = "attempt-recovery", idempotency_key: str = "idem-recovery"):
    return {
        "attempt_id": attempt_id, "requested_at": "2026-09-10T02:01:20+00:00",
        "authorization_id": "auth-recovery", "policy_version": "release-v1",
        "requested_notional_usd": 20.0, "adapter_mode": "DRY_RUN",
        "idempotency_key": idempotency_key,
    }


def authorization():
    result = evaluate_isolated_canary_authorization(
        release_gate(), controls(), authorization_infrastructure(), human_authorization()
    )
    assert result["canary_authorization_result"] == "PASS"
    return result


async def reset_schema():
    assert DB_URL
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("DROP TABLE IF EXISTS dry_run_execution_audit CASCADE")
        await conn.execute("DROP TABLE IF EXISTS canary_authorization_provision_audit CASCADE")
        await conn.execute("DROP TABLE IF EXISTS canary_authorization_state CASCADE")
        await conn.execute("DROP FUNCTION IF EXISTS fail_dry_run_audit_insert() CASCADE")
        root = Path(__file__).resolve().parents[1] / "migrations"
        await conn.execute((root / "002_dry_run_execution_persistence.sql").read_text())
        await conn.execute((root / "003_canary_authorization_provisioning.sql").read_text())
    finally:
        await conn.close()


async def provision(sessions, canary_authorization):
    async with sessions() as session:
        result = await provision_canary_authorization_state(session, canary_authorization)
        assert result["provisioning_result"] == "TRANSACTION_STAGED"
        await session.commit()


async def state_and_audit_count(sessions):
    async with sessions() as session:
        state = (await session.execute(text(
            "SELECT consumed, use_count, version, consumed_by_attempt_id, idempotency_key "
            "FROM canary_authorization_state WHERE authorization_id='auth-recovery'"
        ))).mappings().one()
        audit_count = (await session.execute(text(
            "SELECT count(*) FROM dry_run_execution_audit WHERE authorization_id='auth-recovery'"
        ))).scalar_one()
        return state, audit_count


def assert_unused(state, audit_count):
    assert state == {
        "consumed": False,
        "use_count": 0,
        "version": 0,
        "consumed_by_attempt_id": None,
        "idempotency_key": None,
    }
    assert audit_count == 0


@pytest.mark.asyncio
async def test_interruption_before_commit_rolls_back_staged_consumption_and_audit():
    await reset_schema()
    assert DB_URL
    engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    canary_authorization = authorization()
    try:
        await provision(sessions, canary_authorization)

        async with sessions() as session:
            lifecycle = await prepare_and_persist_dry_run_canary_lifecycle(
                session, canary_authorization, runtime(), runtime_infrastructure(), request(),
                pre_persist_runtime=runtime(),
                pre_persist_infrastructure=runtime_infrastructure(),
            )
            assert lifecycle["lifecycle_result"] == "TRANSACTION_STAGED"
            assert lifecycle["persistence_staged"] is True
            await session.rollback()  # process/request interruption before durable commit

        state, audit_count = await state_and_audit_count(sessions)
        assert_unused(state, audit_count)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_audit_insert_failure_rolls_back_successful_cas_update():
    await reset_schema()
    assert DB_URL
    sqlalchemy_url = DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(sqlalchemy_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    canary_authorization = authorization()
    try:
        await provision(sessions, canary_authorization)

        conn = await asyncpg.connect(DB_URL)
        try:
            await conn.execute("""
                CREATE FUNCTION fail_dry_run_audit_insert() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'intentional dry-run audit failure';
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER fail_dry_run_audit_insert_trigger
                BEFORE INSERT ON dry_run_execution_audit
                FOR EACH ROW EXECUTE FUNCTION fail_dry_run_audit_insert();
            """)
        finally:
            await conn.close()

        async with sessions() as session:
            with pytest.raises(Exception, match="intentional dry-run audit failure"):
                await prepare_and_persist_dry_run_canary_lifecycle(
                    session, canary_authorization, runtime(), runtime_infrastructure(), request(),
                    pre_persist_runtime=runtime(),
                    pre_persist_infrastructure=runtime_infrastructure(),
                )
            await session.rollback()

        state, audit_count = await state_and_audit_count(sessions)
        assert_unused(state, audit_count)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_kill_switch_flip_after_adapter_preparation_blocks_before_consumption():
    await reset_schema()
    assert DB_URL
    engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    canary_authorization = authorization()
    try:
        await provision(sessions, canary_authorization)

        async with sessions() as session:
            lifecycle = await prepare_and_persist_dry_run_canary_lifecycle(
                session, canary_authorization, runtime(), runtime_infrastructure(), request(),
                pre_persist_runtime=runtime(kill_switch_armed=False),
                pre_persist_infrastructure=runtime_infrastructure(),
            )
            assert lifecycle["lifecycle_result"] == "BLOCKED"
            assert lifecycle["stopped_at"] == "pre_persistence_recheck"
            assert lifecycle["preorder_passed"] is True
            assert lifecycle["adapter_prepared"] is True
            assert lifecycle["pre_persistence_recheck_passed"] is False
            assert lifecycle["persistence_staged"] is False
            assert "kill_switch_not_armed" in lifecycle["stage_result"]["blockers"]
            await session.commit()

        state, audit_count = await state_and_audit_count(sessions)
        assert_unused(state, audit_count)
    finally:
        await engine.dispose()
