"""Deterministic historical similarity. Not a probability. Shows every outcome class.

Exact 10-band match remains the strong claim (sample ≥ 5, ≥ 3 informative bands).
Partial match counts overlapping informative bands. Empty fingerprints cannot match.
Future rows are excluded via as-of + exclude_mint.
"""

from __future__ import annotations

from typing import Any

from stinky_core.fingerprint import (
    FINGERPRINT_VERSION,
    informative_band_count,
    matching_informative_bands,
)
from stinky_core.memory import IntelligenceMemory, _before, _parse_ts

SIMILARITY_VERSION = "similarity-v1.0.0"
MIN_INFORMATIVE = 3
EXACT_SAMPLE_FLOOR = 5
MODERATE_BANDS = 7
WEAK_BANDS = 4


def _empty(*, reason: str) -> dict[str, Any]:
    return {
        "version": SIMILARITY_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "strong_matches": 0,
        "moderate_matches": 0,
        "weak_matches": 0,
        "runner_matches": 0,
        "held_matches": 0,
        "fade_matches": 0,
        "unknown_matches": 0,
        "high_risk_matches": 0,
        "runner_similarity": "UNKNOWN",
        "synthetic_similarity": "UNKNOWN",
        "rug_similarity": "UNKNOWN",
        "similarity_score": None,
        "similarity_confidence": "UNKNOWN",
        "historical_matches": [],
        "explanations": [],
        "sample_count": 0,
        "calibrated_probability": False,
        "note": reason,
    }


def _label_of(memory: IntelligenceMemory, mint: str, as_of: Any) -> str:
    cutoff = _parse_ts(as_of)
    labs = [
        o.label
        for o in memory.fingerprint_outcomes
        if o.mint == mint and _before(o.labeled_at, cutoff)
    ]
    if not labs:
        # Decision-row later labels are still future if labeled_at missing — stay UNKNOWN.
        for o in memory.wallet_outcomes:
            if o.mint == mint and _before(o.labeled_at, cutoff):
                return o.label
        return "UNKNOWN"
    return labs[-1]


def _strength(overlap: int, exact: bool, sample_exact: int) -> str | None:
    if exact and sample_exact >= EXACT_SAMPLE_FLOOR:
        return "strong"
    if overlap >= MODERATE_BANDS:
        return "moderate"
    if overlap >= WEAK_BANDS:
        return "weak"
    return None


def _class_label(n: int, resolved: int) -> str:
    if resolved < EXACT_SAMPLE_FLOOR:
        return "UNKNOWN"
    if n >= 3 and resolved and (n / resolved) >= 0.5:
        return "HIGH"
    if n >= 1:
        return "LOW"
    return "LOW"


def historical_similarity(
    memory: IntelligenceMemory | None,
    fingerprint: str | None,
    *,
    as_of: Any = None,
    exclude_mint: str | None = None,
    query_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fp = (fingerprint or "").strip()
    if not fp or informative_band_count(fp) < MIN_INFORMATIVE:
        return _empty(reason="fingerprint has too few observed bands to claim resemblance")
    if memory is None:
        return _empty(reason="no memory")
    cutoff = _parse_ts(as_of)
    exclude = (exclude_mint or "").strip()
    exact_prior = [
        r for r in memory.fingerprints
        if r.fingerprint == fp and r.mint != exclude and _before(r.observed_at, cutoff)
    ]
    exact_n = len(exact_prior)
    seen: set[str] = set()
    matches: list[dict[str, Any]] = []
    counts = {"RUNNER": 0, "HELD": 0, "FADE": 0, "UNKNOWN": 0, "HIGH_RISK": 0}
    strong = moderate = weak = 0

    def add(rec, overlap: int, exact: bool) -> None:
        nonlocal strong, moderate, weak
        if rec.mint in seen:
            return
        strength = _strength(overlap, exact, exact_n if exact else 0)
        if strength is None:
            return
        seen.add(rec.mint)
        label = _label_of(memory, rec.mint, as_of)
        if label not in counts:
            label = "UNKNOWN"
        counts[label] += 1
        if strength == "strong":
            strong += 1
        elif strength == "moderate":
            moderate += 1
        else:
            weak += 1
        shared = matching_informative_bands(fp, rec.fingerprint)
        matches.append({
            "mint": rec.mint,
            "fingerprint": rec.fingerprint,
            "outcome": label,
            "strength": strength,
            "overlap_bands": overlap,
            "exact": exact,
            "shared_characteristics": shared,
            "observed_at": rec.observed_at.isoformat() if rec.observed_at else None,
            "similarity_score": overlap,  # band count, not a percent chance
            "calibrated_probability": False,
        })

    for rec in exact_prior:
        add(rec, 10 if informative_band_count(fp) >= 10 else informative_band_count(fp), True)

    for rec in memory.fingerprints:
        if rec.mint == exclude or rec.fingerprint == fp:
            continue
        if not _before(rec.observed_at, cutoff):
            continue
        if informative_band_count(rec.fingerprint) < MIN_INFORMATIVE:
            continue
        shared = matching_informative_bands(fp, rec.fingerprint)
        add(rec, len(shared), False)

    matches.sort(key=lambda m: (-int(m["exact"]), -int(m["overlap_bands"]), str(m["mint"])))
    resolved = counts["RUNNER"] + counts["HELD"] + counts["FADE"]
    sample = len(matches)
    score = None
    conf: Any = "UNKNOWN"
    if sample >= EXACT_SAMPLE_FLOOR:
        # Similarity score is overlap density, not P(runner).
        score = round(min(100.0, 20 + 8 * strong + 4 * moderate + weak), 1)
        conf = round(min(0.8, 0.2 + 0.06 * sample), 2)
    return {
        "version": SIMILARITY_VERSION,
        "fingerprint_version": FINGERPRINT_VERSION,
        "strong_matches": strong,
        "moderate_matches": moderate,
        "weak_matches": weak,
        "runner_matches": counts["RUNNER"],
        "held_matches": counts["HELD"],
        "fade_matches": counts["FADE"],
        "unknown_matches": counts["UNKNOWN"],
        "high_risk_matches": counts["HIGH_RISK"],
        "runner_similarity": _class_label(counts["RUNNER"], resolved),
        "synthetic_similarity": "UNKNOWN",
        "rug_similarity": "UNKNOWN",
        "similarity_score": score,
        "similarity_confidence": conf,
        "historical_matches": matches[:24],
        "explanations": [
            {
                "mint": m["mint"],
                "outcome": m["outcome"],
                "shared_characteristics": m["shared_characteristics"],
                "similarity": m["similarity_score"],
                "strength": m["strength"],
            }
            for m in matches[:12]
        ],
        "sample_count": sample,
        "exact_sample_count": exact_n,
        "query_features_present": bool(query_features),
        "calibrated_probability": False,
        "note": (
            "Shows runners AND fades AND unknown. similarity_score is band overlap, "
            "not a chance of running. Need ≥5 matches to claim confidence."
        ),
    }
