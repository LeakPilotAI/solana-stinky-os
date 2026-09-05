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

from stinky_api.db import get_session

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
        # Entity counters are current aggregates, not historical snapshots.
        # They must not masquerade as as-of values.
        for key in ("wallet_count", "launch_count", "early_buy_count"):
            result[key] = None
        result["historical_aggregate_status"] = "UNKNOWN"
        result["historical_aggregate_missing"] = ["entity_snapshot"]
        result["temporal_cutoff_enforced"] = True
    return result


async def _assemble(
    session: AsyncSession,
    entity_id: UUID,
    wallet_limit: int,
    relationship_limit: int,
    *,
    as_of: datetime | str | None = None,
) -> dict[str, Any] | None:
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return None
    entity = (
        await session.execute(
            text("""
                SELECT entity_id::text AS entity_id, entity_type, display_label,
                       primary_wallet, wallet_count, launch_count, early_buy_count,
                       confidence, created_at, updated_at, meta
                FROM entities WHERE entity_id = :entity_id
            """),
            {"entity_id": entity_id},
        )
    ).mappings().first()
    if entity is None:
        return None
    entity = dict(entity)
    if cutoff is not None and entity.get("created_at") is not None and entity["created_at"] > cutoff:
        return None

    wallet_clause = "AND first_seen_at <= :as_of" if cutoff is not None else ""
    wallet_params: dict[str, Any] = {"entity_id": entity_id, "wallet_limit": wallet_limit}
    if cutoff is not None:
        wallet_params["as_of"] = cutoff
    wallets = (
        await session.execute(
            text(f"""
                SELECT wallet, entity_id::text AS entity_id, role, link_reason,
                       confidence, first_seen_at, last_seen_at, evidence
                FROM entity_wallets
                WHERE entity_id = :entity_id
                  {wallet_clause}
                ORDER BY first_seen_at ASC NULLS LAST, wallet ASC
                LIMIT :wallet_limit
            """),
            wallet_params,
        )
    ).mappings().all()
    wallet_values = [str(row["wallet"]) for row in wallets]
    if not wallet_values:
        result = {
            "entity": _historical_entity(entity, cutoff),
            "wallets": [], "relationships": [],
            "bounded": {"wallet_limit": wallet_limit, "relationship_limit": relationship_limit},
            "evidence_only": True, "status": "KNOWN_ENTITY_NO_WALLET_EDGES",
        }
        if cutoff is not None:
            result["as_of"] = cutoff.isoformat()
            result["temporal_cutoff_enforced"] = True
        return result

    relationship_clause = "AND wr.first_seen_at <= :as_of" if cutoff is not None else ""
    relationship_params: dict[str, Any] = {"wallets": wallet_values, "relationship_limit": relationship_limit}
    if cutoff is not None:
        relationship_params["as_of"] = cutoff
    relationships = (
        await session.execute(
            text(f"""
                SELECT wr.wallet_a, wr.wallet_b, wr.relationship_kind,
                       wr.observation_count, wr.first_seen_at, wr.last_seen_at,
                       wr.confidence, wr.evidence,
                       ea.entity_id::text AS entity_a_id, eb.entity_id::text AS entity_b_id
                FROM wallet_relationships wr
                LEFT JOIN entity_wallets wa ON wa.wallet = wr.wallet_a
                LEFT JOIN entity_wallets wb ON wb.wallet = wr.wallet_b
                LEFT JOIN entities ea ON ea.entity_id = wa.entity_id
                LEFT JOIN entities eb ON eb.entity_id = wb.entity_id
                WHERE (wr.wallet_a = ANY(:wallets) OR wr.wallet_b = ANY(:wallets))
                  {relationship_clause}
                ORDER BY wr.observation_count DESC NULLS LAST,
                         wr.last_seen_at DESC NULLS LAST,
                         wr.wallet_a, wr.wallet_b
                LIMIT :relationship_limit
            """),
            relationship_params,
        )
    ).mappings().all()

    seen: set[tuple[str, str, str]] = set()
    edges: list[dict[str, Any]] = []
    for row in relationships:
        a, b, kind = str(row["wallet_a"]), str(row["wallet_b"]), str(row["relationship_kind"])
        if a == b:
            continue
        key = (min(a, b), max(a, b), kind)
        if key in seen:
            continue
        seen.add(key)
        edge = dict(row)
        first_seen = edge.get("first_seen_at")
        last_seen = edge.get("last_seen_at")
        edge["first_seen_at"] = _iso(first_seen)
        edge["last_seen_at"] = _iso(last_seen)
        if cutoff is not None and last_seen is not None and last_seen > cutoff:
            # Relationship counts are cumulative aggregates. Once their last
            # observation is after the cutoff, the historical count cannot be
            # reconstructed from this table without leaking future evidence.
            edge["observation_count"] = None
            edge["last_seen_at"] = None
            edge["historical_observation_status"] = "UNKNOWN"
            edge["historical_observation_missing"] = ["relationship_observation_history"]
        edges.append(edge)

    historical_wallets = []
    for row in wallets:
        item = dict(row)
        last_seen = item.get("last_seen_at")
        item["first_seen_at"] = _iso(item.get("first_seen_at"))
        item["last_seen_at"] = _iso(last_seen)
        if cutoff is not None and last_seen is not None and last_seen > cutoff:
            item["last_seen_at"] = None
            item["historical_last_seen_status"] = "UNKNOWN"
            item["historical_last_seen_missing"] = ["wallet_observation_history"]
        historical_wallets.append(item)

    result = {
        "entity": _historical_entity(entity, cutoff),
        "wallets": historical_wallets,
        "relationships": edges,
        "bounded": {"wallet_limit": wallet_limit, "relationship_limit": relationship_limit},
        "evidence_only": True, "status": "KNOWN_ENTITY",
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result


@router.get("/{entity_id}")
async def entity_graph(
    entity_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    wallet_limit: int = Query(100, ge=1, le=500),
    relationship_limit: int = Query(500, ge=1, le=500),
    as_of: datetime | None = Query(None),
) -> dict[str, Any]:
    """Return a bounded descriptive graph for one known entity."""
    graph = await _assemble(session, entity_id, wallet_limit, relationship_limit, as_of=as_of)
    if graph is None:
        raise HTTPException(status_code=404, detail="entity not found or invalid as_of")
    return graph
