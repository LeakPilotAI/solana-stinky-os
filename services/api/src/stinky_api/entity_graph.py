"""Read-only entity relationship graph API for Genesis investigations.

The graph is descriptive evidence only. It never assigns quality, risk,
prediction, or trade direction. Bounds are enforced at the API boundary.
"""

from __future__ import annotations

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


async def _assemble(
    session: AsyncSession,
    entity_id: UUID,
    wallet_limit: int,
    relationship_limit: int,
) -> dict[str, Any] | None:
    entity = (
        await session.execute(
            text(
                """
                SELECT entity_id::text AS entity_id, entity_type, display_label,
                       primary_wallet, wallet_count, launch_count, early_buy_count,
                       confidence, created_at, updated_at, meta
                FROM entities
                WHERE entity_id = :entity_id
                """
            ),
            {"entity_id": entity_id},
        )
    ).mappings().first()
    if entity is None:
        return None

    wallets = (
        await session.execute(
            text(
                """
                SELECT wallet, entity_id::text AS entity_id, role, link_reason,
                       confidence, first_seen_at, last_seen_at, evidence
                FROM entity_wallets
                WHERE entity_id = :entity_id
                ORDER BY first_seen_at ASC NULLS LAST, wallet ASC
                LIMIT :wallet_limit
                """
            ),
            {"entity_id": entity_id, "wallet_limit": wallet_limit},
        )
    ).mappings().all()
    wallet_values = [str(row["wallet"]) for row in wallets]
    if not wallet_values:
        return {
            "entity": {k: (_iso(v) if k in {"created_at", "updated_at"} else v) for k, v in dict(entity).items()},
            "wallets": [],
            "relationships": [],
            "bounded": {"wallet_limit": wallet_limit, "relationship_limit": relationship_limit},
            "evidence_only": True,
            "status": "KNOWN_ENTITY_NO_WALLET_EDGES",
        }

    relationships = (
        await session.execute(
            text(
                """
                SELECT
                    wr.wallet_a,
                    wr.wallet_b,
                    wr.relationship_kind,
                    wr.observation_count,
                    wr.first_seen_at,
                    wr.last_seen_at,
                    wr.confidence,
                    wr.evidence,
                    ea.entity_id::text AS entity_a_id,
                    eb.entity_id::text AS entity_b_id
                FROM wallet_relationships wr
                LEFT JOIN entity_wallets wa ON wa.wallet = wr.wallet_a
                LEFT JOIN entity_wallets wb ON wb.wallet = wr.wallet_b
                LEFT JOIN entities ea ON ea.entity_id = wa.entity_id
                LEFT JOIN entities eb ON eb.entity_id = wb.entity_id
                WHERE wr.wallet_a = ANY(:wallets) OR wr.wallet_b = ANY(:wallets)
                ORDER BY wr.observation_count DESC NULLS LAST,
                         wr.last_seen_at DESC NULLS LAST,
                         wr.wallet_a, wr.wallet_b
                LIMIT :relationship_limit
                """
            ),
            {"wallets": wallet_values, "relationship_limit": relationship_limit},
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
        edge["first_seen_at"] = _iso(edge.get("first_seen_at"))
        edge["last_seen_at"] = _iso(edge.get("last_seen_at"))
        edges.append(edge)

    return {
        "entity": {k: (_iso(v) if k in {"created_at", "updated_at"} else v) for k, v in dict(entity).items()},
        "wallets": [
            {k: (_iso(v) if k in {"first_seen_at", "last_seen_at"} else v) for k, v in dict(row).items()}
            for row in wallets
        ],
        "relationships": edges,
        "bounded": {"wallet_limit": wallet_limit, "relationship_limit": relationship_limit},
        "evidence_only": True,
        "status": "KNOWN_ENTITY",
    }


@router.get("/{entity_id}")
async def entity_graph(
    entity_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    wallet_limit: int = Query(100, ge=1, le=500),
    relationship_limit: int = Query(500, ge=1, le=500),
) -> dict[str, Any]:
    """Return a bounded descriptive graph for one known entity."""
    graph = await _assemble(session, entity_id, wallet_limit, relationship_limit)
    if graph is None:
        raise HTTPException(status_code=404, detail="entity not found")
    return graph
