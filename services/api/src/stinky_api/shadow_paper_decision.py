"""Shadow/paper decision bridge over calibrated empirical probabilities.

This module never places orders and never grants live trading authority. It only
turns already-calibrated empirical evidence into an explicit counterfactual
paper action under a caller-supplied policy. Genesis does not invent thresholds.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

AUTHORITY = {
    "interpretation": "SHADOW_PAPER_DECISION_ONLY",
    "paper_only": True,
    "live_execution": False,
    "trading_authority": False,
    "predictive_authority": False,
    "trade_signal": False,
    "recommendation": False,
}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _prob(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0.0 <= number <= 1.0 else None


def _unknown(mint: str | None, missing: list[str], **extra: Any) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "mint": mint,
        "missing": list(dict.fromkeys(missing)),
        **extra,
        **AUTHORITY,
    }


def build_shadow_paper_decision(
    probability_distribution: dict[str, Any],
    decision_context: dict[str, Any],
    paper_policy: dict[str, Any],
) -> dict[str, Any]:
    """Build one frozen paper-only WOULD_ENTER/WOULD_SKIP decision.

    Thresholds are required inputs. Missing or unsafe evidence fails closed to
    UNKNOWN rather than manufacturing a decision.
    """
    mint = str(decision_context.get("mint") or "").strip()
    decided_at = _dt(decision_context.get("decided_at"))
    evidence_snapshot = decision_context.get("evidence_snapshot")
    missing: list[str] = []

    if not mint:
        missing.append("mint")
    if decided_at is None:
        missing.append("decided_at")
    if not isinstance(evidence_snapshot, dict) or not evidence_snapshot:
        missing.append("frozen_t0_evidence_snapshot")
    if decision_context.get("temporal_cutoff_enforced") is not True:
        missing.append("temporal_cutoff_enforced")
    if decision_context.get("future_evidence_used") is not False:
        missing.append("future_evidence_excluded")

    if not isinstance(probability_distribution, dict) or probability_distribution.get("status") != "CALIBRATED_EMPIRICAL":
        missing.append("calibrated_empirical_probability_distribution")
    else:
        for authority_key in ("live_execution", "trading_authority", "trade_signal"):
            if probability_distribution.get(authority_key) is not False:
                missing.append("non_authoritative_probability_input")
                break

    policy_version = str(paper_policy.get("policy_version") or "").strip()
    horizon = str(paper_policy.get("horizon") or "").strip()
    min_runner = _prob(paper_policy.get("min_runner_probability"))
    max_fade = _prob(paper_policy.get("max_fade_probability"))
    min_upside = _prob(paper_policy.get("min_nonnegative_market_cap_probability"))
    if not policy_version:
        missing.append("paper_policy_version")
    if not horizon:
        missing.append("paper_policy_horizon")
    if min_runner is None:
        missing.append("min_runner_probability")
    if max_fade is None:
        missing.append("max_fade_probability")
    if min_upside is None:
        missing.append("min_nonnegative_market_cap_probability")

    outcome_probs: dict[str, Any] = {}
    market_cap_probs: dict[str, Any] = {}
    if isinstance(probability_distribution, dict):
        outcome_block = probability_distribution.get("outcome_distribution")
        if isinstance(outcome_block, dict):
            outcome_probs = outcome_block.get("probabilities") if isinstance(outcome_block.get("probabilities"), dict) else {}
        market_block = probability_distribution.get("market_cap_change_distributions")
        if isinstance(market_block, dict):
            horizon_block = market_block.get(horizon)
            if isinstance(horizon_block, dict) and horizon_block.get("status") == "CALIBRATED_EMPIRICAL":
                market_cap_probs = horizon_block.get("probabilities") if isinstance(horizon_block.get("probabilities"), dict) else {}

    runner_probability = _prob(outcome_probs.get("RUNNER"))
    fade_probability = _prob(outcome_probs.get("FADE"))
    up_0_100 = _prob(market_cap_probs.get("UP_0_TO_100"))
    up_gte_100 = _prob(market_cap_probs.get("UP_GTE_100"))
    if runner_probability is None:
        missing.append("runner_probability")
    if fade_probability is None:
        missing.append("fade_probability")
    if up_0_100 is None or up_gte_100 is None:
        missing.append("calibrated_market_cap_probability_horizon")

    calibrated_horizons = probability_distribution.get("calibrated_horizons") if isinstance(probability_distribution, dict) else []
    if horizon and horizon not in (calibrated_horizons or []):
        missing.append("policy_horizon_not_calibrated")

    if missing:
        return _unknown(mint or None, missing, policy_version=policy_version or None, horizon=horizon or None)

    assert decided_at is not None
    assert min_runner is not None and max_fade is not None and min_upside is not None
    assert runner_probability is not None and fade_probability is not None
    assert up_0_100 is not None and up_gte_100 is not None

    nonnegative_market_cap_probability = up_0_100 + up_gte_100
    checks = {
        "runner_probability": {
            "value": runner_probability,
            "operator": ">=",
            "threshold": min_runner,
            "passed": runner_probability >= min_runner,
        },
        "fade_probability": {
            "value": fade_probability,
            "operator": "<=",
            "threshold": max_fade,
            "passed": fade_probability <= max_fade,
        },
        "nonnegative_market_cap_probability": {
            "value": nonnegative_market_cap_probability,
            "operator": ">=",
            "threshold": min_upside,
            "passed": nonnegative_market_cap_probability >= min_upside,
        },
    }
    all_passed = all(check["passed"] for check in checks.values())
    action = "WOULD_ENTER" if all_passed else "WOULD_SKIP"

    return {
        "status": "SHADOW_DECISION",
        "mint": mint,
        "action": action,
        "decided_at": decided_at.isoformat(),
        "policy_version": policy_version,
        "horizon": horizon,
        "checks": checks,
        "reason_codes": [name for name, check in checks.items() if not check["passed"]],
        "evidence_snapshot": deepcopy(evidence_snapshot),
        "probability_snapshot": {
            "pattern_hash": probability_distribution.get("pattern_hash"),
            "runner_probability": runner_probability,
            "held_probability": _prob(outcome_probs.get("HELD")),
            "fade_probability": fade_probability,
            "nonnegative_market_cap_probability": nonnegative_market_cap_probability,
            "horizon": horizon,
        },
        "temporal_cutoff_enforced": True,
        "future_evidence_used": False,
        "counterfactual_journal_compatible": True,
        **AUTHORITY,
    }
