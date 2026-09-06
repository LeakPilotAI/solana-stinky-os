"""Compose the evidence-only market-pattern calibration surface for investigations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.market_pattern_calibration_synthesis import synthesize_market_pattern_calibration_evidence
from stinky_api.market_pattern_calibration_transitions import describe_calibration_state_transitions
from stinky_api.market_pattern_conditional_performance import summarize_conditional_pattern_performance
from stinky_api.market_pattern_regime_memory import calibration_regime_memory
from stinky_api.market_pattern_regime_segmentation import segment_pattern_occurrences_by_regime
from stinky_api.market_pattern_regime_stability import assess_regime_conditioned_stability


SURFACE_KEYS = (
    "market_pattern_calibration_transitions",
    "market_pattern_regime_memory",
    "market_pattern_regime_segmentation",
    "market_pattern_conditional_performance",
    "market_pattern_regime_stability",
    "market_pattern_calibration_synthesis",
)


def unknown_calibration_surface(
    *,
    status: str = "UNKNOWN",
    pattern_hash: str | None = None,
    limit: int = 500,
) -> dict[str, dict[str, Any]]:
    bounded = max(1, min(int(limit), 500))
    return {
        "market_pattern_calibration_transitions": {
            "status": status,
            "pattern_hash": pattern_hash,
            "state_runs": [],
            "transitions": [],
            "missing": ["market_pattern_calibration_memory"],
            "evidence_only": True,
        },
        "market_pattern_regime_memory": {
            "status": status,
            "pattern_count": 0,
            "state_counts": {},
            "missing": ["market_pattern_calibration_snapshots"],
            "bounded": {"pattern_limit": bounded},
            "shared_cause_inferred": False,
            "evidence_only": True,
        },
        "market_pattern_regime_segmentation": {
            "status": status,
            "pattern_hash": pattern_hash,
            "occurrence_count": 0,
            "segmented_occurrence_count": 0,
            "records": [],
            "regime_counts": {},
            "missing": ["historical_regime_evidence"],
            "bounded": {"occurrence_limit": bounded, "regime_lookback_hours": 24},
            "future_regime_leakage_permitted": False,
            "evidence_only": True,
        },
        "market_pattern_conditional_performance": {
            "status": status,
            "pattern_hash": pattern_hash,
            "regimes": {},
            "sufficient_regimes": [],
            "insufficient_regimes": [],
            "missing": ["market_pattern_regime_segmentation"],
            "future_regime_leakage_permitted": False,
            "evidence_only": True,
        },
        "market_pattern_regime_stability": {
            "status": status,
            "pattern_hash": pattern_hash,
            "regimes": {},
            "stable_regimes": [],
            "unstable_regimes": [],
            "insufficient_regimes": [],
            "missing": ["market_pattern_regime_segmentation"],
            "future_evaluation_leakage_permitted": False,
            "regime_assignment_leakage_permitted": False,
            "evidence_only": True,
        },
        "market_pattern_calibration_synthesis": {
            "status": status,
            "pattern_hash": pattern_hash,
            "evidence_status": "INSUFFICIENT_EVIDENCE",
            "chain_status": {},
            "observed_layer_count": 0,
            "layer_count": 7,
            "current_calibration_state": "INSUFFICIENT_EVIDENCE",
            "transition_count": 0,
            "missing": ["calibration_evidence_chain"],
            "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
            "predictive_authority": False,
            "trade_signal": False,
            "shared_cause_inferred": False,
            "evidence_only": True,
        },
    }


def _synthesize(surface: dict[str, dict[str, Any]], *, rolling: dict[str, Any], memory: dict[str, Any]) -> None:
    try:
        surface["market_pattern_calibration_synthesis"] = synthesize_market_pattern_calibration_evidence(
            rolling=rolling,
            memory=memory,
            transitions=surface["market_pattern_calibration_transitions"],
            regime_memory=surface["market_pattern_regime_memory"],
            segmentation=surface["market_pattern_regime_segmentation"],
            conditional_performance=surface["market_pattern_conditional_performance"],
            stability=surface["market_pattern_regime_stability"],
        )
    except Exception:
        pass


async def build_investigation_calibration_surface(
    session: AsyncSession,
    *,
    pattern_hash: str | None,
    calibration: dict[str, Any],
    calibration_memory: dict[str, Any],
    rolling_calibration: dict[str, Any] | None = None,
    as_of: Any = None,
    occurrence_limit: int = 500,
    pattern_limit: int = 500,
    regime_lookback_hours: int = 24,
) -> dict[str, dict[str, Any]]:
    """Build a fail-soft, cutoff-safe evidence surface from existing calibration layers."""
    pattern_hash = str(pattern_hash or "").strip() or None
    occurrence_limit = max(1, min(int(occurrence_limit), 500))
    pattern_limit = max(1, min(int(pattern_limit), 2000))
    rolling = rolling_calibration if isinstance(rolling_calibration, dict) else {}
    surface = unknown_calibration_surface(
        status="UNKNOWN",
        pattern_hash=pattern_hash,
        limit=occurrence_limit,
    )

    try:
        transitions = describe_calibration_state_transitions(calibration_memory)
        surface["market_pattern_calibration_transitions"] = transitions
    except Exception:
        pass

    regime_kwargs: dict[str, Any] = {
        "lookback_hours": regime_lookback_hours,
        "pattern_limit": pattern_limit,
    }
    if as_of is not None:
        regime_kwargs["as_of"] = as_of
    try:
        surface["market_pattern_regime_memory"] = await calibration_regime_memory(
            session,
            **regime_kwargs,
        )
    except Exception:
        pass

    if not pattern_hash:
        _synthesize(surface, rolling=rolling, memory=calibration_memory)
        return surface

    segmentation_kwargs: dict[str, Any] = {
        "occurrence_limit": occurrence_limit,
        "regime_lookback_hours": regime_lookback_hours,
    }
    if as_of is not None:
        segmentation_kwargs["as_of"] = as_of
    try:
        segmentation = await segment_pattern_occurrences_by_regime(
            session,
            pattern_hash,
            **segmentation_kwargs,
        )
        surface["market_pattern_regime_segmentation"] = segmentation
    except Exception:
        segmentation = surface["market_pattern_regime_segmentation"]

    try:
        surface["market_pattern_conditional_performance"] = summarize_conditional_pattern_performance(
            calibration,
            segmentation,
        )
    except Exception:
        pass

    try:
        surface["market_pattern_regime_stability"] = assess_regime_conditioned_stability(
            calibration,
            segmentation,
        )
    except Exception:
        pass

    _synthesize(surface, rolling=rolling, memory=calibration_memory)
    return surface
