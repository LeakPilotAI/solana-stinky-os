"""Descriptive stability gate for recurring developer relationship evidence.

This module measures whether the same factual relationship identities recur across
chronological evidence windows. Stability is evidence persistence only; it does not
infer ownership, coordination, intent, risk, quality, predictive value, or a trade signal.
"""
from __future__ import annotations

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


def _identity_key(row: dict[str, Any]) -> str | None:
    kind = str(row.get("kind") or "").strip()
    identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
    clean = {str(k): str(v).strip() for k, v in identity.items() if v is not None and str(v).strip()}
    if not kind or not clean:
        return None
    return kind + "|" + json.dumps(clean, sort_keys=True, separators=(",", ":"))


def _snapshot_relationships(record: dict[str, Any]) -> set[str]:
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    repetition = evidence.get("repetition_analysis") if isinstance(evidence.get("repetition_analysis"), dict) else {}
    keys: set[str] = set()
    for row in repetition.get("records") or []:
        if isinstance(row, dict):
            key = _identity_key(row)
            if key:
                keys.add(key)
    return keys


def assess_developer_relationship_stability(
    records: list[dict[str, Any]], *, as_of: datetime | str | None = None,
    min_snapshots: int = 4, min_per_slice: int = 2,
) -> dict[str, Any]:
    """Measure cross-window recurrence of exact relationship identities."""
    cutoff = _dt(as_of) if as_of is not None else None
    eligible: list[tuple[datetime, dict[str, Any]]] = []
    excluded = 0
    seen_hashes: set[str] = set()
    for record in records or []:
        if not isinstance(record, dict):
            continue
        observed = _dt(record.get("observed_at"))
        ingested = _dt(record.get("ingested_at"))
        if observed is None or (cutoff is not None and (observed > cutoff or ingested is None or ingested > cutoff)):
            excluded += 1
            continue
        digest = str(record.get("evidence_hash") or "").strip()
        if digest and digest in seen_hashes:
            continue
        if digest:
            seen_hashes.add(digest)
        eligible.append((observed, record))
    eligible.sort(key=lambda item: item[0])

    base = {
        "stable": False,
        "snapshot_count": len(eligible),
        "excluded_snapshot_count": excluded,
        "minimum_snapshot_count": min_snapshots,
        "minimum_snapshots_per_slice": min_per_slice,
        **AUTHORITY,
    }
    if cutoff is not None:
        base["as_of"] = cutoff.isoformat()
        base["temporal_cutoff_enforced"] = True
    if len(eligible) < min_snapshots:
        return {**base, "stability_status": "NOT_EVALUATED", "blockers": ["INSUFFICIENT_SNAPSHOT_HISTORY"], "records": []}

    midpoint = len(eligible) // 2
    early, late = eligible[:midpoint], eligible[midpoint:]
    if len(early) < min_per_slice or len(late) < min_per_slice:
        return {**base, "stability_status": "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION", "blockers": ["INSUFFICIENT_SLICE_SAMPLE"], "slice_sizes": {"early": len(early), "late": len(late)}, "records": []}

    def counts(rows: list[tuple[datetime, dict[str, Any]]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for _, record in rows:
            for key in _snapshot_relationships(record):
                out[key] = out.get(key, 0) + 1
        return out

    early_counts, late_counts = counts(early), counts(late)
    identities = sorted(set(early_counts) | set(late_counts))
    relationship_records: list[dict[str, Any]] = []
    stable_count = 0
    for key in identities:
        ec, lc = early_counts.get(key, 0), late_counts.get(key, 0)
        state = "CROSS_WINDOW_RECURRENT" if ec > 0 and lc > 0 else "WINDOW_LOCAL_ONLY"
        if state == "CROSS_WINDOW_RECURRENT":
            stable_count += 1
        relationship_records.append({
            "relationship_key": key,
            "early_snapshot_count": ec,
            "late_snapshot_count": lc,
            "total_snapshot_count": ec + lc,
            "recurrence_state": state,
            **AUTHORITY,
        })

    blockers: list[str] = []
    if not identities:
        blockers.append("NO_RELATIONSHIP_EVIDENCE")
    elif stable_count == 0:
        blockers.append("NO_CROSS_WINDOW_RECURRENCE")
    status = "STABLE_FOR_DESCRIPTIVE_CALIBRATION" if not blockers else "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION"
    return {
        **base,
        "stable": not blockers,
        "stability_status": status,
        "blockers": blockers,
        "slice_sizes": {"early": len(early), "late": len(late)},
        "relationship_identity_count": len(identities),
        "cross_window_recurrent_count": stable_count,
        "window_local_only_count": len(identities) - stable_count,
        "records": relationship_records,
        "recurrence_is_not_strength_score": True,
    }


async def developer_relationship_stability(
    session: AsyncSession, entity_id: str, *, limit: int = 40, as_of: datetime | None = None,
) -> dict[str, Any]:
    """DB-backed stability assessment over immutable developer correlation snapshots."""
    limit = max(4, min(100, int(limit)))
    clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
    params: dict[str, Any] = {"entity_id": entity_id, "limit": limit}
    if as_of is not None:
        params["as_of"] = as_of
    try:
        rows = (await session.execute(text(f"""
            SELECT id, evidence_hash, evidence, observed_at, ingested_at
            FROM developer_correlation_snapshots
            WHERE entity_id = CAST(:entity_id AS UUID) {clause}
            ORDER BY observed_at DESC, id DESC LIMIT :limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "UNKNOWN", "entity_id": entity_id, "stable": False,
                "stability_status": "NOT_EVALUATED", "blockers": ["CORRELATION_HISTORY_UNAVAILABLE"],
                "missing": ["developer_correlation_snapshots"], **AUTHORITY}
    result = assess_developer_relationship_stability([dict(row) for row in rows], as_of=as_of)
    result["entity_id"] = entity_id
    result["status"] = "OBSERVED" if rows else "UNKNOWN"
    result["bounded"] = {"limit": limit}
    return result
