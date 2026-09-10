"""Provision persistent single-use state from passed isolated-canary evidence only."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from math import isfinite
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_CANARY_NOTIONAL_USD = 20.0

AUTHORITY = {
    "interpretation": "CANARY_AUTHORIZATION_PROVISIONING_ONLY",
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

_INSERT_STATE = text("""
INSERT INTO canary_authorization_state (
    authorization_id, policy_version, consumed, use_count, version,
    authorized_at, authorized_notional_usd, max_loss_usd, authorization_evidence
) VALUES (
    :authorization_id, :policy_version, FALSE, 0, 0,
    :authorized_at, :authorized_notional_usd, :max_loss_usd, CAST(:evidence AS JSONB)
)
ON CONFLICT (authorization_id) DO NOTHING
RETURNING authorization_id, policy_version, consumed, use_count, version
""")

_INSERT_AUDIT = text("""
INSERT INTO canary_authorization_provision_audit (
    authorization_id, policy_version, authorized_at, authorized_notional_usd,
    max_loss_usd, authorization_evidence
) VALUES (
    :authorization_id, :policy_version, :authorized_at, :authorized_notional_usd,
    :max_loss_usd, CAST(:evidence AS JSONB)
)
""")


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _timestamp(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return raw


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "provisioning_result": "UNKNOWN",
        "authorization_state_staged": False,
        "provision_audit_staged": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _blocked(blockers: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "OBSERVED",
        "provisioning_result": "BLOCKED",
        "authorization_state_staged": False,
        "provision_audit_staged": False,
        "blockers": list(dict.fromkeys(blockers)),
        **extra,
        **AUTHORITY,
    }


def _claims_authority(value: dict[str, Any]) -> bool:
    return any(value.get(key) is True for key in (
        "live_execution", "trading_authority", "trade_signal", "recommendation_authority",
        "rpc_contact_allowed", "transaction_signing_allowed", "order_submission_allowed",
        "rpc_contacted", "transaction_signed", "order_submitted", "wallet_mutated",
        "automatic_canary_activation", "automatic_execution",
    ))


def validate_canary_authorization_for_provisioning(
    canary_authorization: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Normalize only a genuine #162 PASS result; otherwise fail closed."""
    if not isinstance(canary_authorization, dict):
        return None, _unknown(["canary_authorization_evidence"])
    if _claims_authority(canary_authorization):
        return None, _unknown(["non_authoritative_canary_authorization"])

    missing: list[str] = []
    if canary_authorization.get("status") != "OBSERVED":
        missing.append("observed_canary_authorization")
    if canary_authorization.get("canary_authorization_result") != "PASS":
        missing.append("passed_canary_authorization")
    if canary_authorization.get("canary_execution_eligible") is not True:
        missing.append("canary_execution_eligibility")
    if canary_authorization.get("human_authorized") is not True:
        missing.append("human_authorization")

    authorization_id = str(canary_authorization.get("authorization_id") or "").strip()
    policy_version = str(canary_authorization.get("policy_version") or "").strip()
    authorized_at = _timestamp(canary_authorization.get("authorized_at"))
    notional = _number(canary_authorization.get("canary_notional_usd"))
    max_loss = _number(canary_authorization.get("max_loss_usd"))
    if not authorization_id:
        missing.append("authorization_id")
    if not policy_version:
        missing.append("policy_version")
    if authorized_at is None:
        missing.append("valid_authorized_at")
    if notional is None or notional <= 0:
        missing.append("valid_canary_notional_usd")
    if max_loss is None or max_loss <= 0:
        missing.append("valid_max_loss_usd")
    if missing:
        return None, _unknown(missing, authorization_id=authorization_id or None)

    blockers: list[str] = []
    assert notional is not None and max_loss is not None
    if notional > MAX_CANARY_NOTIONAL_USD:
        blockers.append("canary_notional_exceeds_20_usd")
    if max_loss > notional:
        blockers.append("loss_cap_exceeds_canary_notional")
    if canary_authorization.get("max_open_positions") != 1:
        blockers.append("single_position_isolation_required")
    for key in ("kill_switch_armed", "isolated_funds", "isolated_account_or_wallet"):
        if canary_authorization.get(key) is not True:
            blockers.append(f"{key}_required")
    if blockers:
        return None, _blocked(blockers, authorization_id=authorization_id)

    normalized = {
        "authorization_id": authorization_id,
        "policy_version": policy_version,
        "authorized_at": authorized_at,
        "authorized_notional_usd": notional,
        "max_loss_usd": max_loss,
        "evidence": deepcopy(canary_authorization),
    }
    return normalized, None


async def provision_canary_authorization_state(
    session: AsyncSession,
    canary_authorization: dict[str, Any],
) -> dict[str, Any]:
    """Stage initial version-0 state and immutable provenance in one outer transaction."""
    normalized, failure = validate_canary_authorization_for_provisioning(canary_authorization)
    if failure is not None:
        return failure
    assert normalized is not None

    params = {
        **normalized,
        "evidence": json.dumps(normalized["evidence"], sort_keys=True, separators=(",", ":")),
    }
    result = await session.execute(_INSERT_STATE, params)
    row = result.mappings().first()
    if row is None:
        return _blocked(
            ["authorization_id_already_provisioned"],
            authorization_id=normalized["authorization_id"],
            next_step="DO_NOT_REPROVISION_OR_RESET_SINGLE_USE_STATE",
        )

    # No internal commit: if this immutable audit INSERT fails, the outer request
    # transaction rolls the state INSERT back too.
    await session.execute(_INSERT_AUDIT, params)
    return {
        "status": "OBSERVED",
        "provisioning_result": "TRANSACTION_STAGED",
        "authorization_state_staged": True,
        "provision_audit_staged": True,
        "durable_commit_managed_by_request_session": True,
        "authorization_id": normalized["authorization_id"],
        "policy_version": normalized["policy_version"],
        "authorized_at": normalized["authorized_at"],
        "authorized_notional_usd": normalized["authorized_notional_usd"],
        "max_loss_usd": normalized["max_loss_usd"],
        "consumed": False,
        "use_count": 0,
        "version": 0,
        "authorization_evidence": deepcopy(normalized["evidence"]),
        "next_step": "RUNTIME_PREORDER_RECHECK_MAY_READ_THIS_SINGLE_USE_STATE",
        **AUTHORITY,
    }
