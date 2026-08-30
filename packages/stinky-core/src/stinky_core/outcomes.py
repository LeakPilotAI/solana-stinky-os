"""Deterministic outcome labeling.

Do not casually label every pump a runner. Unknown remains unknown.
Store the exact evidence used to produce the label. Future path never
belongs on the original decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

LABEL_VERSION = "outcome-v1.1.0"
OUTCOME_RULE_VERSION = LABEL_VERSION

RUNNER = "RUNNER"
HELD = "HELD"
FADE = "FADE"
RUG = "RUG"
UNKNOWN = "UNKNOWN"

DEFAULT_OBSERVATION_WINDOW_SEC = 3600.0
RUNNER_PEAK_MULTIPLE = 2.0
HELD_DRAWDOWN_MAX = 0.35


@dataclass(frozen=True)
class Outcome:
    label: str
    label_version: str
    observation_window: float | None
    peak_multiple: float | None
    peak_volume: float | None
    drawdown: float | None
    time_to_peak: float | None
    time_to_drawdown: float | None
    reason: str
    entry_volume: float | None = None
    entry_price: float | None = None
    decision_timestamp: str | None = None
    peak_after_alert: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.setdefault("evidence", {})
        return d


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def label_outcome(
    *,
    peak_multiple: Any = None,
    peak_volume: Any = None,
    entry_volume: Any = None,
    entry_price: Any = None,
    decision_timestamp: Any = None,
    drawdown: Any = None,
    time_to_peak: Any = None,
    time_to_drawdown: Any = None,
    observation_window: Any = DEFAULT_OBSERVATION_WINDOW_SEC,
    observation_complete: bool = False,
    runner_peak_multiple: float = RUNNER_PEAK_MULTIPLE,
    held_drawdown_max: float = HELD_DRAWDOWN_MAX,
    rug_level: Any = None,
    liquidity_drop: Any = None,
) -> Outcome:
    """Assign RUNNER / HELD / FADE / RUG / UNKNOWN from measured path statistics.

    Insufficient data → UNKNOWN. Never force a label. Future path never
    belongs on the original decision — this label is for later evaluation only.
    RUG requires stored rug evidence AND measured collapse. Not inferred from fade.
    """
    window = _f(observation_window)
    multiple = _f(peak_multiple)
    if multiple is None:
        ev = _f(entry_volume)
        pv = _f(peak_volume)
        if ev is not None and ev > 0 and pv is not None:
            multiple = pv / ev
    peak_vol = _f(peak_volume)
    dd = _f(drawdown)
    ttp = _f(time_to_peak)
    ttd = _f(time_to_drawdown)
    entry_vol = _f(entry_volume)
    entry_px = _f(entry_price)
    decision_ts = str(decision_timestamp) if decision_timestamp else None

    evidence = {
        "peak_volume": peak_vol,
        "entry_volume": entry_vol,
        "entry_price": entry_px,
        "peak_multiple": multiple,
        "peak_alert_multiple": multiple,
        "time_to_peak": ttp,
        "drawdown": dd,
        "time_to_drawdown": ttd,
        "observation_window": window,
        "observation_complete": bool(observation_complete),
        "runner_peak_multiple_threshold": float(runner_peak_multiple),
        "held_drawdown_max": float(held_drawdown_max),
        "decision_timestamp": decision_ts,
        "rug_level": str(rug_level).upper() if rug_level else None,
        "liquidity_drop": _f(liquidity_drop),
        "note": "Outcome evidence is post-decision. It must not leak into Gate 1 or the original score.",
    }

    common = dict(
        label_version=LABEL_VERSION,
        observation_window=window,
        peak_multiple=multiple,
        peak_volume=peak_vol,
        drawdown=dd,
        time_to_peak=ttp,
        time_to_drawdown=ttd,
        entry_volume=entry_vol,
        entry_price=entry_px,
        decision_timestamp=decision_ts,
        peak_after_alert=peak_vol,
        evidence=evidence,
    )

    if not observation_complete or (multiple is None and peak_vol is None and _f(liquidity_drop) is None):
        return Outcome(label=UNKNOWN, reason="insufficient_observation", **common)

    rug = str(rug_level or "").upper()
    liq_drop = _f(liquidity_drop)
    if rug in ("HIGH", "CRITICAL") and liq_drop is not None and liq_drop >= 0.70:
        return Outcome(label=RUG, reason="rug_evidence_and_liquidity_collapse", **common)

    if multiple is not None and multiple + 1e-9 >= float(runner_peak_multiple):
        return Outcome(label=RUNNER, reason="peak_multiple_met", **common)

    if dd is not None and dd + 1e-9 >= 0.5:
        return Outcome(label=FADE, reason="drawdown_fade", **common)

    if dd is not None and dd <= float(held_drawdown_max):
        return Outcome(label=HELD, reason="held_within_drawdown", **common)

    return Outcome(label=UNKNOWN, reason="no_deterministic_class", **common)
