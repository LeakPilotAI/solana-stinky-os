"""Persisted dry-run canary lifecycle coordinator for Project Genesis.

This module wires the already-proven canary boundaries together without adding
any live execution authority. It reads the persisted single-use authorization
state, runs the pre-order safety check, prepares the DRY_RUN adapter, performs a
second fail-closed safety recheck immediately before persistence, and stages the
atomic compare-and-swap consumption plus immutable audit in the caller-owned
database transaction.

It never commits internally, contacts an RPC, signs a transaction, submits an
order, mutates a wallet, or grants trading authority.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .canary_preorder_runtime_safety import evaluate_canary_preorder_runtime_safety
from .dry_run_execution_adapter import prepare_dry_run_canary_execution
from .dry_run_execution_persistence import persist_dry_run_canary_execution

AUTHORITY = {
    "interpretation": "PERSISTED_DRY_RUN_CANARY_LIFECYCLE_ONLY",
    "adapter_mode": "DRY_RUN",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
    "automatic_execution": False,
}

_STATE_SQL = text("""
SELECT
    authorization_id,
    policy_version,
    consumed,
    use_count,
    version,
    consumed_by_attempt_id,
    consumed_at,
    idempotency_key
FROM canary_authorization_state
WHERE authorization_id = :authorization_id
""")


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "lifecycle_result": "UNKNOWN",
        "preorder_passed": False,
        "adapter_prepared": False,
        "pre_persistence_recheck_passed": False,
        "persistence_staged": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _stopped(stage: str, result: dict[str, Any]) -> dict[str, Any]:
    status = "UNKNOWN" if result.get("status") == "UNKNOWN" else "OBSERVED"
    lifecycle_result = "UNKNOWN" if status == "UNKNOWN" else "BLOCKED"
    preorder_passed = stage not in {"authorization_state", "preorder"}
    adapter_prepared = stage in {"pre_persistence_authorization_state", "pre_persistence_recheck", "persistence"}
    pre_persistence_recheck_passed = stage == "persistence"
    return {
        "status": status,
        "lifecycle_result": lifecycle_result,
        "stopped_at": stage,
        "preorder_passed": preorder_passed,
        "adapter_prepared": adapter_prepared,
        "pre_persistence_recheck_passed": pre_persistence_recheck_passed,
        "persistence_staged": False,
        "stage_result": deepcopy(result),
        **AUTHORITY,
    }


async def load_canary_authorization_state(
    session: AsyncSession,
    authorization_id: str,
) -> dict[str, Any] | None:
    """Read the durable single-use state required by the runtime boundary."""
    normalized_id = str(authorization_id or "").strip()
    if not normalized_id:
        return None
    result = await session.execute(_STATE_SQL, {"authorization_id": normalized_id})
    row = result.mappings().first()
    if row is None:
        return None
    state = dict(row)
    value = state.get("consumed_at")
    if value is not None:
        state["consumed_at"] = value.isoformat()
    return state


async def prepare_and_persist_dry_run_canary_lifecycle(
    session: AsyncSession,
    canary_authorization: dict[str, Any],
    runtime: dict[str, Any],
    infrastructure: dict[str, Any],
    request: dict[str, Any],
    *,
    pre_persist_runtime: dict[str, Any],
    pre_persist_infrastructure: dict[str, Any],
) -> dict[str, Any]:
    """Drive persisted-state -> preorder -> adapter -> final recheck -> CAS/audit.

    The caller owns commit/rollback. A PASS result means only that the dry-run
    state transition and immutable audit have been staged in the current
    transaction. The mandatory second runtime/infrastructure snapshot closes the
    time-of-check/time-of-use window between adapter preparation and persistence.
    No external execution is attempted or permitted here.
    """
    inputs = {
        "canary_authorization": canary_authorization,
        "runtime": runtime,
        "infrastructure": infrastructure,
        "request": request,
        "pre_persist_runtime": pre_persist_runtime,
        "pre_persist_infrastructure": pre_persist_infrastructure,
    }
    malformed = [name for name, value in inputs.items() if not isinstance(value, dict)]
    if malformed:
        return _unknown([f"{name}_evidence" for name in malformed])

    authorization_id = str(canary_authorization.get("authorization_id") or "").strip()
    if not authorization_id:
        return _unknown(["authorization_id"])

    authorization_state = await load_canary_authorization_state(session, authorization_id)
    if authorization_state is None:
        return _unknown(
            ["persisted_authorization_state"],
            authorization_id=authorization_id,
            stopped_at="authorization_state",
        )

    preorder = evaluate_canary_preorder_runtime_safety(
        canary_authorization,
        runtime,
        infrastructure,
        authorization_state,
    )
    if preorder.get("preorder_result") != "PASS":
        return _stopped("preorder", preorder)

    prepared = prepare_dry_run_canary_execution(preorder, authorization_state, request)
    if prepared.get("adapter_result") != "DRY_RUN_READY":
        return _stopped("adapter", prepared)

    pre_persist_state = await load_canary_authorization_state(session, authorization_id)
    if pre_persist_state is None:
        return _unknown(
            ["persisted_authorization_state_before_persistence"],
            authorization_id=authorization_id,
            stopped_at="pre_persistence_authorization_state",
        )

    pre_persist_check = evaluate_canary_preorder_runtime_safety(
        canary_authorization,
        pre_persist_runtime,
        pre_persist_infrastructure,
        pre_persist_state,
    )
    if pre_persist_check.get("preorder_result") != "PASS":
        return _stopped("pre_persistence_recheck", pre_persist_check)

    persisted = await persist_dry_run_canary_execution(session, prepared)
    if persisted.get("persistence_result") != "TRANSACTION_STAGED":
        return _stopped("persistence", persisted)

    return {
        "status": "OBSERVED",
        "lifecycle_result": "TRANSACTION_STAGED",
        "preorder_passed": True,
        "adapter_prepared": True,
        "pre_persistence_recheck_passed": True,
        "persistence_staged": True,
        "durable_commit_managed_by_request_session": True,
        "authorization_id": authorization_id,
        "attempt_id": persisted.get("attempt_id"),
        "idempotency_key": persisted.get("idempotency_key"),
        "policy_version": persisted.get("policy_version"),
        "requested_notional_usd": persisted.get("requested_notional_usd"),
        "authorization_version_before": persisted.get("authorization_version_before"),
        "authorization_version_after": persisted.get("authorization_version_after"),
        "authorization_transition_applied": True,
        "evidence": {
            "authorization_state_before": deepcopy(authorization_state),
            "preorder": deepcopy(preorder),
            "prepared_adapter": deepcopy(prepared),
            "authorization_state_pre_persistence": deepcopy(pre_persist_state),
            "pre_persistence_recheck": deepcopy(pre_persist_check),
            "persistence": deepcopy(persisted),
        },
        "next_step": "CALLER_TRANSACTION_MUST_COMMIT; ROLLBACK_OR_CRASH_BEFORE_COMMIT_MUST_NOT_CONSUME",
        **AUTHORITY,
    }
