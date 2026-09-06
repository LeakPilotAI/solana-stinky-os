"""Immutable descriptive audit trail for compact calibration synthesis snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _canonical_payload(summary: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "pattern_hash",
        "evidence_status",
        "chain_status",
        "observed_layer_count",
        "layer_count",
        "current_calibration_state",
        "transition_count",
        "open_degradation_episode",
        "regime_memory",
        "historical_segmentation",
        "conditional_evidence",
        "chronological_generalization",
        "missing",
        "interpretation",
        "predictive_authority",
        "trade_signal",
        "shared_cause_inferred",
        "evidence_only",
        "as_of",
        "temporal_cutoff_enforced",
    )
    return {key: summary.get(key) for key in keys if key in summary}


def synthesis_hash(summary: dict[str, Any]) -> str:
    payload = json.dumps(_canonical_payload(summary), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_counts(summary: dict[str, Any]) -> dict[str, Any]:
    regime_memory = summary.get("regime_memory") if isinstance(summary, dict) else None
    counts = regime_memory.get("state_counts") if isinstance(regime_memory, dict) else None
    return counts if isinstance(counts, dict) else {}


def _list(summary: dict[str, Any], parent: str, key: str) -> list[str]:
    obj = summary.get(parent) if isinstance(summary, dict) else None
    value = obj.get(key) if isinstance(obj, dict) else None
    return [str(x) for x in value] if isinstance(value, list) else []


def describe_synthesis_change(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Describe factual differences between two synthesis snapshots without judging them."""
    if not previous:
        return {
            "status": "INITIAL_SNAPSHOT",
            "changed": False,
            "changes": [],
            "previous_hash": None,
            "current_hash": synthesis_hash(current),
            "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
            "predictive_authority": False,
            "trade_signal": False,
            "evidence_only": True,
        }

    changes: list[dict[str, Any]] = []

    def scalar(field: str) -> None:
        before, after = previous.get(field), current.get(field)
        if before != after:
            changes.append({"kind": "FIELD_CHANGED", "field": field, "before": before, "after": after})

    for field in (
        "evidence_status",
        "observed_layer_count",
        "current_calibration_state",
        "transition_count",
        "open_degradation_episode",
    ):
        scalar(field)

    before_missing = {str(x) for x in previous.get("missing", []) or []}
    after_missing = {str(x) for x in current.get("missing", []) or []}
    resolved = sorted(before_missing - after_missing)
    introduced = sorted(after_missing - before_missing)
    if resolved:
        changes.append({"kind": "UNKNOWN_RESOLVED", "fields": resolved})
    if introduced:
        changes.append({"kind": "UNKNOWN_INTRODUCED", "fields": introduced})

    before_counts, after_counts = _state_counts(previous), _state_counts(current)
    if before_counts != after_counts:
        changes.append({"kind": "REGIME_STATE_COUNTS_CHANGED", "before": before_counts, "after": after_counts})

    for parent, key in (
        ("conditional_evidence", "sufficient_regimes"),
        ("chronological_generalization", "stable_regimes"),
        ("chronological_generalization", "unstable_regimes"),
        ("chronological_generalization", "insufficient_regimes"),
    ):
        before_values, after_values = set(_list(previous, parent, key)), set(_list(current, parent, key))
        if before_values != after_values:
            changes.append({
                "kind": "SET_CHANGED",
                "field": f"{parent}.{key}",
                "added": sorted(after_values - before_values),
                "removed": sorted(before_values - after_values),
            })

    previous_hash, current_hash = synthesis_hash(previous), synthesis_hash(current)
    return {
        "status": "CHANGED" if changes else "UNCHANGED",
        "changed": bool(changes),
        "changes": changes,
        "previous_hash": previous_hash,
        "current_hash": current_hash,
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "predictive_authority": False,
        "trade_signal": False,
        "shared_cause_inferred": False,
        "evidence_only": True,
    }


async def ensure_synthesis_audit_table(session: AsyncSession) -> None:
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS market_pattern_calibration_synthesis_snapshots (
            id BIGSERIAL PRIMARY KEY,
            pattern_hash TEXT NOT NULL,
            synthesis_hash TEXT NOT NULL,
            synthesis JSONB NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (pattern_hash, synthesis_hash)
        )
    """))
    await session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_market_pattern_calibration_synthesis_snapshots_pattern_time
        ON market_pattern_calibration_synthesis_snapshots(pattern_hash, observed_at DESC, id DESC)
    """))


async def persist_synthesis_snapshot(
    session: AsyncSession,
    summary: dict[str, Any],
    *,
    observed_at: datetime | None = None,
) -> str | None:
    pattern_hash = str(summary.get("pattern_hash") or "").strip()
    if not pattern_hash:
        return None
    await ensure_synthesis_audit_table(session)
    digest = synthesis_hash(summary)
    ts = observed_at or datetime.now(timezone.utc)
    await session.execute(
        text("""
            INSERT INTO market_pattern_calibration_synthesis_snapshots
                (pattern_hash, synthesis_hash, synthesis, observed_at)
            VALUES (:pattern_hash, :synthesis_hash, CAST(:synthesis AS JSONB), :observed_at)
            ON CONFLICT (pattern_hash, synthesis_hash) DO NOTHING
        """),
        {
            "pattern_hash": pattern_hash,
            "synthesis_hash": digest,
            "synthesis": json.dumps(_canonical_payload(summary), sort_keys=True, default=str),
            "observed_at": ts,
        },
    )
    return digest


async def synthesis_audit_history(
    session: AsyncSession,
    pattern_hash: str,
    *,
    limit: int = 20,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    limit = max(1, min(100, int(limit)))
    try:
        await ensure_synthesis_audit_table(session)
        clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
        params: dict[str, Any] = {"pattern_hash": pattern_hash, "limit": limit}
        if as_of is not None:
            params["as_of"] = as_of
        rows = (await session.execute(text(f"""
            SELECT id, pattern_hash, synthesis_hash, synthesis, observed_at, ingested_at
            FROM market_pattern_calibration_synthesis_snapshots
            WHERE pattern_hash = :pattern_hash {clause}
            ORDER BY observed_at DESC, id DESC
            LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "records": [], "changes": [], "missing": ["market_pattern_calibration_synthesis_snapshots"], "evidence_only": True}

    records = []
    chronological = list(reversed(rows))
    previous_summary: dict[str, Any] | None = None
    changes = []
    for row in chronological:
        summary = dict(row.get("synthesis") or {})
        record = {
            "id": row.get("id"),
            "pattern_hash": row.get("pattern_hash"),
            "synthesis_hash": row.get("synthesis_hash"),
            "observed_at": row.get("observed_at").isoformat() if row.get("observed_at") else None,
            "ingested_at": row.get("ingested_at").isoformat() if row.get("ingested_at") else None,
            "synthesis": summary,
        }
        records.append(record)
        change = describe_synthesis_change(previous_summary, summary)
        change["observed_at"] = record["observed_at"]
        changes.append(change)
        previous_summary = summary

    records.reverse()
    changes.reverse()
    result = {
        "status": "OBSERVED" if records else "UNKNOWN",
        "pattern_hash": pattern_hash,
        "snapshot_count": len(records),
        "records": records,
        "changes": changes,
        "latest_change": changes[0] if changes else None,
        "bounded": {"limit": limit},
        "interpretation": "DESCRIPTIVE_EVIDENCE_ONLY",
        "predictive_authority": False,
        "trade_signal": False,
        "shared_cause_inferred": False,
        "evidence_only": True,
    }
    if as_of is not None:
        result["as_of"] = as_of.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
