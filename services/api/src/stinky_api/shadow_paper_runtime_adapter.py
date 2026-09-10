"""Strict #158 -> #159 runtime adapter. Evidence only; never executes trades."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

AUTHORITY = {
    "interpretation": "SHADOW_TO_PAPER_RUNTIME_ADAPTER_ONLY",
    "paper_only": True,
    "live_execution": False,
    "trading_authority": False,
    "trade_signal": False,
    "recommendation_authority": False,
    "rpc_contacted": False,
    "transaction_signed": False,
    "order_submitted": False,
}


def adapt_shadow_decision_for_paper(shadow: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    if not isinstance(shadow, dict) or shadow.get("status") != "SHADOW_DECISION":
        missing.append("shadow_decision")
        shadow = {} if not isinstance(shadow, dict) else shadow
    action = shadow.get("action")
    if action not in {"WOULD_ENTER", "WOULD_SKIP"}:
        missing.append("shadow_action")
    if shadow.get("temporal_cutoff_enforced") is not True:
        missing.append("temporal_cutoff_enforced")
    if shadow.get("future_evidence_used") is not False:
        missing.append("future_evidence_excluded")
    if not isinstance(shadow.get("evidence_snapshot"), dict):
        missing.append("frozen_evidence_snapshot")
    for key in ("live_execution", "trading_authority", "trade_signal"):
        if shadow.get(key) is not False:
            missing.append(f"shadow_{key}_disabled")
    if shadow.get("paper_only") is not True:
        missing.append("shadow_paper_only")
    if missing:
        return {"status": "UNKNOWN", "missing": list(dict.fromkeys(missing)), **AUTHORITY}
    return {
        "status": "OBSERVED",
        "shadow_action": action,
        "mint": shadow.get("mint"),
        "policy_version": shadow.get("policy_version"),
        "decided_at": shadow.get("decided_at"),
        "t0_snapshot": {
            "evidence": deepcopy(shadow["evidence_snapshot"]),
            "probability": deepcopy(shadow.get("probability_snapshot")),
            "temporal_cutoff_enforced": True,
            "future_evidence_used": False,
        },
        "source_shadow_decision": deepcopy(shadow),
        "missing": [],
        **AUTHORITY,
    }
