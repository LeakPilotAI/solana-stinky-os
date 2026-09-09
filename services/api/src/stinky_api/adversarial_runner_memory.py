"""Evidence-only adversarial memory for runner-like prospective observations.

This module binds a frozen point-in-time feature record to a later canonical
measured outcome. It deliberately does not decide whether a token was a scam,
insider-controlled, collusive, risky, high quality, or tradeable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


AUTHORITY = {
    "interpretation": "ADVERSARIAL_RUNNER_MEMORY_EVIDENCE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "intent_inferred": False,
    "ownership_inferred": False,
    "collusion_inferred": False,
    "evidence_only": True,
}

_FAILED_OUTCOMES = {"FADE"}


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _label(outcome: dict[str, Any]) -> str | None:
    raw = outcome.get("label")
    return str(raw).strip().upper() if raw is not None else None


def build_adversarial_runner_memory(
    feature_record: dict[str, Any],
    outcome: dict[str, Any],
) -> dict[str, Any]:
    """Bind one frozen T0 feature record to a strictly later measured outcome.

    ``feature_record`` is expected to come from a prospective/dual-time-safe
    corpus. ``outcome`` must be canonical measured evidence. Missing or
    temporally invalid evidence remains UNKNOWN rather than being inferred.
    """
    mint = str(feature_record.get("mint") or "").strip()
    feature_as_of = _dt(feature_record.get("feature_as_of"))
    outcome_observed_at = _dt(outcome.get("completed_at") or outcome.get("observed_at"))
    label = _label(outcome)

    missing: list[str] = []
    if not mint:
        missing.append("mint")
    if feature_as_of is None:
        missing.append("feature_as_of")
    if not feature_record.get("feature_complete"):
        missing.append("complete_t0_feature_evidence")
    if not outcome.get("canonical_classification"):
        missing.append("canonical_measured_outcome")
    if label not in {"RUNNER", "HELD", "FADE"}:
        missing.append("classified_outcome")
    if outcome_observed_at is None:
        missing.append("outcome_observed_at")

    if missing:
        return {
            "status": "UNKNOWN",
            "mint": mint or None,
            "missing": list(dict.fromkeys(missing)),
            **AUTHORITY,
        }

    assert feature_as_of is not None
    assert outcome_observed_at is not None
    if outcome_observed_at <= feature_as_of:
        return {
            "status": "UNKNOWN",
            "mint": mint,
            "missing": ["strictly_later_outcome_evidence"],
            "feature_as_of": feature_as_of.isoformat(),
            "outcome_observed_at": outcome_observed_at.isoformat(),
            "temporal_violation": True,
            **AUTHORITY,
        }

    contradiction = label in _FAILED_OUTCOMES
    return {
        "status": "OBSERVED",
        "mint": mint,
        "entity_id": feature_record.get("entity_id"),
        "migration_event_id": feature_record.get("migration_event_id"),
        "feature_as_of": feature_as_of.isoformat(),
        "feature_snapshot": {
            "developer_dual_time_visible": bool(feature_record.get("developer_dual_time_visible")),
            "correlation_dual_time_visible": bool(feature_record.get("correlation_dual_time_visible")),
            "lifecycle_dual_time_visible": bool(feature_record.get("lifecycle_dual_time_visible")),
            "lifecycle_evidence_basis": feature_record.get("lifecycle_evidence_basis"),
        },
        "outcome": {
            "label": label,
            "observed_at": outcome_observed_at.isoformat(),
            "evidence_basis": outcome.get("evidence_basis"),
            "source_table": outcome.get("source_table"),
        },
        "adversarial_case": contradiction,
        "adversarial_basis": "runner_like_t0_evidence_then_later_fade" if contradiction else None,
        "temporal_cutoff_enforced": True,
        "future_evidence_used_in_t0_features": False,
        **AUTHORITY,
    }
