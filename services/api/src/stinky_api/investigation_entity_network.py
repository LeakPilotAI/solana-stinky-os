"""Hydrate investigation responses with bounded entity-network evidence.

This adapter bridges the canonical investigation result to the entity graph
store without putting API/database concerns into stinky-core intelligence.
The network is descriptive evidence only; missing entities remain UNKNOWN.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.entity_graph import _assemble
from stinky_api.entity_history_synthesis import synthesize_entity_history
from stinky_api.funding_history import funding_history_for_entity


def _unknown(*, status: str, wallet_limit: int, relationship_limit: int) -> dict[str, Any]:
    return {
        "status": status,
        "entity": None,
        "wallets": [],
        "relationships": [],
        "funding_history": [],
        "bounded": {
            "wallet_limit": wallet_limit,
            "relationship_limit": relationship_limit,
            "funding_observation_limit": relationship_limit,
        },
        "evidence_only": True,
        "missing": ["entity_history"],
    }


async def entity_network_for_investigation(
    session: AsyncSession,
    *,
    entity_id: str | None = None,
    creator_wallet: str | None = None,
    wallet_limit: int = 100,
    relationship_limit: int = 500,
) -> dict[str, Any]:
    """Resolve creator entity and return bounded network plus funding evidence."""
    wallet_limit = max(1, min(500, int(wallet_limit)))
    relationship_limit = max(1, min(500, int(relationship_limit)))

    resolved_entity_id: UUID | None = None
    if entity_id:
        try:
            resolved_entity_id = UUID(str(entity_id))
        except (TypeError, ValueError, AttributeError):
            resolved_entity_id = None

    if resolved_entity_id is None and creator_wallet:
        try:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT entity_id
                        FROM entity_wallets
                        WHERE wallet = :wallet
                        LIMIT 1
                        """
                    ),
                    {"wallet": str(creator_wallet).strip()},
                )
            ).first()
        except Exception:
            return _unknown(
                status="UNKNOWN",
                wallet_limit=wallet_limit,
                relationship_limit=relationship_limit,
            )
        if row and row[0]:
            try:
                resolved_entity_id = UUID(str(row[0]))
            except (TypeError, ValueError, AttributeError):
                return _unknown(
                    status="UNKNOWN",
                    wallet_limit=wallet_limit,
                    relationship_limit=relationship_limit,
                )

    if resolved_entity_id is None:
        return _unknown(
            status="NEW-UNKNOWN",
            wallet_limit=wallet_limit,
            relationship_limit=relationship_limit,
        )

    try:
        graph = await _assemble(
            session,
            resolved_entity_id,
            wallet_limit,
            relationship_limit,
        )
        if graph is None:
            return _unknown(
                status="UNKNOWN",
                wallet_limit=wallet_limit,
                relationship_limit=relationship_limit,
            )
        funding_history = await funding_history_for_entity(
            session,
            resolved_entity_id,
            wallet_limit=wallet_limit,
            observation_limit=relationship_limit,
        )
        history = await synthesize_entity_history(
            session,
            resolved_entity_id,
            graph=graph,
            funding_history=funding_history,
            launch_limit=relationship_limit,
        )
    except Exception:
        return _unknown(
            status="UNKNOWN",
            wallet_limit=wallet_limit,
            relationship_limit=relationship_limit,
        )

    graph["status"] = "KNOWN_ENTITY"
    graph["funding_history"] = funding_history
    graph["history"] = history
    graph["bounded"]["funding_observation_limit"] = relationship_limit
    graph["bounded"]["launch_history_limit"] = relationship_limit
    graph["evidence_only"] = True
    return graph
