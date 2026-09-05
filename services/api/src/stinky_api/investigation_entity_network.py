"""Hydrate investigation responses with bounded entity-network evidence.

This adapter bridges the canonical investigation result to the entity graph
store without putting API/database concerns into stinky-core intelligence.
The network is descriptive evidence only; missing entities remain UNKNOWN.
"""

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


def _unknown(*, status: str, wallet_limit: int, relationship_limit: int) -> dict[str, Any]:
    return {
        "status": status, "entity": None, "wallets": [], "relationships": [], "funding_history": [],
        "historical_analogues": {"status": "UNKNOWN" if status == "UNKNOWN" else "NEW-UNKNOWN", "records": [], "missing": ["entity_history"], "evidence_only": True},
        "historical_outcome_comparison": {"status": "UNKNOWN" if status == "UNKNOWN" else "NEW-UNKNOWN", "records": [], "missing": ["entity_history"], "evidence_only": True},
        "historical_outcome_calibration": {"status": "UNKNOWN" if status == "UNKNOWN" else "NEW-UNKNOWN", "analogue_count": 0, "analogue_with_launches": 0, "launch_count_observed": 0, "outcomes_known": 0, "outcomes_unknown": 0, "completed_count": 0, "outcome_coverage": None, "missing": ["entity_history"], "evidence_only": True},
        "bounded": {"wallet_limit": wallet_limit, "relationship_limit": relationship_limit, "funding_observation_limit": relationship_limit, "analogue_limit": 10, "analogue_candidate_limit": 500, "outcome_launch_limit_per_analogue": 20},
        "evidence_only": True, "missing": ["entity_history"],
    }


async def entity_network_for_investigation(
    session: AsyncSession,
    *,
    entity_id: str | None = None,
    creator_wallet: str | None = None,
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

    resolved_entity_id: UUID | None = None
    if entity_id:
        try:
            resolved_entity_id = UUID(str(entity_id))
        except (TypeError, ValueError, AttributeError):
            resolved_entity_id = None
    if resolved_entity_id is None and creator_wallet:
        try:
            row = (await session.execute(text("""
                SELECT entity_id FROM entity_wallets WHERE wallet = :wallet LIMIT 1
            """), {"wallet": str(creator_wallet).strip()})).first()
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
    graph["historical_analogues"] = historical_analogues
    graph["historical_outcome_comparison"] = historical_outcomes
    graph["historical_outcome_calibration"] = historical_calibration
    graph["bounded"]["funding_observation_limit"] = relationship_limit
    graph["bounded"]["launch_history_limit"] = relationship_limit
    graph["bounded"]["analogue_limit"] = analogue_limit
    graph["bounded"]["analogue_candidate_limit"] = analogue_candidate_limit
    graph["bounded"]["outcome_launch_limit_per_analogue"] = outcome_launch_limit_per_analogue
    if as_of is not None:
        graph["as_of"] = historical_analogues.get("as_of")
        graph["temporal_cutoff_enforced"] = historical_analogues.get("temporal_cutoff_enforced", False)
    graph["evidence_only"] = True
    return graph
