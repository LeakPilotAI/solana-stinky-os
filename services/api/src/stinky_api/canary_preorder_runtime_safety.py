"""Fail-closed pre-order runtime safety contract for the isolated Genesis canary.

This module performs the final in-process eligibility recheck immediately before
an external execution adapter could be considered. It does not contact an RPC,
sign a transaction, submit an order, or grant trading authority.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any

MAX_CANARY_NOTIONAL_USD = 20.0

AUTHORITY = {
    "interpretation": "CANARY_PREORDER_RUNTIME_SAFETY_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "rpc_contact_allowed": False,
    "transaction_signing_allowed": False,
    "order_submission_allowed": False,
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
        "preorder_result": "UNKNOWN",
        "execution_adapter_eligible": False,
        "authorization_consumable": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _blocked(blockers: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "OBSERVED",
        "preorder_result": "BLOCKED",
        "execution_adapter_eligible": False,
        "authorization_consumable": False,
        "blockers": list(dict.fromkeys(blockers)),
        **extra,
        **AUTHORITY,
    }


def _claims_authority(value: dict[str, Any]) -> bool:
    return any(
        value.get(key) is True
        for key in (
            "live_execution",
            "trading_authority",
            "trade_signal",
            "recommendation_authority",
            "rpc_contact_allowed",
            "transaction_signing_allowed",
            "order_submission_allowed",
            "automatic_execution",
        )
    )


def evaluate_canary_preorder_runtime_safety(
    canary_authorization: dict[str, Any],
    runtime: dict[str, Any],
    infrastructure: dict[str, Any],
    authorization_state: dict[str, Any],
) -> dict[str, Any]:
    """Revalidate one isolated canary immediately before any execution adapter.

    PASS means only that a separate adapter may consume this exact authorization
    once. The adapter is outside this module and must still enforce its own
    signing/submission controls. Missing evidence fails closed to UNKNOWN;
    observed control failures return BLOCKED.
    """
    inputs = {
        "canary_authorization": canary_authorization,
        "runtime": runtime,
        "infrastructure": infrastructure,
        "authorization_state": authorization_state,
    }
    malformed = [name for name, value in inputs.items() if not isinstance(value, dict)]
    if malformed:
        return _unknown([f"{name}_evidence" for name in malformed])

    contaminated = [name for name, value in inputs.items() if _claims_authority(value)]
    if contaminated:
        return _unknown(
            ["non_authoritative_preorder_evidence"],
            authority_contamination=contaminated,
        )

    missing: list[str] = []
    if canary_authorization.get("status") != "OBSERVED":
        missing.append("observed_canary_authorization")
    if canary_authorization.get("canary_authorization_result") != "PASS":
        missing.append("passed_canary_authorization")
    if canary_authorization.get("canary_execution_eligible") is not True:
        missing.append("canary_execution_eligibility")

    authorization_id = str(canary_authorization.get("authorization_id") or "").strip()
    policy_version = str(canary_authorization.get("policy_version") or "").strip()
    authorized_notional = _number(canary_authorization.get("canary_notional_usd"))
    max_loss = _number(canary_authorization.get("max_loss_usd"))
    if not authorization_id:
        missing.append("authorization_id")
    if not policy_version:
        missing.append("policy_version")
    if authorized_notional is None or authorized_notional <= 0:
        missing.append("valid_authorized_canary_notional")
    if max_loss is None or max_loss <= 0:
        missing.append("valid_authorized_loss_cap")

    requested_notional = _number(runtime.get("requested_notional_usd"))
    realized_loss = _number(runtime.get("realized_loss_usd"))
    open_positions = runtime.get("open_positions")
    required_runtime = (
        "kill_switch_armed",
        "isolated_funds",
        "isolated_account_or_wallet",
        "no_borrowing",
        "no_leverage",
    )
    for key in required_runtime:
        if key not in runtime:
            missing.append(key)
    if requested_notional is None or requested_notional <= 0:
        missing.append("valid_requested_notional_usd")
    if realized_loss is None or realized_loss < 0:
        missing.append("valid_realized_loss_usd")
    if not isinstance(open_positions, int) or isinstance(open_positions, bool) or open_positions < 0:
        missing.append("valid_open_positions")

    if infrastructure.get("status") not in {"HEALTHY", "OBSERVED"}:
        missing.append("observed_runtime_infrastructure")
    if "critical_services_healthy" not in infrastructure:
        missing.append("critical_services_healthy_evidence")
    if "unresolved_critical_incidents" not in infrastructure:
        missing.append("unresolved_critical_incidents_evidence")
    checked_at = _dt(infrastructure.get("checked_at"))
    evaluated_at = _dt(runtime.get("evaluated_at"))
    max_age_seconds = runtime.get("max_infrastructure_age_seconds")
    if checked_at is None:
        missing.append("runtime_infrastructure_checked_at")
    if evaluated_at is None:
        missing.append("runtime_evaluated_at")
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or max_age_seconds <= 0:
        missing.append("valid_max_infrastructure_age_seconds")

    state_authorization_id = str(authorization_state.get("authorization_id") or "").strip()
    if not state_authorization_id:
        missing.append("authorization_state_id")
    if "consumed" not in authorization_state:
        missing.append("authorization_consumed_state")
    use_count = authorization_state.get("use_count")
    if not isinstance(use_count, int) or isinstance(use_count, bool) or use_count < 0:
        missing.append("valid_authorization_use_count")

    if missing:
        return _unknown(missing, authorization_id=authorization_id or None)

    blockers: list[str] = []
    if authorization_state.get("consumed") is not False or use_count != 0:
        blockers.append("authorization_already_consumed")
    if state_authorization_id != authorization_id:
        blockers.append("authorization_state_mismatch")

    if requested_notional > MAX_CANARY_NOTIONAL_USD:
        blockers.append("requested_notional_exceeds_20_usd")
    if requested_notional > authorized_notional:
        blockers.append("requested_notional_exceeds_authorized_notional")
    if max_loss > authorized_notional:
        blockers.append("loss_cap_exceeds_authorized_notional")
    if realized_loss >= max_loss:
        blockers.append("loss_cap_reached")
    if open_positions != 0:
        blockers.append("existing_open_position_blocks_new_canary")
    if runtime.get("kill_switch_armed") is not True:
        blockers.append("kill_switch_not_armed")
    if runtime.get("isolated_funds") is not True:
        blockers.append("funds_not_isolated")
    if runtime.get("isolated_account_or_wallet") is not True:
        blockers.append("account_or_wallet_not_isolated")
    if runtime.get("no_borrowing") is not True:
        blockers.append("borrowing_not_prohibited")
    if runtime.get("no_leverage") is not True:
        blockers.append("leverage_not_prohibited")

    if infrastructure.get("critical_services_healthy") is not True:
        blockers.append("critical_services_unhealthy")
    if infrastructure.get("unresolved_critical_incidents") != 0:
        blockers.append("unresolved_critical_incidents")
    if checked_at is not None and evaluated_at is not None:
        age = (evaluated_at - checked_at).total_seconds()
        if age < 0 or age > max_age_seconds:
            blockers.append("infrastructure_recheck_stale")

    if blockers:
        return _blocked(
            blockers,
            authorization_id=authorization_id,
            policy_version=policy_version,
            requested_notional_usd=requested_notional,
            max_loss_usd=max_loss,
            evidence=deepcopy(inputs),
            next_step="DO_NOT_CALL_EXECUTION_ADAPTER",
        )

    return {
        "status": "OBSERVED",
        "preorder_result": "PASS",
        "execution_adapter_eligible": True,
        "authorization_consumable": True,
        "single_use": True,
        "authorization_id": authorization_id,
        "policy_version": policy_version,
        "requested_notional_usd": requested_notional,
        "maximum_canary_notional_usd": MAX_CANARY_NOTIONAL_USD,
        "max_loss_usd": max_loss,
        "realized_loss_usd": realized_loss,
        "open_positions": open_positions,
        "kill_switch_armed": True,
        "infrastructure_rechecked": True,
        "evidence": deepcopy(inputs),
        "next_step": "SEPARATE_EXECUTION_ADAPTER_MAY_CONSUME_AUTHORIZATION_ONCE",
        **AUTHORITY,
    }
