"""In-process metrics counters for the collector."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class CollectorMetrics:
    migrations_received: int = 0
    tracks_started: int = 0
    tracks_completed: int = 0
    trades_observed: int = 0
    early_buyers_captured: int = 0
    market_snapshots: int = 0
    performance_updates: int = 0
    events_emitted: int = 0
    errors: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            cur = getattr(self, name, None)
            if isinstance(cur, int):
                setattr(self, name, cur + n)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "migrations_received": self.migrations_received,
                "tracks_started": self.tracks_started,
                "tracks_completed": self.tracks_completed,
                "trades_observed": self.trades_observed,
                "early_buyers_captured": self.early_buyers_captured,
                "market_snapshots": self.market_snapshots,
                "performance_updates": self.performance_updates,
                "events_emitted": self.events_emitted,
                "errors": self.errors,
            }


metrics = CollectorMetrics()
