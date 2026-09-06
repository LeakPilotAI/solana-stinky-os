"""Live end-to-end Phase 10 evidence audit for operator-driven research.

This module composes the temporally safe dataset, descriptive discovery, temporal
validation, immutable persistence memory, and the Phase 10 readiness gate. It is not
part of the Command Center poll and grants no predictive or trading authority.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.descriptive_pattern_discovery import discover_descriptive_patterns
from stinky_api.historical_research_bridge import historical_research_bridge_preflight
from stinky_api.pattern_discovery_dataset import form_pattern_discovery_dataset
from stinky_api.pattern_stability_memory import persist_pattern_stability_snapshot
from stinky_api.pattern_temporal_validation import validate_pattern_temporal_stability
from stinky_api.phase10_readiness_gate import (
    audit_phase10_readiness,
    pattern_persistence_readiness_summary,
)

AUTHORITY = {
    "interpretation": "LIVE_PHASE_10_RESEARCH_READINESS_ONLY",
    "phase_11_authorized": False,
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}


def _compact_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": dataset.get("status"),
        "formation_status": dataset.get("formation_status"),
        "dataset_hash": dataset.get("dataset_hash"),
        "as_of": dataset.get("as_of"),
        "feature_horizon": dataset.get("feature_horizon"),
        "row_count": dataset.get("row_count", 0),
        "coverage": dataset.get("coverage") or {},
        "criteria": dataset.get("criteria") or {},
        "bounded": dataset.get("bounded") or {},
        "missing": dataset.get("missing") or [],
        "failure_stage": dataset.get("failure_stage"),
    }


def _compact_discovery(discovery: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": discovery.get("status"),
        "discovery_status": discovery.get("discovery_status"),
        "dataset_hash": discovery.get("dataset_hash"),
        "pattern_count": discovery.get("pattern_count", 0),
        "candidate_pattern_count_before_support_dedup": discovery.get("candidate_pattern_count_before_support_dedup", 0),
        "criteria": discovery.get("criteria") or {},
        "pattern_hashes": [str(p.get("pattern_hash")) for p in (discovery.get("patterns") or []) if isinstance(p, dict) and p.get("pattern_hash")],
    }


def _compact_validation(validation: dict[str, Any]) -> dict[str, Any]:
    patterns = [p for p in (validation.get("patterns") or []) if isinstance(p, dict)]
    return {
        "status": validation.get("status"),
        "validation_status": validation.get("validation_status"),
        "dataset_hash": validation.get("dataset_hash"),
        "pattern_count": validation.get("pattern_count", 0),
        "stability_counts": validation.get("stability_counts") or {},
        "criteria": validation.get("criteria") or {},
        "patterns": [
            {
                "pattern_hash": p.get("pattern_hash"),
                "pattern_key": p.get("pattern_key"),
                "stability_status": p.get("stability_status"),
                "full_support_count": p.get("full_support_count"),
                "early_support_count": (p.get("early") or {}).get("support_count") if isinstance(p.get("early"), dict) else None,
                "late_support_count": (p.get("late") or {}).get("support_count") if isinstance(p.get("late"), dict) else None,
                "max_outcome_drift_pct_points": (p.get("outcome_distribution_drift") or {}).get("max_drift_pct_points") if isinstance(p.get("outcome_distribution_drift"), dict) else None,
            }
            for p in patterns
        ],
    }


async def run_live_phase10_readiness(
    session: AsyncSession,
    *,
    dataset_limit: int = 200,
    feature_horizon: str = "5m",
    as_of: datetime | str | None = None,
    persist_current: bool = True,
) -> dict[str, Any]:
    """Run the live descriptive research chain and return a compact readiness report."""
    dataset_limit = max(50, min(500, int(dataset_limit)))
    historical_replay = as_of is not None

    bridge_preflight = await historical_research_bridge_preflight(session)
    dataset = await form_pattern_discovery_dataset(
        session,
        limit=dataset_limit,
        as_of=as_of,
        feature_horizon=feature_horizon,
        min_rows=50,
        min_label_coverage=0.60,
        min_feature_source_coverage=0.50,
    )
    discovery = discover_descriptive_patterns(
        dataset,
        min_support=5,
        max_pattern_size=3,
        pattern_limit=100,
    )
    validation = validate_pattern_temporal_stability(
        dataset,
        discovery,
        min_slice_support=3,
        min_known_label_coverage=0.50,
        max_outcome_drift_pct_points=25.0,
        rolling_window_size=20,
        rolling_step=10,
    )

    validated_patterns = [p for p in (validation.get("patterns") or []) if isinstance(p, dict) and p.get("pattern_hash")]
    persisted_hashes: list[str] = []
    persistence_write_status = "SKIPPED_HISTORICAL_REPLAY" if historical_replay else "SKIPPED_BY_REQUEST"
    if persist_current and not historical_replay and validated_patterns:
        try:
            for pattern in validated_patterns:
                digest = await persist_pattern_stability_snapshot(session, pattern)
                if digest:
                    persisted_hashes.append(digest)
            await session.commit()
            persistence_write_status = "PERSISTED_OR_DEDUPED"
        except Exception:
            await session.rollback()
            persistence_write_status = "UNAVAILABLE"

    pattern_hashes = [str(p.get("pattern_hash")) for p in validated_patterns if p.get("pattern_hash")]
    persistence = await pattern_persistence_readiness_summary(
        session,
        pattern_hashes,
        as_of=as_of,
    )
    gate = audit_phase10_readiness(dataset, discovery, validation, persistence)

    bridge_counts = bridge_preflight.get("counts") if isinstance(bridge_preflight.get("counts"), dict) else {}
    unbridged = bridge_counts.get("unbridged_historically_resolvable_migrations")
    dataset_missing = dataset.get("missing") or []
    if dataset.get("row_count", 0) == 0 and dataset_missing:
        operator_note = "Phase 11 remains blocked because the historical research dataset query is unavailable. Inspect dataset.missing and bridge_preflight before collecting more data."
    elif dataset.get("row_count", 0) == 0 and isinstance(unbridged, int) and unbridged > 0:
        operator_note = "Phase 11 remains blocked. Historically resolvable migration rows exist but have not yet been bridged into entity_launches; run the explicit recovery command, then audit again."
    elif gate.get("completion_status") == "PHASE_10_COMPLETE":
        operator_note = "Phase 10 evidence criteria pass. This permits controlled Phase 11 research design only; it grants no predictive authority."
    else:
        operator_note = "Phase 11 remains blocked. Keep collecting or repairing the specific failed evidence criteria shown below."

    return {
        "available": True,
        "engine": "phase10-live-readiness-v1.1-bridge-diagnostics",
        "completion_status": gate.get("completion_status"),
        "ready_for_phase_11_research": gate.get("ready_for_phase_11_research", False),
        "bridge_preflight": bridge_preflight,
        "dataset": _compact_dataset(dataset),
        "discovery": _compact_discovery(discovery),
        "validation": _compact_validation(validation),
        "persistence": persistence,
        "persistence_write_status": persistence_write_status,
        "persisted_or_deduped_evidence_count": len(persisted_hashes),
        "audit": gate,
        "failed_criteria": gate.get("failed_criteria") or [],
        "operator_note": operator_note,
        "historical_replay": historical_replay,
        "command_center_coupled": False,
        "bounded": {
            "dataset_limit": dataset_limit,
            "dataset_query_count": (dataset.get("bounded") or {}).get("query_count"),
            "bridge_preflight_query_count_max": (bridge_preflight.get("bounded") or {}).get("count_queries_max"),
            "persistence_query_count": (persistence.get("bounded") or {}).get("query_count", 1 if pattern_hashes else 0),
            "max_patterns": 100,
        },
        **AUTHORITY,
    }
