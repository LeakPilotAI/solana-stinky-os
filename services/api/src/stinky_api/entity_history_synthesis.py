"""Synthesize bounded entity history evidence for Genesis investigations.

This module combines independently persisted evidence surfaces without turning
observations into quality, risk, ownership, intent, prediction, or trading
signals. Each source retains its own evidence basis and unknown state.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _unknown_source(reason: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "records": [], "missing": [reason]}


async def synthesize_entity_history(
    session: AsyncSession,
    entity_id: UUID,
    *,
    graph: dict[str, Any],
    funding_history: list[dict[str, Any]],
    launch_limit: int = 100,
) -> dict[str, Any]:
    """Combine independent entity evidence into one bounded descriptive record."""
    launch_limit = max(1, min(500, int(launch_limit)))

    try:
        launch_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, entity_id::text AS entity_id, deployer_wallet, mint,
                           event_id, observed_at, outcome_status, outcome_meta, created_at
                    FROM entity_launches
                    WHERE entity_id = :entity_id
                    ORDER BY observed_at DESC, id DESC
                    LIMIT :launch_limit
                    """
                ),
                {"entity_id": entity_id, "launch_limit": launch_limit},
            )
        ).mappings().all()
        launches = []
        for row in launch_rows:
            item = dict(row)
            item["observed_at"] = _iso(item.get("observed_at"))
            item["created_at"] = _iso(item.get("created_at"))
            launches.append(item)
        launch_history = {
            "status": "OBSERVED",
            "records": launches,
            "evidence_basis": "entity_launches",
        }
    except Exception:
        launch_history = _unknown_source("launch_history")
        launch_history["evidence_basis"] = "unknown_table_or_query"

    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT fingerprint, computed_at
                    FROM entity_behavior_fingerprints
                    WHERE entity_id = :entity_id
                    LIMIT 1
                    """
                ),
                {"entity_id": entity_id},
            )
        ).mappings().first()
        if row is None:
            behavior = _unknown_source("behavior_fingerprint")
            behavior["evidence_basis"] = "no_persisted_fingerprint"
        else:
            behavior = {
                "status": "OBSERVED",
                "fingerprint": row["fingerprint"],
                "computed_at": _iso(row["computed_at"]),
                "evidence_basis": "entity_behavior_fingerprints",
            }
    except Exception:
        behavior = _unknown_source("behavior_fingerprint")
        behavior["evidence_basis"] = "unknown_table_or_query"

    relationships = {
        "status": "OBSERVED",
        "wallets": list(graph.get("wallets") or []),
        "records": list(graph.get("relationships") or []),
        "evidence_basis": "entity_wallets+wallet_relationships",
    }

    funding = {
        "status": "OBSERVED",
        "records": list(funding_history),
        "evidence_basis": "wallet_funding_observations+direct_transfer_observation",
    }

    return {
        "status": "KNOWN_ENTITY",
        "entity_id": str(entity_id),
        "launch_history": launch_history,
        "behavior_fingerprint": behavior,
        "wallet_relationships": relationships,
        "funding_history": funding,
        "bounded": {
            "launch_limit": launch_limit,
            "wallet_limit": graph.get("bounded", {}).get("wallet_limit"),
            "relationship_limit": graph.get("bounded", {}).get("relationship_limit"),
            "funding_observation_limit": graph.get("bounded", {}).get("funding_observation_limit"),
        },
        "evidence_only": True,
    }
