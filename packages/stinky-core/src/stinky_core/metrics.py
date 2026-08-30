"""In-process latency counters. Fixture timing is labeled. Never invented production p95."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

METRICS_VERSION = "metrics-v1.0.0"


def _pct(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 3)
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return round(sorted_vals[idx], 3)


class LatencyLog:
    def __init__(self) -> None:
        self._samples: dict[str, list[float]] = defaultdict(list)
        self.counters: dict[str, int] = defaultdict(int)

    def record(self, name: str, ms: float) -> None:
        try:
            x = float(ms)
        except (TypeError, ValueError):
            return
        if x != x or x < 0:
            return
        self._samples[name].append(x)

    def inc(self, name: str, n: int = 1) -> None:
        self.counters[name] += int(n)

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, vals in self._samples.items():
            ordered = sorted(vals)
            out[name] = {
                "n": len(ordered),
                "p50_ms": _pct(ordered, 50),
                "p95_ms": _pct(ordered, 95),
                "max_ms": round(ordered[-1], 3) if ordered else None,
            }
        return {
            "version": METRICS_VERSION,
            "latencies": out,
            "counters": dict(self.counters),
            "note": "In-process samples only. Production p95 is NOT MEASURED unless the full stack is running.",
        }

    def reset(self) -> None:
        self._samples.clear()
        self.counters.clear()


ENGINE_METRICS = LatencyLog()
