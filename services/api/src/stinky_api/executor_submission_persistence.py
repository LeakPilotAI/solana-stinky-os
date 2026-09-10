"""Durable persistence for the non-broadcasting executor state machine.

The caller owns commit/rollback. This module performs only PostgreSQL state/audit
writes. It never contacts an RPC, signs or serializes a transaction, submits an
order, reads key material, or mutates a wallet.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import text

ALLOWED_STATES = {"NOT_SENT", "SUBMISSION_UNKNOWN", "SUBMITTED", "CONFIRMED", "FAILED"}
FORBIDDEN_EVIDENCE_KEYS = {
    "private_key", "private_key_material", "secret_key", "seed_phrase", "mnemonic",
    "signature", "signed_transaction", "raw_transaction",
}
AUTHORITY = {
    "interpretation": "DURABLE_NON_BROADCASTING_EXECUTOR_SUBMISSION_STATE_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
    "automatic_execution": False,
    "automatic_retry_allowed": False,
}


def _contains_forbidden(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(k).lower() in FORBIDDEN_EVIDENCE_KEYS or _contains_forbidden(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden(v) for v in value)
    return False


async def load_executor_submission_state(session, attempt_id: str) -> dict[str, Any] | None:
    attempt = str(attempt_id or "").strip()
    if not attempt:
        return None
    row = (await session.execute(text("""
        SELECT attempt_id, authorization_id, policy_version, idempotency_key,
               submission_state, version, last_event, reconciliation_required,
               manual_retry_review_eligible, state_evidence, created_at, updated_at
        FROM executor_submission_state WHERE attempt_id = :attempt_id
    """), {"attempt_id": attempt})).mappings().first()
    return dict(row) if row else None


async def provision_executor_submission_state(session, executor_contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(executor_contract, dict):
        return {"status": "UNKNOWN", "persistence_result": "UNKNOWN", "missing": ["executor_contract"], **AUTHORITY}
    required = {
        "authorization_id": str(executor_contract.get("authorization_id") or "").strip(),
        "policy_version": str(executor_contract.get("policy_version") or "").strip(),
        "attempt_id": str(executor_contract.get("attempt_id") or "").strip(),
        "idempotency_key": str(executor_contract.get("idempotency_key") or "").strip(),
    }
    missing = [k for k, v in required.items() if not v]
    if executor_contract.get("status") != "OBSERVED" or executor_contract.get("executor_boundary_result") != "CONTRACT_READY" or executor_contract.get("executor_contract_ready") is not True:
        missing.append("ready_executor_contract")
    if executor_contract.get("submission_state") != "NOT_SENT":
        missing.append("initial_not_sent_state")
    if _contains_forbidden(executor_contract):
        missing.append("forbidden_secret_or_transaction_material")
    if missing:
        return {"status": "UNKNOWN", "persistence_result": "UNKNOWN", "missing": list(dict.fromkeys(missing)), **AUTHORITY}

    result = await session.execute(text("""
        INSERT INTO executor_submission_state
            (attempt_id, authorization_id, policy_version, idempotency_key, submission_state,
             version, reconciliation_required, manual_retry_review_eligible, state_evidence)
        VALUES (:attempt_id, :authorization_id, :policy_version, :idempotency_key,
                'NOT_SENT', 0, FALSE, FALSE, CAST(:evidence AS jsonb))
        ON CONFLICT DO NOTHING
        RETURNING attempt_id, authorization_id, policy_version, idempotency_key, submission_state, version
    """), {**required, "evidence": __import__("json").dumps(deepcopy(executor_contract))})
    row = result.mappings().first()
    if row is None:
        return {"status": "OBSERVED", "persistence_result": "BLOCKED", "blockers": ["executor_submission_identity_or_idempotency_already_exists"], **AUTHORITY}
    return {"status": "OBSERVED", "persistence_result": "PROVISIONED", "state": dict(row), **AUTHORITY}


async def persist_executor_failure_transition(session, transition: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(transition, dict):
        return {"status": "UNKNOWN", "persistence_result": "UNKNOWN", "missing": ["transition"], **AUTHORITY}
    if transition.get("status") != "OBSERVED" or transition.get("state_machine_result") != "TRANSITION_OBSERVED":
        return {"status": "UNKNOWN", "persistence_result": "UNKNOWN", "missing": ["observed_state_machine_transition"], **AUTHORITY}
    if _contains_forbidden(transition):
        return {"status": "UNKNOWN", "persistence_result": "UNKNOWN", "missing": ["forbidden_secret_or_transaction_material"], **AUTHORITY}

    attempt_id = str(transition.get("attempt_id") or "").strip()
    authorization_id = str(transition.get("authorization_id") or "").strip()
    policy_version = str(transition.get("policy_version") or "").strip()
    idempotency_key = str(transition.get("idempotency_key") or "").strip()
    prior_state = str(transition.get("prior_submission_state") or "").strip()
    new_state = str(transition.get("submission_state") or "").strip()
    event = str(transition.get("event") or "").strip()
    if not all((attempt_id, authorization_id, policy_version, idempotency_key, event)) or prior_state not in ALLOWED_STATES or new_state not in ALLOWED_STATES:
        return {"status": "UNKNOWN", "persistence_result": "UNKNOWN", "missing": ["complete_valid_transition_identity_and_state"], **AUTHORITY}

    current = await load_executor_submission_state(session, attempt_id)
    if current is None:
        return {"status": "OBSERVED", "persistence_result": "BLOCKED", "blockers": ["executor_submission_state_missing"], **AUTHORITY}
    if any((current["authorization_id"] != authorization_id, current["policy_version"] != policy_version, current["idempotency_key"] != idempotency_key)):
        return {"status": "OBSERVED", "persistence_result": "BLOCKED", "blockers": ["execution_identity_mismatch"], **AUTHORITY}
    expected_version = int(current["version"])
    if current["submission_state"] != prior_state:
        return {"status": "OBSERVED", "persistence_result": "BLOCKED", "blockers": ["durable_prior_state_mismatch"], **AUTHORITY}

    evidence_json = __import__("json").dumps(deepcopy(transition))
    updated = (await session.execute(text("""
        UPDATE executor_submission_state
        SET submission_state = :new_state,
            version = version + 1,
            last_event = :event,
            reconciliation_required = :reconciliation_required,
            manual_retry_review_eligible = :manual_retry_review_eligible,
            state_evidence = CAST(:evidence AS jsonb),
            updated_at = now()
        WHERE attempt_id = :attempt_id
          AND authorization_id = :authorization_id
          AND policy_version = :policy_version
          AND idempotency_key = :idempotency_key
          AND submission_state = :prior_state
          AND version = :expected_version
        RETURNING version
    """), {
        "new_state": new_state, "event": event,
        "reconciliation_required": transition.get("reconciliation_required") is True,
        "manual_retry_review_eligible": transition.get("manual_retry_review_eligible") is True,
        "evidence": evidence_json, "attempt_id": attempt_id, "authorization_id": authorization_id,
        "policy_version": policy_version, "idempotency_key": idempotency_key,
        "prior_state": prior_state, "expected_version": expected_version,
    })).mappings().first()
    if updated is None:
        return {"status": "OBSERVED", "persistence_result": "BLOCKED", "blockers": ["executor_submission_compare_and_swap_failed"], **AUTHORITY}

    new_version = int(updated["version"])
    await session.execute(text("""
        INSERT INTO executor_submission_transition_audit
            (attempt_id, authorization_id, policy_version, idempotency_key, prior_state, new_state,
             event, prior_version, new_version, reconciliation_required,
             manual_retry_review_eligible, transition_evidence)
        VALUES (:attempt_id, :authorization_id, :policy_version, :idempotency_key, :prior_state,
                :new_state, :event, :prior_version, :new_version, :reconciliation_required,
                :manual_retry_review_eligible, CAST(:evidence AS jsonb))
    """), {
        "attempt_id": attempt_id, "authorization_id": authorization_id, "policy_version": policy_version,
        "idempotency_key": idempotency_key, "prior_state": prior_state, "new_state": new_state,
        "event": event, "prior_version": expected_version, "new_version": new_version,
        "reconciliation_required": transition.get("reconciliation_required") is True,
        "manual_retry_review_eligible": transition.get("manual_retry_review_eligible") is True,
        "evidence": evidence_json,
    })
    return {"status": "OBSERVED", "persistence_result": "TRANSITION_STAGED", "prior_version": expected_version, "new_version": new_version, "submission_state": new_state, "commit_required": True, **AUTHORITY}
