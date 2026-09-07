"""Operator-facing entity readiness summaries for the Command Center.

This surface only explains stored readiness evidence. It does not score, rank,
predict, infer risk/quality, or create trading authority.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.db import get_session
from stinky_api.entity_readiness_transition_audit import (
    AUTHORITY,
    describe_entity_readiness_transition,
    ensure_entity_readiness_audit_table,
)
from stinky_api.entity_graph import router


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def summarize_readiness_records(rows: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Collapse chronological immutable snapshots into operator explainability rows."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identity: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        entity_id = str(row.get("entity_id") or "").strip()
        if not entity_id:
            continue
        grouped[entity_id].append(row)
        identity[entity_id] = {
            "entity_id": entity_id,
            "primary_wallet": row.get("primary_wallet"),
            "display_label": row.get("display_label"),
        }

    out: list[dict[str, Any]] = []
    for entity_id, records in grouped.items():
        records.sort(key=lambda r: (_dt(r.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc), int(r.get("id") or 0)))
        previous: dict[str, Any] | None = None
        latest_transition: dict[str, Any] | None = None
        regressions = 0
        for record in records:
            readiness = record.get("readiness") if isinstance(record.get("readiness"), dict) else {}
            transition = describe_entity_readiness_transition(previous, readiness)
            latest_transition = transition
            if transition.get("transition") == "REGRESSED_FROM_DESCRIPTIVE_CALIBRATION_READINESS":
                regressions += 1
            previous = readiness
        latest = records[-1]
        readiness = latest.get("readiness") if isinstance(latest.get("readiness"), dict) else {}
        components = readiness.get("components") if isinstance(readiness.get("components"), dict) else {}
        out.append({
            **identity[entity_id],
            "status": readiness.get("status") or "UNKNOWN",
            "ready": bool(readiness.get("ready")),
            "blockers": [str(x) for x in (readiness.get("blockers") or [])],
            "components": {
                name: {
                    "status": (components.get(name) or {}).get("status") if isinstance(components.get(name), dict) else None,
                    "passed": bool((components.get(name) or {}).get("passed")) if isinstance(components.get(name), dict) else False,
                    "blockers": [str(x) for x in ((components.get(name) or {}).get("blockers") or [])] if isinstance(components.get(name), dict) else [],
                }
                for name in ("developer_history", "relationship_history", "outcome_history")
            },
            "latest_transition": (latest_transition or {}).get("transition") or "INITIAL_STATE",
            "latest_changes": list((latest_transition or {}).get("changes") or []),
            "regression_count": regressions,
            "snapshot_count": len(records),
            "observed_at": latest.get("observed_at").isoformat() if hasattr(latest.get("observed_at"), "isoformat") else latest.get("observed_at"),
            "interpretation": "DESCRIPTIVE_READINESS_EXPLAINABILITY_ONLY",
            **{k: v for k, v in AUTHORITY.items() if k != "interpretation"},
        })

    out.sort(key=lambda r: (str(r.get("observed_at") or ""), str(r.get("entity_id") or "")), reverse=True)
    return out[: max(1, min(25, int(limit)))]


async def command_center_readiness_summary(
    session: AsyncSession,
    *,
    limit: int = 8,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    cutoff = _dt(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        return {"status": "UNKNOWN", "items": [], "blockers": ["INVALID_AS_OF"], "evidence_only": True}
    try:
        await ensure_entity_readiness_audit_table(session)
        clause = "WHERE ers.observed_at <= :as_of AND ers.ingested_at <= :as_of" if cutoff is not None else ""
        params: dict[str, Any] = {"row_limit": max(50, min(1000, int(limit) * 100))}
        if cutoff is not None:
            params["as_of"] = cutoff
        rows = (await session.execute(text(f"""
            SELECT ers.id, ers.entity_id::text AS entity_id, ers.readiness,
                   ers.observed_at, ers.ingested_at,
                   e.primary_wallet, e.display_label
            FROM entity_readiness_snapshots ers
            LEFT JOIN entities e ON e.entity_id = ers.entity_id
            {clause}
            ORDER BY ers.observed_at DESC, ers.id DESC
            LIMIT :row_limit
        """), params)).mappings().all()
    except Exception:
        return {
            "status": "UNKNOWN",
            "items": [],
            "missing": ["entity_readiness_snapshots"],
            "interpretation": "DESCRIPTIVE_READINESS_EXPLAINABILITY_ONLY",
            "predictive_authority": False,
            "risk_inferred": False,
            "quality_inferred": False,
            "trade_signal": False,
            "evidence_only": True,
        }
    items = summarize_readiness_records([dict(r) for r in rows], limit=limit)
    result: dict[str, Any] = {
        "status": "OBSERVED" if items else "UNKNOWN",
        "items": items,
        "count": len(items),
        "note": "Calibration readiness is descriptive evidence sufficiency, not token quality, risk, prediction, or a buy/sell signal.",
        "interpretation": "DESCRIPTIVE_READINESS_EXPLAINABILITY_ONLY",
        "predictive_authority": False,
        "risk_inferred": False,
        "quality_inferred": False,
        "trade_signal": False,
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result


@router.get("/command-center-readiness")
async def command_center_readiness_endpoint(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(8, ge=1, le=25),
    as_of: datetime | None = Query(None),
) -> dict[str, Any]:
    return await command_center_readiness_summary(session, limit=limit, as_of=as_of)


@router.get("/live-readiness-cohort")
async def live_readiness_cohort_endpoint(
    session: AsyncSession = Depends(get_session),
    entity_limit: int = Query(100, ge=1, le=500),
    snapshot_limit: int = Query(100, ge=2, le=200),
    as_of: datetime | None = Query(None),
    include_entities: bool = Query(False),
) -> dict[str, Any]:
    """Read-only live cohort validation executed inside the running Genesis API runtime."""
    from stinky_api.entity_readiness_live_cohort import live_entity_readiness_cohort_validation

    return await live_entity_readiness_cohort_validation(
        session,
        entity_limit=entity_limit,
        snapshot_limit_per_entity=snapshot_limit,
        as_of=as_of,
        include_entities=include_entities,
    )
