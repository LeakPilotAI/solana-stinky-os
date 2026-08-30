"""Sample-aware reputation. Documented floors. Never fabricates edge.

Wallet status used by the intelligence gate remains UNKNOWN / OBSERVED / KNOWN.
These tiers are extra evidence labels. They do not replace the gate.
2 wins / 2 trades is never STRONG.
"""

from __future__ import annotations

from typing import Any

REPUTATION_VERSION = "reputation-v1.0.0"

# Wallet floors (resolved outcomes unless noted).
WALLET_OBSERVED_MAX_RESOLVED = 2          # 0–2 resolved → OBSERVED
WALLET_DEVELOPING_MIN_RESOLVED = 3        # 3–7 → DEVELOPING
WALLET_MEASURED_MIN_RESOLVED = 8          # 8–14 → MEASURED
WALLET_STRONG_MIN_RESOLVED = 15           # ≥15 and consistent → STRONG
WALLET_STRONG_MIN_RUNNERS = 5

# Creator floors.
CREATOR_OBSERVED_MAX_LAUNCHES = 2         # <3 launches → OBSERVED
CREATOR_DEVELOPING_MIN_LAUNCHES = 3       # 3–7 → DEVELOPING
CREATOR_MEASURED_MIN_LAUNCHES = 8
CREATOR_MEASURED_MIN_RESOLVED = 3
CREATOR_HIGH_CONF_MIN_LAUNCHES = 8
CREATOR_HIGH_CONF_MIN_RESOLVED = 5
CREATOR_HIGH_CONF_MIN_RUNNERS = 3
CREATOR_SERIAL_LAUNCHES = 15              # serial is HIGH_RISK, not confidence
CREATOR_POOR_SUCCESS = 0.08
CREATOR_POOR_MIN_RESOLVED = 5

WALLET_TIERS = ("OBSERVED", "DEVELOPING", "MEASURED", "STRONG")
CREATOR_TIERS = ("UNKNOWN", "OBSERVED", "DEVELOPING", "MEASURED", "HIGH_CONFIDENCE", "HIGH_RISK")


def _i(v: Any) -> int:
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return 0
    return n if n >= 0 else 0


def _f(v: Any) -> float | None:
    if v is None or v is True or v is False:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _conf(resolved: int, *, floor: float = 0.15, cap: float = 0.8) -> float:
    return round(min(cap, floor + 0.04 * max(0, resolved)), 2)


def wallet_reputation(
    *,
    sample_size: int | None = None,
    sample_resolved: int | None = None,
    runners: int | None = None,
    fades: int | None = None,
    held: int | None = None,
    hit_rate: float | None = None,
    observation_window: str | None = None,
) -> dict[str, Any]:
    """Tier from resolved historical outcomes. Tiny samples stay OBSERVED."""
    size = _i(sample_size)
    resolved = _i(sample_resolved)
    rn = _i(runners)
    fd = _i(fades)
    hd = _i(held)
    if resolved == 0 and (rn or fd or hd):
        resolved = rn + fd + hd
    hr = _f(hit_rate)
    if resolved <= WALLET_OBSERVED_MAX_RESOLVED:
        tier = "OBSERVED"
    elif resolved < WALLET_MEASURED_MIN_RESOLVED:
        tier = "DEVELOPING"
    elif resolved < WALLET_STRONG_MIN_RESOLVED:
        tier = "MEASURED"
    else:
        consistent = rn >= WALLET_STRONG_MIN_RUNNERS or (hr is not None and hr + 1e-9 >= 0.5)
        tier = "STRONG" if consistent else "MEASURED"
    return {
        "version": REPUTATION_VERSION,
        "tier": tier,
        "sample_size": size,
        "sample_resolved": resolved,
        "successful_outcomes": rn,
        "failed_outcomes": fd,
        "held_outcomes": hd,
        "hit_rate": hr,
        "confidence": None if resolved <= WALLET_OBSERVED_MAX_RESOLVED else _conf(resolved),
        "observation_window": observation_window,
        "calibrated_probability": False,
        "note": (
            "OBSERVED <3 resolved; DEVELOPING 3–7; MEASURED ≥8; "
            "STRONG ≥15 resolved AND (≥5 runners or hit_rate ≥ 0.5). "
            "2/2 is never STRONG."
        ),
    }


def creator_reputation(
    *,
    launches: int | None = None,
    runners: int | None = None,
    fades: int | None = None,
    held: int | None = None,
    success_rate: float | None = None,
    observation_window: str | None = None,
) -> dict[str, Any]:
    n = _i(launches)
    rn = _i(runners)
    fd = _i(fades)
    hd = _i(held)
    resolved = rn + fd + hd
    sr = _f(success_rate)
    if n <= 0:
        tier = "UNKNOWN"
    elif n <= CREATOR_OBSERVED_MAX_LAUNCHES:
        tier = "OBSERVED"
    elif n >= CREATOR_SERIAL_LAUNCHES:
        tier = "HIGH_RISK"
    elif resolved >= CREATOR_POOR_MIN_RESOLVED and sr is not None and sr < CREATOR_POOR_SUCCESS:
        tier = "HIGH_RISK"
    elif (
        n >= CREATOR_HIGH_CONF_MIN_LAUNCHES
        and resolved >= CREATOR_HIGH_CONF_MIN_RESOLVED
        and rn >= CREATOR_HIGH_CONF_MIN_RUNNERS
        and n < CREATOR_SERIAL_LAUNCHES
    ):
        tier = "HIGH_CONFIDENCE"
    elif n >= CREATOR_MEASURED_MIN_LAUNCHES and resolved >= CREATOR_MEASURED_MIN_RESOLVED:
        tier = "MEASURED"
    else:
        tier = "DEVELOPING"
    return {
        "version": REPUTATION_VERSION,
        "tier": tier,
        "sample_size": n,
        "sample_resolved": resolved,
        "successful_outcomes": rn,
        "failed_outcomes": fd,
        "held_outcomes": hd,
        "success_rate": sr if resolved >= 3 else None,
        "confidence": None if n <= CREATOR_OBSERVED_MAX_LAUNCHES else _conf(resolved if resolved else n),
        "observation_window": observation_window,
        "calibrated_probability": False,
        "note": (
            "UNKNOWN = no launches. OBSERVED <3. DEVELOPING 3–7. "
            "MEASURED ≥8 launches and ≥3 resolved. HIGH_CONFIDENCE ≥8 launches, "
            "≥5 resolved, ≥3 runners, not serial. HIGH_RISK if serial (≥15) or poor success."
        ),
    }
