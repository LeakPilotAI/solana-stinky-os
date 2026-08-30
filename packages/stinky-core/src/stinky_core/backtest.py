"""Backtest: Gate 1 at decision-time volume, then as-of investigation, then outcome.

Peak / future volume, future wallet performance, future patterns, future
creator history, and future outcome labels MUST NOT decide Gate 1 or the
historical score.

The IntelligenceMemory accumulates observations AFTER each decision so later
mints can use earlier evidence. Outcomes are labeled at labeled_at, which
must be strictly after the decision to be visible to later as-of queries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from stinky_core.admission import (
    ALERT_MIN_SCORE,
    FILTER_VERSION,
    GATE1_VOLUME_5M_USD,
    FilterConfig,
    FilterDecision,
    clamp_gate1_volume,
    evaluate_gate1,
)
from stinky_core.dataset import decision_row
from stinky_core.identity import UniqueMintIndex
from stinky_core.intelligence import (
    STATUS_ALERT,
    STATUS_HIGH_RISK,
    STATUS_QUALIFIED,
    STATUS_UNKNOWN,
    can_alert_investigation,
    investigate,
)
from stinky_core.memory import IntelligenceMemory, _parse_ts
from stinky_core.outcomes import LABEL_VERSION, label_outcome

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
    "labeled_at",
    "outcome_at",
)


def decision_time_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a historical row with future keys removed.

    Wallet / creator / pattern / entity fields are kept only when the caller
    marks them as-of-decision. Otherwise they are leak risk and stripped —
    IntelligenceMemory is the as-of source during backtest.
    """
    snap = dict(row)
    for k in DECISION_TIME_STRIP:
        snap.pop(k, None)
    if not snap.get("wallets_as_of_decision"):
        snap.pop("wallet_performance", None)
    if not snap.get("patterns_as_of_decision"):
        snap.pop("historical_patterns", None)
    if not snap.get("creator_as_of_decision"):
        snap.pop("creator_profile", None)
    return snap


def _row_decision_ts(m: Mapping[str, Any], index: int) -> datetime:
    ts = _parse_ts(m.get("decision_timestamp") or m.get("as_of") or m.get("observed_at"))
    if ts is not None:
        return ts
    return datetime.fromtimestamp(1_000_000 + index, tz=timezone.utc)


