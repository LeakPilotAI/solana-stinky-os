"""Non-broadcasting live-executor boundary contract for Project Genesis.

This module defines the narrow contract that a future live executor would have to
satisfy. It never contacts an RPC, signs a transaction, submits an order, reads a
private key, or mutates a wallet. PASS means only that a caller has supplied a
coherent, still-safe execution intent that may advance to a separate failure-mode
review/simulation layer.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any

MAX_CANARY_NOTIONAL_USD = 20.0
ALLOWED_SUBMISSION_STATES = (
    "NOT_SENT",
    "SUBMISSION_UNKNOWN",
    "SUBMITTED",
    "CONFIRMED",
    "FAILED",
)

AUTHORITY = {
    "interpretation": "NON_BROADCASTING_LIVE_EXECUTOR_BOUNDARY_CONTRACT_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "rpc_contact_allowed": False,
    "transaction_signing_allowed": False,
    "order_submission_allowed": False,
    "wallet_mutation_allowed": False,
    "automatic_execution": False,
    "automatic_retry_allowed": False,
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "executor_boundary_result": "UNKNOWN",
        "executor_contract_ready": False,
        "submission_state": "NOT_SENT",
        "safe_to_retry": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def _blocked(blockers: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "OBSERVED",
        "executor_boundary_result": "BLOCKED",
        "executor_contract_ready": False,
        "submission_state": "NOT_SENT",
        "safe_to_retry": False,
        "blockers": list(dict.fromkeys(blockers)),
        **extra,
        **AUTHORITY,
    }


def _claims_external_authority(value: dict[str, Any]) -> bool:
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
            "rpc_contacted",
            "transaction_signed",
            "order_submitted",
            "wallet_mutated",
            "wallet_mutation_allowed",
            "automatic_execution",
            "automatic_retry_allowed",
        )
    )


def evaluate_live_executor_boundary_contract(
    final_readiness: dict[str, Any],
    authorization_state: dict[str, Any],
    runtime: dict[str, Any],
    quote: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Validate a future live-executor intent without performing any execution.

    The contract is fail closed. It requires a final-readiness PASS, an unconsumed
    single-use authorization, a fresh quote, immediate kill-switch/isolation checks,
    exact policy/authorization identity, explicit idempotency, and zero evidence of
    an earlier/uncertain submission. Unknown submission outcomes are never safe to
    retry automatically.
    """
    inputs = {
        "final_readiness": final_readiness,
        "authorization_state": authorization_state,
        "runtime": runtime,
        "quote": quote,
        "request": request,
    }
    malformed = [name for name, value in inputs.items() if not isinstance(value, dict)]
    if malformed:
        return _unknown([f"{name}_evidence" for name in malformed])

    contaminated = [name for name, value in inputs.items() if _claims_external_authority(value)]
    if contaminated:
        return _unknown(
            ["non_authoritative_executor_boundary_evidence"],
            authority_contamination=contaminated,
        )

    missing: list[str] = []
    if final_readiness.get("status") != "OBSERVED":
        missing.append("observed_final_readiness")
    if final_readiness.get("operational_readiness_result") != "PASS":
        missing.append("passed_final_readiness")
    if final_readiness.get("eligible_for_live_executor_review") is not True:
        missing.append("live_executor_review_eligibility")
    if final_readiness.get("live_canary_unlocked") is not False:
        missing.append("final_readiness_does_not_unlock_live")

    readiness_policy = str(final_readiness.get("policy_version") or "").strip()
    readiness_auth = str(final_readiness.get("authorization_id") or "").strip()
    readiness_notional = _number(final_readiness.get("canary_notional_usd"))
    readiness_loss = _number(final_readiness.get("max_loss_usd"))
    if not readiness_policy:
        missing.append("readiness_policy_version")
    if not readiness_auth:
        missing.append("readiness_authorization_id")
    if readiness_notional is None or readiness_notional <= 0:
        missing.append("readiness_canary_notional_usd")
    if readiness_loss is None or readiness_loss <= 0:
        missing.append("readiness_max_loss_usd")

    state_auth = str(authorization_state.get("authorization_id") or "").strip()
    state_policy = str(authorization_state.get("policy_version") or "").strip()
    state_version = authorization_state.get("version")
    if not state_auth:
        missing.append("authorization_state_id")
    if not state_policy:
        missing.append("authorization_state_policy_version")
    if not isinstance(state_version, int) or isinstance(state_version, bool) or state_version < 0:
        missing.append("authorization_state_version")
    if "consumed" not in authorization_state:
        missing.append("authorization_consumed_state")
    if "use_count" not in authorization_state:
        missing.append("authorization_use_count")

    requested_notional = _number(runtime.get("requested_notional_usd"))
    realized_loss = _number(runtime.get("realized_loss_usd"))
    open_positions = runtime.get("open_positions")
    evaluated_at = _dt(runtime.get("evaluated_at"))
    for key in (
        "kill_switch_armed",
        "isolated_funds",
        "isolated_account_or_wallet",
        "no_borrowing",
        "no_leverage",
    ):
        if key not in runtime:
            missing.append(key)
    if requested_notional is None or requested_notional <= 0:
        missing.append("valid_requested_notional_usd")
    if realized_loss is None or realized_loss < 0:
        missing.append("valid_realized_loss_usd")
    if not isinstance(open_positions, int) or isinstance(open_positions, bool) or open_positions < 0:
        missing.append("valid_open_positions")
    if evaluated_at is None:
        missing.append("runtime_evaluated_at")

    quote_id = str(quote.get("quote_id") or "").strip()
    quoted_at = _dt(quote.get("quoted_at"))
    expires_at = _dt(quote.get("expires_at"))
    quote_notional = _number(quote.get("notional_usd"))
    if not quote_id:
        missing.append("quote_id")
    if quoted_at is None:
        missing.append("quote_quoted_at")
    if expires_at is None:
        missing.append("quote_expires_at")
    if quote_notional is None or quote_notional <= 0:
        missing.append("quote_notional_usd")

    request_auth = str(request.get("authorization_id") or "").strip()
    request_policy = str(request.get("policy_version") or "").strip()
    attempt_id = str(request.get("attempt_id") or "").strip()
    idempotency_key = str(request.get("idempotency_key") or "").strip()
    request_quote = str(request.get("quote_id") or "").strip()
    requested_at = _dt(request.get("requested_at"))
    prior_submission_state = str(request.get("prior_submission_state") or "").strip()
    if not request_auth:
        missing.append("request_authorization_id")
    if not request_policy:
        missing.append("request_policy_version")
    if not attempt_id:
        missing.append("attempt_id")
    if not idempotency_key:
        missing.append("idempotency_key")
    if not request_quote:
        missing.append("request_quote_id")
    if requested_at is None:
        missing.append("request_requested_at")
    if prior_submission_state not in ALLOWED_SUBMISSION_STATES:
        missing.append("valid_prior_submission_state")

    if missing:
        return _unknown(missing, authorization_id=readiness_auth or request_auth or None)

    assert requested_notional is not None
    assert realized_loss is not None
    assert readiness_notional is not None
    assert readiness_loss is not None
    assert quote_notional is not None
    assert evaluated_at is not None and quoted_at is not None and expires_at is not None and requested_at is not None

    blockers: list[str] = []
    if not (readiness_policy == state_policy == request_policy):
        blockers.append("policy_version_mismatch")
    if not (readiness_auth == state_auth == request_auth):
        blockers.append("authorization_id_mismatch")
    if authorization_state.get("consumed") is not False or authorization_state.get("use_count") != 0:
        blockers.append("authorization_not_fresh_single_use")
    if requested_notional > MAX_CANARY_NOTIONAL_USD:
        blockers.append("requested_notional_exceeds_20_usd")
    if requested_notional > readiness_notional:
        blockers.append("requested_notional_exceeds_readiness_notional")
    if quote_notional != requested_notional:
        blockers.append("quote_notional_mismatch")
    if realized_loss >= readiness_loss:
        blockers.append("max_loss_reached")
    if open_positions != 0:
        blockers.append("existing_open_position")
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
    if request_quote != quote_id:
        blockers.append("quote_id_mismatch")
    if expires_at <= quoted_at:
        blockers.append("invalid_quote_expiry_window")
    if requested_at < quoted_at:
        blockers.append("request_precedes_quote")
    if requested_at >= expires_at or evaluated_at >= expires_at:
        blockers.append("quote_expired")
    if prior_submission_state != "NOT_SENT":
        blockers.append("prior_submission_not_proven_not_sent")

    if blockers:
        return _blocked(
            blockers,
            authorization_id=readiness_auth,
            attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            prior_submission_state=prior_submission_state,
            evidence=deepcopy(inputs),
            next_step=(
                "DO_NOT_RETRY; RECONCILE_SUBMISSION_STATE"
                if prior_submission_state == "SUBMISSION_UNKNOWN"
                else "REMAIN_NON_BROADCASTING_AND_FIX_BLOCKERS"
            ),
        )

    return {
        "status": "OBSERVED",
        "executor_boundary_result": "CONTRACT_READY",
        "executor_contract_ready": True,
        "authorization_id": readiness_auth,
        "authorization_version": state_version,
        "policy_version": readiness_policy,
        "attempt_id": attempt_id,
        "idempotency_key": idempotency_key,
        "quote_id": quote_id,
        "requested_notional_usd": requested_notional,
        "max_loss_usd": readiness_loss,
        "submission_state": "NOT_SENT",
        "safe_to_retry": False,
        "private_key_material_required": False,
        "private_key_material_logged": False,
        "intelligence_direct_executor_access": False,
        "checks": {
            "final_readiness_passed": True,
            "fresh_single_use_authorization": True,
            "policy_and_authorization_match": True,
            "hard_20_usd_cap": True,
            "loss_cap_not_reached": True,
            "no_existing_open_position": True,
            "kill_switch_armed": True,
            "isolated_no_borrowing_no_leverage": True,
            "quote_fresh_and_matching": True,
            "idempotency_present": True,
            "prior_submission_proven_not_sent": True,
        },
        "evidence": deepcopy(inputs),
        "next_step": "EXECUTOR_FAILURE_MODE_SIMULATION_REVIEW_ONLY",
        **AUTHORITY,
    }
