"""Evidence-only readiness and threshold proposal for a first paper policy.

This module never provisions or activates a policy. It converts an already
cutoff-safe calibrated empirical distribution into a reviewable threshold
proposal only when caller-supplied sufficiency criteria are met. Insufficient,
malformed, or non-calibrated evidence remains UNKNOWN.

The proposal uses Wilson 95% binomial bounds: lower bounds for desirable events
(RUNNER and non-negative market-cap change) and an upper bound for FADE. These
are descriptive conservative bounds over observed evidence, not trading advice.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from stinky_api.prospective_paper_intake_producer import (
    PRODUCER_VERSION,
    cohort_signature,
    _probability_as_of,
)
from stinky_api.market_path_patterns import canonical_pattern_hash

AUTHORITY = {
    "interpretation": "EVIDENCE_ONLY_PAPER_POLICY_THRESHOLD_PROPOSAL",
    "paper_only": True,
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "automatic_activation": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
    "wallet_mutated": False,
}
_Z_95 = 1.959963984540054


def _unknown(missing: list[str], **extra: Any) -> dict[str, Any]:
    return {"status": "UNKNOWN", "missing": list(dict.fromkeys(missing)), **extra, **AUTHORITY}


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _prob(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and 0.0 <= n <= 1.0 else None


def wilson_interval(successes: int, total: int) -> tuple[float, float] | None:
    """Two-sided 95% Wilson score interval for a binomial proportion."""
    if total <= 0 or successes < 0 or successes > total:
        return None
    p = successes / total
    z2 = _Z_95 * _Z_95
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    margin = (_Z_95 / denom) * math.sqrt((p * (1.0 - p) / total) + z2 / (4.0 * total * total))
    return max(0.0, center - margin), min(1.0, center + margin)


def derive_threshold_proposal(
    probability_distribution: dict[str, Any],
    *,
    min_closed_outcomes: int,
    min_market_cap_samples: int,
    min_outcome_classes: int,
) -> dict[str, Any]:
    """Derive conservative empirical thresholds; never invent missing evidence."""
    required_closed = _positive_int(min_closed_outcomes)
    required_market = _positive_int(min_market_cap_samples)
    required_classes = _positive_int(min_outcome_classes)
    if required_closed is None or required_market is None or required_classes is None or required_classes > 3:
        return _unknown(["valid_explicit_sufficiency_criteria"])
    criteria = {
        "min_closed_outcomes": required_closed,
        "min_market_cap_samples": required_market,
        "min_outcome_classes": required_classes,
    }
    if not isinstance(probability_distribution, dict) or probability_distribution.get("status") != "CALIBRATED_EMPIRICAL":
        return _unknown(["calibrated_empirical_probability_distribution"], criteria=criteria)
    if probability_distribution.get("future_evidence_used_in_t0_decisions") is not False:
        return _unknown(["temporal_safe_probability_distribution"], criteria=criteria)

    outcome = probability_distribution.get("outcome_distribution")
    if not isinstance(outcome, dict):
        return _unknown(["outcome_distribution"], criteria=criteria)
    total = _positive_int(outcome.get("sample_count"))
    counts = outcome.get("counts") if isinstance(outcome.get("counts"), dict) else {}
    runner = _positive_int(counts.get("RUNNER")) or 0
    held = _positive_int(counts.get("HELD")) or 0
    fade = _positive_int(counts.get("FADE")) or 0
    if total is None or runner + held + fade != total:
        return _unknown(["internally_consistent_closed_outcomes"], criteria=criteria)
    if total < required_closed:
        return _unknown(["sufficient_closed_outcomes"], closed_outcomes=total, criteria=criteria)
    represented = sum(1 for n in (runner, held, fade) if n > 0)
    if represented < required_classes:
        return _unknown(["sufficient_outcome_class_diversity"], closed_outcomes=total, represented_outcome_classes=represented, criteria=criteria)

    runner_ci = wilson_interval(runner, total)
    fade_ci = wilson_interval(fade, total)
    if runner_ci is None or fade_ci is None:
        return _unknown(["outcome_confidence_bounds"], criteria=criteria)

    market = probability_distribution.get("market_cap_change_distributions")
    horizons = probability_distribution.get("calibrated_horizons")
    if not isinstance(market, dict) or not isinstance(horizons, list):
        return _unknown(["calibrated_market_cap_horizon"], criteria=criteria)
    eligible: list[tuple[int, str, dict[str, Any]]] = []
    for horizon in horizons:
        record = market.get(horizon)
        if not isinstance(record, dict) or record.get("status") != "CALIBRATED_EMPIRICAL":
            continue
        samples = _positive_int(record.get("sample_count"))
        probs = record.get("probabilities") if isinstance(record.get("probabilities"), dict) else {}
        p_up0 = _prob(probs.get("UP_0_TO_100"))
        p_up100 = _prob(probs.get("UP_GTE_100"))
        if samples is None or samples < required_market or p_up0 is None or p_up100 is None:
            continue
        nonnegative_successes = round((p_up0 + p_up100) * samples)
        if 0 <= nonnegative_successes <= samples:
            eligible.append((samples, str(horizon), {"record": record, "successes": nonnegative_successes}))
    if not eligible:
        return _unknown(["sufficient_calibrated_market_cap_samples"], closed_outcomes=total, criteria=criteria)
    eligible.sort(key=lambda item: (-item[0], item[1]))
    market_samples, horizon, selected = eligible[0]
    market_ci = wilson_interval(selected["successes"], market_samples)
    if market_ci is None:
        return _unknown(["market_cap_confidence_bounds"], criteria=criteria)

    return {
        "status": "READY_FOR_OPERATOR_REVIEW",
        "method": "wilson_95pct_conservative_empirical_bounds",
        "pattern_hash": probability_distribution.get("pattern_hash"),
        "evidence": {
            "closed_outcomes": total,
            "outcome_counts": {"RUNNER": runner, "HELD": held, "FADE": fade},
            "represented_outcome_classes": represented,
            "market_cap_horizon": horizon,
            "market_cap_samples": market_samples,
        },
        "threshold_proposal": {
            "horizon": horizon,
            "min_runner_probability": runner_ci[0],
            "max_fade_probability": fade_ci[1],
            "min_nonnegative_market_cap_probability": market_ci[0],
        },
        "point_estimates": {
            "runner_probability": runner / total,
            "fade_probability": fade / total,
            "nonnegative_market_cap_probability": selected["successes"] / market_samples,
        },
        "criteria": criteria,
        "missing": [],
        "requires_operator_supplied_execution_assumptions": True,
        "requires_explicit_registry_provisioning": True,
        **AUTHORITY,
    }


async def assess_current_prospective_policy_readiness(
    session,
    *,
    min_closed_outcomes: int,
    min_market_cap_samples: int,
    min_outcome_classes: int,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Assess only the current prospective cohort; no pre-epoch backfill."""
    cutoff = as_of or datetime.now(timezone.utc)
    pattern_hash = canonical_pattern_hash(cohort_signature(str(__import__("stinky_api.prospective_paper_intake_producer", fromlist=["FILTER_VERSION"]).FILTER_VERSION or "UNKNOWN")))
    state = (await session.execute(text("SELECT prospective_started_at FROM paper_intake_producer_state WHERE singleton=TRUE"))).first()
    if not state:
        return _unknown(["prospective_epoch"], as_of=cutoff.isoformat())
    counts = (await session.execute(text("""
        SELECT canonical_outcome, count(*)
        FROM paper_prospective_candidate
        WHERE producer_version=:version AND cohort_pattern_hash=:pattern_hash
          AND decided_at >= :started AND decided_at <= :cutoff
          AND outcome_observed_at IS NOT NULL AND outcome_observed_at <= :cutoff
          AND canonical_outcome IN ('RUNNER','HELD','FADE')
        GROUP BY canonical_outcome
    """), {"version": PRODUCER_VERSION, "pattern_hash": pattern_hash, "started": state[0], "cutoff": cutoff})).all()
    observed = {str(label): int(count) for label, count in counts}
    closed = sum(observed.values())
    if closed < (_positive_int(min_closed_outcomes) or 10**18):
        return _unknown(
            ["sufficient_closed_outcomes"], as_of=cutoff.isoformat(), prospective_started_at=state[0],
            closed_outcomes=closed, outcome_counts=observed,
            criteria={"min_closed_outcomes": min_closed_outcomes, "min_market_cap_samples": min_market_cap_samples, "min_outcome_classes": min_outcome_classes},
        )
    probability = await _probability_as_of(session, pattern_hash, cutoff)
    result = derive_threshold_proposal(
        probability,
        min_closed_outcomes=min_closed_outcomes,
        min_market_cap_samples=min_market_cap_samples,
        min_outcome_classes=min_outcome_classes,
    )
    return {
        **result,
        "as_of": cutoff.isoformat(),
        "prospective_started_at": state[0],
        "prospective_closed_outcomes": closed,
        "prospective_outcome_counts": observed,
    }
