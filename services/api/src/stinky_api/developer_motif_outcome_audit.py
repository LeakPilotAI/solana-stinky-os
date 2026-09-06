"""Immutable, descriptive audit for historical developer-motif outcome context."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
    "analogue_history_is_not_prediction": True,
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "ownership_inferred": False,
    "coordination_inferred": False,
    "expected_return_inferred": False,
    "evidence_only": True,
}


def _launch_key(row: dict[str, Any]) -> str:
    return "|".join([
        str(row.get("entity_id") or ""),
        str(row.get("mint") or ""),
        str(row.get("launch_observed_at") or ""),
    ])


def _launches(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for analogue in context.get("records") or []:
        if not isinstance(analogue, dict):
            continue
        for row in analogue.get("launches") or []:
            if not isinstance(row, dict):
                continue
            key = _launch_key(row)
            if key.strip("|"):
                found[key] = {
                    "entity_id": row.get("entity_id"),
                    "mint": row.get("mint"),
                    "launch_observed_at": row.get("launch_observed_at"),
                    "outcome": str(row.get("outcome") or "UNKNOWN").upper(),
                    "outcome_observed_at": row.get("outcome_observed_at"),
                }
    return found


def _analogue_keys(context: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    for row in context.get("records") or []:
        if not isinstance(row, dict):
            continue
        keys.add("|".join([
            str(row.get("motif_kind") or ""),
            str(row.get("motif_state") or ""),
            ",".join(sorted(str(x) for x in (row.get("component_kinds") or []) if x)),
            ",".join(sorted(str(x) for x in (row.get("related_entity_ids") or []) if x)),
        ]))
    return sorted(keys)


def _canonical(context: dict[str, Any]) -> dict[str, Any]:
    launches = _launches(context)
    launch_records = [
        "|".join([
            key,
            str(value.get("outcome") or "UNKNOWN"),
            str(value.get("outcome_observed_at") or ""),
        ])
        for key, value in sorted(launches.items())
    ]
    counts = context.get("outcome_counts") if isinstance(context.get("outcome_counts"), dict) else {}
    return {
        "entity_id": context.get("entity_id"),
        "status": context.get("status"),
        "motif_analogue_count": context.get("motif_analogue_count"),
        "launch_analogue_count": context.get("launch_analogue_count"),
        "outcome_counts": {k: int(counts.get(k) or 0) for k in ("RUNNER", "HELD", "FADE", "UNKNOWN")},
        "analogue_keys": _analogue_keys(context),
        "launch_records": launch_records,
        "missing": sorted(str(x) for x in (context.get("missing") or [])),
        **AUTHORITY,
    }


def motif_outcome_context_hash(context: dict[str, Any]) -> str:
    raw = json.dumps(_canonical(context), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def describe_motif_outcome_change(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return {"status": "INITIAL_SNAPSHOT", "changed": False, "changes": [], **AUTHORITY}
    prev = _canonical(previous); cur = _canonical(current); changes: list[dict[str, Any]] = []
    if prev["status"] != cur["status"]:
        changes.append({"kind": "MOTIF_OUTCOME_STATUS_CHANGED", "before": prev["status"], "after": cur["status"]})

    prev_analogues, cur_analogues = set(prev["analogue_keys"]), set(cur["analogue_keys"])
    if cur_analogues - prev_analogues:
        changes.append({"kind": "MOTIF_ANALOGUE_ADDED", "added": sorted(cur_analogues - prev_analogues)})
    if prev_analogues - cur_analogues:
        changes.append({"kind": "MOTIF_ANALOGUE_REMOVED_OR_UNAVAILABLE", "removed": sorted(prev_analogues - cur_analogues)})

    prev_launches, cur_launches = _launches(previous), _launches(current)
    prev_keys, cur_keys = set(prev_launches), set(cur_launches)
    if cur_keys - prev_keys:
        changes.append({"kind": "HISTORICAL_LAUNCH_ADDED", "added": sorted(cur_keys - prev_keys)})
    if prev_keys - cur_keys:
        changes.append({"kind": "HISTORICAL_LAUNCH_REMOVED_OR_UNAVAILABLE", "removed": sorted(prev_keys - cur_keys)})
    for key in sorted(prev_keys & cur_keys):
        before = str(prev_launches[key].get("outcome") or "UNKNOWN").upper()
        after = str(cur_launches[key].get("outcome") or "UNKNOWN").upper()
        if before == after:
            continue
        if before == "UNKNOWN" and after in {"RUNNER", "HELD", "FADE"}:
            kind = "HISTORICAL_OUTCOME_RESOLVED"
        elif before in {"RUNNER", "HELD", "FADE"} and after == "UNKNOWN":
            kind = "HISTORICAL_OUTCOME_BECAME_UNKNOWN_OR_UNAVAILABLE"
        else:
            kind = "HISTORICAL_OUTCOME_CHANGED"
        changes.append({"kind": kind, "launch": key, "before": before, "after": after})

    if prev["outcome_counts"] != cur["outcome_counts"]:
        changes.append({"kind": "HISTORICAL_OUTCOME_COUNTS_CHANGED", "before": prev["outcome_counts"], "after": cur["outcome_counts"]})
    before_missing, after_missing = set(prev["missing"]), set(cur["missing"])
    if before_missing - after_missing:
        changes.append({"kind": "UNKNOWN_RESOLVED", "fields": sorted(before_missing - after_missing)})
    if after_missing - before_missing:
        changes.append({"kind": "UNKNOWN_INTRODUCED", "fields": sorted(after_missing - before_missing)})
    return {"status": "CHANGED" if changes else "UNCHANGED", "changed": bool(changes), "changes": changes, **AUTHORITY}


async def ensure_motif_outcome_audit_table(session: AsyncSession) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS developer_motif_outcome_snapshots (
            id BIGSERIAL PRIMARY KEY,
            entity_id UUID NOT NULL,
            evidence_hash TEXT NOT NULL,
            evidence JSONB NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (entity_id, evidence_hash)
        )
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_developer_motif_outcome_snapshots_entity_time
        ON developer_motif_outcome_snapshots(entity_id, observed_at DESC, id DESC)
    """))


