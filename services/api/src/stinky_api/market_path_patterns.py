"""Descriptive cross-market pattern discovery over observed lifecycle signatures."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from stinky_api.market_outcome_analysis import market_path_signature


def canonical_pattern_hash(signature: dict[str, Any]) -> str:
    """Return a stable content hash for a market path signature."""
    payload = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def discover_market_path_patterns(analyses: list[dict[str, Any]], *, limit: int = 20) -> dict[str, Any]:
    """Group observed markets by identical structural path signatures.

    Repetition is described only; no pattern is evaluated as good, bad,
    predictive, risky, or tradeable.
    """
    bounded_limit = max(1, min(int(limit), 100))
    groups: Counter[str] = Counter()
    signatures: dict[str, dict[str, Any]] = {}
    for analysis in analyses:
        result = market_path_signature(analysis)
        if result.get("status") != "OBSERVED":
            continue
        signature = result["signature"]
        pattern_hash = canonical_pattern_hash(signature)
        groups[pattern_hash] += 1
        signatures[pattern_hash] = signature

    ordered = sorted(groups.items(), key=lambda item: (-item[1], item[0]))[:bounded_limit]
    records = [
        {
            "pattern_id": pattern_hash,
            "pattern_hash": pattern_hash,
            "occurrence_count": count,
            "signature": signatures[pattern_hash],
            "evidence_basis": "observed_market_lifecycle_analysis",
            "evidence_only": True,
        }
        for pattern_hash, count in ordered
    ]
    if not records:
        return {
            "status": "UNKNOWN",
            "patterns": [],
            "observed_market_count": 0,
            "missing": ["market_lifecycle_analysis"],
            "bounded": {"limit": bounded_limit},
            "evidence_only": True,
        }
    return {
        "status": "OBSERVED",
        "patterns": records,
        "observed_market_count": sum(groups.values()),
        "missing": [],
        "bounded": {"limit": bounded_limit},
        "evidence_basis": "observed_market_lifecycle_analysis",
        "evidence_only": True,
    }
