"""Fail-closed isolated-canary authorization boundary for Project Genesis.

This module does not submit orders, contact RPCs, sign transactions, or unlock
live execution. It only evaluates whether an already-passed release-gate result
plus explicit canary controls and human authorization are sufficient to mark a
single isolated canary as eligible for a separate runtime execution path.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

MAX_CANARY_NOTIONAL_USD = 20.0

AUTHORITY = {
    "interpretation": "ISOLATED_CANARY_AUTHORIZATION_BOUNDARY_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "order_submission_allowed": False,
    "transaction_signing_allowed": False,
    "rpc_contact_allowed": False,
    "automatic_canary_activation": False,
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "canary_authorization_result": "UNKNOWN",
        "canary_execution_eligible": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _blocked(blockers: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "OBSERVED",
        "canary_authorization_result": "BLOCKED",
        "canary_execution_eligible": False,
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
            "order_submission_allowed",
            "transaction_signing_allowed",
            "rpc_contact_allowed",
            "automatic_canary_activation",
        )
    )


def evaluate_isolated_canary_authorization(
    release_gate: dict[str, Any],
    controls: dict[str, Any],
    infrastructure: dict[str, Any],
    authorization: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate eligibility for one isolated, human-authorized $20-max canary.

    Missing/malformed evidence fails closed to UNKNOWN. Fully observed but
    failing controls produce BLOCKED. PASS means only that a separate runtime
    execution path may be considered; this function itself never enables or
    performs live execution.
    """
    inputs = {
        "release_gate": release_gate,
        "controls": controls,
        "infrastructure": infrastructure,
        "authorization": authorization,
    }
    malformed = [name for name, value in inputs.items() if not isinstance(value, dict)]
    if malformed:
        return _unknown([f"{name}_evidence" for name in malformed])

    contaminated = [name for name, value in inputs.items() if _claims_authority(value)]
    if contaminated:
        return _unknown(
            ["non_authoritative_canary_evidence"],
            authority_contamination=contaminated,
        )

    missing: list[str] = []

    if release_gate.get("status") != "OBSERVED":
        missing.append("observed_release_gate")
    if release_gate.get("live_canary_unlocked") is not False:
        missing.append("release_gate_does_not_unlock_live_canary")
    if release_gate.get("automatic_canary_activation") is not False:
        missing.append("release_gate_no_automatic_activation")
    policy_version = str(release_gate.get("policy_version") or "").strip()
    if not policy_version:
        missing.append("release_policy_version")

    notional = _number(controls.get("canary_notional_usd"))
    loss_cap = _number(controls.get("max_loss_usd"))
    max_open_positions = controls.get("max_open_positions")
    required_control_keys = (
        "isolated_funds",
        "isolated_account_or_wallet",
        "kill_switch_armed",
        "no_borrowing",
        "no_leverage",
    )
    for key in required_control_keys:
        if key not in controls:
            missing.append(key)
    if notional is None or notional <= 0:
        missing.append("valid_canary_notional_usd")
    if loss_cap is None or loss_cap <= 0:
        missing.append("valid_max_loss_usd")
    if not isinstance(max_open_positions, int) or isinstance(max_open_positions, bool) or max_open_positions <= 0:
        missing.append("valid_max_open_positions")

    if infrastructure.get("status") not in {"HEALTHY", "OBSERVED"}:
        missing.append("observed_canary_infrastructure")
    if "critical_services_healthy" not in infrastructure:
        missing.append("critical_services_healthy_evidence")
    if "unresolved_critical_incidents" not in infrastructure:
        missing.append("unresolved_critical_incidents_evidence")
    if infrastructure.get("revalidated_for_canary") is not True:
        missing.append("canary_infrastructure_revalidation")
    if not str(infrastructure.get("checked_at") or "").strip():
        missing.append("canary_infrastructure_checked_at")

    if "human_authorized" not in authorization:
        missing.append("human_authorized_evidence")
    authorization_id = str(authorization.get("authorization_id") or "").strip()
    authorized_at = str(authorization.get("authorized_at") or "").strip()
    authorized_notional = _number(authorization.get("authorized_notional_usd"))
    authorized_policy_version = str(authorization.get("policy_version") or "").strip()
    if not authorization_id:
        missing.append("authorization_id")
    if not authorized_at:
        missing.append("authorized_at")
    if authorized_notional is None or authorized_notional <= 0:
        missing.append("valid_authorized_notional_usd")
    if not authorized_policy_version:
        missing.append("authorized_policy_version")

    if missing:
        return _unknown(missing, policy_version=policy_version or None)

    blockers: list[str] = []
    if release_gate.get("release_gate_result") != "PASS" or release_gate.get("eligible_for_isolated_canary_review") is not True:
        blockers.append("release_gate_not_passed")

    if notional > MAX_CANARY_NOTIONAL_USD:
        blockers.append("canary_notional_exceeds_20_usd")
    if loss_cap > notional:
        blockers.append("loss_cap_exceeds_canary_notional")
    if max_open_positions != 1:
        blockers.append("single_position_isolation_required")
    if controls.get("isolated_funds") is not True:
        blockers.append("funds_not_isolated")
    if controls.get("isolated_account_or_wallet") is not True:
        blockers.append("account_or_wallet_not_isolated")
    if controls.get("kill_switch_armed") is not True:
        blockers.append("kill_switch_not_armed")
    if controls.get("no_borrowing") is not True:
        blockers.append("borrowing_not_prohibited")
    if controls.get("no_leverage") is not True:
        blockers.append("leverage_not_prohibited")

    if infrastructure.get("critical_services_healthy") is not True:
        blockers.append("critical_services_unhealthy")
    if infrastructure.get("unresolved_critical_incidents") != 0:
        blockers.append("unresolved_critical_incidents")

    if authorization.get("human_authorized") is not True:
        blockers.append("human_authorization_missing")
    if authorized_notional > MAX_CANARY_NOTIONAL_USD:
        blockers.append("authorized_notional_exceeds_20_usd")
    if notional > authorized_notional:
        blockers.append("requested_notional_exceeds_authorized_notional")
    if authorized_policy_version != policy_version:
        blockers.append("authorization_policy_version_mismatch")

    if blockers:
        return _blocked(
            blockers,
            policy_version=policy_version,
            canary_notional_usd=notional,
            max_loss_usd=loss_cap,
            authorization_id=authorization_id,
            evidence=deepcopy(inputs),
            next_step="REMAIN_PAPER_ONLY",
        )

    return {
        "status": "OBSERVED",
        "canary_authorization_result": "PASS",
        "canary_execution_eligible": True,
        "canary_notional_usd": notional,
        "maximum_canary_notional_usd": MAX_CANARY_NOTIONAL_USD,
        "max_loss_usd": loss_cap,
        "max_open_positions": max_open_positions,
        "kill_switch_armed": True,
        "isolated_funds": True,
        "isolated_account_or_wallet": True,
        "human_authorized": True,
        "authorization_id": authorization_id,
        "authorized_at": authorized_at,
        "policy_version": policy_version,
        "evidence": deepcopy(inputs),
        "next_step": "SEPARATE_RUNTIME_CANARY_EXECUTION_PATH_WITH_PRE_ORDER_RECHECKS",
        **AUTHORITY,
    }
