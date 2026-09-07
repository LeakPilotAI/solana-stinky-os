"""Fail-closed combined readiness gate for descriptive entity-intelligence calibration.

This module composes existing developer-history stability, developer-relationship
stability, and historical-outcome coverage contracts. Readiness is descriptive
only and never grants predictive, risk/quality, ownership/coordination, or trading
authority.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MIN_OUTCOME_LAUNCHES = 5
MIN_KNOWN_OUTCOMES = 3
MIN_OUTCOME_COVERAGE = 0.60

AUTHORITY = {
    "interpretation": "DESCRIPTIVE_CALIBRATION_READINESS_ONLY",
    "ownership_inferred": False,
    "coordination_inferred": False,
    "intent_inferred": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "predictive_authority": False,
    "trade_signal": False,
    "evidence_only": True,
}


def assess_entity_intelligence_calibration_readiness(
    developer_stability: dict[str, Any],
    relationship_stability: dict[str, Any],
    outcome_calibration: dict[str, Any],
    *,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Compose independent descriptive evidence gates into one entity-level decision."""
    developer_ok = bool(developer_stability.get("stable")) and developer_stability.get("stability_status") == "STABLE_FOR_DESCRIPTIVE_CALIBRATION"
    relationship_ok = bool(relationship_stability.get("stable")) and relationship_stability.get("stability_status") == "STABLE_FOR_DESCRIPTIVE_CALIBRATION"

    outcome_status = outcome_calibration.get("status")
    launch_count = int(outcome_calibration.get("launch_count_observed") or 0)
    known = int(outcome_calibration.get("outcomes_known") or 0)
    coverage_raw = outcome_calibration.get("outcome_coverage")
    try:
        coverage = float(coverage_raw) if coverage_raw is not None else None
    except (TypeError, ValueError):
        coverage = None
    outcome_ok = (
        outcome_status == "OBSERVED"
        and launch_count >= MIN_OUTCOME_LAUNCHES
        and known >= MIN_KNOWN_OUTCOMES
        and coverage is not None
        and coverage >= MIN_OUTCOME_COVERAGE
    )

    blockers: list[str] = []
    if not developer_ok:
        blockers.append("DEVELOPER_HISTORY_NOT_STABLE")
    if not relationship_ok:
        blockers.append("RELATIONSHIP_HISTORY_NOT_STABLE")
    if outcome_status != "OBSERVED":
        blockers.append("OUTCOME_HISTORY_UNAVAILABLE")
    else:
        if launch_count < MIN_OUTCOME_LAUNCHES:
            blockers.append("INSUFFICIENT_OUTCOME_LAUNCHES")
        if known < MIN_KNOWN_OUTCOMES:
            blockers.append("INSUFFICIENT_KNOWN_OUTCOMES")
        if coverage is None or coverage < MIN_OUTCOME_COVERAGE:
            blockers.append("INSUFFICIENT_OUTCOME_COVERAGE")

    temporal_checks = {
        "developer_cutoff_enforced": bool(developer_stability.get("temporal_cutoff_enforced")) if as_of is not None else None,
        "relationship_cutoff_enforced": bool(relationship_stability.get("temporal_cutoff_enforced")) if as_of is not None else None,
    }
    if as_of is not None and not all(v is True for v in temporal_checks.values()):
        blockers.append("TEMPORAL_INTEGRITY_NOT_ESTABLISHED")

    evidence_independence = {
        "developer_source": developer_stability.get("source") or "developer_longitudinal_snapshots",
        "relationship_source": relationship_stability.get("source") or "developer_correlation_snapshots",
        "outcome_source": outcome_calibration.get("evidence_basis") or "entity_launches",
    }
    distinct_sources = len({str(v) for v in evidence_independence.values() if v}) == 3
    if not distinct_sources:
        blockers.append("EVIDENCE_INDEPENDENCE_NOT_ESTABLISHED")

    ready = not blockers
    result: dict[str, Any] = {
        "status": "READY_FOR_DESCRIPTIVE_CALIBRATION" if ready else "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION",
        "ready": ready,
        "blockers": blockers,
        "components": {
            "developer_history": {
                "status": developer_stability.get("stability_status"),
                "passed": developer_ok,
                "blockers": list(developer_stability.get("blockers") or []),
            },
            "relationship_history": {
                "status": relationship_stability.get("stability_status"),
                "passed": relationship_ok,
                "blockers": list(relationship_stability.get("blockers") or []),
            },
            "outcome_history": {
                "status": outcome_status,
                "passed": outcome_ok,
                "launch_count_observed": launch_count,
                "outcomes_known": known,
                "outcome_coverage": coverage,
            },
        },
        "thresholds": {
            "min_outcome_launches": MIN_OUTCOME_LAUNCHES,
            "min_known_outcomes": MIN_KNOWN_OUTCOMES,
            "min_outcome_coverage": MIN_OUTCOME_COVERAGE,
        },
        "temporal_integrity": temporal_checks,
        "evidence_independence": {**evidence_independence, "distinct_sources": distinct_sources},
        "calibration_scope": "ENTITY_INTELLIGENCE_DESCRIPTIVE_ONLY",
        **AUTHORITY,
    }
    if as_of is not None:
        result["as_of"] = str(as_of)
        result["temporal_cutoff_enforced"] = all(v is True for v in temporal_checks.values())
    return result


