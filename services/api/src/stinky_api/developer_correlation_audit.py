"""Immutable, evidence-only longitudinal audit for developer identity correlation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


AUTHORITY = {
    "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
    "ownership_inferred": False,
    "coordination_inferred": False,
    "intent_inferred": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "predictive_authority": False,
    "trade_signal": False,
    "evidence_only": True,
}


def _keyed(records: list[Any], fields: tuple[str, ...]) -> list[str]:
    values: set[str] = set()
    for row in records or []:
        if not isinstance(row, dict):
            continue
        parts = [str(row.get(field) or "").strip() for field in fields]
        if any(parts): values.add(":".join(parts))
    return sorted(values)


def _canonical_repetition(evidence: dict[str, Any]) -> dict[str, Any]:
    repetition = evidence.get("repetition_analysis") if isinstance(evidence.get("repetition_analysis"), dict) else {}
    records: list[str] = []
    for row in repetition.get("records") or []:
        if not isinstance(row, dict): continue
        identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
        identity_key = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
        records.append("|".join([
            str(row.get("kind") or ""), identity_key,
            str(row.get("independent_observation_count")), str(row.get("distinct_launch_count")),
            str(row.get("temporal_spread_seconds")), str(row.get("repetition_state") or "UNKNOWN"),
        ]))
    return {
        "relationship_count_observed": repetition.get("relationship_count_observed"),
        "repeated_relationship_count": repetition.get("repeated_relationship_count"),
        "multi_launch_relationship_count": repetition.get("multi_launch_relationship_count"),
        "total_independent_observation_count": repetition.get("total_independent_observation_count"),
        "max_temporal_spread_seconds": repetition.get("max_temporal_spread_seconds"),
        "records": sorted(records),
        "missing": sorted(str(x) for x in (repetition.get("missing") or [])),
    }


def _canonical_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": evidence.get("entity_id"), "status": evidence.get("status"),
        "wallets": sorted(str(x) for x in (evidence.get("wallets") or []) if x),
        "shared_funders": _keyed(evidence.get("shared_funders") or [], ("funder_wallet", "other_entity_id")),
        "cross_entity_wallet_reuse": _keyed(evidence.get("cross_entity_wallet_reuse") or [], ("wallet", "other_entity_id")),
        "deployer_buyer_recurrence": _keyed(evidence.get("deployer_buyer_recurrence") or [], ("wallet", "buyer_entity_id")),
        "shared_relationship_structures": _keyed(evidence.get("shared_relationship_structures") or [], ("relationship_kind", "other_entity_id")),
        "repetition_analysis": _canonical_repetition(evidence),
        "missing": sorted(str(x) for x in (evidence.get("missing") or [])),
        **AUTHORITY,
    }


def developer_correlation_hash(evidence: dict[str, Any]) -> str:
    raw = json.dumps(_canonical_payload(evidence), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def describe_developer_correlation_change(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    cur = _canonical_payload(current)
    if not previous: return {"status": "INITIAL_SNAPSHOT", "changed": False, "changes": [], **AUTHORITY}
    prev = _canonical_payload(previous); changes: list[dict[str, Any]] = []
    if prev.get("status") != cur.get("status"):
        changes.append({"kind": "CORRELATION_STATUS_CHANGED", "before": prev.get("status"), "after": cur.get("status")})
    specs = (
        ("shared_funders", "SHARED_FUNDER_ADDED", "SHARED_FUNDER_REMOVED_OR_UNAVAILABLE"),
        ("cross_entity_wallet_reuse", "WALLET_REUSE_ADDED", "WALLET_REUSE_REMOVED_OR_UNAVAILABLE"),
        ("deployer_buyer_recurrence", "DEPLOYER_BUYER_RECURRENCE_ADDED", "DEPLOYER_BUYER_RECURRENCE_REMOVED_OR_UNAVAILABLE"),
        ("shared_relationship_structures", "RELATIONSHIP_STRUCTURE_ADDED", "RELATIONSHIP_STRUCTURE_REMOVED_OR_UNAVAILABLE"),
    )
    for field, added_kind, removed_kind in specs:
        before, after = set(prev.get(field) or []), set(cur.get(field) or [])
        added, removed = sorted(after - before), sorted(before - after)
        if added: changes.append({"kind": added_kind, "field": field, "added": added, "removed": []})
        if removed: changes.append({"kind": removed_kind, "field": field, "added": [], "removed": removed})
    if prev.get("repetition_analysis") != cur.get("repetition_analysis"):
        changes.append({
            "kind": "REPETITION_EVIDENCE_CHANGED",
            "before": prev.get("repetition_analysis"),
            "after": cur.get("repetition_analysis"),
            "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        })
    before_missing, after_missing = set(prev.get("missing") or []), set(cur.get("missing") or [])
    if before_missing - after_missing: changes.append({"kind": "UNKNOWN_RESOLVED", "fields": sorted(before_missing - after_missing)})
    if after_missing - before_missing: changes.append({"kind": "UNKNOWN_INTRODUCED", "fields": sorted(after_missing - before_missing)})
    return {"status": "CHANGED" if changes else "UNCHANGED", "changed": bool(changes), "changes": changes, **AUTHORITY}


async def ensure_developer_correlation_audit_table(session: AsyncSession) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS developer_correlation_snapshots (
            id BIGSERIAL PRIMARY KEY, entity_id UUID NOT NULL, evidence_hash TEXT NOT NULL,
            evidence JSONB NOT NULL, observed_at TIMESTAMPTZ NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (entity_id, evidence_hash)
        )
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_developer_correlation_snapshots_entity_time
        ON developer_correlation_snapshots(entity_id, observed_at DESC, id DESC)
    """))


