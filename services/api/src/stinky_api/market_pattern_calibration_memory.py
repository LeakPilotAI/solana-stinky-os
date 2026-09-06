"""Persist and read longitudinal rolling-calibration evidence.

Snapshots are immutable evidence records keyed by pattern, evidence boundary, and
criteria. They preserve descriptive calibration history only and do not grant
prediction, confidence, quality/risk scoring, or trading authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _criteria_hash(criteria: dict[str, Any]) -> str:
    payload = json.dumps(criteria, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


def _evidence_boundary(rolling: dict[str, Any]) -> datetime | None:
    windows = rolling.get("windows") if isinstance(rolling, dict) else None
    if not isinstance(windows, list):
        return None
    candidates: list[datetime] = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        evaluation_window = window.get("evaluation_window")
        if not isinstance(evaluation_window, dict):
            continue
        observed_at = _parse_time(evaluation_window.get("last_observed_at"))
        if observed_at is not None:
            candidates.append(observed_at)
    return max(candidates) if candidates else None


def _unknown(reason: str, *, pattern_hash: str | None, limit: int) -> dict[str, Any]:
    return {
        "status": "UNKNOWN",
        "pattern_hash": pattern_hash,
        "snapshot_count": 0,
        "records": [],
        "missing": [reason],
        "bounded": {"limit": limit},
        "evidence_basis": "market_pattern_calibration_snapshots",
        "evidence_only": True,
    }


async def persist_rolling_calibration_snapshot(
    session: AsyncSession,
    rolling: dict[str, Any],
    *,
    computed_at: datetime | str | None = None,
) -> dict[str, Any] | None:
    """Persist one idempotent rolling-calibration snapshot."""
    if not isinstance(rolling, dict) or rolling.get("status") != "OBSERVED":
        return None
    pattern_hash = str(rolling.get("pattern_hash") or "").strip()
    trend_status = str(rolling.get("trend_status") or "").strip()
    criteria = rolling.get("criteria") if isinstance(rolling.get("criteria"), dict) else {}
    evidence_through = _evidence_boundary(rolling)
    if not pattern_hash or not trend_status or evidence_through is None:
        return None
    computed = _parse_time(computed_at) if computed_at is not None else datetime.now(timezone.utc)
    if computed is None:
        return None
    as_of = _parse_time(rolling.get("as_of")) if rolling.get("as_of") is not None else None
    if rolling.get("as_of") is not None and as_of is None:
        return None

    criteria_hash = _criteria_hash(criteria)
    payload = json.dumps(rolling, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    criteria_payload = json.dumps(criteria, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    params = {
        "pattern_hash": pattern_hash,
        "evidence_through_observed_at": evidence_through,
        "as_of": as_of,
        "computed_at": computed,
        "trend_status": trend_status,
        "window_count": int(rolling.get("window_count") or 0),
        "evaluated_window_count": int(rolling.get("evaluated_window_count") or 0),
        "criteria_hash": criteria_hash,
        "criteria": criteria_payload,
        "snapshot": payload,
        "evidence_basis": "successive_chronological_reference_and_evaluation_windows",
    }
    try:
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO market_pattern_calibration_snapshots (
                        pattern_hash, evidence_through_observed_at, as_of, computed_at,
                        trend_status, window_count, evaluated_window_count, criteria_hash,
                        criteria, snapshot, evidence_basis
                    ) VALUES (
                        :pattern_hash, :evidence_through_observed_at, :as_of, :computed_at,
                        :trend_status, :window_count, :evaluated_window_count, :criteria_hash,
                        CAST(:criteria AS jsonb), CAST(:snapshot AS jsonb), :evidence_basis
                    )
                    ON CONFLICT (pattern_hash, evidence_through_observed_at, criteria_hash)
                    DO NOTHING
                    RETURNING id
                    """
                ),
                params,
            )
        ).first()
        if row:
            await session.commit()
            snapshot_id = int(row[0])
        else:
            await session.rollback()
            existing = (
                await session.execute(
                    text(
                        """
                        SELECT id FROM market_pattern_calibration_snapshots
                        WHERE pattern_hash = :pattern_hash
                          AND evidence_through_observed_at = :evidence_through_observed_at
                          AND criteria_hash = :criteria_hash
                        LIMIT 1
                        """
                    ),
                    params,
                )
            ).first()
            snapshot_id = int(existing[0]) if existing else 0
        return {
            "snapshot_id": snapshot_id or None,
            "pattern_hash": pattern_hash,
            "evidence_through_observed_at": evidence_through.isoformat(),
            "criteria_hash": criteria_hash,
            "evidence_only": True,
        }
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
        return None


async def calibration_longitudinal_memory(
    session: AsyncSession,
    pattern_hash: str,
    *,
    limit: int = 100,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Return bounded persisted calibration snapshots, optionally at a cutoff."""
    pattern_hash = str(pattern_hash or "").strip()
    bounded_limit = max(1, min(int(limit), 500))
    if not pattern_hash:
        return _unknown("pattern_hash", pattern_hash=None, limit=bounded_limit)
    cutoff = _parse_time(as_of)
    if as_of is not None and cutoff is None:
        return _unknown("invalid_as_of", pattern_hash=pattern_hash, limit=bounded_limit)

    cutoff_clause = ""
    params: dict[str, Any] = {"pattern_hash": pattern_hash, "limit": bounded_limit}
    if cutoff is not None:
        cutoff_clause = "AND evidence_through_observed_at <= :as_of"
        params["as_of"] = cutoff
    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT id, pattern_hash, evidence_through_observed_at, as_of,
                           computed_at, ingested_at, trend_status, window_count,
                           evaluated_window_count, criteria_hash, criteria, snapshot,
                           evidence_basis, created_at
                    FROM market_pattern_calibration_snapshots
                    WHERE pattern_hash = :pattern_hash
                      {cutoff_clause}
                    ORDER BY evidence_through_observed_at ASC, id ASC
                    LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()
    except Exception:
        return _unknown("market_pattern_calibration_snapshots", pattern_hash=pattern_hash, limit=bounded_limit)

    if not rows:
        result = _unknown("market_pattern_calibration_snapshots", pattern_hash=pattern_hash, limit=bounded_limit)
        if cutoff is not None:
            result["as_of"] = cutoff.isoformat()
            result["temporal_cutoff_enforced"] = True
        return result

    records: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        for key in ("evidence_through_observed_at", "as_of", "computed_at", "ingested_at", "created_at"):
            value = record.get(key)
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()
        record["evidence_only"] = True
        records.append(record)

    result: dict[str, Any] = {
        "status": "OBSERVED",
        "pattern_hash": pattern_hash,
        "snapshot_count": len(records),
        "records": records,
        "missing": [],
        "bounded": {"limit": bounded_limit},
        "evidence_basis": "market_pattern_calibration_snapshots",
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
