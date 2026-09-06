"""Historical outcome context for observed developer-correlation motifs.

This module answers a descriptive question only: what outcomes were already observed
for prior launches attached to entities participating in the same observed motif?
Historical outcomes are analogues, not prediction, risk, quality, confidence, expected
return, or trade authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    if value is None: return None
    if isinstance(value, datetime): return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip(); raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _outcome_visible(status: Any, meta: Any, cutoff: datetime | None) -> tuple[str, Any]:
    raw = str(status or "UNKNOWN").upper()
    status_value = raw if raw in {"RUNNER", "HELD", "FADE", "UNKNOWN"} else "UNKNOWN"
    observed = meta.get("observed_at") if isinstance(meta, dict) else None
    observed_dt = _parse(observed) if observed else None
    if cutoff is not None and status_value != "UNKNOWN":
        if observed_dt is None or observed_dt > cutoff:
            return "UNKNOWN", _iso(observed)
    return status_value, _iso(observed)


def _counts(records: list[dict[str, Any]]) -> dict[str, int]:
    result = {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0}
    for row in records:
        key = str(row.get("outcome") or "UNKNOWN").upper()
        result[key if key in result else "UNKNOWN"] += 1
    return result


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
    cutoff = _parse(as_of)
    if as_of is not None and cutoff is None:
        return {"status": "UNKNOWN", "records": [], "missing": ["valid_as_of"], **AUTHORITY}

    motifs = [m for m in (network_motifs.get("records") or []) if isinstance(m, dict)] if isinstance(network_motifs, dict) else []
    if not motifs:
        return {"status": "NEW-UNKNOWN", "records": [], "motif_analogue_count": 0, "launch_analogue_count": 0,
                "outcome_counts": {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0},
                "analogue_history_is_not_prediction": True, "bounded": {"launch_limit": launch_limit}, **AUTHORITY}

    related_ids = sorted({str(e) for m in motifs for e in (m.get("other_entity_ids") or []) if e})
    if not related_ids:
        return {"status": "UNKNOWN", "records": [], "missing": ["motif_related_entities"], **AUTHORITY}

    params: dict[str, Any] = {"entity_ids": related_ids, "limit": launch_limit, "current_mint": current_mint}
    clause = "AND l.observed_at <= :as_of" if cutoff is not None else ""
    if cutoff is not None: params["as_of"] = cutoff
    try:
        rows = (await session.execute(text(f"""
            SELECT l.entity_id::text AS entity_id, l.mint, l.deployer_wallet, l.observed_at,
                   l.outcome_status, l.outcome_meta, l.created_at
            FROM entity_launches l
            WHERE l.entity_id::text = ANY(:entity_ids)
              AND (:current_mint IS NULL OR l.mint <> :current_mint)
              {clause}
            ORDER BY l.observed_at DESC, l.id DESC
            LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "records": [], "missing": ["historical_motif_launch_outcomes"], **AUTHORITY}

    launches: list[dict[str, Any]] = []
    for row in rows:
        outcome, outcome_observed_at = _outcome_visible(row.get("outcome_status"), row.get("outcome_meta"), cutoff)
        launches.append({
            "entity_id": row.get("entity_id"), "mint": row.get("mint"), "deployer_wallet": row.get("deployer_wallet"),
            "launch_observed_at": _iso(row.get("observed_at")), "outcome": outcome,
            "outcome_observed_at": outcome_observed_at, "ingested_at": _iso(row.get("created_at")),
        })

    by_entity: dict[str, list[dict[str, Any]]] = {}
    for launch in launches: by_entity.setdefault(str(launch.get("entity_id") or ""), []).append(launch)
    analogues: list[dict[str, Any]] = []
    for motif in motifs:
        ids = sorted(str(x) for x in (motif.get("other_entity_ids") or []) if x)
        motif_launches = [launch for eid in ids for launch in by_entity.get(eid, [])]
        if not motif_launches: continue
        analogues.append({
            "motif_kind": motif.get("motif_kind"), "motif_state": motif.get("motif_state"),
            "component_kinds": motif.get("component_kinds") or [], "related_entity_ids": ids,
            "historical_launch_count": len(motif_launches), "outcome_counts": _counts(motif_launches),
            "launches": motif_launches, "analogue_basis": "observed_motif_related_entity_launch_history",
            "analogue_is_not_prediction": True,
        })

    result = {
        "status": "OBSERVED" if analogues else "UNKNOWN",
        "entity_id": str(entity_id), "motif_analogue_count": len(analogues), "launch_analogue_count": len(launches),
        "outcome_counts": _counts(launches), "records": analogues,
        "analogue_history_is_not_prediction": True,
        "bounded": {"launch_limit": launch_limit, "related_entity_count": len(related_ids)},
        **AUTHORITY,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat(); result["temporal_cutoff_enforced"] = True
    return result
