"""Temporal-safe bridge from #159 paper execution realism to #160 walk-forward validation.

The producer and consumer intentionally keep separate schemas. This adapter maps only
validated SIMULATED_CLOSED records into the canonical CLOSED evidence shape expected
by walk-forward validation. It never invents chronology: closed_at must be supplied
by the caller from contemporaneous paper-execution evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from stinky_api.paper_policy_identity import validated_policy_identity

AUTHORITY = {
    "interpretation": "PAPER_WALK_FORWARD_SCHEMA_ADAPTER_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "paper_only": True,
    "release_evidence_only": True,
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "adapted_for_walk_forward": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def adapt_simulated_execution_for_walk_forward(
    simulated_execution: dict[str, Any],
    *,
    closed_at: str,
    mint: str | None = None,
) -> dict[str, Any]:
    """Map one genuine #159 closed simulation into #160's closed-record schema."""
    if not isinstance(simulated_execution, dict):
        return _unknown(["simulated_execution"])

    missing: list[str] = []
    if simulated_execution.get("status") != "SIMULATED_CLOSED":
        missing.append("simulated_closed_execution")
    if simulated_execution.get("paper_only") is not True:
        missing.append("paper_only_execution")
    if simulated_execution.get("round_trip_costs_included") is not True:
        missing.append("round_trip_costs_included")
    if simulated_execution.get("assumptions_caller_supplied") is not True:
        missing.append("caller_supplied_execution_assumptions")
    if any(simulated_execution.get(key) is not False for key in (
        "live_execution", "trading_authority", "trade_signal",
        "rpc_contacted", "transaction_signed", "order_submitted",
    )):
        missing.append("non_executing_paper_record")
    if any(simulated_execution.get(key, False) is not False for key in (
        "wallet_mutated", "recommendation_authority", "automatic_activation",
    )):
        missing.append("non_executing_paper_record")

    identity = validated_policy_identity(simulated_execution.get("policy_identity"))
    if identity is None:
        missing.append("policy_identity")
        identity = {}
    policy_version = str(identity.get("policy_version") or "").strip()
    policy_sha256 = str(identity.get("policy_sha256") or "").strip()
    provenance = identity.get("provenance")
    if not policy_version:
        missing.append("policy_version")
    if len(policy_sha256) != 64:
        missing.append("policy_sha256")
    if not isinstance(provenance, dict) or type(provenance.get("evidence_backed")) is not bool:
        missing.append("policy_provenance")

    close_time = _dt(closed_at)
    net_return = _number(simulated_execution.get("net_return_pct"))
    net_pnl = _number(simulated_execution.get("net_pnl_usd"))
    notional = _number(simulated_execution.get("notional_usd"))
    if close_time is None:
        missing.append("caller_supplied_closed_at")
    if net_return is None:
        missing.append("net_return_pct")
    if net_pnl is None:
        missing.append("net_pnl_usd")
    if notional is None or notional <= 0:
        missing.append("positive_notional_usd")

    if missing:
        return _unknown(missing)

    assert close_time is not None and net_return is not None and net_pnl is not None and notional is not None
    return {
        "status": "CLOSED",
        "adapted_for_walk_forward": True,
        "closed_at": close_time.isoformat(),
        "net_return_pct": net_return,
        "net_pnl": net_pnl,
        "paper_notional": notional,
        "mint": str(mint).strip() if mint is not None and str(mint).strip() else None,
        "policy_identity": {
            "policy_version": policy_version,
            "policy_sha256": policy_sha256,
            "provenance": deepcopy(provenance),
        },
        "rpc_contacted": False,
        "transaction_signed": False,
        "order_submitted": False,
        "source_status": "SIMULATED_CLOSED",
        "source_execution": deepcopy(simulated_execution),
        "chronology_caller_supplied": True,
        **AUTHORITY,
    }
