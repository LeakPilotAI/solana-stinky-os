"""One unique-mint decision row. The laboratory export. Not a training set yet.

Do not train ML on this in this phase.
"""

from __future__ import annotations

from typing import Any, Mapping

from stinky_core.admission import FILTER_VERSION
from stinky_core.intelligence import INTEL_VERSION, Investigation
from stinky_core.outcomes import LABEL_VERSION, Outcome

DATASET_VERSION = "dataset-v1.0.0"


def decision_row(
    *,
    mint: str | None,
    decision_timestamp: str | None,
    protocol: str | None,
    volume_m5_usd: float | None,
    gate1_eligible: bool,
    investigation: Investigation | None,
    alert_ok: bool,
    alert_reason: str | None,
    outcome: Outcome | Mapping[str, Any] | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inv = investigation
    oc = outcome.to_dict() if hasattr(outcome, "to_dict") else (dict(outcome) if outcome else None)
    score = inv.score if inv else None
    return {
        "dataset_version": DATASET_VERSION,
        "filter_version": FILTER_VERSION,
        "intel_version": inv.model_version if inv else INTEL_VERSION,
        "label_version": (oc or {}).get("label_version") or LABEL_VERSION,
        "mint": mint,
        "decision_timestamp": decision_timestamp,
        "protocol": protocol,
        "volume_m5_usd": volume_m5_usd,
        "gate1_passed": bool(gate1_eligible),
        "pipeline_status": inv.pipeline_status if inv else ("REJECTED" if not gate1_eligible else "DISCOVERED"),
        "has_intelligence": bool(inv.has_intelligence) if inv else False,
        "promote": bool(getattr(inv, "promote", False)) if inv else False,
        "insufficient_evidence": bool(getattr(inv, "insufficient_evidence", True)) if inv else True,
        "stinky_score": score.score if score else None,
        "score_actionable": bool(getattr(score, "actionable", False)) if score else False,
        "score_interpretation": (getattr(score, "interpretation", None) or "INSUFFICIENT_EVIDENCE") if score else "INSUFFICIENT_EVIDENCE",
        "unknown_not_bullish": True,
        "score_confidence": score.confidence if score else None,
        "score_components": dict(score.components) if score else None,
        "calibrated_probability": False,
        "synthetic_level": inv.synthetic.level if inv else None,
        "rug_level": inv.rug.level if inv else None,
        "creator_status": inv.creator.status if inv else None,
        "wallet_status": inv.wallets.status if inv else None,
        "pattern_confidence": inv.patterns.pattern_confidence if inv else None,
        "entity_links": (inv.entities or {}).get("link_count") if inv and getattr(inv, "entities", None) else None,
        "alert_ok": bool(alert_ok),
        "alert_reason": alert_reason,
        "outcome_label": (oc or {}).get("label"),
        "peak_multiple": (oc or {}).get("peak_multiple"),
        "missing_data": list(inv.missing_data) if inv else ["investigation"],
        "would_change_conclusion": list(getattr(inv, "would_change", []) or []) if inv else [],
        **dict(extra or {}),
    }
