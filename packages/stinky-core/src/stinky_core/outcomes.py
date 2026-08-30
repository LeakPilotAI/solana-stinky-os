"""Deterministic outcome labeling.

Do not casually label every pump a runner. Unknown remains unknown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

LABEL_VERSION = "outcome-v1.0.0"

RUNNER = "RUNNER"
HELD = "HELD"
FADE = "FADE"
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    drawdown: Any = None,
    time_to_peak: Any = None,
    time_to_drawdown: Any = None,
    observation_window: Any = DEFAULT_OBSERVATION_WINDOW_SEC,
    observation_complete: bool = False,
    runner_peak_multiple: float = RUNNER_PEAK_MULTIPLE,
    held_drawdown_max: float = HELD_DRAWDOWN_MAX,
) -> Outcome:
    """Assign RUNNER / HELD / FADE / UNKNOWN from measured path statistics.

    Insufficient data → UNKNOWN. Never force a label.
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

    if not observation_complete or (multiple is None and peak_vol is None):
        return Outcome(
            label=UNKNOWN,
            label_version=LABEL_VERSION,
            observation_window=window,
            peak_multiple=multiple,
            peak_volume=peak_vol,
            drawdown=dd,
            time_to_peak=ttp,
            time_to_drawdown=ttd,
            reason="insufficient_observation",
        )

    if multiple is not None and multiple + 1e-9 >= float(runner_peak_multiple):
        return Outcome(
            label=RUNNER,
            label_version=LABEL_VERSION,
            observation_window=window,
            peak_multiple=multiple,
            peak_volume=peak_vol,
            drawdown=dd,
            time_to_peak=ttp,
            time_to_drawdown=ttd,
            reason="peak_multiple_met",
        )

    if dd is not None and dd + 1e-9 >= 0.5:
        return Outcome(
            label=FADE,
            label_version=LABEL_VERSION,
            observation_window=window,
            peak_multiple=multiple,
            peak_volume=peak_vol,
            drawdown=dd,
            time_to_peak=ttp,
            time_to_drawdown=ttd,
            reason="drawdown_fade",
        )

    if dd is not None and dd <= float(held_drawdown_max):
        return Outcome(
            label=HELD,
            label_version=LABEL_VERSION,
            observation_window=window,
            peak_multiple=multiple,
            peak_volume=peak_vol,
            drawdown=dd,
            time_to_peak=ttp,
            time_to_drawdown=ttd,
            reason="held_within_drawdown",
        )

    return Outcome(
        label=UNKNOWN,
        label_version=LABEL_VERSION,
        observation_window=window,
        peak_multiple=multiple,
        peak_volume=peak_vol,
        drawdown=dd,
        time_to_peak=ttp,
        time_to_drawdown=ttd,
        reason="no_deterministic_class",
    )