def backtest_candidates(
    markets: Iterable[Mapping[str, Any]],
    *,
    config: FilterConfig | None = None,
    min_score: float = ALERT_MIN_SCORE,
    min_volume_usd: float = GATE1_VOLUME_5M_USD,
    memory: IntelligenceMemory | None = None,
    learn: bool = True,
) -> dict[str, Any]:
    del config
    min_volume_usd = clamp_gate1_volume(min_volume_usd)
    mem = memory if memory is not None else IntelligenceMemory()
    idx = UniqueMintIndex()
    unique: list[Mapping[str, Any]] = []
    dropped_dupes = 0
    for m in markets:
        mint = m.get("mint") if isinstance(m, Mapping) else None
        if idx.add(str(mint) if mint else None):
            unique.append(m)
        else:
            dropped_dupes += 1

    ordered = sorted(enumerate(unique), key=lambda iv: _row_decision_ts(iv[1], iv[0]))

    evaluated: list[dict[str, Any]] = []
    dataset: list[dict[str, Any]] = []
    gate1_n = 0
    deep_n = 0
    qualified_n = 0
    high_risk_n = 0
    unknown_pipeline_n = 0
    alerted_n = 0
    runners = 0
    held = 0
    fades = 0
    unknown = 0
    fee_verified = 0
    fee_unknown = 0
    outcome_runner_all = 0
    outcome_unknown_all = 0

    for i, m in ordered:
        ts = _row_decision_ts(m, i)
        snap = decision_time_snapshot(m)
        snap["decision_timestamp"] = ts.isoformat()
        if m.get("creator") and "creator" not in snap:
            snap["creator"] = m.get("creator")
        decision: FilterDecision = evaluate_gate1(snap, min_volume_usd=min_volume_usd)
        inv = None
        alert_ok = False
        alert_reason = decision.rejection_reason
        if decision.eligible:
            gate1_n += 1
            inv = investigate(snap, memory=mem)
            deep_n += 1
            if inv.pipeline_status == STATUS_QUALIFIED:
                qualified_n += 1
            elif inv.pipeline_status == STATUS_HIGH_RISK:
                high_risk_n += 1
            elif inv.pipeline_status == STATUS_UNKNOWN:
                unknown_pipeline_n += 1
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
            entry_price=m.get("entry_price") or m.get("price_usd"),
            decision_timestamp=ts.isoformat(),
            drawdown=m.get("drawdown"),
            time_to_peak=m.get("time_to_peak"),
            time_to_drawdown=m.get("time_to_drawdown"),
            observation_window=m.get("observation_window"),
            observation_complete=bool(m.get("observation_complete")),
        )
        if outcome.label == "RUNNER":
            outcome_runner_all += 1
        if outcome.label == "UNKNOWN":
            outcome_unknown_all += 1
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

        if learn:
            buyers = m.get("buyers") if isinstance(m.get("buyers"), list) else None
            fp = inv.fingerprint if inv else None
            mem.ingest_decision(
                mint=str(decision.mint or m.get("mint") or ""),
                observed_at=ts,
                buyers=buyers,
                creator=str(m["creator"]) if m.get("creator") else None,
                fingerprint=fp,
                features=inv.fingerprint_features if inv else None,
            )
            mem.record_market_tick(
                mint=str(decision.mint or m.get("mint") or ""),
                observed_at=ts,
                volume_m5_usd=snap.get("volume_usd") or snap.get("volume_m5_usd"),
                price_usd=m.get("entry_price") or m.get("price_usd"),
                liquidity_usd=snap.get("liquidity_usd"),
            )
            labeled_at = _parse_ts(m.get("labeled_at") or m.get("outcome_at"))
            if labeled_at is None and m.get("observation_complete"):
                labeled_at = ts
            if labeled_at is not None and m.get("observation_complete"):
                wallets = []
                for b in buyers or []:
                    w = str(b.get("wallet") or b.get("userAddress") or "").strip()
                    if w:
                        wallets.append(w)
                mem.record_outcome(
                    mint=str(decision.mint or m.get("mint") or ""),
                    labeled_at=labeled_at,
                    label=outcome.label,
                    wallets=wallets,
                    creator=str(m["creator"]) if m.get("creator") else None,
                    fingerprint=fp,
                    label_version=outcome.label_version or LABEL_VERSION,
                )

        row = {
            "mint": decision.mint,
            "eligible": decision.eligible,
            "gate1_passed": decision.eligible,
            "rejection_reason": decision.rejection_reason,
            "reason_codes": decision.reason_codes,
            "alert_ok": alert_ok,
            "alert_reason": alert_reason,
            "pipeline_status": inv.pipeline_status if inv else "REJECTED",
            "promote": bool(inv.promote) if inv else False,
            "insufficient_evidence": bool(inv.insufficient_evidence) if inv else True,
            "stinky_score": inv.score.score if inv else None,
            "has_intelligence": inv.has_intelligence if inv else False,
            "synthetic_level": inv.synthetic.level if inv else None,
            "rug_level": inv.rug.level if inv else None,
            "outcome": outcome.to_dict(),
            "filter_version": decision.filter_version,
            "decision_timestamp": ts.isoformat(),
        }
        evaluated.append(row)
        mem.record_decision({
            **row,
            "protocol": str(m.get("protocol") or m.get("dex_id") or ""),
            "volume_m5_usd": snap.get("volume_usd") or snap.get("volume_m5_usd"),
            "outcome_label": outcome.label,
            "label_version": outcome.label_version or LABEL_VERSION,
            "model_version": inv.model_version if inv else None,
        })
        dataset.append(
            decision_row(
                mint=decision.mint,
                decision_timestamp=ts.isoformat(),
                protocol=str(m.get("protocol") or m.get("dex_id") or ""),
                volume_m5_usd=snap.get("volume_usd") or snap.get("volume_m5_usd"),
                gate1_eligible=bool(decision.eligible),
                investigation=inv,
                alert_ok=alert_ok,
                alert_reason=alert_reason,
                outcome=outcome,
            )
        )

    precision = (runners / alerted_n) if alerted_n else None
    total = len(unique)
    coverage = (deep_n / total) if total else None
    resolved_alerts = runners + held + fades
    fpr = (fades / resolved_alerts) if resolved_alerts else None
    recall = (runners / outcome_runner_all) if outcome_runner_all else None
    unknown_rate = (outcome_unknown_all / total) if total else None
    return {
        "engine": "stinky-backtest-v1.6.0-recognition",
        "filter_version": FILTER_VERSION,
        "memory_version": mem.version,
        "input": len(unique) + dropped_dupes,
        "unique_mints": len(unique),
        "unique_candidates": total,
        "duplicate_mints_dropped": dropped_dupes,
        "gate1_passed": gate1_n,
        "gate1_pass_rate": (gate1_n / total) if total else None,
        "investigated": deep_n,
        "deep_inspected": deep_n,
        "qualified": qualified_n,
        "qualified_rate": (qualified_n / total) if total else None,
        "high_risk": high_risk_n,
        "high_risk_rate": (high_risk_n / total) if total else None,
        "unknown_pipeline": unknown_pipeline_n,
        "unknown_pipeline_rate": (unknown_pipeline_n / total) if total else None,
        "eligible": gate1_n,
        "alerts": alerted_n,
        "alerted": alerted_n,
        "alert_rate": (alerted_n / total) if total else None,
        "runners": runners,
        "held": held,
        "fades": fades,
        "unknown": unknown,
        "precision": precision,
        "precision_runner": precision,
        "recall_runner": recall,
        "coverage": coverage,
        "false_positive_rate": fpr,
        "unknown_rate": unknown_rate,
        "sample_size": total,
        "alert_sample_size": alerted_n,
        "fee_verified": fee_verified,
        "fee_unknown": fee_unknown,
        "fee_verified_rate": (fee_verified / total) if total else None,
        "memory": mem.to_stats(),
        "book_size": mem.to_stats().get("intelligence_decisions") or mem.to_stats().get("fingerprints"),
        "mean_advantage_count": (
            (sum(int((r.get("information_advantage") or {}).get("advantage_count") or 0) for r in dataset) / len(dataset))
            if dataset else None
        ),
        "by_volume_band": _band_counts(dataset, "volume_m5_usd"),
        "by_wallet_status": _group_counts(dataset, "wallet_status"),
        "by_creator_status": _group_counts(dataset, "creator_status"),
        "by_protocol": _group_counts([{"protocol": r.get("protocol")} for r in dataset], "protocol"),
        "items": evaluated,
        "dataset": dataset,
    }


def _group_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "UNKNOWN")
        out[k] = out.get(k, 0) + 1
    return out


def _band_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out = {"below_150k": 0, "150k_200k": 0, "above_200k": 0, "unknown": 0}
    for r in rows:
        v = r.get(key)
        try:
            f = float(v) if v is not None else None
        except (TypeError, ValueError):
            f = None
        if f is None:
            out["unknown"] += 1
        elif f < 150_000:
            out["below_150k"] += 1
        elif f <= 200_000:
            out["150k_200k"] += 1
        else:
            out["above_200k"] += 1
    return out
