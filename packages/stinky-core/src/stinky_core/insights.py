"""Candidate insights from the labeled dataset. Human review required.

Does NOT change production score weights or Gate 1.
Tiny samples stay UNKNOWN. Holdout rows are never used to mint a pattern.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

INSIGHTS_VERSION = "insights-v1.0.0"
MIN_PATTERN_SAMPLE = 20
MIN_CELL = 5


def _label(row: Mapping[str, Any]) -> str:
    lab = str(row.get("outcome_label") or row.get("future_outcome") or "UNKNOWN").upper()
    if lab not in ("RUNNER", "HELD", "FADE", "UNKNOWN"):
        return "UNKNOWN"
    return lab


def candidate_insights(
    rows: Iterable[Mapping[str, Any]],
    *,
    holdout_mints: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Count pattern occurrence by outcome on development rows only.

    Production scoring is not updated. Human review is required.
    """
    hold = {(m or "").strip() for m in (holdout_mints or []) if m}
    dev: list[Mapping[str, Any]] = []
    skipped_holdout = 0
    for r in rows:
        mint = str(r.get("mint") or "").strip()
        if mint and mint in hold:
            skipped_holdout += 1
            continue
        dev.append(r)
    n = len(dev)
    if n < MIN_PATTERN_SAMPLE:
        return {
            "version": INSIGHTS_VERSION,
            "sample": n,
            "skipped_holdout": skipped_holdout,
            "candidates": [],
            "human_review_required": True,
            "promoted_to_score": False,
            "calibrated_probability": False,
            "note": f"SAMPLE SIZE TOO SMALL ({n} < {MIN_PATTERN_SAMPLE}). No candidate insight.",
        }

    by_pattern: dict[str, Counter[str]] = defaultdict(Counter)
    pattern_n: Counter[str] = Counter()
    for r in dev:
        kinds = []
        pf = r.get("pattern_features") if isinstance(r.get("pattern_features"), Mapping) else {}
        matches = (pf or {}).get("pattern_matches") or r.get("pattern_matches") or []
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, Mapping) and m.get("kind"):
                    kinds.append(str(m["kind"]))
                elif isinstance(m, str):
                    kinds.append(m)
        lab = _label(r)
        for k in set(kinds):
            by_pattern[k][lab] += 1
            pattern_n[k] += 1

    outcome_n = Counter(_label(r) for r in dev)
    candidates: list[dict[str, Any]] = []
    for kind, counts in sorted(by_pattern.items(), key=lambda kv: -sum(kv[1].values())):
        total = sum(counts.values())
        if total < MIN_CELL:
            continue
        runners = counts.get("RUNNER", 0)
        fades = counts.get("FADE", 0)
        held = counts.get("HELD", 0)
        unknown = counts.get("UNKNOWN", 0)
        resolved = runners + fades + held
        runner_share = round(runners / resolved, 3) if resolved >= MIN_CELL else None
        candidates.append({
            "pattern": kind,
            "occurrences": total,
            "RUNNER": runners,
            "HELD": held,
            "FADE": fades,
            "UNKNOWN": unknown,
            "runner_share_among_resolved": runner_share,
            "base_runner_rate": round(outcome_n["RUNNER"] / n, 3) if n else None,
            "human_review_required": True,
            "promoted_to_score": False,
            "calibrated_probability": False,
            "note": (
                f"{kind} appeared on {total} development rows: "
                f"{runners} RUNNER / {held} HELD / {fades} FADE / {unknown} UNKNOWN. "
                "Not a production rule."
            ),
        })
    return {
        "version": INSIGHTS_VERSION,
        "sample": n,
        "skipped_holdout": skipped_holdout,
        "outcome_distribution": dict(outcome_n),
        "candidates": candidates,
        "human_review_required": True,
        "promoted_to_score": False,
        "calibrated_probability": False,
        "note": "Candidate insights only. Do not auto-promote into scoring. Holdout was not used.",
    }
