"""Compact operator-facing synthesis of market-pattern calibration evidence.

This module compresses already-computed evidence into an auditable summary. It
must not manufacture a score, forecast, probability, risk/quality judgment,
causality claim, or trading authority. UNKNOWN and insufficient evidence remain
visible rather than being collapsed into positive or negative interpretation.
"""

from __future__ import annotations

from typing import Any


def _status(value: Any) -> str:
    if not isinstance(value, dict):
        return "UNKNOWN"
    return str(value.get("status") or "UNKNOWN")


def _missing(*items: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for value in item.get("missing", []) or []:
            text = str(value or "").strip()
            if text and text not in out:
                out.append(text)
    return out


def synthesize_market_pattern_calibration_evidence(
    *,
    rolling: dict[str, Any],
    memory: dict[str, Any],
    transitions: dict[str, Any],
    regime_memory: dict[str, Any],
    segmentation: dict[str, Any],
    conditional_performance: dict[str, Any],
    stability: dict[str, Any],
) -> dict[str, Any]:
    """Return a compact descriptive summary of the calibration evidence chain."""
    pattern_hash = str(
        rolling.get("pattern_hash")
        or memory.get("pattern_hash")
        or transitions.get("pattern_hash")
        or segmentation.get("pattern_hash")
        or conditional_performance.get("pattern_hash")
        or stability.get("pattern_hash")
        or ""
    ).strip() or None

    persisted_rolling_observed = _status(memory) == "OBSERVED" and bool(memory.get("records"))
    rolling_status = _status(rolling)
    if rolling_status != "OBSERVED" and persisted_rolling_observed:
        rolling_status = "OBSERVED"

    current_state = (
        transitions.get("current_state")
        if _status(transitions) == "OBSERVED"
        else rolling.get("trend_status")
        if _status(rolling) == "OBSERVED"
        else "INSUFFICIENT_EVIDENCE"
    )
    transition_count = int(transitions.get("transition_count") or 0) if isinstance(transitions, dict) else 0

    state_counts = regime_memory.get("state_counts") if isinstance(regime_memory, dict) else None
    if not isinstance(state_counts, dict):
        state_counts = {}
    regime_pattern_count = int(regime_memory.get("pattern_count") or 0) if isinstance(regime_memory, dict) else 0

    segmentation_counts = segmentation.get("regime_counts") if isinstance(segmentation, dict) else None
    if not isinstance(segmentation_counts, dict):
        segmentation_counts = {}
    segmented_occurrences = int(segmentation.get("segmented_occurrence_count") or 0) if isinstance(segmentation, dict) else 0

    sufficient_regimes = conditional_performance.get("sufficient_regimes") if isinstance(conditional_performance, dict) else []
    if not isinstance(sufficient_regimes, list):
        sufficient_regimes = []

    stable_regimes = stability.get("stable_regimes") if isinstance(stability, dict) else []
    unstable_regimes = stability.get("unstable_regimes") if isinstance(stability, dict) else []
    insufficient_regimes = stability.get("insufficient_regimes") if isinstance(stability, dict) else []
    stable_regimes = stable_regimes if isinstance(stable_regimes, list) else []
    unstable_regimes = unstable_regimes if isinstance(unstable_regimes, list) else []
    insufficient_regimes = insufficient_regimes if isinstance(insufficient_regimes, list) else []

    chain_status = {
        "rolling": rolling_status,
        "memory": _status(memory),
        "transitions": _status(transitions),
        "regime_memory": _status(regime_memory),
        "segmentation": _status(segmentation),
        "conditional_performance": _status(conditional_performance),
        "stability": _status(stability),
    }
    observed_layers = sum(1 for value in chain_status.values() if value == "OBSERVED")
    if observed_layers == len(chain_status):
        evidence_status = "COMPLETE_OBSERVED_CHAIN"
    elif observed_layers:
        evidence_status = "PARTIAL_EVIDENCE"
    else:
        evidence_status = "INSUFFICIENT_EVIDENCE"

    missing = _missing(
        rolling,
        memory,
        transitions,
        regime_memory,
        segmentation,
        conditional_performance,
        stability,
    )

    result: dict[str, Any] = {
        "status": "OBSERVED" if observed_layers else "UNKNOWN",
        "pattern_hash": pattern_hash,
        "evidence_status": evidence_status,
        "chain_status": chain_status,
        "observed_layer_count": observed_layers,
        "layer_count": len(chain_status),
        "current_calibration_state": current_state,
        "transition_count": transition_count,
        "open_degradation_episode": bool(transitions.get("open_degradation_episode")) if isinstance(transitions, dict) else False,
        "regime_memory": {
            "pattern_count": regime_pattern_count,
            "state_counts": state_counts,
            "shared_cause_inferred": False,
        },
        "historical_segmentation": {
            "segmented_occurrence_count": segmented_occurrences,
            "regime_counts": segmentation_counts,
            "future_regime_leakage_permitted": False,
        },
        "conditional_evidence": {
            "sufficient_regimes": sufficient_regimes,
            "sufficient_regime_count": len(sufficient_regimes),
        },
        "chronological_generalization": {
            "stable_regimes": stable_regimes,
            "unstable_regimes": unstable_regimes,
            "insufficient_regimes": insufficient_regimes,
            "future_evaluation_leakage_permitted": False,
            "regime_assignment_leakage_permitted": False,
        },
        "missing": missing,
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "predictive_authority": False,
        "trade_signal": False,
        "shared_cause_inferred": False,
        "evidence_only": True,
    }

    as_of = None
    for item in (stability, segmentation, regime_memory, transitions, memory):
        if isinstance(item, dict) and item.get("as_of") is not None:
            as_of = item.get("as_of")
            break
    if as_of is not None:
        result["as_of"] = as_of
        result["temporal_cutoff_enforced"] = True
    return result
