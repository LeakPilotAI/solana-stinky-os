"""Descriptive outcome evidence for previously observed historical analogues.

This module compares only measured lifecycle outcomes already persisted for
analogue entities. It does not infer missing outcomes or convert history into
prediction, quality, risk, intent, or trading semantics.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def historical_outcomes_for_analogues(
    session: AsyncSession,
    analogue_records: list[dict[str, Any]],
    *,
    limit_per_entity: int = 20,
) -> dict[str, Any]:
    """Attach bounded observed launch outcomes to historical analogue IDs."""
    limit_per_entity = max(1, min(100, int(limit_per_entity)))
    analogue_ids: list[UUID] = []
    for record in analogue_records:
        try:
            analogue_ids.append(UUID(str(record["entity_id"])))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue

    if not analogue_ids:
        return {
            "status": "UNKNOWN",
            "records": [],
            "missing": ["historical_analogue_ids"],
            "evidence_basis": "entity_launches",
            "bounded": {"limit_per_entity": limit_per_entity},
            "evidence_only": True,
        }

    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT entity_id::text AS entity_id,
                           mint,
                           event_id,
                           observed_at,
                           outcome_status,
                           outcome_meta
                    FROM entity_launches
                    WHERE entity_id = ANY(CAST(:entity_ids AS uuid[]))
                    ORDER BY entity_id, observed_at DESC, id DESC
                    """
                ),
                {"entity_ids": analogue_ids},
            )
        ).mappings().all()
    except Exception:
        return {
            "status": "UNKNOWN",
            "records": [],
            "missing": ["entity_launches"],
            "evidence_basis": "entity_launches",
            "bounded": {"limit_per_entity": limit_per_entity},
            "evidence_only": True,
        }

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        entity_id = str(row["entity_id"])
        bucket = grouped.setdefault(entity_id, [])
        if len(bucket) >= limit_per_entity:
            continue
        observed_at = row.get("observed_at")
        bucket.append(
            {
                "mint": row.get("mint"),
                "event_id": row.get("event_id"),
                "observed_at": observed_at.isoformat() if hasattr(observed_at, "isoformat") else observed_at,
                "outcome_status": row.get("outcome_status"),
                "outcome_meta": row.get("outcome_meta") or {},
                "outcome_observed": row.get("outcome_status") is not None,
            }
        )

    records: list[dict[str, Any]] = []
    for analogue in analogue_records:
        entity_id = str(analogue.get("entity_id", ""))
        launches = grouped.get(entity_id, [])
        known = sum(1 for launch in launches if launch["outcome_observed"])
        completed = sum(1 for launch in launches if launch["outcome_status"] == "completed")
        unknown = len(launches) - known
        records.append(
            {
                "entity_id": entity_id,
                "launches": launches,
                "launch_count_observed": len(launches),
                "outcomes_known": known,
                "completed_count": completed,
                "outcomes_unknown": unknown,
                "evidence_basis": "entity_launches",
            }
        )

    return {
        "status": "OBSERVED",
        "records": records,
        "evidence_basis": "entity_launches",
        "bounded": {"limit_per_entity": limit_per_entity},
        "evidence_only": True,
    }
