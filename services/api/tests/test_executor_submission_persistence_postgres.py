import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api.executor_submission_persistence import (
    load_executor_submission_state,
    persist_executor_failure_transition,
    provision_executor_submission_state,
)

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="real PostgreSQL test requires API_TEST_DATABASE_URL")


def contract(attempt="attempt-173", key="idem-173"):
    return {
        "status": "OBSERVED", "executor_boundary_result": "CONTRACT_READY",
        "executor_contract_ready": True, "submission_state": "NOT_SENT",
        "authorization_id": "auth-173", "policy_version": "release-v1",
        "attempt_id": attempt, "idempotency_key": key,
        "live_execution": False, "rpc_contact_allowed": False,
        "transaction_signing_allowed": False, "order_submission_allowed": False,
        "wallet_mutation_allowed": False, "automatic_execution": False,
    }


def transition(prior, new, event, attempt="attempt-173", key="idem-173", reconcile=False, retry=False):
    return {
        "status": "OBSERVED", "state_machine_result": "TRANSITION_OBSERVED",
        "prior_submission_state": prior, "submission_state": new, "event": event,
        "authorization_id": "auth-173", "policy_version": "release-v1",
        "attempt_id": attempt, "idempotency_key": key,
        "reconciliation_required": reconcile, "manual_retry_review_eligible": retry,
        "live_execution": False, "rpc_contacted": False, "transaction_signed": False,
        "order_submitted": False, "wallet_mutated": False, "automatic_execution": False,
        "automatic_retry_allowed": False,
    }


async def apply_migration():
    assert DB_URL
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("DROP TABLE IF EXISTS executor_submission_transition_audit CASCADE")
        await conn.execute("DROP TABLE IF EXISTS executor_submission_state CASCADE")
        root = Path(__file__).resolve().parents[1] / "migrations"
        await conn.execute((root / "004_executor_submission_state.sql").read_text())
    finally:
        await conn.close()


