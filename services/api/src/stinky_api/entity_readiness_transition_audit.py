"""Immutable audit and transition semantics for combined entity calibration readiness.

Transitions describe evidence-state changes only. They do not create predictive,
risk/quality, ownership/coordination, or trading authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "DESCRIPTIVE_READINESS_TRANSITION_ONLY",
    "ownership_inferred": False,
    "coordination_inferred": False,
    "intent_inferred": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "predictive_authority": False,
    "trade_signal": False,
    "evidence_only": True,
}


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


def _component(value: Any) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    return {
        "status": row.get("status"),
        "passed": bool(row.get("passed")),
        "blockers": sorted(str(x) for x in (row.get("blockers") or [])),
        "launch_count_observed": row.get("launch_count_observed"),
        "outcomes_known": row.get("outcomes_known"),
        "outcome_coverage": row.get("outcome_coverage"),
        "evidence_hash": row.get("evidence_hash"),
    }


def canonical_entity_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
    components = readiness.get("components") if isinstance(readiness.get("components"), dict) else {}
    temporal = readiness.get("temporal_integrity") if isinstance(readiness.get("temporal_integrity"), dict) else {}
    independence = readiness.get("evidence_independence") if isinstance(readiness.get("evidence_independence"), dict) else {}
    return {
        "status": readiness.get("status"),
        "ready": bool(readiness.get("ready")),
        "blockers": sorted(str(x) for x in (readiness.get("blockers") or [])),
        "components": {
            "developer_history": _component(components.get("developer_history")),
            "relationship_history": _component(components.get("relationship_history")),
            "outcome_history": _component(components.get("outcome_history")),
        },
        "temporal_integrity": {str(k): temporal.get(k) for k in sorted(temporal)},
        "evidence_independence": {str(k): independence.get(k) for k in sorted(independence)},
        "calibration_scope": readiness.get("calibration_scope"),
        **AUTHORITY,
    }


def entity_readiness_hash(readiness: dict[str, Any]) -> str:
    raw = json.dumps(canonical_entity_readiness(readiness), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def describe_entity_readiness_transition(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    cur = canonical_entity_readiness(current)
    if previous is None:
        return {"transition": "INITIAL_STATE", "changed": False, "changes": [], **AUTHORITY}
    prev = canonical_entity_readiness(previous)
    if prev == cur:
        return {"transition": "UNCHANGED", "changed": False, "changes": [], **AUTHORITY}

    changes: list[dict[str, Any]] = []
    if prev["ready"] != cur["ready"]:
        changes.append({"kind": "READINESS_CHANGED", "before": prev["ready"], "after": cur["ready"]})
    if prev["status"] != cur["status"]:
        changes.append({"kind": "STATUS_CHANGED", "before": prev["status"], "after": cur["status"]})
    before_blockers, after_blockers = set(prev["blockers"]), set(cur["blockers"])
    if before_blockers != after_blockers:
        changes.append({
            "kind": "BLOCKERS_CHANGED",
            "added": sorted(after_blockers - before_blockers),
            "resolved": sorted(before_blockers - after_blockers),
        })
    for name in ("developer_history", "relationship_history", "outcome_history"):
        if prev["components"][name] != cur["components"][name]:
            changes.append({"kind": "COMPONENT_CHANGED", "component": name, "before": prev["components"][name], "after": cur["components"][name]})

    if not prev["ready"] and cur["ready"]:
        transition = "BECAME_READY_FOR_DESCRIPTIVE_CALIBRATION"
    elif prev["ready"] and not cur["ready"]:
        transition = "REGRESSED_FROM_DESCRIPTIVE_CALIBRATION_READINESS"
    else:
        transition = "READINESS_EVIDENCE_CHANGED"
    return {"transition": transition, "changed": True, "changes": changes, **AUTHORITY}


async def ensure_entity_readiness_audit_table(session: AsyncSession) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS entity_readiness_snapshots (
            id BIGSERIAL PRIMARY KEY,
            entity_id UUID NOT NULL,
            evidence_hash TEXT NOT NULL,
            readiness JSONB NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (entity_id, evidence_hash)
        )
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_entity_readiness_snapshots_entity_time
        ON entity_readiness_snapshots(entity_id, observed_at DESC, id DESC)
    """))