async def persist_motif_outcome_snapshot(session: AsyncSession, context: dict[str, Any], *, observed_at: datetime | None = None) -> str | None:
    entity_id = str(context.get("entity_id") or "").strip()
    if not entity_id:
        return None
    await ensure_motif_outcome_audit_table(session)
    digest = motif_outcome_context_hash(context)
    await session.execute(text("""
        INSERT INTO developer_motif_outcome_snapshots (entity_id, evidence_hash, evidence, observed_at)
        VALUES (CAST(:entity_id AS UUID), :evidence_hash, CAST(:evidence AS JSONB), :observed_at)
        ON CONFLICT (entity_id, evidence_hash) DO NOTHING
    """), {
        "entity_id": entity_id,
        "evidence_hash": digest,
        "evidence": json.dumps(context, sort_keys=True, default=str),
        "observed_at": observed_at or datetime.now(timezone.utc),
    })
    return digest


async def motif_outcome_audit_history(session: AsyncSession, entity_id: str, *, limit: int = 20, as_of: datetime | None = None) -> dict[str, Any]:
    limit = max(1, min(100, int(limit)))
    try:
        if as_of is None:
            await ensure_motif_outcome_audit_table(session)
        clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"entity_id": entity_id, "limit": limit}
        if as_of is not None:
            params["as_of"] = as_of
        rows = (await session.execute(text(f"""
            SELECT id, entity_id::text AS entity_id, evidence_hash, evidence, observed_at, ingested_at
            FROM developer_motif_outcome_snapshots
            WHERE entity_id = CAST(:entity_id AS UUID) {clause}
            ORDER BY observed_at DESC, id DESC LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "entity_id": entity_id, "snapshot_count": 0, "records": [], "changes": [], "latest_change": None,
                "missing": ["developer_motif_outcome_snapshots"], **AUTHORITY}

    chronological = list(reversed(rows)); previous: dict[str, Any] | None = None
    records: list[dict[str, Any]] = []; changes: list[dict[str, Any]] = []
    for row in chronological:
        evidence = dict(row.get("evidence") or {})
        record = {
            "id": row.get("id"), "entity_id": row.get("entity_id"), "evidence_hash": row.get("evidence_hash"),
            "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None,
            "ingested_at": row.get("ingested_at").isoformat() if row.get("ingested_at") else None,
            "evidence": evidence,
        }
        change = describe_motif_outcome_change(previous, evidence)
        change["observed_at"] = record["observed_at"]; change["evidence_hash"] = record["evidence_hash"]
        records.append(record); changes.append(change); previous = evidence
    records.reverse(); changes.reverse()
    result = {
        "status": "OBSERVED" if records else "UNKNOWN", "entity_id": entity_id, "snapshot_count": len(records),
        "records": records, "changes": changes, "latest_change": changes[0] if changes else None,
        "bounded": {"limit": limit}, **AUTHORITY,
    }
    if as_of is not None:
        result["as_of"] = as_of.isoformat(); result["temporal_cutoff_enforced"] = True
    return result


async def motif_outcome_change_feed(session: AsyncSession, *, limit: int = 50, as_of: datetime | None = None, include_unchanged: bool = False) -> dict[str, Any]:
    limit = max(1, min(200, int(limit)))
    try:
        if as_of is None:
            await ensure_motif_outcome_audit_table(session)
        clause = "WHERE observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"limit": limit}
        if as_of is not None:
            params["as_of"] = as_of
        rows = (await session.execute(text(f"""
            WITH ranked AS (
                SELECT entity_id, evidence, evidence_hash, observed_at, ingested_at,
                       ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY observed_at DESC, id DESC) AS rn
                FROM developer_motif_outcome_snapshots {clause}
            )
            SELECT a.entity_id::text AS entity_id, a.evidence AS current_evidence, a.evidence_hash,
                   a.observed_at, b.evidence AS previous_evidence, e.primary_wallet, e.display_label
            FROM ranked a LEFT JOIN ranked b ON b.entity_id = a.entity_id AND b.rn = 2
            LEFT JOIN entities e ON e.entity_id = a.entity_id
            WHERE a.rn = 1 ORDER BY a.observed_at DESC, a.entity_id LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "items": [], "count": 0, "missing": ["developer_motif_outcome_snapshots"], **AUTHORITY}

    items: list[dict[str, Any]] = []
    for row in rows:
        current = dict(row.get("current_evidence") or {}); previous_raw = row.get("previous_evidence")
        previous = dict(previous_raw or {}) if previous_raw is not None else None
        change = describe_motif_outcome_change(previous, current)
        if not include_unchanged and change.get("status") == "UNCHANGED":
            continue
        kinds = [str(c.get("kind")) for c in (change.get("changes") or []) if isinstance(c, dict) and c.get("kind")]
        counts = current.get("outcome_counts") if isinstance(current.get("outcome_counts"), dict) else {}
        items.append({
            "entity_id": row.get("entity_id"), "primary_wallet": row.get("primary_wallet"), "display_label": row.get("display_label"),
            "context_status": current.get("status"), "motif_analogue_count": current.get("motif_analogue_count"),
            "launch_analogue_count": current.get("launch_analogue_count"),
            "outcome_counts": {k: int(counts.get(k) or 0) for k in ("RUNNER", "HELD", "FADE", "UNKNOWN")},
            "evidence_hash": row.get("evidence_hash"),
            "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None,
            "change_status": change.get("status"), "change_kinds": kinds, "changes": change.get("changes") or [], **AUTHORITY,
        })
    result = {"status": "OBSERVED" if items else "UNKNOWN", "items": items, "count": len(items), "bounded": {"limit": limit}, **AUTHORITY}
    if as_of is not None:
        result["as_of"] = as_of.isoformat(); result["temporal_cutoff_enforced"] = True
    return result
