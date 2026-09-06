"""Persistence and longitudinal change tracking for descriptive pattern stability.

Stores immutable snapshots of temporal validation evidence. This is descriptive memory
only: no prediction, probability, confidence, expected return, risk, quality, or trade signal.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "DESCRIPTIVE_PATTERN_STABILITY_MEMORY_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}

VALID_STATES = {"STABLE", "UNSTABLE", "INSUFFICIENT_EVIDENCE"}


def _canonical_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    drift = pattern.get("outcome_distribution_drift") if isinstance(pattern.get("outcome_distribution_drift"), dict) else {}
    early = pattern.get("early") if isinstance(pattern.get("early"), dict) else {}
    late = pattern.get("late") if isinstance(pattern.get("late"), dict) else {}
    state = str(pattern.get("stability_status") or "INSUFFICIENT_EVIDENCE")
    if state not in VALID_STATES:
        state = "INSUFFICIENT_EVIDENCE"
    return {
        "pattern_hash": pattern.get("pattern_hash"),
        "pattern_key": pattern.get("pattern_key"),
        "feature_tokens": sorted(str(x) for x in (pattern.get("feature_tokens") or [])),
        "stability_status": state,
        "full_support_count": int(pattern.get("full_support_count") or 0),
        "early_support_count": int(early.get("support_count") or 0),
        "late_support_count": int(late.get("support_count") or 0),
        "early_known_label_coverage": early.get("known_label_coverage"),
        "late_known_label_coverage": late.get("known_label_coverage"),
        "max_outcome_drift_pct_points": drift.get("max_drift_pct_points"),
        "dataset_hash": pattern.get("dataset_hash"),
        **AUTHORITY,
    }


def pattern_stability_hash(pattern: dict[str, Any]) -> str:
    raw = json.dumps(_canonical_pattern(pattern), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def describe_pattern_stability_change(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    cur = _canonical_pattern(current)
    if not previous:
        return {"status": "INITIAL_SNAPSHOT", "changed": False, "changes": [], **AUTHORITY}
    prev = _canonical_pattern(previous)
    changes: list[dict[str, Any]] = []
    if prev["stability_status"] != cur["stability_status"]:
        changes.append({"kind": "STABILITY_STATE_CHANGED", "before": prev["stability_status"], "after": cur["stability_status"]})
    for field, kind in (
        ("full_support_count", "SUPPORT_COUNT_CHANGED"),
        ("early_support_count", "EARLY_SUPPORT_CHANGED"),
        ("late_support_count", "LATE_SUPPORT_CHANGED"),
        ("early_known_label_coverage", "EARLY_LABEL_COVERAGE_CHANGED"),
        ("late_known_label_coverage", "LATE_LABEL_COVERAGE_CHANGED"),
        ("max_outcome_drift_pct_points", "OUTCOME_DRIFT_CHANGED"),
        ("dataset_hash", "DATASET_CHANGED"),
    ):
        if prev.get(field) != cur.get(field):
            changes.append({"kind": kind, "field": field, "before": prev.get(field), "after": cur.get(field)})
    return {"status": "CHANGED" if changes else "UNCHANGED", "changed": bool(changes), "changes": changes, **AUTHORITY}


async def ensure_pattern_stability_table(session: AsyncSession) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS pattern_stability_snapshots (
            id BIGSERIAL PRIMARY KEY,
            pattern_hash TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            evidence JSONB NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (pattern_hash, evidence_hash)
        )
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_pattern_stability_snapshots_pattern_time
        ON pattern_stability_snapshots(pattern_hash, observed_at DESC, id DESC)
    """))


async def persist_pattern_stability_snapshot(session: AsyncSession, pattern: dict[str, Any], *, observed_at: datetime | None = None) -> str | None:
    pattern_hash = str(pattern.get("pattern_hash") or "").strip()
    if not pattern_hash:
        return None
    await ensure_pattern_stability_table(session)
    digest = pattern_stability_hash(pattern)
    await session.execute(text("""
        INSERT INTO pattern_stability_snapshots (pattern_hash, evidence_hash, evidence, observed_at)
        VALUES (:pattern_hash, :evidence_hash, CAST(:evidence AS JSONB), :observed_at)
        ON CONFLICT (pattern_hash, evidence_hash) DO NOTHING
    """), {
        "pattern_hash": pattern_hash,
        "evidence_hash": digest,
        "evidence": json.dumps(pattern, sort_keys=True, default=str),
        "observed_at": observed_at or datetime.now(timezone.utc),
    })
    return digest


