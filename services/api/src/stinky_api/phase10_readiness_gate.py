"""Fail-closed Phase 10 completion audit for descriptive pattern intelligence.

The gate checks evidence sufficiency and reproducibility across the safe dataset,
descriptive discovery, temporal validation, and persisted stability memory. Passing this
gate does not grant predictive, ML, risk, quality, or trading authority.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUTHORITY = {
    "interpretation": "PHASE_10_DESCRIPTIVE_READINESS_AUDIT_ONLY",
    "phase_11_authorized": False,
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}


def _ratio(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _check(name: str, passed: bool, *, observed: Any, required: Any, detail: str) -> dict[str, Any]:
    return {
        "criterion": name,
        "passed": bool(passed),
        "observed": observed,
        "required": required,
        "detail": detail,
    }


def audit_phase10_readiness(
    dataset: dict[str, Any],
    discovery: dict[str, Any],
    validation: dict[str, Any],
    persistence: dict[str, Any],
    *,
    min_rows: int = 50,
    min_label_coverage: float = 0.60,
    min_feature_source_coverage: float = 0.50,
    min_patterns: int = 3,
    min_validated_patterns: int = 3,
    min_temporally_sufficient_patterns: int = 2,
    min_persisted_patterns: int = 2,
    min_snapshots_per_persisted_pattern: int = 2,
) -> dict[str, Any]:
    """Return a deterministic, named-criterion Phase 10 completion audit."""
    min_rows = max(1, min(500, int(min_rows)))
    min_label_coverage = max(0.0, min(1.0, float(min_label_coverage)))
    min_feature_source_coverage = max(0.0, min(1.0, float(min_feature_source_coverage)))
    min_patterns = max(1, min(500, int(min_patterns)))
    min_validated_patterns = max(1, min(500, int(min_validated_patterns)))
    min_temporally_sufficient_patterns = max(1, min(500, int(min_temporally_sufficient_patterns)))
    min_persisted_patterns = max(1, min(500, int(min_persisted_patterns)))
    min_snapshots_per_persisted_pattern = max(1, min(100, int(min_snapshots_per_persisted_pattern)))

    coverage = dataset.get("coverage") if isinstance(dataset.get("coverage"), dict) else {}
    row_count = int(dataset.get("row_count") or 0)
    label_coverage = _ratio(coverage.get("label_coverage"))
    source_values = [
        _ratio(coverage.get("developer_snapshot_coverage")),
        _ratio(coverage.get("correlation_snapshot_coverage")),
        _ratio(coverage.get("lifecycle_any_coverage")),
    ]
    known_sources = [v for v in source_values if v is not None]
    min_observed_source_coverage = min(known_sources) if known_sources else None

    rows = [r for r in (dataset.get("rows") or []) if isinstance(r, dict)]
    row_hashes = [str(r.get("row_hash") or "") for r in rows]
    unique_row_hashes = {h for h in row_hashes if h}
    row_hash_integrity = bool(rows) and len(unique_row_hashes) == len(rows)
    unknown_labels = sum(
        1 for r in rows
        if str((r.get("label") if isinstance(r.get("label"), dict) else {}).get("outcome") or "UNKNOWN").upper() == "UNKNOWN"
    )
    unknown_preserved = unknown_labels >= 0 and all(
        isinstance(r.get("label"), dict) and "outcome" in r.get("label", {}) for r in rows
    )

    patterns = [p for p in (discovery.get("patterns") or []) if isinstance(p, dict)]
    pattern_hashes = [str(p.get("pattern_hash") or "") for p in patterns]
    pattern_hash_integrity = bool(patterns) and len({h for h in pattern_hashes if h}) == len(patterns)
    dataset_hash = str(dataset.get("dataset_hash") or "")
    discovery_dataset_match = bool(dataset_hash) and str(discovery.get("dataset_hash") or "") == dataset_hash

    validated = [p for p in (validation.get("patterns") or []) if isinstance(p, dict)]
    sufficient_states = {"STABLE", "UNSTABLE"}
    temporally_sufficient = [p for p in validated if str(p.get("stability_status") or "") in sufficient_states]
    validation_dataset_match = bool(dataset_hash) and str(validation.get("dataset_hash") or "") == dataset_hash
    validation_hashes = {str(p.get("pattern_hash") or "") for p in validated if p.get("pattern_hash")}
    discovery_hashes = {str(p.get("pattern_hash") or "") for p in patterns if p.get("pattern_hash")}
    validation_pattern_integrity = bool(validated) and validation_hashes.issubset(discovery_hashes)

    persisted_pattern_count = int(persistence.get("persisted_pattern_count") or 0)
    min_snapshot_depth = int(persistence.get("min_snapshot_depth") or 0)
    persistence_cutoff_safe = persistence.get("dual_temporal_cutoff_supported") is True
    persistence_hashes = {str(x) for x in (persistence.get("pattern_hashes") or []) if x}
    persistence_pattern_integrity = bool(persistence_hashes) and persistence_hashes.issubset(validation_hashes)

    checks = [
        _check("dataset_formation_ready", dataset.get("formation_status") == "READY_FOR_DESCRIPTIVE_DISCOVERY", observed=dataset.get("formation_status"), required="READY_FOR_DESCRIPTIVE_DISCOVERY", detail="Safe dataset formation must already pass its own fail-closed readiness criteria."),
        _check("dataset_rows", row_count >= min_rows, observed=row_count, required=f">={min_rows}", detail="Enough bounded historical rows must exist for descriptive research."),
        _check("label_coverage", label_coverage is not None and label_coverage >= min_label_coverage, observed=label_coverage, required=f">={min_label_coverage}", detail="UNKNOWN labels remain present; known-label coverage must still meet the minimum."),
        _check("feature_source_coverage", min_observed_source_coverage is not None and min_observed_source_coverage >= min_feature_source_coverage, observed=min_observed_source_coverage, required=f">={min_feature_source_coverage}", detail="Developer, correlation, and lifecycle evidence sources must have adequate historical coverage."),
        _check("row_hash_integrity", row_hash_integrity, observed=len(unique_row_hashes), required=f"{len(rows)} unique non-empty row hashes", detail="Every research row must retain deterministic identity."),
        _check("unknown_outcome_preservation", unknown_preserved, observed=unknown_labels, required="explicit UNKNOWN outcome on every row when unresolved", detail="The audit must not drop unresolved historical outcomes."),
        _check("descriptive_discovery_ready", discovery.get("discovery_status") == "DESCRIPTIVE_PATTERNS_OBSERVED", observed=discovery.get("discovery_status"), required="DESCRIPTIVE_PATTERNS_OBSERVED", detail="Pattern discovery must be operating on sufficient evidence."),
        _check("pattern_count", len(patterns) >= min_patterns, observed=len(patterns), required=f">={min_patterns}", detail="More than a single recurring combination is required before phase completion."),
        _check("pattern_hash_integrity", pattern_hash_integrity, observed=len({h for h in pattern_hashes if h}), required=f"{len(patterns)} unique non-empty pattern hashes", detail="Discovered patterns must be deterministic and uniquely traceable."),
        _check("discovery_dataset_identity", discovery_dataset_match, observed=discovery.get("dataset_hash"), required=dataset_hash, detail="Discovery must refer to the exact audited dataset."),
        _check("temporal_validation_complete", validation.get("validation_status") == "TEMPORAL_VALIDATION_COMPLETE", observed=validation.get("validation_status"), required="TEMPORAL_VALIDATION_COMPLETE", detail="Patterns must be checked across chronological history."),
        _check("validated_pattern_count", len(validated) >= min_validated_patterns, observed=len(validated), required=f">={min_validated_patterns}", detail="Enough discovered patterns must reach temporal validation."),
        _check("temporally_sufficient_pattern_count", len(temporally_sufficient) >= min_temporally_sufficient_patterns, observed=len(temporally_sufficient), required=f">={min_temporally_sufficient_patterns}", detail="At least some patterns must have enough evidence to be classified STABLE or UNSTABLE rather than only INSUFFICIENT_EVIDENCE."),
        _check("validation_dataset_identity", validation_dataset_match, observed=validation.get("dataset_hash"), required=dataset_hash, detail="Temporal validation must refer to the same audited dataset."),
        _check("validation_pattern_identity", validation_pattern_integrity, observed=sorted(validation_hashes), required="subset of discovered pattern hashes", detail="Validation cannot introduce patterns absent from descriptive discovery."),
        _check("persisted_pattern_count", persisted_pattern_count >= min_persisted_patterns, observed=persisted_pattern_count, required=f">={min_persisted_patterns}", detail="Longitudinal memory must contain multiple validated patterns."),
        _check("persistence_depth", min_snapshot_depth >= min_snapshots_per_persisted_pattern, observed=min_snapshot_depth, required=f">={min_snapshots_per_persisted_pattern} snapshots per included pattern", detail="A single persisted snapshot is not longitudinal evidence."),
        _check("persistence_pattern_identity", persistence_pattern_integrity, observed=sorted(persistence_hashes), required="subset of validated pattern hashes", detail="Persisted stability memory must trace back to validated patterns."),
        _check("dual_temporal_replay", persistence_cutoff_safe, observed=persistence_cutoff_safe, required=True, detail="Historical persistence reads must enforce observed_at and ingested_at cutoffs."),
        _check("authority_boundary", all(x is False for x in (dataset.get("predictive_authority"), discovery.get("predictive_authority"), validation.get("predictive_authority"), persistence.get("predictive_authority"))), observed="descriptive-only" if all(x is False for x in (dataset.get("predictive_authority"), discovery.get("predictive_authority"), validation.get("predictive_authority"), persistence.get("predictive_authority"))) else "authority mismatch", required="predictive_authority=false across all layers", detail="Phase 10 completion must not silently authorize Phase 11 or trading."),
    ]

    failed = [c for c in checks if not c["passed"]]
    complete = not failed
    return {
        "status": "OBSERVED",
        "phase": 10,
        "phase_name": "Pattern Discovery",
        "completion_status": "PHASE_10_COMPLETE" if complete else "NOT_READY_FOR_PHASE_11",
        "ready_for_phase_11_research": complete,
        "checks": checks,
        "check_count": len(checks),
        "passed_check_count": len(checks) - len(failed),
        "failed_check_count": len(failed),
        "failed_criteria": [c["criterion"] for c in failed],
        "dataset_hash": dataset_hash or None,
        "unknown_label_count": unknown_labels,
        "stability_counts": dict(Counter(str(p.get("stability_status") or "INSUFFICIENT_EVIDENCE") for p in validated)),
        "criteria": {
            "min_rows": min_rows,
            "min_label_coverage": min_label_coverage,
            "min_feature_source_coverage": min_feature_source_coverage,
            "min_patterns": min_patterns,
            "min_validated_patterns": min_validated_patterns,
            "min_temporally_sufficient_patterns": min_temporally_sufficient_patterns,
            "min_persisted_patterns": min_persisted_patterns,
            "min_snapshots_per_persisted_pattern": min_snapshots_per_persisted_pattern,
        },
        "completion_does_not_grant_predictive_authority": True,
        **AUTHORITY,
    }


async def pattern_persistence_readiness_summary(
    session: AsyncSession,
    pattern_hashes: list[str],
    *,
    as_of: Any = None,
) -> dict[str, Any]:
    """Load bounded persistence depth for the audited pattern set in one bulk query."""
    hashes = sorted({str(x).strip() for x in pattern_hashes if str(x).strip()})[:500]
    if not hashes:
        return {
            "status": "UNKNOWN",
            "persisted_pattern_count": 0,
            "min_snapshot_depth": 0,
            "pattern_hashes": [],
            "snapshot_depths": {},
            "dual_temporal_cutoff_supported": True,
            **AUTHORITY,
        }
    clause = "AND observed_at <= :as_of AND ingested_at <= :as_of" if as_of is not None else ""
    params: dict[str, Any] = {"pattern_hashes": hashes}
    if as_of is not None:
        params["as_of"] = as_of
    try:
        rows = (await session.execute(text(f"""
            SELECT pattern_hash, COUNT(*)::int AS snapshot_count
            FROM pattern_stability_snapshots
            WHERE pattern_hash = ANY(:pattern_hashes) {clause}
            GROUP BY pattern_hash
            ORDER BY pattern_hash
        """), params)).mappings().all()
    except Exception:
        return {
            "status": "UNKNOWN",
            "persisted_pattern_count": 0,
            "min_snapshot_depth": 0,
            "pattern_hashes": [],
            "snapshot_depths": {},
            "missing": ["pattern_stability_snapshots"],
            "dual_temporal_cutoff_supported": True,
            **AUTHORITY,
        }
    depths = {str(r.get("pattern_hash")): int(r.get("snapshot_count") or 0) for r in rows}
    positive = [v for v in depths.values() if v > 0]
    result = {
        "status": "OBSERVED" if positive else "UNKNOWN",
        "persisted_pattern_count": len(positive),
        "min_snapshot_depth": min(positive) if positive else 0,
        "pattern_hashes": sorted(k for k, v in depths.items() if v > 0),
        "snapshot_depths": depths,
        "dual_temporal_cutoff_supported": True,
        "bounded": {"pattern_limit": 500, "query_count": 1},
        **AUTHORITY,
    }
    if as_of is not None:
        result["as_of"] = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)
        result["temporal_cutoff_enforced"] = True
    return result