async def persist_developer_correlation_snapshot(session: AsyncSession, evidence: dict[str, Any], *, observed_at: datetime | None = None) -> str | None:
    entity_id = str(evidence.get("entity_id") or "").strip()
    if not entity_id: return None
    await ensure_developer_correlation_audit_table(session)
    digest = developer_correlation_hash(evidence); ts = observed_at or datetime.now(timezone.utc)
    await session.execute(text("""
        INSERT INTO developer_correlation_snapshots (entity_id, evidence_hash, evidence, observed_at)
        VALUES (CAST(:entity_id AS UUID), :evidence_hash, CAST(:evidence AS JSONB), :observed_at)
        ON CONFLICT (entity_id, evidence_hash) DO NOTHING
    """), {"entity_id": entity_id, "evidence_hash": digest,
             "evidence": json.dumps(evidence, sort_keys=True, default=str), "observed_at": ts})
    return digest


async def developer_correlation_audit_history(session: AsyncSession, entity_id: str, *, limit: int = 20, as_of: datetime | None = None) -> dict[str, Any]:
    limit = max(1, min(100, int(limit)))
    try:
        await ensure_developer_correlation_audit_table(session)
        clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"entity_id": entity_id, "limit": limit}
        if as_of is not None: params["as_of"] = as_of
        rows = (await session.execute(text(f"""
            SELECT id, entity_id::text AS entity_id, evidence_hash, evidence, observed_at, ingested_at
            FROM developer_correlation_snapshots WHERE entity_id = CAST(:entity_id AS UUID) {clause}
            ORDER BY observed_at DESC, id DESC LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "entity_id": entity_id, "records": [], "changes": [], "latest_change": None,
                "missing": ["developer_correlation_snapshots"], **AUTHORITY}
    chronological = list(reversed(rows)); previous: dict[str, Any] | None = None; records: list[dict[str, Any]] = []; changes: list[dict[str, Any]] = []
    for row in chronological:
        evidence = dict(row.get("evidence") or {})
        record = {"id": row.get("id"), "entity_id": row.get("entity_id"), "evidence_hash": row.get("evidence_hash"),
                  "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None,
                  "ingested_at": row.get("ingested_at").isoformat() if row.get("ingested_at") else None, "evidence": evidence}
        records.append(record); change = describe_developer_correlation_change(previous, evidence)
        change["observed_at"] = record["observed_at"]; change["evidence_hash"] = record["evidence_hash"]
        changes.append(change); previous = evidence
    records.reverse(); changes.reverse()
    result = {"status": "OBSERVED" if records else "UNKNOWN", "entity_id": entity_id, "snapshot_count": len(records),
              "records": records, "changes": changes, "latest_change": changes[0] if changes else None,
              "bounded": {"limit": limit}, **AUTHORITY}
    if as_of is not None: result["as_of"] = as_of.isoformat(); result["temporal_cutoff_enforced"] = True
    return result


async def developer_correlation_change_feed(session: AsyncSession, *, limit: int = 50, as_of: datetime | None = None, include_unchanged: bool = False) -> dict[str, Any]:
    limit = max(1, min(200, int(limit)))
    try:
        await ensure_developer_correlation_audit_table(session)
        clause = "WHERE observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"limit": limit}
        if as_of is not None: params["as_of"] = as_of
        rows = (await session.execute(text(f"""
            WITH ranked AS (
                SELECT entity_id, evidence, evidence_hash, observed_at, ingested_at,
                       ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY observed_at DESC, id DESC) AS rn
                FROM developer_correlation_snapshots {clause}
            )
            SELECT a.entity_id::text AS entity_id, a.evidence AS current_evidence, a.evidence_hash,
                   a.observed_at, b.evidence AS previous_evidence, e.primary_wallet, e.display_label
            FROM ranked a LEFT JOIN ranked b ON b.entity_id = a.entity_id AND b.rn = 2
            LEFT JOIN entities e ON e.entity_id = a.entity_id
            WHERE a.rn = 1 ORDER BY a.observed_at DESC, a.entity_id LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "items": [], "count": 0, "missing": ["developer_correlation_snapshots"], **AUTHORITY}
    items: list[dict[str, Any]] = []
    for row in rows:
        current = dict(row.get("current_evidence") or {}); previous_raw = row.get("previous_evidence")
        previous = dict(previous_raw or {}) if previous_raw is not None else None
        change = describe_developer_correlation_change(previous, current)
        if not include_unchanged and change.get("status") == "UNCHANGED": continue
        kinds: list[str] = []
        for item in change.get("changes") or []:
            kind = str(item.get("kind") or "") if isinstance(item, dict) else ""
            if kind and kind not in kinds: kinds.append(kind)
        repetition = current.get("repetition_analysis") if isinstance(current.get("repetition_analysis"), dict) else {}
        items.append({"entity_id": row.get("entity_id"), "primary_wallet": row.get("primary_wallet"), "display_label": row.get("display_label"),
                      "correlation_status": current.get("status"), "evidence_hash": row.get("evidence_hash"),
                      "repeated_relationship_count": repetition.get("repeated_relationship_count"),
                      "multi_launch_relationship_count": repetition.get("multi_launch_relationship_count"),
                      "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None,
                      "change_status": change.get("status"), "change_kinds": kinds, "changes": change.get("changes") or [], **AUTHORITY})
    result = {"status": "OBSERVED" if items else "UNKNOWN", "items": items, "count": len(items), "bounded": {"limit": limit}, **AUTHORITY}
    if as_of is not None: result["as_of"] = as_of.isoformat(); result["temporal_cutoff_enforced"] = True
    return result
