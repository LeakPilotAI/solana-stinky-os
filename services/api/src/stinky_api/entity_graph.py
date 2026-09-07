"""Read-only entity relationship graph API for Genesis investigations.

The graph is descriptive evidence only. It never assigns quality, risk,
prediction, or trade direction. Bounds are enforced at the API boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.cross_investigation_calibration_change_feed import calibration_change_feed
from stinky_api.db import get_session
from stinky_api.developer_correlation_audit import (
    developer_correlation_audit_history,
    developer_correlation_change_feed,
    persist_developer_correlation_snapshot,
)
from stinky_api.developer_longitudinal_audit import (
    developer_audit_history,
    developer_change_feed,
    persist_developer_snapshot,
)
from stinky_api.developer_motif_outcome_audit import motif_outcome_change_feed
from stinky_api.live_phase10_readiness import run_live_phase10_readiness

router = APIRouter(prefix="/v1/entity-graph", tags=["entity-graph"])


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _parse_as_of(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _historical_entity(row: dict[str, Any], cutoff: datetime | None) -> dict[str, Any]:
    result = dict(row)
    for key in ("created_at", "updated_at"):
        result[key] = _iso(result.get(key))
    if cutoff is not None:
        for key in ("wallet_count", "launch_count", "early_buy_count"):
            result[key] = None
        result["historical_aggregate_status"] = "UNKNOWN"
        result["historical_aggregate_missing"] = ["entity_snapshot"]
        result["temporal_cutoff_enforced"] = True
    return result


async def _assemble(session: AsyncSession, entity_id: UUID, wallet_limit: int, relationship_limit: int, *, as_of: datetime | str | None = None) -> dict[str, Any] | None:
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return None
    entity = (await session.execute(text("""
        SELECT entity_id::text AS entity_id, entity_type, display_label,
               primary_wallet, wallet_count, launch_count, early_buy_count,
               confidence, created_at, updated_at, meta
        FROM entities WHERE entity_id = :entity_id
    """), {"entity_id": entity_id})).mappings().first()
    if entity is None:
        return None
    entity = dict(entity)
    if cutoff is not None and entity.get("created_at") is not None and entity["created_at"] > cutoff:
        return None
    wallet_clause = "AND first_seen_at <= :as_of" if cutoff is not None else ""
    wallet_params: dict[str, Any] = {"entity_id": entity_id, "wallet_limit": wallet_limit}
    if cutoff is not None:
        wallet_params["as_of"] = cutoff
    wallets = (await session.execute(text(f"""
        SELECT wallet, entity_id::text AS entity_id, role, link_reason,
               confidence, first_seen_at, last_seen_at, evidence
        FROM entity_wallets
        WHERE entity_id = :entity_id {wallet_clause}
        ORDER BY first_seen_at ASC NULLS LAST, wallet ASC
        LIMIT :wallet_limit
    """), wallet_params)).mappings().all()
    wallet_values = [str(row["wallet"]) for row in wallets]
    if not wallet_values:
        result = {"entity": _historical_entity(entity, cutoff), "wallets": [], "relationships": [],
                  "bounded": {"wallet_limit": wallet_limit, "relationship_limit": relationship_limit},
                  "evidence_only": True, "status": "KNOWN_ENTITY_NO_WALLET_EDGES"}
        if cutoff is not None:
            result["as_of"] = cutoff.isoformat(); result["temporal_cutoff_enforced"] = True
        return result
    relationship_clause = "AND wr.first_seen_at <= :as_of" if cutoff is not None else ""
    relationship_params: dict[str, Any] = {"wallets": wallet_values, "relationship_limit": relationship_limit}
    if cutoff is not None:
        relationship_params["as_of"] = cutoff
    relationships = (await session.execute(text(f"""
        SELECT wr.wallet_a, wr.wallet_b, wr.relationship_kind,
               wr.observation_count, wr.first_seen_at, wr.last_seen_at,
               wr.confidence, wr.evidence,
               ea.entity_id::text AS entity_a_id, eb.entity_id::text AS entity_b_id
        FROM wallet_relationships wr
        LEFT JOIN entity_wallets wa ON wa.wallet = wr.wallet_a
        LEFT JOIN entity_wallets wb ON wb.wallet = wr.wallet_b
        LEFT JOIN entities ea ON ea.entity_id = wa.entity_id
        LEFT JOIN entities eb ON eb.entity_id = wb.entity_id
        WHERE (wr.wallet_a = ANY(:wallets) OR wr.wallet_b = ANY(:wallets)) {relationship_clause}
        ORDER BY wr.observation_count DESC NULLS LAST, wr.last_seen_at DESC NULLS LAST, wr.wallet_a, wr.wallet_b
        LIMIT :relationship_limit
    """), relationship_params)).mappings().all()
    seen: set[tuple[str, str, str]] = set(); edges: list[dict[str, Any]] = []
    for row in relationships:
        a, b, kind = str(row["wallet_a"]), str(row["wallet_b"]), str(row["relationship_kind"])
        if a == b: continue
        key = (min(a, b), max(a, b), kind)
        if key in seen: continue
        seen.add(key); edge = dict(row)
        first_seen = edge.get("first_seen_at"); last_seen = edge.get("last_seen_at")
        edge["first_seen_at"] = _iso(first_seen); edge["last_seen_at"] = _iso(last_seen)
        if cutoff is not None and last_seen is not None and last_seen > cutoff:
            edge["observation_count"] = None; edge["last_seen_at"] = None
            edge["historical_observation_status"] = "UNKNOWN"; edge["historical_observation_missing"] = ["relationship_observation_history"]
        edges.append(edge)
    historical_wallets = []
    for row in wallets:
        item = dict(row); last_seen = item.get("last_seen_at")
        item["first_seen_at"] = _iso(item.get("first_seen_at")); item["last_seen_at"] = _iso(last_seen)
        if cutoff is not None and last_seen is not None and last_seen > cutoff:
            item["last_seen_at"] = None; item["historical_last_seen_status"] = "UNKNOWN"; item["historical_last_seen_missing"] = ["wallet_observation_history"]
        historical_wallets.append(item)
    result = {"entity": _historical_entity(entity, cutoff), "wallets": historical_wallets, "relationships": edges,
              "bounded": {"wallet_limit": wallet_limit, "relationship_limit": relationship_limit}, "evidence_only": True, "status": "KNOWN_ENTITY"}
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat(); result["temporal_cutoff_enforced"] = True
    return result


@router.get("/calibration-changes")
async def cross_investigation_calibration_changes(session: Annotated[AsyncSession, Depends(get_session)], limit: int = Query(50, ge=1, le=200), as_of: datetime | None = Query(None), include_unchanged: bool = Query(False)) -> dict[str, Any]:
    return await calibration_change_feed(session, limit=limit, as_of=as_of, include_unchanged=include_unchanged)


@router.get("/developer-changes")
async def cross_developer_changes(session: Annotated[AsyncSession, Depends(get_session)], limit: int = Query(50, ge=1, le=200), as_of: datetime | None = Query(None), include_unchanged: bool = Query(False)) -> dict[str, Any]:
    return await developer_change_feed(session, limit=limit, as_of=as_of, include_unchanged=include_unchanged)


@router.get("/developer-correlation-changes")
async def cross_developer_correlation_changes(session: Annotated[AsyncSession, Depends(get_session)], limit: int = Query(50, ge=1, le=200), as_of: datetime | None = Query(None), include_unchanged: bool = Query(False)) -> dict[str, Any]:
    """Latest factual correlation-evidence delta per developer entity."""
    return await developer_correlation_change_feed(session, limit=limit, as_of=as_of, include_unchanged=include_unchanged)


@router.get("/developer-motif-outcome-changes")
async def cross_developer_motif_outcome_changes(session: Annotated[AsyncSession, Depends(get_session)], limit: int = Query(50, ge=1, le=200), as_of: datetime | None = Query(None), include_unchanged: bool = Query(False)) -> dict[str, Any]:
    """Latest factual historical motif-outcome delta per developer entity."""
    return await motif_outcome_change_feed(session, limit=limit, as_of=as_of, include_unchanged=include_unchanged)


@router.get("/developer-correlation/{entity_id}")
async def developer_correlation_for_entity(entity_id: UUID, session: Annotated[AsyncSession, Depends(get_session)], as_of: datetime | None = Query(None), limit: int = Query(100, ge=1, le=200)) -> dict[str, Any]:
    from stinky_api.investigation_entity_network import entity_network_for_investigation
    network = await entity_network_for_investigation(session, entity_id=str(entity_id), wallet_limit=min(100, limit), relationship_limit=limit, as_of=as_of)
    correlation = network.get("developer_identity_correlation")
    if not isinstance(correlation, dict):
        correlation = {"status": "UNKNOWN", "entity_id": str(entity_id), "wallets": [], "shared_funders": [], "cross_entity_wallet_reuse": [],
                       "deployer_buyer_recurrence": [], "shared_relationship_structures": [], "missing": ["developer_identity_correlation"],
                       "bounded": {"limit": limit}, "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "ownership_inferred": False,
                       "coordination_inferred": False, "intent_inferred": False, "risk_inferred": False, "quality_inferred": False,
                       "predictive_authority": False, "trade_signal": False, "evidence_only": True}
    try:
        if as_of is None:
            await persist_developer_correlation_snapshot(session, correlation)
        audit = await developer_correlation_audit_history(session, str(entity_id), limit=20, as_of=as_of)
    except Exception:
        audit = {"status": "UNKNOWN", "entity_id": str(entity_id), "records": [], "changes": [], "latest_change": None,
                 "missing": ["developer_correlation_snapshots"], "evidence_only": True}
    return {**correlation, "audit": audit, "latest_change": audit.get("latest_change"), "snapshot_count": audit.get("snapshot_count", 0)}


@router.get("/developer-correlation/{entity_id}/history")
async def developer_correlation_history(entity_id: UUID, session: Annotated[AsyncSession, Depends(get_session)], as_of: datetime | None = Query(None), limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    return await developer_correlation_audit_history(session, str(entity_id), limit=limit, as_of=as_of)


@router.get("/investigation/{mint}/calibration")
async def investigation_calibration_evidence(mint: str, session: Annotated[AsyncSession, Depends(get_session)], as_of: datetime | None = Query(None)) -> dict[str, Any]:
    from stinky_api.investigation_entity_network import entity_network_for_investigation
    mint = str(mint or "").strip()
    if not mint: raise HTTPException(status_code=400, detail="mint required")
    creator_wallet: str | None = None; entity_id: str | None = None

    # The Entity Resolver persists the mint/entity association before it invokes
    # this prospective capture surface. Prefer that exact factual association so
    # developer/correlation snapshots do not depend on a second wallet identity
    # lookup that can legitimately be unavailable for a fresh entity.
    try:
        row = (await session.execute(text("""SELECT entity_id::text FROM entity_launches WHERE mint = :mint AND entity_id IS NOT NULL ORDER BY observed_at DESC NULLS LAST, id DESC LIMIT 1"""), {"mint": mint})).first()
        if row and row[0]: entity_id = str(row[0]).strip() or None
    except Exception: entity_id = None

    # Preserve the previous creator-wallet resolution path for investigations
    # that predate entity_launch persistence or otherwise have no resolved entity.
    if entity_id is None:
        try:
            row = (await session.execute(text("""SELECT creator FROM migration_tracks WHERE mint = :mint AND creator IS NOT NULL ORDER BY migration_at DESC NULLS LAST LIMIT 1"""), {"mint": mint})).first()
            if row and row[0]: creator_wallet = str(row[0]).strip() or None
        except Exception: creator_wallet = None

    network = await entity_network_for_investigation(session, entity_id=entity_id, creator_wallet=creator_wallet, mint=mint, wallet_limit=100, relationship_limit=500, as_of=as_of)
    synthesis = network.get("market_pattern_calibration_synthesis")
    if not isinstance(synthesis, dict):
        synthesis = {"status": "UNKNOWN", "pattern_hash": None, "evidence_status": "INSUFFICIENT_EVIDENCE", "current_calibration_state": "INSUFFICIENT_EVIDENCE", "missing": ["market_pattern_calibration_synthesis"], "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "predictive_authority": False, "trade_signal": False, "evidence_only": True}
    audit = network.get("market_pattern_calibration_synthesis_audit")
    if not isinstance(audit, dict):
        audit = {"status": "UNKNOWN", "pattern_hash": synthesis.get("pattern_hash"), "snapshot_count": 0, "records": [], "changes": [], "latest_change": None, "missing": ["market_pattern_calibration_synthesis_snapshots"], "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "predictive_authority": False, "trade_signal": False, "evidence_only": True}
    history = network.get("history") if isinstance(network.get("history"), dict) else {}; sources = history.get("sources") if isinstance(history, dict) else {}
    developer = sources.get("developer_longitudinal") if isinstance(sources, dict) else None
    if not isinstance(developer, dict):
        developer = {"status": "NEW-UNKNOWN", "history_state": "NEW-UNKNOWN", "fresh_entity_interpretation": "NEW-UNKNOWN", "missing": ["developer_longitudinal_evidence"], "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "risk_inferred": False, "quality_inferred": False, "predictive_authority": False, "trade_signal": False, "evidence_only": True}
    correlation = network.get("developer_identity_correlation")
    if not isinstance(correlation, dict):
        correlation = {"status": "UNKNOWN", "entity_id": developer.get("entity_id"), "wallets": [], "shared_funders": [], "cross_entity_wallet_reuse": [], "deployer_buyer_recurrence": [], "shared_relationship_structures": [], "missing": ["developer_identity_correlation"], "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "ownership_inferred": False, "coordination_inferred": False, "intent_inferred": False, "risk_inferred": False, "quality_inferred": False, "predictive_authority": False, "trade_signal": False, "evidence_only": True}
    developer_entity_id = str(developer.get("entity_id") or correlation.get("entity_id") or "").strip()
    try:
        if developer_entity_id and as_of is None: await persist_developer_snapshot(session, developer)
        developer_audit = await developer_audit_history(session, developer_entity_id, limit=20, as_of=as_of) if developer_entity_id else {"status": "NEW-UNKNOWN", "records": [], "changes": [], "latest_change": None, "missing": ["developer_entity_id"], "evidence_only": True}
    except Exception:
        developer_audit = {"status": "UNKNOWN", "records": [], "changes": [], "latest_change": None, "missing": ["developer_longitudinal_snapshots"], "evidence_only": True}
    try:
        if developer_entity_id and as_of is None: await persist_developer_correlation_snapshot(session, correlation)
        correlation_audit = await developer_correlation_audit_history(session, developer_entity_id, limit=20, as_of=as_of) if developer_entity_id else {"status": "NEW-UNKNOWN", "records": [], "changes": [], "latest_change": None, "missing": ["developer_entity_id"], "evidence_only": True}
    except Exception:
        correlation_audit = {"status": "UNKNOWN", "records": [], "changes": [], "latest_change": None, "missing": ["developer_correlation_snapshots"], "evidence_only": True}
    return {"mint": mint, "status": synthesis.get("status", "UNKNOWN"), "calibration": synthesis, "audit": audit, "latest_change": audit.get("latest_change"),
            "developer": developer, "developer_audit": developer_audit, "developer_latest_change": developer_audit.get("latest_change"),
            "developer_correlation": correlation, "developer_correlation_audit": correlation_audit,
            "developer_correlation_latest_change": correlation_audit.get("latest_change"),
            "evidence_only": True, "ownership_inferred": False, "coordination_inferred": False, "risk_inferred": False, "quality_inferred": False,
            "predictive_authority": False, "trade_signal": False}


@router.get("/research/phase10-readiness")
async def phase10_research_readiness(
    session: Annotated[AsyncSession, Depends(get_session)],
    dataset_limit: int = Query(200, ge=50, le=500),
    feature_horizon: str = Query("5m", pattern="^(launch|5m|15m|30m)$"),
    as_of: datetime | None = Query(None),
    persist_current: bool = Query(True),
) -> dict[str, Any]:
    """Operator-driven live Phase 10 evidence audit; never called by Command Center."""
    return await run_live_phase10_readiness(
        session,
        dataset_limit=dataset_limit,
        feature_horizon=feature_horizon,
        as_of=as_of,
        persist_current=persist_current,
    )


@router.get("/{entity_id}")
async def entity_graph(entity_id: UUID, session: Annotated[AsyncSession, Depends(get_session)], wallet_limit: int = Query(100, ge=1, le=500), relationship_limit: int = Query(500, ge=1, le=500), as_of: datetime | None = Query(None)) -> dict[str, Any]:
    graph = await _assemble(session, entity_id, wallet_limit, relationship_limit, as_of=as_of)
    if graph is None: raise HTTPException(status_code=404, detail="entity not found or invalid as_of")
    return graph