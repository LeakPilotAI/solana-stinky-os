"""Deterministic descriptive pattern discovery over temporally safe research rows.

This module finds recurring historical feature combinations and reports their observed
outcome distributions. It does not estimate probability, confidence, expected return,
risk, quality, or trading direction.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from itertools import combinations
from typing import Any

from stinky_api.pattern_discovery_dataset import form_pattern_discovery_dataset

CANONICAL_OUTCOMES = ("RUNNER", "HELD", "FADE", "UNKNOWN")
AUTHORITY = {
    "interpretation": "DESCRIPTIVE_HISTORICAL_ASSOCIATION_ONLY",
    "pattern_discovery_mode": "DESCRIPTIVE_ONLY",
    "predictive_authority": False,
    "trade_signal": False,
    "risk_inferred": False,
    "quality_inferred": False,
    "expected_return_inferred": False,
    "probability_inferred": False,
    "confidence_inferred": False,
    "evidence_only": True,
}


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _token(namespace: str, value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return f"{namespace}={text}"


def _categorical_metric_tokens(lifecycle: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    horizons = lifecycle.get("horizons") if isinstance(lifecycle.get("horizons"), dict) else {}
    for horizon, record in sorted(horizons.items()):
        if not isinstance(record, dict):
            continue
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        for key, value in sorted(metrics.items()):
            # Numeric bucketing is deliberately excluded until thresholds are formally governed.
            if isinstance(value, bool) or isinstance(value, str):
                t = _token(f"lifecycle.{horizon}.metric.{key}", value)
                if t:
                    tokens.append(t)
    return tokens


def extract_discrete_feature_tokens(row: dict[str, Any], *, token_limit: int = 32) -> list[str]:
    """Extract bounded, repeatable factual categorical tokens from one safe dataset row."""
    token_limit = max(1, min(64, int(token_limit)))
    features = row.get("features") if isinstance(row.get("features"), dict) else {}
    developer = features.get("developer_snapshot") if isinstance(features.get("developer_snapshot"), dict) else {}
    correlation = features.get("correlation_snapshot") if isinstance(features.get("correlation_snapshot"), dict) else {}
    lifecycle = features.get("market_lifecycle") if isinstance(features.get("market_lifecycle"), dict) else {}

    tokens: list[str] = []
    for namespace, value in (
        ("developer.history_state", developer.get("history_state")),
        ("developer.status", developer.get("status")),
        ("correlation.status", correlation.get("status")),
    ):
        t = _token(namespace, value)
        if t:
            tokens.append(t)

    for field in ("associated_wallets", "funding_relationships", "recurring_early_buyers"):
        value = developer.get(field)
        if isinstance(value, dict):
            t = _token(f"developer.{field}.status", value.get("status"))
            if t:
                tokens.append(t)

    relation_fields = (
        "shared_funders",
        "cross_entity_wallet_reuse",
        "deployer_buyer_recurrence",
        "shared_relationship_structures",
    )
    for field in relation_fields:
        records = correlation.get(field)
        if isinstance(records, list) and records:
            tokens.append(f"correlation.{field}=OBSERVED")

    repetition = correlation.get("repetition_analysis") if isinstance(correlation.get("repetition_analysis"), dict) else {}
    if repetition:
        if int(repetition.get("multi_launch_relationship_count") or 0) > 0:
            tokens.append("correlation.repetition=MULTI_LAUNCH_REPETITION_PRESENT")
        elif int(repetition.get("repeated_relationship_count") or 0) > 0:
            tokens.append("correlation.repetition=REPEATED_OBSERVATION_PRESENT")
        elif int(repetition.get("relationship_count_observed") or 0) > 0:
            tokens.append("correlation.repetition=NONREPEATED_RELATIONSHIP_PRESENT")
        else:
            t = _token("correlation.repetition.status", repetition.get("status"))
            if t:
                tokens.append(t)

    motifs = correlation.get("network_motifs") if isinstance(correlation.get("network_motifs"), dict) else {}
    for motif in motifs.get("records") or []:
        if not isinstance(motif, dict):
            continue
        kind = str(motif.get("motif_kind") or "").strip()
        state = str(motif.get("motif_state") or "").strip()
        if kind:
            tokens.append(f"motif.kind={kind}")
        if kind and state:
            tokens.append(f"motif.{kind}.state={state}")

    for horizon in lifecycle.get("observed_horizons") or []:
        tokens.append(f"lifecycle.horizon.{horizon}=OBSERVED")
    tokens.extend(_categorical_metric_tokens(lifecycle))

    return sorted(set(tokens))[:token_limit]


def _outcome_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in CANONICAL_OUTCOMES}
    for row in rows:
        label = row.get("label") if isinstance(row.get("label"), dict) else {}
        outcome = str(label.get("outcome") or "UNKNOWN").upper()
        counts[outcome if outcome in counts else "UNKNOWN"] += 1
    return counts


def _canonical_pattern(tokens: tuple[str, ...]) -> dict[str, Any]:
    values = sorted(set(tokens))
    return {
        "feature_tokens": values,
        "feature_count": len(values),
        "pattern_key": " && ".join(values),
    }


def discover_descriptive_patterns(
    dataset: dict[str, Any],
    *,
    min_support: int = 5,
    max_pattern_size: int = 3,
    pattern_limit: int = 100,
    token_limit_per_row: int = 32,
) -> dict[str, Any]:
    """Find recurring categorical feature combinations with factual historical outcomes."""
    min_support = max(2, min(500, int(min_support)))
    max_pattern_size = max(1, min(3, int(max_pattern_size)))
    pattern_limit = max(1, min(500, int(pattern_limit)))
    token_limit_per_row = max(1, min(64, int(token_limit_per_row)))

    rows = [row for row in (dataset.get("rows") or []) if isinstance(row, dict) and row.get("row_hash")]
    dataset_hash = dataset.get("dataset_hash")
    if not rows:
        return {
            "status": "UNKNOWN", "discovery_status": "INSUFFICIENT_EVIDENCE",
            "dataset_hash": dataset_hash, "patterns": [], "pattern_count": 0,
            "missing": ["pattern_discovery_rows"],
            "criteria": {"min_support": min_support, "max_pattern_size": max_pattern_size},
            **AUTHORITY,
        }

    support: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tokens = extract_discrete_feature_tokens(row, token_limit=token_limit_per_row)
        for size in range(1, min(max_pattern_size, len(tokens)) + 1):
            for combo in combinations(tokens, size):
                support[combo].append(row)

    candidates: list[dict[str, Any]] = []
    for combo, supporting_rows in support.items():
        if len(supporting_rows) < min_support:
            continue
        canonical = _canonical_pattern(combo)
        row_hashes = sorted(str(r.get("row_hash")) for r in supporting_rows)
        counts = _outcome_counts(supporting_rows)
        known = sum(counts[name] for name in ("RUNNER", "HELD", "FADE"))
        candidate_identity = {
            "dataset_hash": dataset_hash,
            "feature_tokens": canonical["feature_tokens"],
            "supporting_row_hashes": row_hashes,
        }
        candidates.append({
            **canonical,
            "pattern_hash": _hash(candidate_identity),
            "support_count": len(supporting_rows),
            "known_outcome_count": known,
            "unknown_outcome_count": counts["UNKNOWN"],
            "outcome_counts": counts,
            "supporting_row_hashes": row_hashes,
            "supporting_mints": sorted(str(r.get("mint")) for r in supporting_rows if r.get("mint")),
            "dataset_hash": dataset_hash,
            "association_is_not_prediction": True,
            **AUTHORITY,
        })

    # Collapse patterns that identify the exact same historical support set. Keep the most
    # specific definition, then deterministic lexical order. This suppresses subset spam.
    by_support_set: dict[tuple[str, ...], dict[str, Any]] = {}
    for candidate in candidates:
        key = tuple(candidate["supporting_row_hashes"])
        previous = by_support_set.get(key)
        if previous is None:
            by_support_set[key] = candidate
            continue
        if candidate["feature_count"] > previous["feature_count"]:
            by_support_set[key] = candidate
        elif candidate["feature_count"] == previous["feature_count"] and candidate["pattern_key"] < previous["pattern_key"]:
            by_support_set[key] = candidate

    patterns = list(by_support_set.values())
    patterns.sort(key=lambda p: (-int(p["support_count"]), -int(p["feature_count"]), str(p["pattern_key"])))
    patterns = patterns[:pattern_limit]

    discovery_ready = dataset.get("formation_status") == "READY_FOR_DESCRIPTIVE_DISCOVERY" and bool(patterns)
    result = {
        "status": "OBSERVED" if patterns else "UNKNOWN",
        "discovery_status": "DESCRIPTIVE_PATTERNS_OBSERVED" if discovery_ready else "INSUFFICIENT_EVIDENCE",
        "dataset_hash": dataset_hash,
        "dataset_row_count": len(rows),
        "dataset_feature_horizon": dataset.get("feature_horizon"),
        "patterns": patterns,
        "pattern_count": len(patterns),
        "candidate_pattern_count_before_support_dedup": len(candidates),
        "criteria": {
            "min_support": min_support,
            "max_pattern_size": max_pattern_size,
            "pattern_limit": pattern_limit,
            "token_limit_per_row": token_limit_per_row,
        },
        "numeric_bucketing_enabled": False,
        "subset_spam_suppression": "same_support_set_keep_most_specific",
        "deterministic": True,
        **AUTHORITY,
    }
    return result


async def discover_patterns_from_history(
    session: Any,
    *,
    dataset_limit: int = 100,
    as_of: Any = None,
    feature_horizon: str = "5m",
    min_rows: int = 20,
    min_label_coverage: float = 0.5,
    min_feature_source_coverage: float = 0.5,
    min_support: int = 5,
    max_pattern_size: int = 3,
    pattern_limit: int = 100,
) -> dict[str, Any]:
    """Form the safe dataset once, then run pure descriptive discovery over it."""
    dataset = await form_pattern_discovery_dataset(
        session,
        limit=dataset_limit,
        as_of=as_of,
        feature_horizon=feature_horizon,
        min_rows=min_rows,
        min_label_coverage=min_label_coverage,
        min_feature_source_coverage=min_feature_source_coverage,
    )
    result = discover_descriptive_patterns(
        dataset,
        min_support=min_support,
        max_pattern_size=max_pattern_size,
        pattern_limit=pattern_limit,
    )
    result["dataset_formation_status"] = dataset.get("formation_status")
    result["dataset_coverage"] = dataset.get("coverage")
    result["dataset_as_of"] = dataset.get("as_of")
    result["bounded"] = {
        "dataset_limit": max(1, min(500, int(dataset_limit))),
        "dataset_query_count": (dataset.get("bounded") or {}).get("query_count"),
        "pattern_limit": max(1, min(500, int(pattern_limit))),
    }
    return result
