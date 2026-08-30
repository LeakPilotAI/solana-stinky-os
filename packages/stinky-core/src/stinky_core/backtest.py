"""Backtest population builder.

Live eligibility and historical backtest eligibility MUST use the same
`evaluate_market` implementation. Duplicate mints are one candidate.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from stinky_core.admission import (
    ALERT_MIN_MEANINGFUL_BUYERS,
    ALERT_MIN_SCORE,
    FILTER_VERSION,
    FilterConfig,
    FilterDecision,
    ReasonCode,
    can_alert,
    evaluate_market,
)
from stinky_core.identity import UniqueMintIndex
from stinky_core.outcomes import label_outcome


def backtest_candidates(
    markets: Iterable[Mapping[str, Any]],
    *,
    config: FilterConfig | None = None,
    min_score: float = ALERT_MIN_SCORE,
    min_meaningful_buyers: int = ALERT_MIN_MEANINGFUL_BUYERS,
) -> dict[str, Any]:
    """Deduplicate by mint → canonical eligibility → alert gate → outcome.

    Never reports duplicate-mint rows as independent opportunities.
    """
    idx = UniqueMintIndex()
    unique: list[Mapping[str, Any]] = []
    dropped_dupes = 0
    for m in markets:
        mint = m.get("mint") if isinstance(m, Mapping) else None
        if idx.add(str(mint) if mint else None):
            unique.append(m)
        else:
            dropped_dupes += 1

    evaluated: list[dict[str, Any]] = []
    eligible_n = 0
    alerted_n = 0
    runners = 0
    held = 0
    fades = 0
    unknown = 0
    fee_verified = 0
    fee_unknown = 0
    fee_rejected = 0
    fee_passed = 0

    for m in unique:
        decision: FilterDecision = evaluate_market(m, config=config)
        score = m.get("stinky_score") if "stinky_score" in m else m.get("score")
        mb = m.get("meaningful_buyer_count") or m.get("meaningful_buyers")
        alert_ok, alert_reason = can_alert(
            decision,
            score=score,
            meaningful_buyers=mb,
            min_score=min_score,
            min_meaningful_buyers=min_meaningful_buyers,
        )
        outcome = label_outcome(
            peak_multiple=m.get("peak_multiple"),
            peak_volume=m.get("peak_volume") or m.get("peak_volume_m5_usd"),
            entry_volume=m.get("volume_usd") or m.get("volume_m5_usd"),
            drawdown=m.get("drawdown"),
            time_to_peak=m.get("time_to_peak"),
            time_to_drawdown=m.get("time_to_drawdown"),
            observation_window=m.get("observation_window"),
            observation_complete=bool(m.get("observation_complete")),
        )
        if decision.eligible:
            eligible_n += 1
        fee_codes = set(decision.reason_codes)
        fee_ok = any(f.get("name") == "global_fees" and f.get("passed") for f in decision.passed_filters)
        if ReasonCode.FEES_UNKNOWN in fee_codes:
            fee_unknown += 1
            fee_rejected += 1
        elif ReasonCode.FEES_BELOW_MIN in fee_codes:
            fee_rejected += 1
            if decision.metrics.get("fees_verified") is True:
                fee_verified += 1
        elif fee_ok:
            fee_passed += 1
            fee_verified += 1
        elif decision.metrics.get("fees_verified") is True:
            fee_verified += 1
        else:
            fee_unknown += 1
            fee_rejected += 1
        if alert_ok:
            alerted_n += 1
            if outcome.label == "RUNNER":
                runners += 1
            elif outcome.label == "HELD":
                held += 1
            elif outcome.label == "FADE":
                fades += 1
            else:
                unknown += 1
        evaluated.append(
            {
                "mint": decision.mint,
                "eligible": decision.eligible,
                "rejection_reason": decision.rejection_reason,
                "reason_codes": decision.reason_codes,
                "alert_ok": alert_ok,
                "alert_reason": alert_reason,
                "outcome": outcome.to_dict(),
                "filter_version": decision.filter_version,
            }
        )

    precision = (runners / alerted_n) if alerted_n else None
    total = len(unique)
    return {
        "engine": "stinky-backtest-v1.0.0",
        "filter_version": FILTER_VERSION,
        "input": len(unique) + dropped_dupes,
        "unique_mints": len(unique),
        "duplicate_mints_dropped": dropped_dupes,
        "total_candidates": total,
        "fee_verified": fee_verified,
        "fee_unknown": fee_unknown,
        "fee_rejected": fee_rejected,
        "fee_passed": fee_passed,
        "fee_verified_rate": (fee_verified / total) if total else None,
        "eligible": eligible_n,
        "final_candidates": eligible_n,
        "alerted": alerted_n,
        "runners": runners,
        "held": held,
        "fades": fades,
        "unknown": unknown,
        "precision_runner": precision,
        "items": evaluated,
    }