async def _insert_snapshot(
    session: AsyncSession,
    *,
    entity_id: str,
    digest: str,
    readiness_json: str,
    observed_at: datetime,
    ingested_at: datetime,
) -> None:
    await ensure_entity_readiness_audit_table(session)
    await session.execute(text("""
        INSERT INTO entity_readiness_snapshots (
            entity_id, evidence_hash, readiness, observed_at, ingested_at
        )
        VALUES (
            CAST(:entity_id AS UUID), :evidence_hash, CAST(:readiness AS JSONB),
            :observed_at, :ingested_at
        )
        ON CONFLICT (entity_id, evidence_hash) DO NOTHING
    """), {
        "entity_id": entity_id,
        "evidence_hash": digest,
        "readiness": readiness_json,
        "observed_at": observed_at,
        "ingested_at": ingested_at,
    })


async def persist_entity_readiness_snapshot(session: AsyncSession, entity_id: str, readiness: dict[str, Any], *, observed_at: datetime | None = None) -> str:
    digest = entity_readiness_hash(readiness)
    capture_ts = observed_at or datetime.now(timezone.utc)
    if capture_ts.tzinfo is None:
        capture_ts = capture_ts.replace(tzinfo=timezone.utc)
    payload = json.dumps(readiness, sort_keys=True, default=str)
    try:
        await _insert_snapshot(
            session,
            entity_id=entity_id,
            digest=digest,
            readiness_json=payload,
            observed_at=capture_ts,
            ingested_at=capture_ts,
        )
    except Exception:
        await session.rollback()
        try:
            await _insert_snapshot(
                session,
                entity_id=entity_id,
                digest=digest,
                readiness_json=payload,
                observed_at=capture_ts,
                ingested_at=capture_ts,
            )
        except Exception:
            await session.rollback()
            raise
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return digest


async def entity_readiness_history(session: AsyncSession, entity_id: str, *, limit: int = 50, as_of: datetime | str | None = None) -> dict[str, Any]:
    cutoff = _dt(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        return {"status": "UNKNOWN", "entity_id": entity_id, "records": [], "transitions": [], "blockers": ["INVALID_AS_OF"], **AUTHORITY}
    limit = max(1, min(200, int(limit)))
    clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if cutoff is not None else ""
    params: dict[str, Any] = {"entity_id": entity_id, "limit": limit}
    if cutoff is not None:
        params["as_of"] = cutoff
    try:
        await ensure_entity_readiness_audit_table(session)
        rows = (await session.execute(text(f"""
            SELECT id, evidence_hash, readiness, observed_at, ingested_at
            FROM entity_readiness_snapshots
            WHERE entity_id = CAST(:entity_id AS UUID) {clause}
            ORDER BY observed_at ASC, id ASC LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "entity_id": entity_id, "records": [], "transitions": [], "missing": ["entity_readiness_snapshots"], **AUTHORITY}

    records: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for row in rows:
        readiness = dict(row.get("readiness") or {})
        transition = describe_entity_readiness_transition(previous, readiness)
        record = {
            "id": row.get("id"),
            "evidence_hash": row.get("evidence_hash"),
            "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None,
            "ingested_at": row.get("ingested_at").isoformat() if row.get("ingested_at") else None,
            "readiness": readiness,
            "transition": transition,
        }
        records.append(record)
        transitions.append({"observed_at": record["observed_at"], "evidence_hash": record["evidence_hash"], **transition})
        previous = readiness

    latest = records[-1] if records else None
    regression_count = sum(1 for item in transitions if item.get("transition") == "REGRESSED_FROM_DESCRIPTIVE_CALIBRATION_READINESS")
    result = {
        "status": "OBSERVED" if records else "UNKNOWN",
        "entity_id": entity_id,
        "snapshot_count": len(records),
        "records": list(reversed(records)),
        "transitions": list(reversed(transitions)),
        "latest": latest,
        "latest_transition": transitions[-1] if transitions else None,
        "regression_count": regression_count,
        "bounded": {"limit": limit},
        **AUTHORITY,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
