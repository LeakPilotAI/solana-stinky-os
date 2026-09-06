"""Descriptive repetition analysis for developer/deployer correlation evidence.

Repetition is evidence frequency, not ownership, coordination, intent, risk, quality,
probability, expected return, or a trade signal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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
    except ValueError:
        return None


def _span_seconds(first: Any, last: Any) -> int | None:
    start, end = _dt(first), _dt(last)
    if start is None or end is None or end < start:
        return None
    return int((end - start).total_seconds())


def _state(observation_count: int | None, distinct_launch_count: int | None) -> str:
    if distinct_launch_count is not None and distinct_launch_count >= 2:
        return "MULTI_LAUNCH_REPETITION"
    if observation_count is not None and observation_count >= 2:
        return "REPEATED_OBSERVATION"
    if observation_count == 1 or distinct_launch_count == 1:
        return "SINGLE_OBSERVATION"
    return "UNKNOWN"


def _fact(
    row: dict[str, Any],
    *,
    kind: str,
    identity_fields: tuple[str, ...],
    observation_field: str | None,
    launch_field: str | None,
    first_fields: tuple[str, ...],
    last_fields: tuple[str, ...],
) -> dict[str, Any]:
    identity = {field: row.get(field) for field in identity_fields}
    observation_count: int | None = None
    if observation_field and row.get(observation_field) is not None:
        try: observation_count = max(0, int(row.get(observation_field)))
        except (TypeError, ValueError): observation_count = None
    if observation_count is None and kind == "WALLET_REUSE":
        observation_count = 1
    launch_count: int | None = None
    if launch_field and row.get(launch_field) is not None:
        try: launch_count = max(0, int(row.get(launch_field)))
        except (TypeError, ValueError): launch_count = None
    first = next((row.get(field) for field in first_fields if row.get(field) is not None), None)
    last = next((row.get(field) for field in last_fields if row.get(field) is not None), None)
    return {
        "kind": kind,
        "identity": identity,
        "independent_observation_count": observation_count,
        "distinct_launch_count": launch_count,
        "distinct_related_entity_count": 1 if row.get("other_entity_id") or row.get("buyer_entity_id") else None,
        "first_observed_at": first,
        "last_observed_at": last,
        "temporal_spread_seconds": _span_seconds(first, last),
        "repetition_state": _state(observation_count, launch_count),
        **AUTHORITY,
    }


def analyze_correlation_repetition(correlation: dict[str, Any]) -> dict[str, Any]:
    """Summarize how often factual correlation relationships have been observed."""
    facts: list[dict[str, Any]] = []
    specs = (
        ("shared_funders", "SHARED_FUNDER", ("funder_wallet", "other_entity_id"), "observation_count", None,
         ("first_observed_at",), ("last_observed_at",)),
        ("cross_entity_wallet_reuse", "WALLET_REUSE", ("wallet", "other_entity_id"), None, None,
         ("first_seen_at",), ("last_seen_at",)),
        ("deployer_buyer_recurrence", "DEPLOYER_BUYER_RECURRENCE", ("wallet", "buyer_entity_id"), "launch_count", "launch_count",
         ("first_observed_at",), ("last_observed_at",)),
        ("shared_relationship_structures", "RELATIONSHIP_STRUCTURE", ("relationship_kind", "other_entity_id"), "observation_count", None,
         ("first_observed_at", "first_seen_at"), ("last_observed_at", "last_seen_at")),
    )
    for field, kind, identity_fields, observation_field, launch_field, first_fields, last_fields in specs:
        for row in correlation.get(field) or []:
            if isinstance(row, dict):
                facts.append(_fact(row, kind=kind, identity_fields=identity_fields,
                                   observation_field=observation_field, launch_field=launch_field,
                                   first_fields=first_fields, last_fields=last_fields))

    repeated = [f for f in facts if f["repetition_state"] in {"REPEATED_OBSERVATION", "MULTI_LAUNCH_REPETITION"}]
    multi_launch = [f for f in facts if f["repetition_state"] == "MULTI_LAUNCH_REPETITION"]
    known_counts = [f["independent_observation_count"] for f in facts if f["independent_observation_count"] is not None]
    known_spans = [f["temporal_spread_seconds"] for f in facts if f["temporal_spread_seconds"] is not None]
    missing: list[str] = []
    if facts and len(known_counts) < len(facts): missing.append("some_observation_counts")
    if facts and len(known_spans) < len(facts): missing.append("some_temporal_spans")
    if facts and any(f["distinct_launch_count"] is None for f in facts): missing.append("some_distinct_launch_counts")

    status = "OBSERVED" if facts else ("UNKNOWN" if correlation.get("status") == "UNKNOWN" else "NEW-UNKNOWN")
    return {
        "status": status,
        "relationship_count_observed": len(facts),
        "repeated_relationship_count": len(repeated),
        "multi_launch_relationship_count": len(multi_launch),
        "total_independent_observation_count": sum(known_counts) if known_counts else (0 if not facts else None),
        "max_temporal_spread_seconds": max(known_spans) if known_spans else None,
        "records": facts,
        "missing": missing,
        "repetition_is_not_strength_score": True,
        **AUTHORITY,
    }
