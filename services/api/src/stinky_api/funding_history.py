"""Bounded retrieval of direct wallet funding evidence for investigations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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


async def funding_history_for_entity(
    session: AsyncSession,
    entity_id: UUID,
    *,
    wallet_limit: int = 100,
    observation_limit: int = 500,
    as_of: datetime | str | None = None,
) -> list[dict[str, Any]]:
    """Return factual funding observations touching bounded entity wallets."""
    wallet_limit = max(1, min(500, int(wallet_limit)))
    observation_limit = max(1, min(500, int(observation_limit)))
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return []
    cutoff_clause = "AND wfo.observed_at <= :as_of" if cutoff is not None else ""
    params: dict[str, Any] = {
        "entity_id": entity_id,
        "wallet_limit": wallet_limit,
        "observation_limit": observation_limit,
    }
    if cutoff is not None:
        params["as_of"] = cutoff
    rows = (
        await session.execute(
            text(
                f"""
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
                       wfo.created_at,
                       wfo.evidence
                FROM wallet_funding_observations wfo
                WHERE (wfo.source_wallet IN (SELECT wallet FROM entity_wallets_limited)
                   OR wfo.destination_wallet IN (SELECT wallet FROM entity_wallets_limited))
                  {cutoff_clause}
                ORDER BY wfo.observed_at DESC, wfo.signature DESC
                LIMIT :observation_limit
                """
            ),
            params,
        )
    ).mappings().all()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if hasattr(item.get("observed_at"), "isoformat"):
            item["observed_at"] = item["observed_at"].isoformat()
        if hasattr(item.get("created_at"), "isoformat"):
            item["created_at"] = item["created_at"].isoformat()
        item["ingested_at"] = item.get("created_at")
        result.append(item)
    return result
