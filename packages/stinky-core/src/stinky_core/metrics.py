"""In-process latency counters and structured investigation logs.

Fixture timing is labeled. Never invented production p95.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

METRICS_VERSION = "metrics-v1.1.0"

LOG_STAGES = (
    "DISCOVERED",
    "GATE_PASSED",
    "INVESTIGATION_STARTED",
    "WALLET_DATA",
    "CREATOR_DATA",
    "PATTERN_DATA",
    "HISTORICAL_MATCH",
    "RISK_ASSESSMENT",
    "SCORE",
    "PROMOTION_DECISION",
    "ALERT",
    "OUTCOME",
)


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


class InvestigationLog:
    """Structured investigation events. Never fabricates decisions."""

    def __init__(self, *, cap: int = 400) -> None:
        self.events: list[dict[str, Any]] = []
        self._cap = int(cap)

    def new_correlation_id(self, mint: str | None = None) -> str:
        suffix = uuid4().hex[:10]
        m = (mint or "nomint").strip()[:12]
        return f"{m}:{suffix}"

    def emit(
        self,
        stage: str,
        *,
        mint: str | None = None,
        correlation_id: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
        latency_ms: float | None = None,
        evidence_counts: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        st = str(stage or "").upper()
        if st not in LOG_STAGES:
            st = stage
        event = {
            "stage": st,
            "mint": mint,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id or self.new_correlation_id(mint),
            "latency_ms": round(float(latency_ms), 3) if latency_ms is not None else None,
            "evidence_counts": dict(evidence_counts or {}),
            "decision": decision,
            "reason": reason,
        }
        if extra:
            event["extra"] = dict(extra)
        self.events.append(event)
        if len(self.events) > self._cap:
            self.events = self.events[-self._cap :]
        ENGINE_METRICS.inc(f"log_{str(st).lower()}")
        return event

    def for_mint(self, mint: str) -> list[dict[str, Any]]:
        m = (mint or "").strip()
        return [e for e in self.events if e.get("mint") == m]

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": METRICS_VERSION,
            "event_count": len(self.events),
            "events": list(self.events[-100:]),
            "stages": list(LOG_STAGES),
        }

    def reset(self) -> None:
        self.events.clear()


ENGINE_METRICS = LatencyLog()
ENGINE_LOG = InvestigationLog()
