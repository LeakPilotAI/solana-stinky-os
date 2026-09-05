"""Bounded retrieval of direct wallet funding evidence for investigations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def funding_history_for_entity(
    session: AsyncSession,
    entity_id: UUID,
    *,
    wallet_limit: int = 100,
    observation_limit: int = 500,
) -> list[dict[str, Any]]:
    """Return factual funding observations touching bounded entity wallets."""
    wallet_limit = max(1, min(500, int(wallet_limit)))
    observation_limit = max(1, min(500, int(observation_limit)))
    rows = (
        await session.execute(
            text(
                """
                WITH entity_wallets_limited AS (
                    SELECT wallet
                    FROM entity_wallets
                    WHERE entity_id = :entity_id
                    ORDER BY wallet
                    LIMIT :wallet_limit
                )
                SELECT wfo.source_wallet,
                       wfo.destination_wallet,
                       wfo.amount_lamports,
                       wfo.signature,
                       wfo.observed_at,
                       wfo.evidence
                FROM wallet_funding_observations wfo
                WHERE wfo.source_wallet IN (SELECT wallet FROM entity_wallets_limited)
                   OR wfo.destination_wallet IN (SELECT wallet FROM entity_wallets_limited)
                ORDER BY wfo.observed_at DESC, wfo.signature DESC
                LIMIT :observation_limit
                """
            ),
            {
                "entity_id": entity_id,
                "wallet_limit": wallet_limit,
                "observation_limit": observation_limit,
            },
        )
    ).mappings().all()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if hasattr(item.get("observed_at"), "isoformat"):
            item["observed_at"] = item["observed_at"].isoformat()
        result.append(item)
    return result
