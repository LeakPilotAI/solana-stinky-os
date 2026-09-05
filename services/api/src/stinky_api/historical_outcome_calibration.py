"""Descriptive calibration of observed historical analogue outcomes.

Calibration summarizes evidence that has already been retrieved. It does not
turn historical outcomes into prediction, quality, risk, intent, or trading
semantics. Missing outcomes remain UNKNOWN.
"""

from __future__ import annotations

from typing import Any


def calibrate_historical_outcomes(
    outcome_comparison: dict[str, Any],
) -> dict[str, Any]:
    """Summarize bounded analogue outcome coverage without inference."""
    bounded = dict(outcome_comparison.get("bounded") or {})
    analogue_records = outcome_comparison.get("records") or []
    if not isinstance(analogue_records, list):
        analogue_records = []

    analogue_count = len(analogue_records)
    analogue_with_launches = 0
    launch_count = 0
    outcomes_known = 0
    outcomes_unknown = 0
    completed_count = 0

    for record in analogue_records:
        if not isinstance(record, dict):
            continue
        launches = record.get("launches") or []
        if not isinstance(launches, list):
            launches = []
        if launches:
            analogue_with_launches += 1
        for launch in launches:
            if not isinstance(launch, dict):
                continue
            launch_count += 1
            if launch.get("outcome_observed") is True:
                outcomes_known += 1
            else:
                outcomes_unknown += 1
            if launch.get("outcome_status") == "completed":
                completed_count += 1

    coverage = outcomes_known / launch_count if launch_count else None
    status = outcome_comparison.get("status")
    if status != "OBSERVED":
        return {
            "status": "UNKNOWN",
            "analogue_count": analogue_count,
            "analogue_with_launches": analogue_with_launches,
            "launch_count_observed": launch_count,
            "outcomes_known": outcomes_known,
            "outcomes_unknown": outcomes_unknown,
            "completed_count": completed_count,
            "outcome_coverage": coverage,
            "missing": list(outcome_comparison.get("missing") or ["historical_outcome_comparison"]),
            "bounded": bounded,
            "evidence_basis": "entity_launches",
            "evidence_only": True,
        }

    return {
        "status": "OBSERVED",
        "analogue_count": analogue_count,
        "analogue_with_launches": analogue_with_launches,
        "launch_count_observed": launch_count,
        "outcomes_known": outcomes_known,
        "outcomes_unknown": outcomes_unknown,
        "completed_count": completed_count,
        "outcome_coverage": coverage,
        "bounded": bounded,
        "evidence_basis": "entity_launches",
        "evidence_only": True,
    }
