"""Read-only component-maturity diagnostics for captured readiness evidence."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "READINESS_COMPONENT_MATURITY_DIAGNOSTIC_ONLY",
    "release_authority": False,
    "predictive_authority": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "trade_signal": False,
    "evidence_only": True,
    "read_only": True,
}

_COMPONENTS = ("developer_history", "relationship_history", "outcome_history")


def _counts(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def summarize_readiness_component_maturity(readiness_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize latest captured component states without changing gate semantics."""
    top_blockers: Counter[str] = Counter()
    component_status: dict[str, Counter[str]] = {name: Counter() for name in _COMPONENTS}
    component_blockers: dict[str, Counter[str]] = {name: Counter() for name in _COMPONENTS}
    passed = {name: 0 for name in _COMPONENTS}
    outcome_observed = 0
    outcome_launch_counts: list[int] = []
    outcome_known_counts: list[int] = []
    outcome_coverages: list[float] = []

    valid_rows = [row for row in readiness_rows if isinstance(row, dict)]
    for readiness in valid_rows:
        top_blockers.update(str(item) for item in (readiness.get("blockers") or []))
        components = readiness.get("components") if isinstance(readiness.get("components"), dict) else {}
        for name in _COMPONENTS:
            component = components.get(name) if isinstance(components.get(name), dict) else {}
            status = str(component.get("status") or "UNKNOWN")
            component_status[name][status] += 1
            if bool(component.get("passed")):
                passed[name] += 1
            component_blockers[name].update(str(item) for item in (component.get("blockers") or []))
        outcome = components.get("outcome_history") if isinstance(components.get("outcome_history"), dict) else {}
        if outcome.get("status") == "OBSERVED":
            outcome_observed += 1
        try:
            outcome_launch_counts.append(int(outcome.get("launch_count_observed") or 0))
        except (TypeError, ValueError):
            outcome_launch_counts.append(0)
        try:
            outcome_known_counts.append(int(outcome.get("outcomes_known") or 0))
        except (TypeError, ValueError):
            outcome_known_counts.append(0)
        try:
            if outcome.get("outcome_coverage") is not None:
                outcome_coverages.append(float(outcome["outcome_coverage"]))
        except (TypeError, ValueError):
            pass

    total = len(valid_rows)
    components_out: dict[str, Any] = {}
    for name in _COMPONENTS:
        components_out[name] = {
            "passed_entities": passed[name],
            "passed_ratio": (passed[name] / total if total else None),
            "status_counts": _counts(component_status[name]),
            "blocker_counts": _counts(component_blockers[name]),
        }

    return {
        "status": "MEASURED" if total else "INSUFFICIENT_CAPTURED_HISTORY",
        "entity_count": total,
        "top_level_blocker_counts": _counts(top_blockers),
        "components": components_out,
        "outcome_history_metrics": {
            "observed_entities": outcome_observed,
            "observed_ratio": (outcome_observed / total if total else None),
            "max_launch_count_observed": max(outcome_launch_counts, default=0),
            "max_outcomes_known": max(outcome_known_counts, default=0),
            "max_outcome_coverage": max(outcome_coverages, default=None),
        },
        **AUTHORITY,
    }


async def readiness_component_maturity(
    session: AsyncSession,
    *,
    entity_ids: list[str],
    not_before: datetime,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Read the latest captured readiness per bounded cohort entity."""
    ids = [str(value) for value in entity_ids if str(value).strip()][:500]
    if not ids:
        return summarize_readiness_component_maturity([])
    clauses = ["entity_id = ANY(CAST(:entity_ids AS uuid[]))", "observed_at >= :not_before"]
    params: dict[str, Any] = {"entity_ids": ids, "not_before": not_before}
    if as_of is not None:
        clauses.append("observed_at <= :as_of")
        clauses.append("ingested_at <= :as_of")
        params["as_of"] = as_of
    try:
        rows = (
            await session.execute(
                text(
                    f"""
                    SELECT DISTINCT ON (entity_id) readiness
                    FROM entity_readiness_snapshots
                    WHERE {' AND '.join(clauses)}
                    ORDER BY entity_id, observed_at DESC, ingested_at DESC, id DESC
                    """
                ),
                params,
            )
        ).mappings().all()
    except Exception:
        return {
            **summarize_readiness_component_maturity([]),
            "status": "UNKNOWN",
            "missing": ["entity_readiness_snapshots"],
        }
    return summarize_readiness_component_maturity(
        [dict(row.get("readiness") or {}) for row in rows]
    )
