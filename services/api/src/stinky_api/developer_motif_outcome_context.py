"""Historical outcome and lifecycle context for observed developer-correlation motifs.

This module answers a descriptive question only: what outcomes and lifecycle evidence
were already observed for prior launches attached to entities participating in the
same observed motif? Historical analogues are not prediction, risk, quality,
confidence, expected return, or trade authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.historical_launch_outcome_provenance import historical_launch_outcome_provenance
from stinky_api.lifecycle_analogue_distribution import load_lifecycle_memories_for_mints, synthesize_lifecycle_distribution

AUTHORITY = {
    "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "ownership_inferred": False,
    "coordination_inferred": False,
    "expected_return_inferred": False,
    "evidence_only": True,
}


def _parse(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip()
        raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _counts(records: list[dict[str, Any]]) -> dict[str, int]:
    result = {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0}
    for row in records:
        key = str(row.get("outcome") or "UNKNOWN").upper()
        result[key if key in result else "UNKNOWN"] += 1
    return result


def _empty_distribution() -> dict[str, Any]:
    return synthesize_lifecycle_distribution([])


async def motif_outcome_context(
    session: AsyncSession,
    entity_id: UUID,
    *,
    network_motifs: dict[str, Any],
    current_mint: str | None = None,
    as_of: datetime | str | None = None,
    launch_limit: int = 100,
) -> dict[str, Any]:
    launch_limit = max(1, min(500, int(launch_limit)))
    entity_key = str(entity_id)
    cutoff = _parse(as_of)
    if as_of is not None and cutoff is None:
        return {"status": "UNKNOWN", "entity_id": entity_key, "records": [], "lifecycle_distribution": _empty_distribution(), "missing": ["valid_as_of"], **AUTHORITY}

    reference_provenance = None
    if current_mint:
        try:
            reference_provenance = await historical_launch_outcome_provenance(session, current_mint, as_of=cutoff, observation_limit=20)
        except Exception:
            reference_provenance = {"status": "UNKNOWN", "mint": current_mint, "outcome": "UNKNOWN", "observations": [], "missing": ["reference_launch_outcome_provenance"], **AUTHORITY}

    motifs = [m for m in (network_motifs.get("records") or []) if isinstance(m, dict)] if isinstance(network_motifs, dict) else []
    if not motifs:
        return {
            "status": "NEW-UNKNOWN", "entity_id": entity_key, "records": [], "motif_analogue_count": 0, "launch_analogue_count": 0,
            "outcome_counts": {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0}, "lifecycle_distribution": _empty_distribution(),
            "reference_launch_outcome_provenance": reference_provenance, "analogue_history_is_not_prediction": True,
            "bounded": {"launch_limit": launch_limit}, **AUTHORITY,
        }

    related_ids = sorted({str(e) for m in motifs for e in (m.get("other_entity_ids") or []) if e})
    if not related_ids:
        return {"status": "UNKNOWN", "entity_id": entity_key, "records": [], "lifecycle_distribution": _empty_distribution(), "reference_launch_outcome_provenance": reference_provenance, "missing": ["motif_related_entities"], **AUTHORITY}

    params: dict[str, Any] = {"entity_ids": related_ids, "limit": launch_limit, "current_mint": current_mint}
    clause = "AND l.observed_at <= :as_of" if cutoff is not None else ""
    if cutoff is not None:
        params["as_of"] = cutoff
    try:
        rows = (await session.execute(text(f"""
            SELECT l.entity_id::text AS entity_id, l.mint, l.deployer_wallet,
                   l.observed_at, l.created_at
            FROM entity_launches l
            WHERE l.entity_id::text = ANY(:entity_ids)
              AND (:current_mint IS NULL OR l.mint <> :current_mint)
              {clause}
            ORDER BY l.observed_at DESC, l.id DESC
            LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "entity_id": entity_key, "records": [], "lifecycle_distribution": _empty_distribution(), "reference_launch_outcome_provenance": reference_provenance, "missing": ["historical_motif_launch_outcomes"], **AUTHORITY}

    launch_rows = [dict(row) for row in rows if row.get("mint")]
    mints = [str(row.get("mint")) for row in launch_rows]
    try:
        lifecycle = await load_lifecycle_memories_for_mints(session, mints, as_of=cutoff, mint_limit=launch_limit)
    except Exception:
        lifecycle = {"memories": [], "distribution": _empty_distribution(), "bounded": {"mint_limit": launch_limit, "query_count": 0}, **AUTHORITY}
    memory_by_mint = {str(memory.get("mint") or ""): memory for memory in lifecycle.get("memories", []) if isinstance(memory, dict)}

    launches: list[dict[str, Any]] = []
    for row in launch_rows:
        mint = str(row.get("mint") or "")
        memory = memory_by_mint.get(mint)
        outcome = str(memory.get("outcome") or "UNKNOWN") if isinstance(memory, dict) else "UNKNOWN"
        event = memory.get("outcome_event") if isinstance(memory, dict) and isinstance(memory.get("outcome_event"), dict) else {}
        launches.append({
            "entity_id": row.get("entity_id"), "mint": mint, "deployer_wallet": row.get("deployer_wallet"),
            "launch_observed_at": _iso(row.get("observed_at")), "ingested_at": _iso(row.get("created_at")),
            "outcome": outcome,
            "outcome_observed_at": _iso(event.get("occurred_at")),
            "outcome_ingested_at": _iso(event.get("ingested_at")),
            "outcome_resolution_basis": memory.get("outcome_resolution_basis") if isinstance(memory, dict) else "UNKNOWN",
            "lifecycle_memory": memory,
        })

    by_entity: dict[str, list[dict[str, Any]]] = {}
    for launch in launches:
        by_entity.setdefault(str(launch.get("entity_id") or ""), []).append(launch)

    analogues: list[dict[str, Any]] = []
    for motif in motifs:
        ids = sorted(str(x) for x in (motif.get("other_entity_ids") or []) if x)
        motif_launches = [launch for eid in ids for launch in by_entity.get(eid, [])]
        if not motif_launches:
            continue
        motif_memories = [launch.get("lifecycle_memory") for launch in motif_launches if isinstance(launch.get("lifecycle_memory"), dict)]
        analogues.append({
            "motif_kind": motif.get("motif_kind"), "motif_state": motif.get("motif_state"),
            "component_kinds": motif.get("component_kinds") or [], "related_entity_ids": ids,
            "historical_launch_count": len(motif_launches), "outcome_counts": _counts(motif_launches),
            "lifecycle_distribution": synthesize_lifecycle_distribution(motif_memories),
            "launches": motif_launches, "analogue_basis": "observed_motif_related_entity_launch_lifecycle_history",
            "analogue_is_not_prediction": True,
        })

    result = {
        "status": "OBSERVED" if analogues else "UNKNOWN",
        "entity_id": entity_key, "motif_analogue_count": len(analogues), "launch_analogue_count": len(launches),
        "outcome_counts": _counts(launches), "lifecycle_distribution": lifecycle.get("distribution") or _empty_distribution(),
        "records": analogues, "reference_launch_outcome_provenance": reference_provenance,
        "analogue_history_is_not_prediction": True,
        "bounded": {
            "launch_limit": launch_limit, "related_entity_count": len(related_ids),
            "lifecycle_mint_limit": lifecycle.get("bounded", {}).get("mint_limit"),
            "lifecycle_query_count": lifecycle.get("bounded", {}).get("query_count"),
        },
        **AUTHORITY,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
