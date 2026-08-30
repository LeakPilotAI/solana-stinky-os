"""Backtest: Gate 1 at decision-time volume, then inspection, then outcome.

Peak / future volume, future wallet performance, future patterns, and
future outcome labels MUST NOT decide Gate 1 or the historical score.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from stinky_core.admission import (
    ALERT_MIN_SCORE,
    FILTER_VERSION,
    GATE1_VOLUME_5M_USD,
    FilterConfig,
    FilterDecision,
    ReasonCode,
    clamp_gate1_volume,
    evaluate_gate1,
)
from stinky_core.identity import UniqueMintIndex
from stinky_core.intelligence import (
    STATUS_ALERT,
    STATUS_QUALIFIED,
    can_alert_investigation,
    investigate,
)
from stinky_core.outcomes import label_outcome

# Fields that exist only after the decision timestamp. Never feed these
# into evaluate_gate1 / investigate.
DECISION_TIME_STRIP = (
    "peak_volume",
    "peak_volume_m5_usd",
    "peak_multiple",
    "outcome",
    "outcome_label",
    "drawdown",
    "time_to_peak",
    "time_to_drawdown",
    "observation_window",
    "observation_complete",
    "future_score",
    "score_snapshot",
    "median_peak_multiple",
)


def decision_time_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a historical row with future keys removed.

    `wallet_performance` and `historical_patterns` are kept only when the
    caller explicitly marks them as as-of-decision (`wallets_as_of_decision`,
    `patterns_as_of_decision`). Otherwise they are treated as leak risk.
    """
    snap = dict(row)
    for k in DECISION_TIME_STRIP:
        snap.pop(k, None)
    if not snap.get("wallets_as_of_decision"):
        snap.pop("wallet_performance", None)
    if not snap.get("patterns_as_of_decision"):
        snap.pop("historical_patterns", None)
    return snap


def backtest_candidates(
    markets: Iterable[Mapping[str, Any]],
    *,
    config: FilterConfig | None = None,
    min_score: float = ALERT_MIN_SCORE,
    min_volume_usd: float = GATE1_VOLUME_5M_USD,
) -> dict[str, Any]:
    del config  # canonical Gate 1 only; FilterConfig cannot bypass evaluate_gate1
    min_volume_usd = clamp_gate1_volume(min_volume_usd)
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
    gate1_n = 0
    deep_n = 0
    qualified_n = 0
    alerted_n = 0
    runners = 0
    held = 0
    fades = 0
    unknown = 0
    fee_verified = 0
    fee_unknown = 0

    for m in unique:
        snap = decision_time_snapshot(m)
        decision: FilterDecision = evaluate_gate1(snap, min_volume_usd=min_volume_usd)
        inv = None
        alert_ok = False
        alert_reason = decision.rejection_reason
        if decision.eligible:
            gate1_n += 1
            inv = investigate(snap)
            deep_n += 1
            if inv.pipeline_status == STATUS_QUALIFIED:
                qualified_n += 1
            alert_ok, alert_reason = can_alert_investigation(
                True, inv, min_score=min_score, rejection_reason=None
            )
            if alert_ok:
                inv.pipeline_status = STATUS_ALERT
        if inv and inv.fee_status == "VERIFIED":
            fee_verified += 1
        else:
            fee_unknown += 1
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
                "gate1_passed": decision.eligible,
                "rejection_reason": decision.rejection_reason,
                "reason_codes": decision.reason_codes,
                "alert_ok": alert_ok,
                "alert_reason": alert_reason,
                "pipeline_status": inv.pipeline_status if inv else "REJECTED",
                "stinky_score": inv.score.score if inv else None,
                "has_intelligence": inv.has_intelligence if inv else False,
                "synthetic_level": inv.synthetic.level if inv else None,
                "rug_level": inv.rug.level if inv else None,
                "outcome": outcome.to_dict(),
                "filter_version": decision.filter_version,
            }
        )

    precision = (runners / alerted_n) if alerted_n else None
    total = len(unique)
    coverage = (deep_n / total) if total else None
    # FPR among alerts with a resolved outcome (not UNKNOWN).
    resolved_alerts = runners + held + fades
    fpr = (fades / resolved_alerts) if resolved_alerts else None
    return {
        "engine": "stinky-backtest-v1.1.0-harden",
        "filter_version": FILTER_VERSION,
        "input": len(unique) + dropped_dupes,
        "unique_mints": len(unique),
        "unique_candidates": total,
        "duplicate_mints_dropped": dropped_dupes,
        "gate1_passed": gate1_n,
        "investigated": deep_n,
        "deep_inspected": deep_n,
        "qualified": qualified_n,
        "eligible": gate1_n,
        "alerts": alerted_n,
        "alerted": alerted_n,
        "runners": runners,
        "held": held,
        "fades": fades,
        "unknown": unknown,
        "precision": precision,
        "precision_runner": precision,
        "coverage": coverage,
        "false_positive_rate": fpr,
        "sample_size": total,
        "alert_sample_size": alerted_n,
        "fee_verified": fee_verified,
        "fee_unknown": fee_unknown,
        "fee_verified_rate": (fee_verified / total) if total else None,
        "items": evaluated,
    }