async def pattern_stability_history(session: AsyncSession, pattern_hash: str, *, limit: int = 20, as_of: datetime | None = None) -> dict[str, Any]:
    limit = max(1, min(100, int(limit)))
    try:
        if as_of is None:
            await ensure_pattern_stability_table(session)
        clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"pattern_hash": pattern_hash, "limit": limit}
        if as_of is not None:
            params["as_of"] = as_of
        rows = (await session.execute(text(f"""
            SELECT id, pattern_hash, evidence_hash, evidence, observed_at, ingested_at
            FROM pattern_stability_snapshots
            WHERE pattern_hash = :pattern_hash {clause}
            ORDER BY observed_at DESC, id DESC LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "pattern_hash": pattern_hash, "snapshot_count": 0, "records": [], "changes": [], "latest_change": None, "missing": ["pattern_stability_snapshots"], **AUTHORITY}

    chronological = list(reversed(rows)); previous: dict[str, Any] | None = None
    records: list[dict[str, Any]] = []; changes: list[dict[str, Any]] = []
    for row in chronological:
        evidence = dict(row.get("evidence") or {})
        record = {
            "id": row.get("id"), "pattern_hash": row.get("pattern_hash"), "evidence_hash": row.get("evidence_hash"),
            "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None,
            "ingested_at": row.get("ingested_at").isoformat() if row.get("ingested_at") else None,
            "evidence": evidence,
        }
        change = describe_pattern_stability_change(previous, evidence)
        change["observed_at"] = record["observed_at"]; change["evidence_hash"] = record["evidence_hash"]
        records.append(record); changes.append(change); previous = evidence
    records.reverse(); changes.reverse()
    result = {"status": "OBSERVED" if records else "UNKNOWN", "pattern_hash": pattern_hash, "snapshot_count": len(records), "records": records, "changes": changes, "latest_change": changes[0] if changes else None, "bounded": {"limit": limit}, **AUTHORITY}
    if as_of is not None:
        result["as_of"] = as_of.isoformat(); result["temporal_cutoff_enforced"] = True
    return result


async def pattern_stability_change_feed(session: AsyncSession, *, limit: int = 50, as_of: datetime | None = None, include_unchanged: bool = False) -> dict[str, Any]:
    limit = max(1, min(200, int(limit)))
    try:
        if as_of is None:
            await ensure_pattern_stability_table(session)
        clause = "WHERE observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"limit": limit}
        if as_of is not None:
            params["as_of"] = as_of
        rows = (await session.execute(text(f"""
            WITH ranked AS (
                SELECT pattern_hash, evidence, evidence_hash, observed_at, ingested_at,
                       ROW_NUMBER() OVER (PARTITION BY pattern_hash ORDER BY observed_at DESC, id DESC) AS rn
                FROM pattern_stability_snapshots {clause}
            )
            SELECT a.pattern_hash, a.evidence AS current_evidence, a.evidence_hash, a.observed_at,
                   b.evidence AS previous_evidence
            FROM ranked a LEFT JOIN ranked b ON b.pattern_hash = a.pattern_hash AND b.rn = 2
            WHERE a.rn = 1 ORDER BY a.observed_at DESC, a.pattern_hash LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "items": [], "count": 0, "missing": ["pattern_stability_snapshots"], **AUTHORITY}

    items: list[dict[str, Any]] = []
    for row in rows:
        current = dict(row.get("current_evidence") or {}); previous_raw = row.get("previous_evidence")
        previous = dict(previous_raw or {}) if previous_raw is not None else None
        change = describe_pattern_stability_change(previous, current)
        if not include_unchanged and change.get("status") == "UNCHANGED":
            continue
        items.append({
            "pattern_hash": row.get("pattern_hash"),
            "pattern_key": current.get("pattern_key"),
            "stability_status": current.get("stability_status"),
            "dataset_hash": current.get("dataset_hash"),
            "evidence_hash": row.get("evidence_hash"),
            "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None,
            "change_status": change.get("status"),
            "change_kinds": [str(c.get("kind")) for c in (change.get("changes") or []) if isinstance(c, dict) and c.get("kind")],
            "changes": change.get("changes") or [],
            **AUTHORITY,
        })
    result = {"status": "OBSERVED" if items else "UNKNOWN", "items": items, "count": len(items), "bounded": {"limit": limit}, **AUTHORITY}
    if as_of is not None:
        result["as_of"] = as_of.isoformat(); result["temporal_cutoff_enforced"] = True
    return result
