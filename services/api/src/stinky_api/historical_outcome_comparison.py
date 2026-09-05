"""Descriptive outcome evidence for previously observed historical analogues.

This module compares only measured lifecycle outcomes already persisted for
analogue entities. It does not infer missing outcomes or convert history into
prediction, quality, risk, intent, or trading semantics.
"""

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
        text_value = str(value).strip()
        if text_value.endswith("Z"):
            text_value = text_value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text_value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def historical_outcomes_for_analogues(
    session: AsyncSession,
    analogue_records: list[dict[str, Any]],
    *,
    limit_per_entity: int = 20,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Attach bounded observed launch outcomes to analogue IDs at an optional cutoff."""
    limit_per_entity = max(1, min(100, int(limit_per_entity)))
    cutoff = _parse_as_of(as_of)
    if as_of is not None and cutoff is None:
        return {
            "status": "UNKNOWN",
            "records": [],
            "missing": ["invalid_as_of"],
            "evidence_basis": "entity_launches",
            "bounded": {"limit_per_entity": limit_per_entity},
            "evidence_only": True,
        }

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
        cutoff_clause = "AND observed_at <= :as_of" if cutoff is not None else ""
        params: dict[str, Any] = {"entity_ids": analogue_ids}
        if cutoff is not None:
            params["as_of"] = cutoff
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT entity_id::text AS entity_id,
                           mint,
                           event_id,
                           observed_at,
                           outcome_status,
                           outcome_meta
                    FROM entity_launches
                    WHERE entity_id = ANY(CAST(:entity_ids AS uuid[]))
                      {cutoff_clause}
                    ORDER BY entity_id, observed_at DESC, id DESC
                    """
                ),
                params,
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

    result = {
        "status": "OBSERVED",
        "records": records,
        "evidence_basis": "entity_launches",
        "bounded": {"limit_per_entity": limit_per_entity},
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
