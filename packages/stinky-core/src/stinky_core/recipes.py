"""Runner recipes: what historical RUNNERs looked like at detection.

Deterministic. Shows every outcome class. Not a probability.
Need ≥5 analogues to claim a recipe. Empty fingerprints cannot match.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from stinky_core.fingerprint import BAND_NAMES, informative_band_count
from stinky_core.memory import IntelligenceMemory
from stinky_core.similarity import historical_similarity

RECIPE_VERSION = "recipe-v1.0.0"
MIN_ANALOGUES = 5
MIN_INFORMATIVE = 3


def _empty(*, reason: str) -> dict[str, Any]:
    return {
        "version": RECIPE_VERSION,
        "analogue_count": 0,
        "runner_count": 0,
        "held_count": 0,
        "fade_count": 0,
        "unknown_count": 0,
        "common_traits": [],
        "runner_matches": [],
        "fade_matches": [],
        "held_matches": [],
        "unknown_matches": [],
        "similarity_distribution": {"strong": 0, "moderate": 0, "weak": 0},
        "sample_sufficient": False,
        "calibrated_probability": False,
        "note": reason,
    }


def runner_recipe(
    memory: IntelligenceMemory | None,
    fingerprint: str | None,
    *,
    as_of: Any = None,
    exclude_mint: str | None = None,
    current: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare the current fingerprint to historical analogues as-of.

    Common traits are counted from RUNNER analogues only when sample ≥ 5.
    Fractions are observed counts, not invented thresholds.
    """
    fp = (fingerprint or "").strip()
    if not fp or informative_band_count(fp) < MIN_INFORMATIVE:
        return _empty(reason="fingerprint has too few observed bands to claim a recipe")
    if memory is None:
        return _empty(reason="no memory")
    sim = historical_similarity(memory, fp, as_of=as_of, exclude_mint=exclude_mint)
    matches = list(sim.get("historical_matches") or [])
    by = {"RUNNER": [], "HELD": [], "FADE": [], "UNKNOWN": []}
    for m in matches:
        lab = str(m.get("outcome") or "UNKNOWN")
        if lab not in by:
            lab = "UNKNOWN"
        by[lab].append(m)
    sample = len(matches)
    dist = {
        "strong": int(sim.get("strong_matches") or 0),
        "moderate": int(sim.get("moderate_matches") or 0),
        "weak": int(sim.get("weak_matches") or 0),
    }
    common: list[dict[str, Any]] = []
    runners = by["RUNNER"]
    if sample >= MIN_ANALOGUES and runners:
        band_counts: Counter[str] = Counter()
        for m in runners:
            for name in m.get("shared_characteristics") or []:
                band_counts[str(name)] += 1
        n_r = len(runners)
        for name, n in band_counts.most_common():
            common.append({
                "band": name if name in BAND_NAMES else name,
                "runner_count": n,
                "runner_of": n_r,
                "fraction": round(n / n_r, 3) if n_r else None,
                "note": f"{n}/{n_r} historical RUNNER analogues shared this observed band",
            })
    return {
        "version": RECIPE_VERSION,
        "current": dict(current or {}),
        "fingerprint": fp,
        "analogue_count": sample,
        "runner_count": len(by["RUNNER"]),
        "held_count": len(by["HELD"]),
        "fade_count": len(by["FADE"]),
        "unknown_count": len(by["UNKNOWN"]),
        "similarity_distribution": dist,
        "common_traits": common,
        "runner_matches": [
            {"mint": m.get("mint"), "strength": m.get("strength"), "shared_characteristics": m.get("shared_characteristics"), "outcome": "RUNNER"}
            for m in by["RUNNER"][:12]
        ],
        "fade_matches": [
            {"mint": m.get("mint"), "strength": m.get("strength"), "shared_characteristics": m.get("shared_characteristics"), "outcome": "FADE"}
            for m in by["FADE"][:12]
        ],
        "held_matches": [
            {"mint": m.get("mint"), "strength": m.get("strength"), "outcome": "HELD"}
            for m in by["HELD"][:8]
        ],
        "unknown_matches": [
            {"mint": m.get("mint"), "strength": m.get("strength"), "outcome": "UNKNOWN"}
            for m in by["UNKNOWN"][:8]
        ],
        "sample_sufficient": sample >= MIN_ANALOGUES,
        "calibrated_probability": False,
        "note": (
            f"{sample} historical analogues as-of: "
            f"{len(by['RUNNER'])} RUNNER / {len(by['HELD'])} HELD / {len(by['FADE'])} FADE / {len(by['UNKNOWN'])} UNKNOWN. "
            "Not a chance of running. Need ≥5 analogues to claim a recipe."
            if sample
            else "No historical analogues as-of."
        ),
    }
