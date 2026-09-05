"""Deterministic entity-level graph assembly from persisted evidence."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def assemble_entity_graph(
    *,
    entity: dict[str, Any],
    wallets: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a descriptive graph without inferring new relationships."""
    entity_id = str(entity["entity_id"])
    wallet_nodes = {
        str(row["wallet"]): {
            "wallet": str(row["wallet"]),
            "entity_id": entity_id,
            "role": row.get("role"),
            "link_reason": row.get("link_reason"),
            "confidence": row.get("confidence"),
            "first_seen_at": row.get("first_seen_at"),
            "last_seen_at": row.get("last_seen_at"),
        }
        for row in wallets
    }

    nodes: dict[str, dict[str, Any]] = {
        f"wallet:{wallet}": node for wallet, node in wallet_nodes.items()
    }
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    for row in relationships:
        a = str(row["wallet_a"])
        b = str(row["wallet_b"])
        kind = str(row["relationship_kind"])
        if a == b:
            continue
        edge_key = (min(a, b), max(a, b), kind)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        for wallet in (a, b):
            if wallet not in wallet_nodes:
                nodes.setdefault(
                    f"wallet:{wallet}",
                    {
                        "wallet": wallet,
                        "entity_id": row.get("entity_a_id") if wallet == a else row.get("entity_b_id"),
                        "role": None,
                        "link_reason": None,
                        "confidence": None,
                        "first_seen_at": None,
                        "last_seen_at": None,
                    },
                )

        edges.append(
            {
                "wallet_a": a,
                "wallet_b": b,
                "relationship_kind": kind,
                "observation_count": row.get("observation_count"),
                "first_seen_at": row.get("first_seen_at"),
                "last_seen_at": row.get("last_seen_at"),
                "confidence": row.get("confidence"),
                "evidence": row.get("evidence") or {},
                "entity_a_id": row.get("entity_a_id"),
                "entity_b_id": row.get("entity_b_id"),
            }
        )

    return {
        "entity": {
            "entity_id": entity_id,
            "entity_type": entity.get("entity_type"),
            "display_label": entity.get("display_label"),
            "primary_wallet": entity.get("primary_wallet"),
            "confidence": entity.get("confidence"),
        },
        "nodes": list(nodes.values()),
        "edges": edges,
        "evidence_only": True,
    }


async def assemble_entity_graph_from_store(
    entity_id: UUID,
    *,
    entity_store: Any,
    relationship_store: Any,
    wallet_limit: int = 100,
    relationship_limit: int = 500,
) -> dict[str, Any] | None:
    """Query persisted evidence and assemble one bounded entity graph."""
    wallet_limit = max(1, min(wallet_limit, 500))
    relationship_limit = max(1, min(relationship_limit, 500))

    wallets = await entity_store.list_wallets(entity_id)
    if not wallets:
        return None

    entity = await entity_store.get_entity_for_wallet(wallets[0]["wallet"])
    if not entity:
        return None

    relationships = await relationship_store.list_entity_relationships(
        entity_id,
        limit=relationship_limit,
        wallet_limit=wallet_limit,
    )
    return assemble_entity_graph(
        entity=entity,
        wallets=wallets[:wallet_limit],
        relationships=relationships,
    )