async def _latest_component_evidence_hash(
    session: AsyncSession,
    *,
    table: str,
    entity_id: str,
    as_of: datetime | None,
) -> str | None:
    """Return the latest immutable component snapshot hash visible at the cutoff."""
    if table not in {"developer_longitudinal_snapshots", "developer_correlation_snapshots"}:
        return None
    clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
    params: dict[str, Any] = {"entity_id": entity_id}
    if as_of is not None:
        params["as_of"] = as_of
    try:
        row = (
            await session.execute(
                text(
                    f"""
                    SELECT evidence_hash
                    FROM {table}
                    WHERE entity_id = CAST(:entity_id AS UUID) {clause}
                    ORDER BY observed_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                params,
            )
        ).first()
    except Exception:
        return None
    return str(row[0]) if row and row[0] else None


async def entity_intelligence_calibration_readiness(
    session: AsyncSession,
    entity_id: str,
    outcome_calibration: dict[str, Any],
    *,
    as_of: datetime | None = None,
    developer_limit: int = 100,
    relationship_limit: int = 40,
) -> dict[str, Any]:
    """DB-backed aggregate using immutable developer and relationship histories."""
    from stinky_api.developer_history_calibration_stability import developer_history_calibration_stability
    from stinky_api.developer_relationship_stability import developer_relationship_stability

    developer = await developer_history_calibration_stability(
        session, entity_id, limit=developer_limit, as_of=as_of
    )
    relationship = await developer_relationship_stability(
        session, entity_id, limit=relationship_limit, as_of=as_of
    )
    result = assess_entity_intelligence_calibration_readiness(
        developer, relationship, outcome_calibration, as_of=as_of
    )

    # Preserve the immutable evidence versions that produced the component states.
    # A real launch/outcome evidence change must remain observable even when the
    # readiness blockers themselves have not changed yet. This creates genuine
    # longitudinal depth without timer-generated or fabricated checkpoints.
    developer_hash = await _latest_component_evidence_hash(
        session,
        table="developer_longitudinal_snapshots",
        entity_id=entity_id,
        as_of=as_of,
    )
    relationship_hash = await _latest_component_evidence_hash(
        session,
        table="developer_correlation_snapshots",
        entity_id=entity_id,
        as_of=as_of,
    )
    result["components"]["developer_history"]["evidence_hash"] = developer_hash
    result["components"]["relationship_history"]["evidence_hash"] = relationship_hash
    result["entity_id"] = entity_id
    return result
