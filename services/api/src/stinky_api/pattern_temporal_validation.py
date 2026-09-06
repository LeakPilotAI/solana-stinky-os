"""Temporal stability and significance checks for descriptive historical patterns.

This module validates whether already-discovered descriptive patterns persist across
chronological slices. It does not estimate probability, predictive confidence, expected
return, risk, quality, or trading direction.
"""
from __future__ import annotations

from typing import Any

from stinky_api.descriptive_pattern_discovery import extract_discrete_feature_tokens

CANONICAL_OUTCOMES = ("RUNNER", "HELD", "FADE", "UNKNOWN")
AUTHORITY = {
    "interpretation": "DESCRIPTIVE_TEMPORAL_VALIDATION_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in CANONICAL_OUTCOMES}
    for row in rows:
        label = row.get("label") if isinstance(row.get("label"), dict) else {}
        outcome = str(label.get("outcome") or "UNKNOWN").upper()
        counts[outcome if outcome in counts else "UNKNOWN"] += 1
    return counts


def _known_distribution(counts: dict[str, int]) -> dict[str, float | None]:
    known = sum(counts[name] for name in ("RUNNER", "HELD", "FADE"))
    if known <= 0:
        return {"RUNNER": None, "HELD": None, "FADE": None}
    return {name: counts[name] / known for name in ("RUNNER", "HELD", "FADE")}


def _slice_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _counts(rows)
    known = sum(counts[name] for name in ("RUNNER", "HELD", "FADE"))
    total = len(rows)
    return {
        "support_count": total,
        "known_outcome_count": known,
        "unknown_outcome_count": counts["UNKNOWN"],
        "known_label_coverage": (known / total) if total else None,
        "outcome_counts": counts,
        "known_outcome_distribution": _known_distribution(counts),
        "supporting_row_hashes": [str(r.get("row_hash")) for r in rows if r.get("row_hash")],
        "supporting_mints": [str(r.get("mint")) for r in rows if r.get("mint")],
    }


def _distribution_drift_pct_points(a: dict[str, float | None], b: dict[str, float | None]) -> dict[str, Any]:
    drifts: dict[str, float | None] = {}
    known: list[float] = []
    for name in ("RUNNER", "HELD", "FADE"):
        av, bv = a.get(name), b.get(name)
        if av is None or bv is None:
            drifts[name] = None
        else:
            value = abs(float(av) - float(bv)) * 100.0
            drifts[name] = value
            known.append(value)
    return {"by_outcome": drifts, "max_drift_pct_points": max(known) if known else None}


def _matches(row: dict[str, Any], feature_tokens: list[str]) -> bool:
    tokens = set(extract_discrete_feature_tokens(row, token_limit=64))
    return all(token in tokens for token in feature_tokens)


def validate_pattern_temporal_stability(
    dataset: dict[str, Any],
    discovery: dict[str, Any],
    *,
    min_slice_support: int = 3,
    min_known_label_coverage: float = 0.5,
    max_outcome_drift_pct_points: float = 25.0,
    rolling_window_size: int = 20,
    rolling_step: int = 10,
) -> dict[str, Any]:
    """Validate discovered patterns across chronological halves and rolling windows."""
    min_slice_support = max(2, min(250, int(min_slice_support)))
    min_known_label_coverage = max(0.0, min(1.0, float(min_known_label_coverage)))
    max_outcome_drift_pct_points = max(0.0, min(100.0, float(max_outcome_drift_pct_points)))
    rolling_window_size = max(4, min(500, int(rolling_window_size)))
    rolling_step = max(1, min(rolling_window_size, int(rolling_step)))

    rows = [r for r in (dataset.get("rows") or []) if isinstance(r, dict) and r.get("row_hash")]
    rows.sort(key=lambda r: (str(r.get("launch_observed_at") or ""), str(r.get("row_hash") or "")))
    patterns = [p for p in (discovery.get("patterns") or []) if isinstance(p, dict)]
    if not rows or not patterns:
        return {
            "status": "UNKNOWN", "validation_status": "INSUFFICIENT_EVIDENCE",
            "dataset_hash": dataset.get("dataset_hash"), "patterns": [], "pattern_count": 0,
            "missing": ["discovered_patterns_or_dataset_rows"], **AUTHORITY,
        }

    midpoint = len(rows) // 2
    early_rows, late_rows = rows[:midpoint], rows[midpoint:]
    validated: list[dict[str, Any]] = []

    for pattern in patterns:
        feature_tokens = [str(x) for x in (pattern.get("feature_tokens") or [])]
        early_matches = [r for r in early_rows if _matches(r, feature_tokens)]
        late_matches = [r for r in late_rows if _matches(r, feature_tokens)]
        early = _slice_summary(early_matches)
        late = _slice_summary(late_matches)
        drift = _distribution_drift_pct_points(early["known_outcome_distribution"], late["known_outcome_distribution"])

        windows: list[dict[str, Any]] = []
        if len(rows) >= rolling_window_size:
            for start in range(0, len(rows) - rolling_window_size + 1, rolling_step):
                window_rows = rows[start:start + rolling_window_size]
                matches = [r for r in window_rows if _matches(r, feature_tokens)]
                summary = _slice_summary(matches)
                windows.append({
                    "start_index": start,
                    "end_index_exclusive": start + rolling_window_size,
                    **summary,
                })

        sufficient = (
            early["support_count"] >= min_slice_support
            and late["support_count"] >= min_slice_support
            and early["known_label_coverage"] is not None
            and late["known_label_coverage"] is not None
            and float(early["known_label_coverage"]) >= min_known_label_coverage
            and float(late["known_label_coverage"]) >= min_known_label_coverage
            and drift["max_drift_pct_points"] is not None
        )
        if not sufficient:
            stability = "INSUFFICIENT_EVIDENCE"
        elif float(drift["max_drift_pct_points"]) <= max_outcome_drift_pct_points:
            stability = "STABLE"
        else:
            stability = "UNSTABLE"

        validated.append({
            "pattern_hash": pattern.get("pattern_hash"),
            "pattern_key": pattern.get("pattern_key"),
            "feature_tokens": feature_tokens,
            "full_support_count": pattern.get("support_count"),
            "early": early,
            "late": late,
            "outcome_distribution_drift": drift,
            "rolling_windows": windows,
            "rolling_window_count": len(windows),
            "stability_status": stability,
            "dataset_hash": dataset.get("dataset_hash"),
            "validation_is_not_prediction": True,
            **AUTHORITY,
        })

    counts = {
        "STABLE": sum(1 for p in validated if p["stability_status"] == "STABLE"),
        "UNSTABLE": sum(1 for p in validated if p["stability_status"] == "UNSTABLE"),
        "INSUFFICIENT_EVIDENCE": sum(1 for p in validated if p["stability_status"] == "INSUFFICIENT_EVIDENCE"),
    }
    return {
        "status": "OBSERVED",
        "validation_status": "TEMPORAL_VALIDATION_COMPLETE",
        "dataset_hash": dataset.get("dataset_hash"),
        "dataset_row_count": len(rows),
        "split": {"method": "chronological_halves", "early_row_count": len(early_rows), "late_row_count": len(late_rows)},
        "patterns": validated,
        "pattern_count": len(validated),
        "stability_counts": counts,
        "criteria": {
            "min_slice_support": min_slice_support,
            "min_known_label_coverage": min_known_label_coverage,
            "max_outcome_drift_pct_points": max_outcome_drift_pct_points,
            "rolling_window_size": rolling_window_size,
            "rolling_step": rolling_step,
        },
        "deterministic": True,
        **AUTHORITY,
    }
