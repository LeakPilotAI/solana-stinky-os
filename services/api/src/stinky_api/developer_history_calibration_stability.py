"""Chronological stability gate for developer-history descriptive calibration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.developer_history_calibration_readiness import (
    KNOWN_OUTCOMES,
    assess_developer_history_calibration_readiness,
)

MIN_TOTAL_DISTINCT_LAUNCHES = 6
MIN_SLICE_DISTINCT_LAUNCHES = 3
MIN_SLICE_KNOWN_OUTCOMES = 2
MAX_OUTCOME_SHARE_DRIFT = 0.50
MAX_KNOWN_COVERAGE_DRIFT = 0.35
MAX_CADENCE_RATIO = 4.0


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _visible_snapshot(record: dict[str, Any], cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    observed = _parse_time(record.get("observed_at"))
    ingested = _parse_time(record.get("ingested_at"))
    return observed is not None and ingested is not None and observed <= cutoff and ingested <= cutoff


def _latest_visible_evidence(records: list[dict[str, Any]], cutoff: datetime | None) -> dict[str, Any]:
    visible = [dict(row) for row in records if isinstance(row, dict) and _visible_snapshot(row, cutoff)]
    visible.sort(key=lambda row: (_parse_time(row.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc), int(row.get("id") or 0)))
    return dict(visible[-1].get("evidence") or {}) if visible else {}


def _launches(evidence: dict[str, Any], cutoff: datetime | None) -> tuple[list[dict[str, Any]], int]:
    history = evidence.get("launch_history") if isinstance(evidence.get("launch_history"), dict) else {}
    raw = history.get("records") if isinstance(history.get("records"), list) else []
    by_mint: dict[str, dict[str, Any]] = {}
    excluded = 0
    for item in raw:
        if not isinstance(item, dict):
            excluded += 1
            continue
        row = dict(item)
        mint = str(row.get("mint") or "").strip()
        observed = _parse_time(row.get("observed_at"))
        ingested_raw = row.get("ingested_at")
        ingested = _parse_time(ingested_raw) if ingested_raw is not None else None
        if not mint or observed is None:
            excluded += 1
            continue
        if cutoff is not None and (observed > cutoff or (ingested_raw is not None and (ingested is None or ingested > cutoff))):
            excluded += 1
            continue
        current = by_mint.get(mint)
        if current is None or observed < (_parse_time(current.get("observed_at")) or observed):
            by_mint[mint] = row
    launches = list(by_mint.values())
    launches.sort(key=lambda row: (_parse_time(row.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc), str(row.get("mint") or "")))
    return launches, excluded


def _slice_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0}
    times: list[datetime] = []
    for row in rows:
        outcome = str(row.get("outcome_status") or "UNKNOWN").upper()
        counts[outcome if outcome in KNOWN_OUTCOMES else "UNKNOWN"] += 1
        ts = _parse_time(row.get("observed_at"))
        if ts is not None:
            times.append(ts)
    total = len(rows)
    known = sum(counts[k] for k in KNOWN_OUTCOMES)
    shares = {key: (counts[key] / total if total else 0.0) for key in counts}
    span_days = (max(times) - min(times)).total_seconds() / 86400.0 if len(times) >= 2 else 0.0
    cadence = ((total - 1) / span_days) if total >= 2 and span_days > 0 else None
    return {
        "launch_count": total,
        "known_outcome_count": known,
        "known_outcome_ratio": known / total if total else 0.0,
        "outcome_counts": counts,
        "outcome_shares": shares,
        "span_days": span_days,
        "launches_per_day": cadence,
    }


def assess_developer_history_calibration_stability(records: list[dict[str, Any]], *, as_of: datetime | str | None = None) -> dict[str, Any]:
    cutoff = _parse_time(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        return {"status": "UNKNOWN", "stable": False, "readiness_status": "UNKNOWN", "stability_status": "UNKNOWN", "blockers": ["INVALID_AS_OF"], "missing": ["valid_as_of"], "predictive_authority": False, "risk_inferred": False, "quality_inferred": False, "trade_signal": False, "evidence_only": True}

    normalized = [dict(row) for row in records if isinstance(row, dict)]
    readiness = assess_developer_history_calibration_readiness(normalized, as_of=cutoff)
    evidence = _latest_visible_evidence(normalized, cutoff)
    launches, excluded_launches = _launches(evidence, cutoff)
    criteria = {
        "min_total_distinct_launches": MIN_TOTAL_DISTINCT_LAUNCHES,
        "min_slice_distinct_launches": MIN_SLICE_DISTINCT_LAUNCHES,
        "min_slice_known_outcomes": MIN_SLICE_KNOWN_OUTCOMES,
        "max_outcome_share_drift": MAX_OUTCOME_SHARE_DRIFT,
        "max_known_coverage_drift": MAX_KNOWN_COVERAGE_DRIFT,
        "max_cadence_ratio": MAX_CADENCE_RATIO,
    }
    if not readiness.get("ready"):
        return {"status": "OBSERVED" if normalized else "UNKNOWN", "stable": False, "readiness_status": readiness.get("status"), "stability_status": "NOT_EVALUATED", "blockers": ["READINESS_GATE_NOT_PASSED"], "readiness": readiness, "slice_sizes": {"early": 0, "late": 0}, "criteria": criteria, "temporal_integrity": {"cutoff_enforced": cutoff is not None, "excluded_launch_count": excluded_launches}, "interpretation": "DESCRIPTIVE_STABILITY_ONLY", "predictive_authority": False, "risk_inferred": False, "quality_inferred": False, "trade_signal": False, "evidence_only": True}

    total = len(launches)
    midpoint = total // 2
    early_rows, late_rows = launches[:midpoint], launches[midpoint:]
    early, late = _slice_metrics(early_rows), _slice_metrics(late_rows)
    blockers: list[str] = []
    if total < MIN_TOTAL_DISTINCT_LAUNCHES or len(early_rows) < MIN_SLICE_DISTINCT_LAUNCHES or len(late_rows) < MIN_SLICE_DISTINCT_LAUNCHES:
        blockers.append("INSUFFICIENT_SLICE_SAMPLE")
    if early["known_outcome_count"] < MIN_SLICE_KNOWN_OUTCOMES or late["known_outcome_count"] < MIN_SLICE_KNOWN_OUTCOMES:
        blockers.append("INSUFFICIENT_SLICE_OUTCOMES")

    outcome_share_drift = {key: abs(float(late["outcome_shares"][key]) - float(early["outcome_shares"][key])) for key in ("RUNNER", "HELD", "FADE", "UNKNOWN")}
    max_share_drift = max(outcome_share_drift.values()) if outcome_share_drift else 0.0
    if max_share_drift > MAX_OUTCOME_SHARE_DRIFT:
        blockers.append("OUTCOME_REGIME_DRIFT")
    known_coverage_drift = abs(float(late["known_outcome_ratio"]) - float(early["known_outcome_ratio"]))
    if known_coverage_drift > MAX_KNOWN_COVERAGE_DRIFT:
        blockers.append("KNOWN_COVERAGE_DRIFT")

    cadence_ratio = None
    ec, lc = early.get("launches_per_day"), late.get("launches_per_day")
    if ec is not None and lc is not None and ec > 0 and lc > 0:
        cadence_ratio = max(ec, lc) / min(ec, lc)
        if cadence_ratio > MAX_CADENCE_RATIO:
            blockers.append("LAUNCH_CADENCE_DRIFT")

    stable = not blockers
    result: dict[str, Any] = {
        "status": "OBSERVED",
        "stable": stable,
        "readiness_status": readiness.get("status"),
        "stability_status": "STABLE_FOR_DESCRIPTIVE_CALIBRATION" if stable else "NOT_STABLE_FOR_DESCRIPTIVE_CALIBRATION",
        "blockers": blockers,
        "slice_sizes": {"early": len(early_rows), "late": len(late_rows)},
        "early": early,
        "late": late,
        "drift": {"outcome_share_absolute_drift": {k: round(v, 6) for k, v in outcome_share_drift.items()}, "max_outcome_share_drift": round(max_share_drift, 6), "known_outcome_coverage_drift": round(known_coverage_drift, 6), "launch_cadence_ratio": round(cadence_ratio, 6) if cadence_ratio is not None else None},
        "criteria": criteria,
        "readiness": readiness,
        "temporal_integrity": {"cutoff_enforced": cutoff is not None, "excluded_launch_count": excluded_launches, "missing_or_invalid_timestamps_fail_closed": True},
        "interpretation": "DESCRIPTIVE_STABILITY_ONLY",
        "calibration_scope": "DEVELOPER_HISTORY_DESCRIPTIVE_ONLY",
        "predictive_authority": False,
        "risk_inferred": False,
        "quality_inferred": False,
        "trade_signal": False,
        "evidence_only": True,
    }
    if cutoff is not None:
        result["as_of"] = cutoff.isoformat()
        result["temporal_cutoff_enforced"] = True
    return result


async def developer_history_calibration_stability(session: AsyncSession, entity_id: str, *, limit: int = 100, as_of: datetime | str | None = None) -> dict[str, Any]:
    cutoff = _parse_time(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        result = assess_developer_history_calibration_stability([], as_of=as_of)
        result["entity_id"] = entity_id
        return result
    from stinky_api.developer_longitudinal_audit import developer_audit_history
    history = await developer_audit_history(session, entity_id, limit=max(1, min(100, int(limit))), as_of=cutoff)
    result = assess_developer_history_calibration_stability(history.get("records") if isinstance(history.get("records"), list) else [], as_of=cutoff)
    result["entity_id"] = entity_id
    result["source"] = "developer_longitudinal_snapshots"
    result["source_status"] = history.get("status")
    if history.get("status") == "UNKNOWN" and not history.get("records"):
        result["status"] = "UNKNOWN"
        result["stable"] = False
        result["stability_status"] = "UNKNOWN"
        blockers = list(result.get("blockers") or [])
        if "AUDIT_HISTORY_UNAVAILABLE" not in blockers:
            blockers.insert(0, "AUDIT_HISTORY_UNAVAILABLE")
        result["blockers"] = blockers
        result["missing"] = list(history.get("missing") or ["developer_longitudinal_snapshots"])
    return result