def factory():
    assert DB_URL
    engine = create_async_engine(DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_unknown_submission_survives_fresh_engine_and_cannot_silently_reset():
    await apply_migration()
    engine1, Session1 = factory()
    async with Session1() as session:
        assert (await provision_executor_submission_state(session, contract()))["persistence_result"] == "PROVISIONED"
        await session.commit()
        staged = await persist_executor_failure_transition(session, transition("NOT_SENT", "SUBMISSION_UNKNOWN", "SUBMISSION_TIMEOUT_UNKNOWN", reconcile=True))
        assert staged["persistence_result"] == "TRANSITION_STAGED"
        await session.commit()
    await engine1.dispose()

    engine2, Session2 = factory()
    async with Session2() as session:
        state = await load_executor_submission_state(session, "attempt-173")
        assert state["submission_state"] == "SUBMISSION_UNKNOWN"
        assert state["version"] == 1
        assert state["reconciliation_required"] is True
        with pytest.raises(Exception):
            await session.execute(text("UPDATE executor_submission_state SET submission_state='NOT_SENT' WHERE attempt_id='attempt-173'"))
        await session.rollback()
        state = await load_executor_submission_state(session, "attempt-173")
        assert state["submission_state"] == "SUBMISSION_UNKNOWN"
    await engine2.dispose()


@pytest.mark.asyncio
async def test_reconciliation_not_found_is_atomic_audited_and_never_auto_retry():
    await apply_migration()
    engine, Session = factory()
    async with Session() as session:
        await provision_executor_submission_state(session, contract())
        await session.commit()
        await persist_executor_failure_transition(session, transition("NOT_SENT", "SUBMISSION_UNKNOWN", "SUBMISSION_TIMEOUT_UNKNOWN", reconcile=True))
        await session.commit()
        result = await persist_executor_failure_transition(session, transition("SUBMISSION_UNKNOWN", "NOT_SENT", "RECONCILED_NOT_FOUND", retry=True))
        assert result["persistence_result"] == "TRANSITION_STAGED"
        assert result["automatic_retry_allowed"] is False
        await session.commit()
        state = await load_executor_submission_state(session, "attempt-173")
        assert state["submission_state"] == "NOT_SENT"
        assert state["version"] == 2
        assert state["manual_retry_review_eligible"] is True
        count = (await session.execute(text("SELECT count(*) FROM executor_submission_transition_audit WHERE attempt_id='attempt-173'"))).scalar_one()
        assert count == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_identity_and_idempotency_are_blocked():
    await apply_migration()
    engine, Session = factory()
    async with Session() as session:
        assert (await provision_executor_submission_state(session, contract()))["persistence_result"] == "PROVISIONED"
        await session.commit()
        assert (await provision_executor_submission_state(session, contract()))["persistence_result"] == "BLOCKED"
        assert (await provision_executor_submission_state(session, contract(attempt="attempt-other", key="idem-173")))["persistence_result"] == "BLOCKED"
    await engine.dispose()


@pytest.mark.asyncio
async def test_terminal_state_is_database_immutable():
    await apply_migration()
    engine, Session = factory()
    async with Session() as session:
        await provision_executor_submission_state(session, contract())
        await session.commit()
        await persist_executor_failure_transition(session, transition("NOT_SENT", "SUBMITTED", "SUBMISSION_ACCEPTED", reconcile=True))
        await session.commit()
        await persist_executor_failure_transition(session, transition("SUBMITTED", "CONFIRMED", "CONFIRMED_SUCCESS"))
        await session.commit()
        with pytest.raises(Exception):
            await session.execute(text("UPDATE executor_submission_state SET submission_state='NOT_SENT', version=version+1 WHERE attempt_id='attempt-173'"))
        await session.rollback()
        assert (await load_executor_submission_state(session, "attempt-173"))["submission_state"] == "CONFIRMED"
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_reconciliation_only_one_cas_wins():
    await apply_migration()
    engine, Session = factory()
    async with Session() as session:
        await provision_executor_submission_state(session, contract())
        await session.commit()
        await persist_executor_failure_transition(session, transition("NOT_SENT", "SUBMISSION_UNKNOWN", "SUBMISSION_TIMEOUT_UNKNOWN", reconcile=True))
        await session.commit()

    async def race(new, event):
        async with Session() as session:
            result = await persist_executor_failure_transition(session, transition("SUBMISSION_UNKNOWN", new, event, reconcile=new == "SUBMITTED"))
            await session.commit()
            return result["persistence_result"]

    results = await asyncio.gather(race("CONFIRMED", "RECONCILED_CONFIRMED"), race("FAILED", "RECONCILED_FAILED"))
    assert sorted(results) == ["BLOCKED", "TRANSITION_STAGED"]
    async with Session() as session:
        state = await load_executor_submission_state(session, "attempt-173")
        assert state["submission_state"] in {"CONFIRMED", "FAILED"}
        assert state["version"] == 2
        count = (await session.execute(text("SELECT count(*) FROM executor_submission_transition_audit WHERE attempt_id='attempt-173'"))).scalar_one()
        assert count == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_rollback_discards_state_transition_and_audit():
    await apply_migration()
    engine, Session = factory()
    async with Session() as session:
        await provision_executor_submission_state(session, contract())
        await session.commit()
        assert (await persist_executor_failure_transition(session, transition("NOT_SENT", "SUBMISSION_UNKNOWN", "PROCESS_CRASH_AFTER_SUBMISSION_MAY_HAVE_OCCURRED", reconcile=True)))["persistence_result"] == "TRANSITION_STAGED"
        await session.rollback()
    async with Session() as session:
        state = await load_executor_submission_state(session, "attempt-173")
        assert state["submission_state"] == "NOT_SENT"
        assert state["version"] == 0
        count = (await session.execute(text("SELECT count(*) FROM executor_submission_transition_audit"))).scalar_one()
        assert count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_secret_or_signed_transaction_material_is_rejected_before_persistence():
    await apply_migration()
    engine, Session = factory()
    async with Session() as session:
        contaminated = contract()
        contaminated["private_key"] = "never-store-me"
        result = await provision_executor_submission_state(session, contaminated)
        assert result["persistence_result"] == "UNKNOWN"
        assert "forbidden_secret_or_transaction_material" in result["missing"]
        count = (await session.execute(text("SELECT count(*) FROM executor_submission_state"))).scalar_one()
        assert count == 0
    await engine.dispose()
