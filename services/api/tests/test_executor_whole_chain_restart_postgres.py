import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from stinky_api.executor_failure_mode_state_machine import evaluate_executor_failure_transition
from stinky_api.executor_submission_persistence import (
    load_executor_submission_state,
    persist_executor_failure_transition,
    provision_executor_submission_state,
)
from stinky_api.live_executor_boundary_contract import evaluate_live_executor_boundary_contract

DB_URL = os.getenv("API_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="real PostgreSQL test requires API_TEST_DATABASE_URL")

AUTH = "auth-174"
POLICY = "release-v1"
ATTEMPT = "attempt-174"
IDEM = "idem-174"


def readiness():
    return {
        "status": "OBSERVED",
        "operational_readiness_result": "PASS",
        "eligible_for_live_executor_review": True,
        "live_canary_unlocked": False,
        "live_executor_implemented": False,
        "policy_version": POLICY,
        "authorization_id": AUTH,
        "canary_notional_usd": 20.0,
        "max_loss_usd": 5.0,
        "live_execution": False,
        "trading_authority": False,
        "rpc_contact_allowed": False,
        "transaction_signing_allowed": False,
        "order_submission_allowed": False,
        "automatic_execution": False,
    }


def authorization_state():
    return {
        "authorization_id": AUTH,
        "policy_version": POLICY,
        "version": 0,
        "consumed": False,
        "use_count": 0,
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
        "evaluated_at": "2026-09-10T05:40:10+00:00",
    }


def quote():
    return {
        "quote_id": "quote-174",
        "quoted_at": "2026-09-10T05:40:00+00:00",
        "expires_at": "2026-09-10T05:41:00+00:00",
        "notional_usd": 20.0,
    }


def request():
    return {
        "authorization_id": AUTH,
        "policy_version": POLICY,
        "attempt_id": ATTEMPT,
        "idempotency_key": IDEM,
        "quote_id": "quote-174",
        "requested_at": "2026-09-10T05:40:20+00:00",
        "prior_submission_state": "NOT_SENT",
    }


def prior(state="NOT_SENT"):
    return {
        "submission_state": state,
        "authorization_id": AUTH,
        "policy_version": POLICY,
        "attempt_id": ATTEMPT,
        "idempotency_key": IDEM,
    }


def observation(event):
    return {
        "event": event,
        "authorization_id": AUTH,
        "policy_version": POLICY,
        "attempt_id": ATTEMPT,
        "idempotency_key": IDEM,
    }


async def reset_db():
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


def ready_contract():
    result = evaluate_live_executor_boundary_contract(
        readiness(), authorization_state(), runtime(), quote(), request()
    )
    assert result["executor_boundary_result"] == "CONTRACT_READY"
    assert result["executor_contract_ready"] is True
    assert result["submission_state"] == "NOT_SENT"
    assert result["live_execution"] is False
    assert result["automatic_retry_allowed"] is False
    return result


@pytest.mark.asyncio
async def test_whole_chain_unknown_survives_restart_then_reconciles_confirmed_without_retry():
    await reset_db()
    contract = ready_contract()

    engine1, Session1 = factory()
    async with Session1() as session:
        assert (await provision_executor_submission_state(session, contract))["persistence_result"] == "PROVISIONED"
        await session.commit()

        uncertain = evaluate_executor_failure_transition(
            contract, prior(), observation("SUBMISSION_TIMEOUT_UNKNOWN")
        )
        assert uncertain["submission_state"] == "SUBMISSION_UNKNOWN"
        assert uncertain["reconciliation_required"] is True
        assert uncertain["automatic_retry_allowed"] is False
        assert (await persist_executor_failure_transition(session, uncertain))["persistence_result"] == "TRANSITION_STAGED"
        await session.commit()
    await engine1.dispose()

    # Simulate a completely fresh process/engine after the uncertain submission.
    engine2, Session2 = factory()
    async with Session2() as session:
        durable = await load_executor_submission_state(session, ATTEMPT)
        assert durable["submission_state"] == "SUBMISSION_UNKNOWN"
        assert durable["version"] == 1
        assert durable["reconciliation_required"] is True

        # A fresh executor-boundary request cannot treat UNKNOWN as a new NOT_SENT attempt.
        replay_request = request()
        replay_request["prior_submission_state"] = durable["submission_state"]
        blocked = evaluate_live_executor_boundary_contract(
            readiness(), authorization_state(), runtime(), quote(), replay_request
        )
        assert blocked["executor_boundary_result"] == "BLOCKED"
        assert "prior_submission_not_proven_not_sent" in blocked["blockers"]
        assert blocked["safe_to_retry"] is False
        assert blocked["automatic_retry_allowed"] is False

        reconciled = evaluate_executor_failure_transition(
            contract,
            prior("SUBMISSION_UNKNOWN"),
            observation("RECONCILED_CONFIRMED"),
        )
        assert reconciled["submission_state"] == "CONFIRMED"
        assert reconciled["safe_to_retry"] is False
        assert reconciled["automatic_retry_allowed"] is False
        assert (await persist_executor_failure_transition(session, reconciled))["persistence_result"] == "TRANSITION_STAGED"
        await session.commit()

        final = await load_executor_submission_state(session, ATTEMPT)
        assert final["submission_state"] == "CONFIRMED"
        assert final["version"] == 2
        assert final["reconciliation_required"] is False
        audits = (await session.execute(text(
            "SELECT prior_state, new_state, event FROM executor_submission_transition_audit WHERE attempt_id=:attempt ORDER BY new_version"
        ), {"attempt": ATTEMPT})).all()
        assert audits == [
            ("NOT_SENT", "SUBMISSION_UNKNOWN", "SUBMISSION_TIMEOUT_UNKNOWN"),
            ("SUBMISSION_UNKNOWN", "CONFIRMED", "RECONCILED_CONFIRMED"),
        ]
    await engine2.dispose()


@pytest.mark.asyncio
async def test_whole_chain_duplicate_contract_and_post_restart_duplicate_transition_are_blocked():
    await reset_db()
    contract = ready_contract()
    engine1, Session1 = factory()
    async with Session1() as session:
        assert (await provision_executor_submission_state(session, contract))["persistence_result"] == "PROVISIONED"
        await session.commit()
        uncertain = evaluate_executor_failure_transition(contract, prior(), observation("PROCESS_CRASH_AFTER_SUBMISSION_MAY_HAVE_OCCURRED"))
        assert uncertain["submission_state"] == "SUBMISSION_UNKNOWN"
        assert (await persist_executor_failure_transition(session, uncertain))["persistence_result"] == "TRANSITION_STAGED"
        await session.commit()
    await engine1.dispose()

    engine2, Session2 = factory()
    async with Session2() as session:
        duplicate_provision = await provision_executor_submission_state(session, contract)
        assert duplicate_provision["persistence_result"] == "BLOCKED"
        assert "executor_submission_identity_or_idempotency_already_exists" in duplicate_provision["blockers"]

        # Replaying the stale NOT_SENT transition after restart cannot overwrite durable UNKNOWN.
        stale = evaluate_executor_failure_transition(contract, prior(), observation("SUBMISSION_ACCEPTED"))
        assert stale["submission_state"] == "SUBMITTED"
        blocked = await persist_executor_failure_transition(session, stale)
        assert blocked["persistence_result"] == "BLOCKED"
        assert "durable_prior_state_mismatch" in blocked["blockers"]
        await session.rollback()

        durable = await load_executor_submission_state(session, ATTEMPT)
        assert durable["submission_state"] == "SUBMISSION_UNKNOWN"
        assert durable["version"] == 1
        count = (await session.execute(text(
            "SELECT count(*) FROM executor_submission_transition_audit WHERE attempt_id=:attempt"
        ), {"attempt": ATTEMPT})).scalar_one()
        assert count == 1
    await engine2.dispose()


@pytest.mark.asyncio
async def test_whole_chain_reconciled_not_found_never_becomes_automatic_retry():
    await reset_db()
    contract = ready_contract()
    engine, Session = factory()
    async with Session() as session:
        await provision_executor_submission_state(session, contract)
        await session.commit()
        uncertain = evaluate_executor_failure_transition(contract, prior(), observation("SUBMISSION_TIMEOUT_UNKNOWN"))
        await persist_executor_failure_transition(session, uncertain)
        await session.commit()

        not_found = evaluate_executor_failure_transition(
            contract, prior("SUBMISSION_UNKNOWN"), observation("RECONCILED_NOT_FOUND")
        )
        assert not_found["submission_state"] == "NOT_SENT"
        assert not_found["manual_retry_review_eligible"] is True
        assert not_found["safe_to_retry"] is False
        assert not_found["automatic_retry_allowed"] is False
        staged = await persist_executor_failure_transition(session, not_found)
        assert staged["persistence_result"] == "TRANSITION_STAGED"
        assert staged["automatic_retry_allowed"] is False
        await session.commit()

        durable = await load_executor_submission_state(session, ATTEMPT)
        assert durable["submission_state"] == "NOT_SENT"
        assert durable["manual_retry_review_eligible"] is True
        assert durable["version"] == 2
    await engine.dispose()
