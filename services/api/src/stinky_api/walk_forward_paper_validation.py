"""Chronological paper-validation evidence for Project Genesis.

This module evaluates already-closed simulation-only paper executions. It is a
research/release-evidence surface only: passing it never grants live execution
or trading authority.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any
from stinky_api.paper_policy_identity import validated_policy_identity

# Bump when validation, ordering, metrics, or release-result semantics change.
EVALUATOR_VERSION = "walk-forward-paper-v1"

AUTHORITY = {
    "interpretation": "WALK_FORWARD_PAPER_VALIDATION_ONLY",
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "release_evidence_only": True,
    "paper_only": True,
}

_REQUIRED_POLICY = (
    "minimum_closed_trades",
    "minimum_mean_net_return_pct",
    "maximum_drawdown_pct",
    "minimum_win_rate",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "release_gate_passed": False,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def evaluate_walk_forward_paper(
    executions: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate chronological, closed paper executions after modeled costs.

    Policy thresholds are caller supplied. Genesis does not invent a minimum
    sample size, expectancy target, drawdown ceiling, or win-rate target.
    """
    if not isinstance(policy, dict) or not isinstance(executions, list):
        return _unknown(["explicit_policy_and_execution_records"])
    missing = [key for key in _REQUIRED_POLICY if key not in policy]
    minimum_closed = policy.get("minimum_closed_trades")
    mean_floor = _number(policy.get("minimum_mean_net_return_pct"))
    drawdown_ceiling = _number(policy.get("maximum_drawdown_pct"))
    win_rate_floor = _number(policy.get("minimum_win_rate"))
    if not isinstance(minimum_closed, int) or isinstance(minimum_closed, bool) or minimum_closed <= 0:
        missing.append("valid_minimum_closed_trades")
    if mean_floor is None:
        missing.append("valid_minimum_mean_net_return_pct")
    if drawdown_ceiling is None or drawdown_ceiling < 0:
        missing.append("valid_maximum_drawdown_pct")
    if win_rate_floor is None or not 0 <= win_rate_floor <= 1:
        missing.append("valid_minimum_win_rate")
    if missing:
        return _unknown(missing)

    rows: list[dict[str, Any]] = []
    unsafe: list[int] = []
    cohort_identity: dict[str, Any] | None = None
    for index, execution in enumerate(executions):
        if not isinstance(execution, dict):
            unsafe.append(index)
            continue
        if execution.get("status") != "CLOSED":
            continue
        if execution.get("paper_only") is not True:
            unsafe.append(index)
            continue
        if any(execution.get(key) is not False for key in ("live_execution", "trading_authority", "trade_signal")):
            unsafe.append(index)
            continue
        if execution.get("rpc_contacted") is not False or execution.get("transaction_signed") is not False or execution.get("order_submitted") is not False:
            unsafe.append(index)
            continue
        normalized_identity = validated_policy_identity(execution.get("policy_identity"))
        if normalized_identity is None:
            unsafe.append(index)
            continue
        if cohort_identity is None:
            cohort_identity = normalized_identity
        elif normalized_identity != cohort_identity:
            return _unknown(["single_immutable_policy_cohort"], mixed_policy_record_index=index, expected_policy_identity=cohort_identity, observed_policy_identity=normalized_identity)
        closed_at = _dt(execution.get("closed_at") or execution.get("exit_time"))
        net_return = _number(execution.get("net_return_pct"))
        net_pnl = _number(execution.get("net_pnl"))
        if closed_at is None or net_return is None or net_pnl is None:
            unsafe.append(index)
            continue
        notional = _number(execution.get("paper_notional"))
        if notional is None or notional <= 0:
            return _unknown(["paper_notional_for_drawdown_normalization"], unsafe_record_indexes=[index])
        rows.append({
            "closed_at": closed_at,
            "net_return_pct": net_return,
            "net_pnl": net_pnl,
            "mint": execution.get("mint"),
            "policy_identity": normalized_identity,
            "paper_notional": notional,
            "intake_id": execution.get("intake_id"),
        })

    if unsafe:
        return _unknown(["safe_closed_paper_execution_records"], unsafe_record_indexes=unsafe)
    if len(rows) < minimum_closed:
        return _unknown(
            ["minimum_closed_paper_sample"],
            closed_trade_count=len(rows),
            required_closed_trade_count=minimum_closed,
            evaluated_policy_identity=deepcopy(cohort_identity),
        )

    rows.sort(key=lambda row: row["closed_at"])
    returns = [row["net_return_pct"] for row in rows]
    pnls = [row["net_pnl"] for row in rows]
    mean_return = sum(returns) / len(returns)
    total_pnl = sum(pnls)
    wins = sum(value > 0 for value in pnls)
    win_rate = wins / len(pnls)

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    gross_deployed = sum(row["paper_notional"] for row in rows)
    max_drawdown_pct = (max_drawdown / gross_deployed * 100.0) if gross_deployed > 0 else None
    if max_drawdown_pct is None:
        return _unknown(["paper_notional_for_drawdown_normalization"])
    if not all(isfinite(value) for value in (mean_return, total_pnl, gross_deployed, max_drawdown, max_drawdown_pct)):
        return _unknown(["finite_aggregate_metrics"])

    checks = {
        "minimum_closed_trades": len(rows) >= minimum_closed,
        "mean_net_return_after_costs": mean_return >= mean_floor,
        "maximum_drawdown": max_drawdown_pct <= drawdown_ceiling,
        "minimum_win_rate": win_rate >= win_rate_floor,
    }
    passed = all(checks.values())
    return {
        "status": "OBSERVED",
        "release_gate_passed": passed,
        "release_gate_result": "PASS" if passed else "FAIL",
        "closed_trade_count": len(rows),
        "chronological": True,
        "mean_net_return_pct_after_costs": mean_return,
        "total_net_pnl_after_costs": total_pnl,
        "win_rate": win_rate,
        "maximum_drawdown_pct_of_deployed_notional": max_drawdown_pct,
        "checks": checks,
        "policy": deepcopy(policy),
        "evaluated_policy_identity": deepcopy(cohort_identity),
        "mixed_policy_cohorts": False,
        "evaluated_records": [
            {**row, "closed_at": row["closed_at"].isoformat()} for row in rows
        ],
        "live_canary_unlocked": False,
        **AUTHORITY,
    }
