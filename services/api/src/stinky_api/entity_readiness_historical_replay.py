"""Historical replay validation for immutable entity-readiness evidence.

Replay is observational only. It validates the sequence Genesis actually captured;
it never backdates or reconstructs derived readiness snapshots.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.entity_readiness_transition_audit import (
    AUTHORITY as TRANSITION_AUTHORITY,
    canonical_entity_readiness,
    describe_entity_readiness_transition,
)

AUTHORITY = {
    **TRANSITION_AUTHORITY,
    "interpretation": "HISTORICAL_ENTITY_READINESS_REPLAY_ONLY",
    "historical_snapshot_reconstruction_authorized": False,
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


def validate_entity_readiness_replay(records: list[dict[str, Any]], *, as_of: datetime | str | None = None) -> dict[str, Any]:
    """Validate chronological readiness snapshots without inventing missing history."""
    cutoff = _dt(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        return {"status": "TEMPORAL_VIOLATION", "valid": False, "blockers": ["INVALID_AS_OF"], "checkpoints": [], **AUTHORITY}

    parsed: list[tuple[datetime, datetime, int, dict[str, Any]]] = []
    violations: list[dict[str, Any]] = []
    excluded_future = 0
    for index, record in enumerate(records or []):
        observed = _dt(record.get("observed_at"))
        ingested = _dt(record.get("ingested_at"))
        readiness = record.get("readiness") if isinstance(record.get("readiness"), dict) else None
        if observed is None or ingested is None or readiness is None:
            violations.append({"index": index, "kind": "INVALID_CAPTURED_SNAPSHOT"})
            continue
        if ingested < observed:
            violations.append({"index": index, "kind": "INGESTED_BEFORE_OBSERVED", "observed_at": observed.isoformat(), "ingested_at": ingested.isoformat()})
            continue
        if cutoff is not None and (observed > cutoff or ingested > cutoff):
            excluded_future += 1
            continue
        parsed.append((observed, ingested, index, readiness))

    parsed.sort(key=lambda item: (item[0], item[1], item[2]))
    checkpoints: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    ready_count = 0
    regression_count = 0
    became_ready_count = 0
    for observed, ingested, index, readiness in parsed:
        canonical = canonical_entity_readiness(readiness)
        transition = describe_entity_readiness_transition(previous, readiness)
        if canonical.get("ready"):
            ready_count += 1
        if transition.get("transition") == "REGRESSED_FROM_DESCRIPTIVE_CALIBRATION_READINESS":
            regression_count += 1
        if transition.get("transition") == "BECAME_READY_FOR_DESCRIPTIVE_CALIBRATION":
            became_ready_count += 1
        checkpoints.append({
            "source_index": index,
            "observed_at": observed.isoformat(),
            "ingested_at": ingested.isoformat(),
            "status": canonical.get("status"),
            "ready": canonical.get("ready"),
            "blockers": canonical.get("blockers") or [],
            "transition": transition.get("transition"),
        })
        previous = readiness

    if violations:
        status = "TEMPORAL_VIOLATION"
        valid = False
        blockers = sorted({str(v["kind"]) for v in violations})
    elif not checkpoints:
        status = "INSUFFICIENT_CAPTURED_HISTORY"
        valid = False
        blockers = ["NO_VISIBLE_READINESS_SNAPSHOTS"]
    elif len(checkpoints) < 2:
        status = "INSUFFICIENT_CAPTURED_HISTORY"
        valid = False
        blockers = ["INSUFFICIENT_REPLAY_DEPTH"]
    else:
        status = "VALIDATED"
        valid = True
        blockers = []

    result = {
        "status": status,
        "valid": valid,
        "blockers": blockers,
        "checkpoint_count": len(checkpoints),
        "ready_checkpoint_count": ready_count,
        "not_ready_checkpoint_count": len(checkpoints) - ready_count,
        "became_ready_count": became_ready_count,
        "regression_count": regression_count,
        "checkpoints": checkpoints,
        "temporal_integrity": {
            "missing_or_invalid_timestamps_fail_closed": True,
            "ingested_before_observed_forbidden": True,
            "future_snapshots_excluded": excluded_future,
            "cutoff_enforced": cutoff is not None,
        },
        "historical_policy": {
            "captured_snapshots_only": True,
            "derived_snapshots_are_not_backdated": True,
            "missing_history_remains_unknown": True,
        },
        **AUTHORITY,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
    return result


async def historical_entity_readiness_replay(
    session: AsyncSession,
    *,
    entity_limit: int = 100,
    snapshot_limit_per_entity: int = 100,
    as_of: datetime | str | None = None,
) -> dict[str, Any]:
    """Validate captured readiness sequences across a bounded historical cohort."""
    cutoff = _dt(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        return {"status": "TEMPORAL_VIOLATION", "valid": False, "blockers": ["INVALID_AS_OF"], "entities": [], **AUTHORITY}
    entity_limit = max(1, min(500, int(entity_limit)))
    snapshot_limit_per_entity = max(2, min(200, int(snapshot_limit_per_entity)))
    clause = "WHERE observed_at <= :as_of AND ingested_at <= :as_of" if cutoff is not None else ""
    params: dict[str, Any] = {"entity_limit": entity_limit}
    if cutoff is not None:
        params["as_of"] = cutoff
    try:
        entities = (await session.execute(text(f"""
            SELECT entity_id::text AS entity_id, MAX(observed_at) AS latest_observed_at
            FROM entity_readiness_snapshots
            {clause}
            GROUP BY entity_id
            ORDER BY latest_observed_at DESC, entity_id
            LIMIT :entity_limit
        """), params)).mappings().all()
    except Exception:
        return {"status": "INSUFFICIENT_CAPTURED_HISTORY", "valid": False, "blockers": ["ENTITY_READINESS_SNAPSHOTS_UNAVAILABLE"], "entities": [], "missing": ["entity_readiness_snapshots"], **AUTHORITY}

    results: list[dict[str, Any]] = []
    for row in entities:
        row_params: dict[str, Any] = {"entity_id": row["entity_id"], "limit": snapshot_limit_per_entity}
        row_clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if cutoff is not None else ""
        if cutoff is not None:
            row_params["as_of"] = cutoff
        snapshots = (await session.execute(text(f"""
            SELECT readiness, observed_at, ingested_at
            FROM entity_readiness_snapshots
            WHERE entity_id = CAST(:entity_id AS UUID) {row_clause}
            ORDER BY observed_at ASC, ingested_at ASC, id ASC
            LIMIT :limit
        """), row_params)).mappings().all()
        validation = validate_entity_readiness_replay([dict(item) for item in snapshots], as_of=cutoff)
        results.append({"entity_id": row["entity_id"], **validation})

    counts = {
        "entity_count": len(results),
        "validated": sum(1 for item in results if item.get("status") == "VALIDATED"),
        "insufficient_captured_history": sum(1 for item in results if item.get("status") == "INSUFFICIENT_CAPTURED_HISTORY"),
        "temporal_violations": sum(1 for item in results if item.get("status") == "TEMPORAL_VIOLATION"),
        "entities_with_regressions": sum(1 for item in results if int(item.get("regression_count") or 0) > 0),
    }
    overall = "TEMPORAL_VIOLATION" if counts["temporal_violations"] else ("VALIDATED" if counts["validated"] else "INSUFFICIENT_CAPTURED_HISTORY")
    result = {
        "status": overall,
        "valid": counts["temporal_violations"] == 0 and counts["validated"] > 0,
        "counts": counts,
        "entities": results,
        "bounded": {"entity_limit": entity_limit, "snapshot_limit_per_entity": snapshot_limit_per_entity},
        "historical_policy": {"captured_snapshots_only": True, "derived_snapshots_are_not_backdated": True},
        **AUTHORITY,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result
