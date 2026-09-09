"""Simulation-only execution realism for shadow paper decisions.

This module converts a frozen WOULD_ENTER shadow decision into a hypothetical
paper fill using explicit caller-supplied assumptions. It never submits orders,
contacts an RPC, signs transactions, or grants trading/live authority.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

AUTHORITY = {
    "interpretation": "SIMULATED_PAPER_EXECUTION_ONLY",
    "predictive_authority": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "live_execution": False,
    "paper_only": True,
    "evidence_only": True,
}

_REQUIRED_ASSUMPTIONS = (
    "entry_slippage_bps",
    "exit_slippage_bps",
    "entry_fee_bps",
    "exit_fee_bps",
    "latency_ms",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def simulate_paper_execution(
    shadow_decision: dict[str, Any],
    assumptions: dict[str, Any],
    *,
    reference_entry_price: float,
    notional_usd: float,
    reference_exit_price: float | None = None,
) -> dict[str, Any]:
    """Simulate a paper fill from explicit assumptions and reference prices."""
    missing: list[str] = []

    if not isinstance(shadow_decision, dict) or shadow_decision.get("status") != "OBSERVED":
        missing.append("observed_shadow_decision")
    elif shadow_decision.get("shadow_action") != "WOULD_ENTER":
        missing.append("would_enter_shadow_action")

    if isinstance(shadow_decision, dict):
        for unsafe in ("trading_authority", "trade_signal", "live_execution"):
            if shadow_decision.get(unsafe) is not False:
                missing.append(f"shadow_{unsafe}_disabled")
        if shadow_decision.get("paper_only") is not True:
            missing.append("shadow_paper_only")
        snapshot = shadow_decision.get("t0_snapshot")
        if not isinstance(snapshot, dict):
            missing.append("frozen_t0_snapshot")
        else:
            if snapshot.get("temporal_cutoff_enforced") is not True:
                missing.append("t0_temporal_cutoff")
            if snapshot.get("future_evidence_used") is not False:
                missing.append("t0_future_evidence_excluded")

    if not isinstance(assumptions, dict):
        assumptions = {}
    parsed: dict[str, float] = {}
    for key in _REQUIRED_ASSUMPTIONS:
        value = _number(assumptions.get(key))
        if value is None:
            missing.append(key)
            continue
        if value < 0:
            missing.append(f"nonnegative_{key}")
            continue
        parsed[key] = value

    entry = _number(reference_entry_price)
    notional = _number(notional_usd)
    exit_price = _number(reference_exit_price) if reference_exit_price is not None else None
    if entry is None or entry <= 0:
        missing.append("positive_reference_entry_price")
    if notional is None or notional <= 0:
        missing.append("positive_notional_usd")
    if reference_exit_price is not None and (exit_price is None or exit_price <= 0):
        missing.append("positive_reference_exit_price")

    if missing:
        return _unknown(missing)

    entry_slippage = parsed["entry_slippage_bps"] / 10_000.0
    exit_slippage = parsed["exit_slippage_bps"] / 10_000.0
    entry_fee_rate = parsed["entry_fee_bps"] / 10_000.0
    exit_fee_rate = parsed["exit_fee_bps"] / 10_000.0

    simulated_entry_price = entry * (1.0 + entry_slippage)
    entry_fee_usd = notional * entry_fee_rate
    deployable_usd = notional - entry_fee_usd
    if deployable_usd <= 0:
        return _unknown(["positive_notional_after_entry_fee"])
    simulated_quantity = deployable_usd / simulated_entry_price

    result: dict[str, Any] = {
        "status": "SIMULATED_OPEN" if exit_price is None else "SIMULATED_CLOSED",
        "shadow_decision": deepcopy(shadow_decision),
        "assumptions": deepcopy(parsed),
        "reference_entry_price": entry,
        "simulated_entry_price": simulated_entry_price,
        "notional_usd": notional,
        "entry_fee_usd": entry_fee_usd,
        "simulated_quantity": simulated_quantity,
        "latency_ms": parsed["latency_ms"],
        "assumptions_caller_supplied": True,
        "market_impact_inferred": False,
        "rpc_contacted": False,
        "transaction_signed": False,
        "order_submitted": False,
        "missing": [],
        **AUTHORITY,
    }

    if exit_price is not None:
        simulated_exit_price = exit_price * (1.0 - exit_slippage)
        gross_exit_usd = simulated_quantity * simulated_exit_price
        exit_fee_usd = gross_exit_usd * exit_fee_rate
        net_exit_usd = gross_exit_usd - exit_fee_usd
        net_pnl_usd = net_exit_usd - notional
        result.update({
            "reference_exit_price": exit_price,
            "simulated_exit_price": simulated_exit_price,
            "gross_exit_usd": gross_exit_usd,
            "exit_fee_usd": exit_fee_usd,
            "net_exit_usd": net_exit_usd,
            "net_pnl_usd": net_pnl_usd,
            "net_return_pct": (net_pnl_usd / notional) * 100.0,
            "round_trip_costs_included": True,
        })

    return result
