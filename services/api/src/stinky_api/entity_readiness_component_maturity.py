"""Read-only component-maturity diagnostics for captured readiness evidence."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.entity_readiness_historical_depth import entity_readiness_historical_depth

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
_CLASSIFIED_OUTCOMES = ("RUNNER", "HELD", "FADE")
_PERSISTED_LAUNCH_LIMIT = 5000


def _counts(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def summarize_persisted_outcomes(rows: list[dict[str, Any]], *, limit_hit: bool = False) -> dict[str, Any]:
    """Summarize real persisted launch outcomes without granting calibration authority."""
    status_counts: Counter[str] = Counter()
    evidence_basis_counts: Counter[str] = Counter()
    classification_reason_counts: Counter[str] = Counter()
    classified_entities: set[str] = set()
    entities_with_status: dict[str, set[str]] = {}
    canonical_classified_launches = 0
    unknown_performance_launches = 0
    classification_metadata_launches = 0

    valid_rows = [row for row in rows if isinstance(row, dict)]
    for row in valid_rows:
        entity_id = str(row.get("entity_id") or "").strip()
        raw_status = row.get("outcome_status")
        status = str(raw_status).strip().upper() if raw_status is not None else "NULL"
        status = status or "NULL"
        status_counts[status] += 1
        if entity_id:
            entities_with_status.setdefault(status, set()).add(entity_id)

        meta = row.get("outcome_meta") if isinstance(row.get("outcome_meta"), dict) else {}
        classification = meta.get("classification") if isinstance(meta.get("classification"), dict) else {}
        evidence_basis = str(meta.get("evidence_basis") or classification.get("evidence_basis") or "").strip()
        if evidence_basis:
            evidence_basis_counts[evidence_basis] += 1
        reason = str(classification.get("reason") or "").strip()
        if reason:
            classification_reason_counts[reason] += 1
        if classification:
            classification_metadata_launches += 1
        if str(meta.get("performance_outcome") or "").upper() == "UNKNOWN":
            unknown_performance_launches += 1

        canonical = bool(classification.get("canonical_classification"))
        if status in _CLASSIFIED_OUTCOMES and canonical:
            canonical_classified_launches += 1
            if entity_id:
                classified_entities.add(entity_id)

    entities_with_status_counts = {
        status: len(entity_ids) for status, entity_ids in sorted(entities_with_status.items())
    }
    return {
        "status": "MEASURED" if valid_rows else "NO_PERSISTED_LAUNCH_ROWS",
        "launch_rows": len(valid_rows),
        "launch_limit": _PERSISTED_LAUNCH_LIMIT,
        "launch_limit_hit": bool(limit_hit),
        "launch_status_counts": _counts(status_counts),
        "entities_with_status_counts": entities_with_status_counts,
        "canonical_classified_launches": canonical_classified_launches,
        "entities_with_canonical_classification": len(classified_entities),
        "classification_metadata_launches": classification_metadata_launches,
        "unknown_performance_launches": unknown_performance_launches,
        "classification_reason_counts": _counts(classification_reason_counts),
        "evidence_basis_counts": _counts(evidence_basis_counts),
        "historical_as_of_supported": False,
        "interpretation": "PERSISTED_LAUNCH_OUTCOME_DIAGNOSTIC_ONLY",
        "release_authority": False,
        "predictive_authority": False,
        "risk_inferred": False,
        "quality_inferred": False,
        "trade_signal": False,
        "evidence_only": True,
        "read_only": True,
    }


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


async def _persisted_outcome_diagnostic(
    session: AsyncSession,
    *,
    entity_ids: list[str],
    as_of: datetime | None,
) -> dict[str, Any]:
    """Read current mutable launch outcomes only; never reconstruct them historically."""
    if as_of is not None:
        return {
            **summarize_persisted_outcomes([]),
            "status": "HISTORICAL_OUTCOME_STATE_UNAVAILABLE",
            "reason": "entity_launches does not store an independent outcome-ingested timestamp",
        }
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT entity_id, mint, observed_at, outcome_status, outcome_meta
                    FROM entity_launches
                    WHERE entity_id = ANY(CAST(:entity_ids AS uuid[]))
                    ORDER BY entity_id, observed_at ASC, id ASC
                    LIMIT :launch_limit
                    """
                ),
                {"entity_ids": entity_ids, "launch_limit": _PERSISTED_LAUNCH_LIMIT},
            )
        ).mappings().all()
    except Exception:
        return {
            **summarize_persisted_outcomes([]),
            "status": "UNKNOWN",
            "missing": ["entity_launches"],
        }
    launch_rows = [dict(row) for row in rows]
    return summarize_persisted_outcomes(
        launch_rows,
        limit_hit=len(launch_rows) >= _PERSISTED_LAUNCH_LIMIT,
    )


async def readiness_component_maturity(
    session: AsyncSession,
    *,
    entity_ids: list[str],
    not_before: datetime,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Read latest captured readiness plus current persisted evidence diagnostics."""
    ids = [str(value) for value in entity_ids if str(value).strip()][:500]
    if not ids:
        result = summarize_readiness_component_maturity([])
        result["persisted_outcomes"] = summarize_persisted_outcomes([])
        result["historical_depth"] = await entity_readiness_historical_depth(
            session, entity_ids=[], not_before=not_before, as_of=as_of
        )
        return result
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
            "persisted_outcomes": await _persisted_outcome_diagnostic(
                session, entity_ids=ids, as_of=as_of
            ),
            "historical_depth": await entity_readiness_historical_depth(
                session, entity_ids=ids, not_before=not_before, as_of=as_of
            ),
        }
    result = summarize_readiness_component_maturity(
        [dict(row.get("readiness") or {}) for row in rows]
    )
    result["persisted_outcomes"] = await _persisted_outcome_diagnostic(
        session, entity_ids=ids, as_of=as_of
    )
    result["historical_depth"] = await entity_readiness_historical_depth(
        session, entity_ids=ids, not_before=not_before, as_of=as_of
    )
    return result
