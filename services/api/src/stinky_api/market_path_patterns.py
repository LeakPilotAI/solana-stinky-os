"""Descriptive cross-market pattern discovery over observed lifecycle signatures."""

from __future__ import annotations

from collections import Counter
from typing import Any

from stinky_api.market_outcome_analysis import market_path_signature


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
        key = repr(signature)
        groups[key] += 1
        signatures[key] = signature

    ordered = sorted(groups.items(), key=lambda item: (-item[1], item[0]))[:bounded_limit]
    records = [
        {"pattern_id": f"path-{i + 1}", "occurrence_count": count,
         "signature": signatures[key], "evidence_basis": "observed_market_lifecycle_analysis",
         "evidence_only": True}
        for i, (key, count) in enumerate(ordered)
    ]
    if not records:
        return {"status": "UNKNOWN", "patterns": [], "observed_market_count": 0,
                "missing": ["market_lifecycle_analysis"], "bounded": {"limit": bounded_limit},
                "evidence_only": True}
    return {"status": "OBSERVED", "patterns": records,
            "observed_market_count": sum(groups.values()), "missing": [],
            "bounded": {"limit": bounded_limit},
            "evidence_basis": "observed_market_lifecycle_analysis", "evidence_only": True}
