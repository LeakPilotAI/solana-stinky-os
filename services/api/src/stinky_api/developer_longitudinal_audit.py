"""Immutable, evidence-only audit trail for developer/deployer longitudinal evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _canonical_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    launches = evidence.get("launch_history") if isinstance(evidence.get("launch_history"), dict) else {}
    wallets = evidence.get("associated_wallets") if isinstance(evidence.get("associated_wallets"), dict) else {}
    funding = evidence.get("funding_relationships") if isinstance(evidence.get("funding_relationships"), dict) else {}
    buyers = evidence.get("recurring_early_buyers") if isinstance(evidence.get("recurring_early_buyers"), dict) else {}
    return {
        "entity_id": evidence.get("entity_id"),
        "reference_mint": evidence.get("reference_mint"),
        "history_state": evidence.get("history_state"),
        "historical_launch_count": launches.get("historical_launch_count", 0),
        "outcome_counts": launches.get("outcome_counts") or {},
        "associated_wallets": sorted(str(r.get("wallet")) for r in (wallets.get("records") or []) if isinstance(r, dict) and r.get("wallet")),
        "funding_counterparties": sorted(f"{r.get('wallet')}:{r.get('direction')}" for r in (funding.get("counterparties") or []) if isinstance(r, dict) and r.get("wallet")),
        "recurring_early_buyers": sorted(str(r.get("wallet")) for r in (buyers.get("records") or []) if isinstance(r, dict) and r.get("wallet")),
        "recurring_early_buyer_status": buyers.get("status"),
        "missing": sorted(str(x) for x in (evidence.get("missing") or [])),
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "risk_inferred": False,
        "quality_inferred": False,
        "predictive_authority": False,
        "trade_signal": False,
        "evidence_only": True,
    }


def developer_evidence_hash(evidence: dict[str, Any]) -> str:
    raw = json.dumps(_canonical_payload(evidence), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def describe_developer_change(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    current = _canonical_payload(current)
    if not previous:
        return {"status": "INITIAL_SNAPSHOT", "changed": False, "changes": [], "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "risk_inferred": False, "quality_inferred": False, "predictive_authority": False, "trade_signal": False, "evidence_only": True}
    previous = _canonical_payload(previous)
    changes: list[dict[str, Any]] = []
    if previous.get("history_state") != current.get("history_state"):
        changes.append({"kind": "HISTORY_STATE_CHANGED", "before": previous.get("history_state"), "after": current.get("history_state")})
    before_launches = int(previous.get("historical_launch_count") or 0)
    after_launches = int(current.get("historical_launch_count") or 0)
    if before_launches != after_launches:
        changes.append({"kind": "NEW_LAUNCH_OBSERVED" if after_launches > before_launches else "LAUNCH_HISTORY_COUNT_CHANGED", "before": before_launches, "after": after_launches})
    if previous.get("outcome_counts") != current.get("outcome_counts"):
        changes.append({"kind": "OUTCOME_COUNTS_CHANGED", "before": previous.get("outcome_counts"), "after": current.get("outcome_counts")})
    for field, added_kind, removed_kind in (("associated_wallets", "ASSOCIATED_WALLET_ADDED", "ASSOCIATED_WALLET_REMOVED"), ("funding_counterparties", "FUNDING_COUNTERPARTY_CHANGED", "FUNDING_COUNTERPARTY_CHANGED"), ("recurring_early_buyers", "RECURRING_EARLY_BUYER_CHANGED", "RECURRING_EARLY_BUYER_CHANGED")):
        before = set(previous.get(field) or []); after = set(current.get(field) or [])
        if after - before: changes.append({"kind": added_kind, "field": field, "added": sorted(after - before), "removed": []})
        if before - after: changes.append({"kind": removed_kind, "field": field, "added": [], "removed": sorted(before - after)})
    before_missing = set(previous.get("missing") or []); after_missing = set(current.get("missing") or [])
    if before_missing - after_missing: changes.append({"kind": "UNKNOWN_RESOLVED", "fields": sorted(before_missing - after_missing)})
    if after_missing - before_missing: changes.append({"kind": "UNKNOWN_INTRODUCED", "fields": sorted(after_missing - before_missing)})
    return {"status": "CHANGED" if changes else "UNCHANGED", "changed": bool(changes), "changes": changes, "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "risk_inferred": False, "quality_inferred": False, "predictive_authority": False, "trade_signal": False, "evidence_only": True}


async def ensure_developer_audit_table(session: AsyncSession) -> None:
    await session.execute(text("""CREATE TABLE IF NOT EXISTS developer_longitudinal_snapshots (id BIGSERIAL PRIMARY KEY, entity_id UUID NOT NULL, evidence_hash TEXT NOT NULL, evidence JSONB NOT NULL, observed_at TIMESTAMPTZ NOT NULL, ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (entity_id, evidence_hash))"""))
    await session.execute(text("""CREATE INDEX IF NOT EXISTS idx_developer_longitudinal_snapshots_entity_time ON developer_longitudinal_snapshots(entity_id, observed_at DESC, id DESC)"""))


async def _insert_developer_snapshot(session: AsyncSession, *, entity_id: str, digest: str, evidence_json: str, observed_at: datetime) -> None:
    await ensure_developer_audit_table(session)
    await session.execute(text("""INSERT INTO developer_longitudinal_snapshots (entity_id, evidence_hash, evidence, observed_at) VALUES (CAST(:entity_id AS UUID), :evidence_hash, CAST(:evidence AS JSONB), :observed_at) ON CONFLICT (entity_id, evidence_hash) DO NOTHING"""), {"entity_id": entity_id, "evidence_hash": digest, "evidence": evidence_json, "observed_at": observed_at})


async def persist_developer_snapshot(session: AsyncSession, evidence: dict[str, Any], *, observed_at: datetime | None = None) -> str | None:
    """Persist and durably commit one immutable snapshot.

    Optional investigation reads can poison the request transaction. Recover once,
    retry the identical evidence, then commit immediately so later optional reads
    cannot roll the snapshot back. A commit failure is surfaced to the caller.
    """
    entity_id = str(evidence.get("entity_id") or "").strip()
    if not entity_id: return None
    digest = developer_evidence_hash(evidence); ts = observed_at or datetime.now(timezone.utc)
    evidence_json = json.dumps(evidence, sort_keys=True, default=str)
    try:
        await _insert_developer_snapshot(session, entity_id=entity_id, digest=digest, evidence_json=evidence_json, observed_at=ts)
    except Exception:
        await session.rollback()
        try:
            await _insert_developer_snapshot(session, entity_id=entity_id, digest=digest, evidence_json=evidence_json, observed_at=ts)
        except Exception:
            await session.rollback(); raise
    try:
        await session.commit()
    except Exception:
        await session.rollback(); raise
    return digest


async def developer_audit_history(session: AsyncSession, entity_id: str, *, limit: int = 20, as_of: datetime | None = None) -> dict[str, Any]:
    limit = max(1, min(100, int(limit)))
    try:
        await ensure_developer_audit_table(session)
        clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"entity_id": entity_id, "limit": limit}
        if as_of is not None: params["as_of"] = as_of
        rows = (await session.execute(text(f"""SELECT id, entity_id::text AS entity_id, evidence_hash, evidence, observed_at, ingested_at FROM developer_longitudinal_snapshots WHERE entity_id = CAST(:entity_id AS UUID) {clause} ORDER BY observed_at DESC, id DESC LIMIT :limit"""), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "records": [], "changes": [], "missing": ["developer_longitudinal_snapshots"], "evidence_only": True}
    chronological = list(reversed(rows)); previous: dict[str, Any] | None = None; records = []; changes = []
    for row in chronological:
        evidence = dict(row.get("evidence") or {})
        records.append({"id": row.get("id"), "entity_id": row.get("entity_id"), "evidence_hash": row.get("evidence_hash"), "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None, "ingested_at": row.get("ingested_at").isoformat() if row.get("ingested_at") else None, "evidence": evidence})
        change = describe_developer_change(previous, evidence); change["observed_at"] = records[-1]["observed_at"]; changes.append(change); previous = evidence
    records.reverse(); changes.reverse()
    result = {"status": "OBSERVED" if records else "UNKNOWN", "entity_id": entity_id, "snapshot_count": len(records), "records": records, "changes": changes, "latest_change": changes[0] if changes else None, "bounded": {"limit": limit}, "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "risk_inferred": False, "quality_inferred": False, "predictive_authority": False, "trade_signal": False, "evidence_only": True}
    if as_of is not None: result["as_of"] = as_of.isoformat(); result["temporal_cutoff_enforced"] = True
    return result


async def developer_change_feed(session: AsyncSession, *, limit: int = 50, as_of: datetime | None = None, include_unchanged: bool = False) -> dict[str, Any]:
    limit = max(1, min(200, int(limit)))
    try:
        await ensure_developer_audit_table(session)
        clause = "WHERE observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"limit": limit}
        if as_of is not None: params["as_of"] = as_of
        rows = (await session.execute(text(f"""WITH ranked AS (SELECT entity_id, evidence, observed_at, ingested_at, ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY observed_at DESC, id DESC) AS rn FROM developer_longitudinal_snapshots {clause}) SELECT a.entity_id::text AS entity_id, a.evidence AS current_evidence, a.observed_at, b.evidence AS previous_evidence, e.primary_wallet, e.display_label FROM ranked a LEFT JOIN ranked b ON b.entity_id = a.entity_id AND b.rn = 2 LEFT JOIN entities e ON e.entity_id = a.entity_id WHERE a.rn = 1 ORDER BY a.observed_at DESC, a.entity_id LIMIT :limit"""), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "items": [], "count": 0, "missing": ["developer_longitudinal_snapshots"], "evidence_only": True}
    items = []
    for row in rows:
        current = dict(row.get("current_evidence") or {}); previous_raw = row.get("previous_evidence"); previous = dict(previous_raw or {}) if previous_raw is not None else None
        change = describe_developer_change(previous, current)
        if not include_unchanged and change.get("status") == "UNCHANGED": continue
        kinds = []
        for c in change.get("changes") or []:
            kind = str(c.get("kind") or "") if isinstance(c, dict) else ""
            if kind and kind not in kinds: kinds.append(kind)
        items.append({"entity_id": row.get("entity_id"), "primary_wallet": row.get("primary_wallet"), "display_label": row.get("display_label"), "reference_mint": current.get("reference_mint"), "history_state": current.get("history_state"), "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None, "change_status": change.get("status"), "change_kinds": kinds, "changes": change.get("changes") or [], "risk_inferred": False, "quality_inferred": False, "predictive_authority": False, "trade_signal": False, "evidence_only": True})
    result = {"status": "OBSERVED" if items else "UNKNOWN", "items": items, "count": len(items), "bounded": {"limit": limit}, "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY", "risk_inferred": False, "quality_inferred": False, "predictive_authority": False, "trade_signal": False, "evidence_only": True}
    if as_of is not None: result["as_of"] = as_of.isoformat(); result["temporal_cutoff_enforced"] = True
    return result
