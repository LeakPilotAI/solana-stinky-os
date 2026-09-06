"""Hydrate investigation responses with bounded entity-network evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.entity_graph import _assemble
from stinky_api.entity_history_analogues import find_historical_analogues
from stinky_api.entity_history_synthesis import synthesize_entity_history
from stinky_api.funding_history import funding_history_for_entity
from stinky_api.historical_outcome_calibration import calibrate_historical_outcomes
from stinky_api.historical_outcome_comparison import historical_outcomes_for_analogues
from stinky_api.market_outcome_analysis import analyze_market_lifecycle, market_path_signature
from stinky_api.market_outcome_history import market_lifecycle_for_mint
from stinky_api.market_pattern_calibration_memory import (
    calibration_longitudinal_memory,
    persist_rolling_calibration_snapshot,
)
from stinky_api.market_pattern_calibration_readiness import assess_pattern_calibration_readiness
from stinky_api.market_pattern_history import market_pattern_history, persist_market_pattern_occurrence
from stinky_api.market_pattern_outcome_calibration import calibrate_market_pattern_outcomes
from stinky_api.market_pattern_outcome_distribution import summarize_pattern_outcome_distribution
from stinky_api.market_pattern_rolling_calibration import track_rolling_pattern_calibration


def _unknown(*, status: str, wallet_limit: int, relationship_limit: int) -> dict[str, Any]:
    unknown_status = "UNKNOWN" if status == "UNKNOWN" else "NEW-UNKNOWN"
    return {
        "status": status,
        "entity": None,
        "wallets": [],
        "relationships": [],
        "funding_history": [],
        "market_lifecycle": {"status": unknown_status, "mint": None, "records": [], "missing": ["market_outcome_observations"], "bounded": {"limit": relationship_limit}, "evidence_only": True},
        "market_outcome_analysis": {"status": unknown_status, "observed_horizons": [], "observed_record_count": 0, "metrics": {}, "missing": ["market_outcome_observations"], "bounded": {"limit": relationship_limit}, "evidence_only": True},
        "market_pattern_history": {"status": unknown_status, "pattern_hash": None, "occurrence_count": 0, "distinct_market_count": 0, "records": [], "missing": ["market_path_pattern_occurrences"], "bounded": {"limit": relationship_limit}, "evidence_only": True},
        "market_pattern_outcome_calibration": {"status": unknown_status, "pattern_hash": None, "occurrence_count": 0, "occurrences_with_followup": 0, "occurrences_without_followup": 0, "followup_coverage": None, "horizon_coverage": {}, "records": [], "missing": ["market_pattern_followup_evidence"], "bounded": {"occurrence_limit": relationship_limit}, "evidence_only": True},
        "market_pattern_outcome_distribution": {"status": unknown_status, "pattern_hash": None, "horizons": {}, "sufficient_horizons": [], "insufficient_horizons": [], "criteria": {"min_sample_count": 5, "min_horizon_coverage": 0.5}, "missing": ["market_pattern_outcome_calibration"], "evidence_only": True},
        "market_pattern_calibration_readiness": {"status": unknown_status, "pattern_hash": None, "readiness_status": "INSUFFICIENT_EVIDENCE", "stable_horizons": [], "unstable_horizons": [], "slice_sizes": {"early": 0, "late": 0}, "horizons": {}, "criteria": {"min_total_occurrences": 10, "min_slice_occurrences": 5, "min_horizon_coverage": 0.5, "max_median_drift_pct_points": 25.0}, "missing": ["market_pattern_outcome_calibration"], "evidence_only": True},
        "market_pattern_rolling_calibration": {"status": unknown_status, "pattern_hash": None, "trend_status": "INSUFFICIENT_EVIDENCE", "window_count": 0, "windows": [], "missing": ["calibration_ready_history"], "evidence_only": True},
        "market_pattern_calibration_memory": {"status": unknown_status, "pattern_hash": None, "snapshot_count": 0, "records": [], "missing": ["market_pattern_calibration_snapshots"], "bounded": {"limit": relationship_limit}, "evidence_only": True},
        "historical_analogues": {"status": unknown_status, "records": [], "missing": ["entity_history"], "evidence_only": True},
        "historical_outcome_comparison": {"status": unknown_status, "records": [], "missing": ["entity_history"], "evidence_only": True},
        "historical_outcome_calibration": {"status": unknown_status, "analogue_count": 0, "analogue_with_launches": 0, "launch_count_observed": 0, "outcomes_known": 0, "outcomes_unknown": 0, "completed_count": 0, "outcome_coverage": None, "missing": ["entity_history"], "evidence_only": True},
        "bounded": {
            "wallet_limit": wallet_limit,
            "relationship_limit": relationship_limit,
            "funding_observation_limit": relationship_limit,
            "analogue_limit": 10,
            "analogue_candidate_limit": 500,
            "outcome_launch_limit_per_analogue": 20,
            "market_lifecycle_limit": relationship_limit,
            "market_pattern_history_limit": relationship_limit,
            "market_pattern_outcome_occurrence_limit": relationship_limit,
            "market_pattern_calibration_memory_limit": relationship_limit,
        },
        "evidence_only": True,
        "missing": ["entity_history"],
    }


async def entity_network_for_investigation(
    session: AsyncSession,
    *,
    entity_id: str | None = None,
    creator_wallet: str | None = None,
    mint: str | None = None,
    wallet_limit: int = 100,
    relationship_limit: int = 500,
    analogue_limit: int = 10,
    analogue_candidate_limit: int = 500,
    outcome_launch_limit_per_analogue: int = 20,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Resolve creator entity and return bounded historical evidence at a cutoff."""
    wallet_limit = max(1, min(500, int(wallet_limit)))
    relationship_limit = max(1, min(500, int(relationship_limit)))
    analogue_limit = max(1, min(50, int(analogue_limit)))
    analogue_candidate_limit = max(analogue_limit, min(500, int(analogue_candidate_limit)))
    outcome_launch_limit_per_analogue = max(1, min(100, int(outcome_launch_limit_per_analogue)))
    market_lifecycle_limit = relationship_limit
    market_pattern_history_limit = relationship_limit
    market_pattern_outcome_occurrence_limit = relationship_limit
    market_pattern_calibration_memory_limit = relationship_limit

    resolved_entity_id: UUID | None = None
    if entity_id:
        try:
            resolved_entity_id = UUID(str(entity_id))
        except (TypeError, ValueError, AttributeError):
            resolved_entity_id = None
    if resolved_entity_id is None and creator_wallet:
        try:
            row = (await session.execute(text("SELECT entity_id FROM entity_wallets WHERE wallet = :wallet LIMIT 1"), {"wallet": str(creator_wallet).strip()})).first()
        except Exception:
            return _unknown(status="UNKNOWN", wallet_limit=wallet_limit, relationship_limit=relationship_limit)
        if row and row[0]:
            try:
                resolved_entity_id = UUID(str(row[0]))
            except (TypeError, ValueError, AttributeError):
                return _unknown(status="UNKNOWN", wallet_limit=wallet_limit, relationship_limit=relationship_limit)
    if resolved_entity_id is None:
        return _unknown(status="NEW-UNKNOWN", wallet_limit=wallet_limit, relationship_limit=relationship_limit)

    try:
        assemble_kwargs: dict[str, Any] = {}
        if as_of is not None:
            assemble_kwargs["as_of"] = as_of
        graph = await _assemble(session, resolved_entity_id, wallet_limit, relationship_limit, **assemble_kwargs)
        if graph is None:
            return _unknown(status="UNKNOWN", wallet_limit=wallet_limit, relationship_limit=relationship_limit)
        funding_kwargs = {"wallet_limit": wallet_limit, "observation_limit": relationship_limit}
        if as_of is not None:
            funding_kwargs["as_of"] = as_of
        funding_history = await funding_history_for_entity(session, resolved_entity_id, **funding_kwargs)
        history_kwargs = {"graph": graph, "funding_history": funding_history, "launch_limit": relationship_limit}
        if as_of is not None:
            history_kwargs["as_of"] = as_of
        history = await synthesize_entity_history(session, resolved_entity_id, **history_kwargs)
    except Exception:
        return _unknown(status="UNKNOWN", wallet_limit=wallet_limit, relationship_limit=relationship_limit)

    resolved_mint = str(mint or "").strip() or None
    if resolved_mint is None:
        try:
            mint_row = (await session.execute(text("""
                SELECT mint FROM entity_launches
                WHERE entity_id = :entity_id AND mint IS NOT NULL
                ORDER BY observed_at DESC, id DESC LIMIT 1
            """), {"entity_id": resolved_entity_id})).first()
            if mint_row and mint_row[0]:
                resolved_mint = str(mint_row[0]).strip()
        except Exception:
            resolved_mint = None

    if resolved_mint is None:
        market_lifecycle = {"status": "UNKNOWN", "mint": None, "records": [], "missing": ["mint"], "bounded": {"limit": market_lifecycle_limit}, "evidence_only": True}
    else:
        lifecycle_kwargs: dict[str, Any] = {"limit": market_lifecycle_limit}
        if as_of is not None:
            lifecycle_kwargs["as_of"] = as_of
        market_lifecycle = await market_lifecycle_for_mint(session, resolved_mint, **lifecycle_kwargs)

    market_outcome_analysis = analyze_market_lifecycle(market_lifecycle.get("records", []), limit=market_lifecycle_limit)
    if as_of is not None:
        market_outcome_analysis["as_of"] = market_lifecycle.get("as_of")
        market_outcome_analysis["temporal_cutoff_enforced"] = market_lifecycle.get("temporal_cutoff_enforced", False)
    market_path = market_path_signature(market_outcome_analysis)

    pattern_history = {
        "status": "UNKNOWN", "pattern_hash": None, "occurrence_count": 0,
        "distinct_market_count": 0, "records": [],
        "missing": ["market_path_pattern_occurrences"],
        "bounded": {"limit": market_pattern_history_limit}, "evidence_only": True,
    }
    pattern_outcome_calibration = {
        "status": "UNKNOWN", "pattern_hash": None, "occurrence_count": 0,
        "occurrences_with_followup": 0, "occurrences_without_followup": 0,
        "followup_coverage": None, "horizon_coverage": {}, "records": [],
        "missing": ["market_pattern_followup_evidence"],
        "bounded": {"occurrence_limit": market_pattern_outcome_occurrence_limit},
        "evidence_only": True,
    }
    if resolved_mint and market_path.get("status") == "OBSERVED":
        lifecycle_records = market_lifecycle.get("records", [])
        observed_at = lifecycle_records[-1].get("observed_at") if lifecycle_records else None
        try:
            pattern_hash = await persist_market_pattern_occurrence(
                session,
                mint=resolved_mint,
                signature=market_path.get("signature", {}),
                observed_at=observed_at,
            )
            if pattern_hash:
                history_kwargs: dict[str, Any] = {"limit": market_pattern_history_limit}
                calibration_kwargs: dict[str, Any] = {"occurrence_limit": market_pattern_outcome_occurrence_limit}
                if as_of is not None:
                    history_kwargs["as_of"] = as_of
                    calibration_kwargs["as_of"] = as_of
                pattern_history = await market_pattern_history(session, pattern_hash, **history_kwargs)
                pattern_outcome_calibration = await calibrate_market_pattern_outcomes(session, pattern_hash, **calibration_kwargs)
        except Exception:
            pass

    pattern_outcome_distribution = summarize_pattern_outcome_distribution(pattern_outcome_calibration)
    pattern_calibration_readiness = assess_pattern_calibration_readiness(pattern_outcome_calibration)
    pattern_rolling_calibration = track_rolling_pattern_calibration(
        pattern_outcome_calibration,
        pattern_calibration_readiness,
    )
    pattern_calibration_memory = {
        "status": "UNKNOWN", "pattern_hash": pattern_rolling_calibration.get("pattern_hash"),
        "snapshot_count": 0, "records": [],
        "missing": ["market_pattern_calibration_snapshots"],
        "bounded": {"limit": market_pattern_calibration_memory_limit}, "evidence_only": True,
    }
    rolling_pattern_hash = str(pattern_rolling_calibration.get("pattern_hash") or "").strip()
    if pattern_rolling_calibration.get("status") == "OBSERVED" and rolling_pattern_hash:
        try:
            await persist_rolling_calibration_snapshot(session, pattern_rolling_calibration)
            memory_kwargs: dict[str, Any] = {"limit": market_pattern_calibration_memory_limit}
            if as_of is not None:
                memory_kwargs["as_of"] = as_of
            pattern_calibration_memory = await calibration_longitudinal_memory(
                session,
                rolling_pattern_hash,
                **memory_kwargs,
            )
        except Exception:
            pass

    try:
        analogue_kwargs = {"limit": analogue_limit, "candidate_limit": analogue_candidate_limit}
        if as_of is not None:
            analogue_kwargs["as_of"] = as_of
        historical_analogues = await find_historical_analogues(session, resolved_entity_id, **analogue_kwargs)
    except Exception:
        historical_analogues = {"status": "UNKNOWN", "records": [], "missing": ["historical_analogues"], "evidence_basis": "unknown_query", "bounded": {"limit": analogue_limit, "candidate_limit": analogue_candidate_limit}, "evidence_only": True}
    try:
        outcome_kwargs = {"limit_per_entity": outcome_launch_limit_per_analogue}
        if as_of is not None:
            outcome_kwargs["as_of"] = as_of
        historical_outcomes = await historical_outcomes_for_analogues(session, historical_analogues.get("records", []), **outcome_kwargs)
    except Exception:
        historical_outcomes = {"status": "UNKNOWN", "records": [], "missing": ["historical_outcome_comparison"], "evidence_basis": "unknown_query", "bounded": {"limit_per_entity": outcome_launch_limit_per_analogue}, "evidence_only": True}
    historical_calibration = calibrate_historical_outcomes(historical_outcomes)

    graph["status"] = "KNOWN_ENTITY"
    graph["funding_history"] = funding_history
    graph["history"] = history
    graph["market_lifecycle"] = market_lifecycle
    graph["market_outcome_analysis"] = market_outcome_analysis
    graph["market_path_signature"] = market_path
    graph["market_pattern_history"] = pattern_history
    graph["market_pattern_outcome_calibration"] = pattern_outcome_calibration
    graph["market_pattern_outcome_distribution"] = pattern_outcome_distribution
    graph["market_pattern_calibration_readiness"] = pattern_calibration_readiness
    graph["market_pattern_rolling_calibration"] = pattern_rolling_calibration
    graph["market_pattern_calibration_memory"] = pattern_calibration_memory
    graph["historical_analogues"] = historical_analogues
    graph["historical_outcome_comparison"] = historical_outcomes
    graph["historical_outcome_calibration"] = historical_calibration
    graph["bounded"]["funding_observation_limit"] = relationship_limit
    graph["bounded"]["launch_history_limit"] = relationship_limit
    graph["bounded"]["market_lifecycle_limit"] = market_lifecycle_limit
    graph["bounded"]["market_pattern_history_limit"] = market_pattern_history_limit
    graph["bounded"]["market_pattern_outcome_occurrence_limit"] = market_pattern_outcome_occurrence_limit
    graph["bounded"]["market_pattern_calibration_memory_limit"] = market_pattern_calibration_memory_limit
    graph["bounded"]["analogue_limit"] = analogue_limit
    graph["bounded"]["analogue_candidate_limit"] = analogue_candidate_limit
    graph["bounded"]["outcome_launch_limit_per_analogue"] = outcome_launch_limit_per_analogue
    if as_of is not None:
        graph["as_of"] = historical_analogues.get("as_of")
        graph["temporal_cutoff_enforced"] = historical_analogues.get("temporal_cutoff_enforced", False)
    graph["evidence_only"] = True
    return graph
