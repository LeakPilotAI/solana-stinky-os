"""Observational soak/maturity evaluation for the clean prospective readiness corpus."""
from __future__ import annotations

from typing import Any

SOAK_POLICY = {
    "minimum_entities": 25,
    "minimum_repeat_entities": 5,
    "minimum_validated_entities": 1,
    "minimum_repeat_entity_ratio": 0.20,
}


def evaluate_readiness_corpus_soak(report: dict[str, Any]) -> dict[str, Any]:
    """Assess evidence maturity without granting release/predictive authority."""
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    entities = report.get("entities") if isinstance(report.get("entities"), list) else []
    total = int(coverage.get("entity_count") or len(entities))
    violations = int(coverage.get("temporal_violation_entities") or 0)
    validated = int(coverage.get("validated_entities") or 0)
    repeat_entities = sum(1 for item in entities if int(item.get("checkpoint_count") or 0) >= 2)
    changed_state_entities = sum(
        1 for item in entities
        if len({str(cp.get("status")) + "|" + ",".join(cp.get("blockers") or []) for cp in (item.get("checkpoints") or [])}) >= 2
    )
    repeat_ratio = repeat_entities / total if total else None

    blockers: list[str] = []
    if violations:
        blockers.append("PROSPECTIVE_TEMPORAL_INTEGRITY_VIOLATION")
    if total < SOAK_POLICY["minimum_entities"]:
        blockers.append("PROSPECTIVE_COHORT_TOO_SMALL")
    if repeat_entities < SOAK_POLICY["minimum_repeat_entities"]:
        blockers.append("INSUFFICIENT_REPEAT_ENTITY_COVERAGE")
    if repeat_ratio is None or repeat_ratio < SOAK_POLICY["minimum_repeat_entity_ratio"]:
        blockers.append("INSUFFICIENT_REPEAT_ENTITY_RATIO")
    if validated < SOAK_POLICY["minimum_validated_entities"]:
        blockers.append("NO_VALIDATED_REPLAY_ENTITIES")

    mature = not blockers
    return {
        "status": "SOAK_MATURE" if mature else ("TEMPORAL_VIOLATION" if violations else "ACCUMULATING_EVIDENCE"),
        "mature": mature,
        "blockers": blockers,
        "policy": dict(SOAK_POLICY),
        "metrics": {
            "entity_count": total,
            "repeat_entities": repeat_entities,
            "repeat_entity_ratio": repeat_ratio,
            "changed_state_entities": changed_state_entities,
            "validated_entities": validated,
            "prospective_temporal_violation_entities": violations,
        },
        "interpretation": "PROSPECTIVE_READINESS_CORPUS_SOAK_ONLY",
        "evidence_only": True,
        "read_only": True,
        "release_authority": False,
        "predictive_authority": False,
        "risk_inferred": False,
        "quality_inferred": False,
        "trade_signal": False,
    }
