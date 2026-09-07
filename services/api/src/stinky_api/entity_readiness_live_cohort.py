"""Read-only live cohort coverage measurement for captured entity readiness history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.entity_readiness_historical_replay import (
    AUTHORITY as REPLAY_AUTHORITY,
    historical_entity_readiness_replay,
)

AUTHORITY = {
    **REPLAY_AUTHORITY,
    "interpretation": "LIVE_ENTITY_READINESS_COVERAGE_ONLY",
    "release_authority": False,
}

# PR #126 changed readiness capture to one authoritative timestamp for both
# observed_at and ingested_at. The merge timestamp defines the earliest epoch
# in which that capture contract exists in code. Historical rows remain intact.
PROSPECTIVE_CAPTURE_EPOCH = datetime(2026, 9, 7, 4, 6, 38, tzinfo=timezone.utc)


def summarize_live_cohort_replay(replay: dict[str, Any]) -> dict[str, Any]:
    """Convert bounded replay results into explicit operational coverage metrics."""
    entities = replay.get("entities") if isinstance(replay.get("entities"), list) else []
    total = len(entities)
    validated = sum(1 for item in entities if item.get("status") == "VALIDATED")
    insufficient = sum(1 for item in entities if item.get("status") == "INSUFFICIENT_CAPTURED_HISTORY")
    violations = sum(1 for item in entities if item.get("status") == "TEMPORAL_VIOLATION")
    ever_ready = sum(1 for item in entities if int(item.get("ready_checkpoint_count") or 0) > 0)
    currently_ready = sum(
        1 for item in entities
        if item.get("checkpoints") and bool(item["checkpoints"][-1].get("ready"))
    )
    regressions = sum(1 for item in entities if int(item.get("regression_count") or 0) > 0)

    def ratio(value: int) -> float | None:
        return value / total if total else None

    blockers: list[str] = []
    if total == 0:
        blockers.append("NO_CAPTURED_ENTITY_COHORT")
    if violations:
        blockers.append("TEMPORAL_INTEGRITY_VIOLATIONS_PRESENT")
    if validated == 0:
        blockers.append("NO_VALIDATED_REPLAY_ENTITIES")
    if insufficient:
        blockers.append("CAPTURED_HISTORY_COVERAGE_INCOMPLETE")

    measurement_complete = total > 0 and violations == 0
    result = {
        "status": "MEASURED" if measurement_complete else ("TEMPORAL_VIOLATION" if violations else "INSUFFICIENT_CAPTURED_HISTORY"),
        "measurement_complete": measurement_complete,
        "blockers": blockers,
        "coverage": {
            "entity_count": total,
            "validated_entities": validated,
            "validated_ratio": ratio(validated),
            "insufficient_history_entities": insufficient,
            "insufficient_history_ratio": ratio(insufficient),
            "temporal_violation_entities": violations,
            "temporal_violation_ratio": ratio(violations),
            "ever_ready_entities": ever_ready,
            "ever_ready_ratio": ratio(ever_ready),
            "currently_ready_entities": currently_ready,
            "currently_ready_ratio": ratio(currently_ready),
            "entities_with_regressions": regressions,
            "regression_entity_ratio": ratio(regressions),
        },
        "release_gate": {
            "status": "NOT_AUTHORIZED",
            "reason": "COVERAGE_MEASUREMENT_IS_OBSERVATIONAL_ONLY",
            "requires_separate_release_criteria": True,
        },
        "source": "entity_readiness_snapshots",
        "read_only": True,
        **AUTHORITY,
    }
    if replay.get("as_of") is not None:
        result["as_of"] = replay.get("as_of")
        result["temporal_cutoff_enforced"] = bool(replay.get("temporal_cutoff_enforced"))
    return result


def _historical_integrity_summary(
    historical_replay: dict[str, Any],
    prospective_replay: dict[str, Any],
    *,
    include_entities: bool,
) -> dict[str, Any]:
    historical_entities = historical_replay.get("entities") if isinstance(historical_replay.get("entities"), list) else []
    prospective_entities = prospective_replay.get("entities") if isinstance(prospective_replay.get("entities"), list) else []
    historical_violation_ids = {
        str(item.get("entity_id"))
        for item in historical_entities
        if item.get("status") == "TEMPORAL_VIOLATION" and item.get("entity_id")
    }
    prospective_violation_ids = {
        str(item.get("entity_id"))
        for item in prospective_entities
        if item.get("status") == "TEMPORAL_VIOLATION" and item.get("entity_id")
    }
    legacy_only_ids = sorted(historical_violation_ids - prospective_violation_ids)
    result = {
        "status": historical_replay.get("status"),
        "valid": bool(historical_replay.get("valid")),
        "entity_count": len(historical_entities),
        "temporal_violation_entities": len(historical_violation_ids),
        "prospective_temporal_violation_entities": len(prospective_violation_ids),
        "legacy_temporal_violation_entities": len(legacy_only_ids),
        "legacy_rows_preserved": True,
        "legacy_rows_mutated": False,
        "legacy_violations_excluded_from_prospective_health": True,
        "prospective_violations_fail_live_health": True,
    }
    if include_entities:
        result["legacy_temporal_violation_entity_ids"] = legacy_only_ids
    return result


async def live_entity_readiness_cohort_validation(
    session: AsyncSession,
    *,
    entity_limit: int = 100,
    snapshot_limit_per_entity: int = 100,
    as_of: datetime | str | None = None,
    include_entities: bool = False,
) -> dict[str, Any]:
    """Measure post-fix prospective health while retaining whole-history integrity."""
    historical_replay = await historical_entity_readiness_replay(
        session,
        entity_limit=entity_limit,
        snapshot_limit_per_entity=snapshot_limit_per_entity,
        as_of=as_of,
    )
    prospective_replay = await historical_entity_readiness_replay(
        session,
        entity_limit=entity_limit,
        snapshot_limit_per_entity=snapshot_limit_per_entity,
        as_of=as_of,
        not_before=PROSPECTIVE_CAPTURE_EPOCH,
    )
    summary = summarize_live_cohort_replay(prospective_replay)
    summary["bounded"] = prospective_replay.get("bounded") or {
        "entity_limit": max(1, min(500, int(entity_limit))),
        "snapshot_limit_per_entity": max(2, min(200, int(snapshot_limit_per_entity))),
    }
    summary["prospective_epoch"] = PROSPECTIVE_CAPTURE_EPOCH.isoformat()
    summary["cohort_scope"] = "POST_TIMESTAMP_INTEGRITY_FIX_PROSPECTIVE_CAPTURE"
    summary["replay_status"] = prospective_replay.get("status")
    summary["replay_valid"] = bool(prospective_replay.get("valid"))
    summary["historical_policy"] = historical_replay.get("historical_policy") or {
        "captured_snapshots_only": True,
        "derived_snapshots_are_not_backdated": True,
    }
    summary["historical_integrity"] = _historical_integrity_summary(
        historical_replay,
        prospective_replay,
        include_entities=include_entities,
    )
    if include_entities:
        summary["entities"] = prospective_replay.get("entities") or []
    return summary
