"""Backtest: Gate 1 at decision-time volume, then inspection, then outcome.

Peak / future volume MUST NOT decide Gate 1.
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
    evaluate_gate1,
)
from stinky_core.identity import UniqueMintIndex
from stinky_core.intelligence import can_alert_investigation, investigate
from stinky_core.outcomes import label_outcome


def backtest_candidates(
    markets: Iterable[Mapping[str, Any]],
    *,
    config: FilterConfig | None = None,
    min_score: float = ALERT_MIN_SCORE,
    min_volume_usd: float = GATE1_VOLUME_5M_USD,
) -> dict[str, Any]:
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
    alerted_n = 0
    runners = 0
    held = 0
    fades = 0
    unknown = 0
    fee_verified = 0
    fee_unknown = 0

    for m in unique:
        # Decision-time volume only. peak_volume is reserved for outcomes.
        snap = dict(m)
        snap.pop("peak_volume", None)
        snap.pop("peak_volume_m5_usd", None)
        snap.pop("peak_multiple", None)
        decision: FilterDecision = evaluate_gate1(snap, min_volume_usd=min_volume_usd)
        inv = None
        alert_ok = False
        alert_reason = decision.rejection_reason
        if decision.eligible:
            gate1_n += 1
            inv = investigate(snap)
            deep_n += 1
            alert_ok, alert_reason = can_alert_investigation(
                True, inv, min_score=min_score, rejection_reason=None
            )
            if alert_ok:
                inv.pipeline_status = "ALERT"
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
                "outcome": outcome.to_dict(),
                "filter_version": decision.filter_version,
            }
        )

    precision = (runners / alerted_n) if alerted_n else None
    total = len(unique)
    return {
        "engine": "stinky-backtest-v1.1.0-volume-first",
        "filter_version": FILTER_VERSION,
        "input": len(unique) + dropped_dupes,
        "unique_mints": len(unique),
        "unique_candidates": total,
        "duplicate_mints_dropped": dropped_dupes,
        "gate1_passed": gate1_n,
        "deep_inspected": deep_n,
        "eligible": gate1_n,
        "alerts": alerted_n,
        "alerted": alerted_n,
        "runners": runners,
        "held": held,
        "fades": fades,
        "unknown": unknown,
        "precision_runner": precision,
        "fee_verified": fee_verified,
        "fee_unknown": fee_unknown,
        "fee_verified_rate": (fee_verified / total) if total else None,
        "items": evaluated,
    }
