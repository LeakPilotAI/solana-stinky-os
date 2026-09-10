"""Dry-run execution-adapter contract for the isolated Genesis canary.

This module models the boundary between a passed pre-order safety check and a
future live execution implementation. It never contacts an RPC, signs a
transaction, submits an order, or mutates persistence. Instead it produces a
compare-and-swap authorization-consumption transition plus an immutable audit
record that a future transactional adapter must apply atomically before any live
side effect could occur.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any

MAX_CANARY_NOTIONAL_USD = 20.0

AUTHORITY = {
    "interpretation": "DRY_RUN_EXECUTION_ADAPTER_CONTRACT_ONLY",
    "adapter_mode": "DRY_RUN",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
    "persistence_mutated": False,
    "automatic_execution": False,
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "adapter_result": "UNKNOWN",
        "dry_run_ready": False,
        "authorization_transition_prepared": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _blocked(blockers: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "OBSERVED",
        "adapter_result": "BLOCKED",
        "dry_run_ready": False,
        "authorization_transition_prepared": False,
        "blockers": list(dict.fromkeys(blockers)),
        **extra,
        **AUTHORITY,
    }


def _claims_execution(value: dict[str, Any]) -> bool:
    return any(
        value.get(key) is True
        for key in (
            "live_execution",
            "trading_authority",
            "trade_signal",
            "recommendation_authority",
            "rpc_contacted",
            "transaction_signed",
            "order_submitted",
            "wallet_mutated",
            "persistence_mutated",
            "automatic_execution",
        )
    )


def prepare_dry_run_canary_execution(
    preorder: dict[str, Any],
    authorization_state: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Prepare a no-side-effect canary adapter attempt and CAS state transition.

    The returned transition is descriptive: this function does not persist it.
    A future live adapter must apply the transition atomically with an exact
    compare-and-swap precondition before any external side effect.
    """
    inputs = {
        "preorder": preorder,
        "authorization_state": authorization_state,
        "request": request,
    }
    malformed = [name for name, value in inputs.items() if not isinstance(value, dict)]
    if malformed:
        return _unknown([f"{name}_evidence" for name in malformed])

    contaminated = [name for name, value in inputs.items() if _claims_execution(value)]
    if contaminated:
        return _unknown(
            ["non_executing_dry_run_inputs"],
            execution_contamination=contaminated,
        )

    missing: list[str] = []
    if preorder.get("status") != "OBSERVED":
        missing.append("observed_preorder")
    if preorder.get("preorder_result") != "PASS":
        missing.append("passed_preorder")
    if preorder.get("execution_adapter_eligible") is not True:
        missing.append("execution_adapter_eligibility")
    if preorder.get("authorization_consumable") is not True:
        missing.append("authorization_consumable")
    if preorder.get("single_use") is not True:
        missing.append("single_use_preorder")

    authorization_id = str(preorder.get("authorization_id") or "").strip()
    policy_version = str(preorder.get("policy_version") or "").strip()
    authorized_notional = _number(preorder.get("requested_notional_usd"))
    max_loss = _number(preorder.get("max_loss_usd"))
    if not authorization_id:
        missing.append("authorization_id")
    if not policy_version:
        missing.append("policy_version")
    if authorized_notional is None or authorized_notional <= 0:
        missing.append("valid_preorder_notional")
    if max_loss is None or max_loss <= 0:
        missing.append("valid_preorder_loss_cap")

    state_id = str(authorization_state.get("authorization_id") or "").strip()
    consumed = authorization_state.get("consumed")
    use_count = authorization_state.get("use_count")
    state_version = authorization_state.get("version")
    if not state_id:
        missing.append("authorization_state_id")
    if not isinstance(consumed, bool):
        missing.append("authorization_consumed_state")
    if not isinstance(use_count, int) or isinstance(use_count, bool) or use_count < 0:
        missing.append("valid_authorization_use_count")
    if not isinstance(state_version, int) or isinstance(state_version, bool) or state_version < 0:
        missing.append("valid_authorization_state_version")

    attempt_id = str(request.get("attempt_id") or "").strip()
    requested_at = _dt(request.get("requested_at"))
    request_authorization_id = str(request.get("authorization_id") or "").strip()
    request_policy_version = str(request.get("policy_version") or "").strip()
    requested_notional = _number(request.get("requested_notional_usd"))
    adapter_mode = str(request.get("adapter_mode") or "").strip().upper()
    idempotency_key = str(request.get("idempotency_key") or "").strip()
    if not attempt_id:
        missing.append("attempt_id")
    if requested_at is None:
        missing.append("requested_at")
    if not request_authorization_id:
        missing.append("request_authorization_id")
    if not request_policy_version:
        missing.append("request_policy_version")
    if requested_notional is None or requested_notional <= 0:
        missing.append("valid_requested_notional_usd")
    if not adapter_mode:
        missing.append("adapter_mode")
    if not idempotency_key:
        missing.append("idempotency_key")

    if missing:
        return _unknown(missing, authorization_id=authorization_id or None)

    blockers: list[str] = []
    if adapter_mode != "DRY_RUN":
        blockers.append("adapter_mode_must_be_dry_run")
    if state_id != authorization_id or request_authorization_id != authorization_id:
        blockers.append("authorization_id_mismatch")
    if request_policy_version != policy_version:
        blockers.append("policy_version_mismatch")
    if consumed is not False or use_count != 0:
        blockers.append("authorization_already_consumed")
    if requested_notional > MAX_CANARY_NOTIONAL_USD:
        blockers.append("requested_notional_exceeds_20_usd")
    if requested_notional > authorized_notional:
        blockers.append("requested_notional_exceeds_preorder_notional")
    if max_loss > authorized_notional:
        blockers.append("loss_cap_exceeds_preorder_notional")

    if blockers:
        return _blocked(
            blockers,
            authorization_id=authorization_id,
            attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            evidence=deepcopy(inputs),
        )

    transition = {
        "operation": "COMPARE_AND_SWAP_AUTHORIZATION_CONSUMPTION",
        "authorization_id": authorization_id,
        "expected": {
            "consumed": False,
            "use_count": 0,
            "version": state_version,
        },
        "proposed": {
            "consumed": True,
            "use_count": 1,
            "version": state_version + 1,
            "consumed_by_attempt_id": attempt_id,
            "consumed_at": requested_at.isoformat(),
            "idempotency_key": idempotency_key,
        },
        "must_be_atomic_before_external_side_effect": True,
        "applied": False,
    }
    audit = {
        "event": "CANARY_EXECUTION_ADAPTER_DRY_RUN_PREPARED",
        "attempt_id": attempt_id,
        "authorization_id": authorization_id,
        "policy_version": policy_version,
        "requested_at": requested_at.isoformat(),
        "requested_notional_usd": requested_notional,
        "max_loss_usd": max_loss,
        "adapter_mode": "DRY_RUN",
        "idempotency_key": idempotency_key,
        "external_side_effects": False,
        "rpc_contacted": False,
        "transaction_signed": False,
        "order_submitted": False,
        "authorization_transition_applied": False,
    }

    return {
        "status": "OBSERVED",
        "adapter_result": "DRY_RUN_READY",
        "dry_run_ready": True,
        "authorization_transition_prepared": True,
        "authorization_id": authorization_id,
        "attempt_id": attempt_id,
        "policy_version": policy_version,
        "requested_notional_usd": requested_notional,
        "maximum_canary_notional_usd": MAX_CANARY_NOTIONAL_USD,
        "max_loss_usd": max_loss,
        "idempotency_key": idempotency_key,
        "authorization_transition": transition,
        "post_order_audit_record": audit,
        "evidence": deepcopy(inputs),
        "next_step": "PERSIST_ATOMIC_SINGLE_USE_CONSUMPTION_AND_AUDIT_IN_DRY_RUN_ONLY",
        **AUTHORITY,
    }
