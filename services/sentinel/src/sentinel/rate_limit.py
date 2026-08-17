"""Process-wide Helius / RPC rate-limit gate (free-tier safe).

When any Sentinel path sees HTTP 429, trip this gate so:
  - both WebSocket watchers stop reconnect storms
  - optional RPC history / rescue calls pause
  - logs clearly say we are throttled (not "dead")

Cool-down grows on repeated trips, then decays after a clean window.
"""

from __future__ import annotations

import asyncio
import time
from typing import Final

import structlog

from sentinel.config import settings

logger = structlog.get_logger(__name__)

_MIN_COOLDOWN: Final[float] = 60.0


def is_rate_limit_error(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return (
        "429" in text
        or "too many requests" in text
        or "rate limit" in text
        or "rate_limit" in text
        or "http 429" in text
    )


class RateLimitGate:
    """Shared async gate for one process."""

    def __init__(self) -> None:
        self._until: float = 0.0
        self._trips: int = 0
        self._lock = asyncio.Lock()
        self._last_log: float = 0.0

    @property
    def tripped(self) -> bool:
        return time.monotonic() < self._until

    @property
    def remaining_sec(self) -> float:
        return max(0.0, self._until - time.monotonic())

    def trip(self, reason: str = "429") -> float:
        """Trip the gate. Returns cooldown seconds applied."""
        base = float(getattr(settings, "rate_limit_cooldown_sec", 300.0) or 300.0)
        max_cd = float(getattr(settings, "rate_limit_max_cooldown_sec", 900.0) or 900.0)
        self._trips += 1
        # Grow: 1x, 1.5x, 2x ... capped
        factor = min(1.0 + 0.5 * (self._trips - 1), 3.0)
        cooldown = min(max(base * factor, _MIN_COOLDOWN), max_cd)
        self._until = time.monotonic() + cooldown
        now = time.monotonic()
        if now - self._last_log > 5.0:
            self._last_log = now
            logger.warning(
                "helius.rate_limited",
                reason=reason[:200],
                cooldown_sec=round(cooldown, 1),
                trips=self._trips,
                message=(
                    "Free-tier Helius quota hit. Pausing WS reconnect + extra RPC. "
                    "Not a Stinky crash — waiting for provider cooldown."
                ),
            )
        return cooldown

    def clear_if_elapsed(self) -> bool:
        if self.tripped:
            return False
        if self._trips and self._until > 0 and time.monotonic() >= self._until:
            logger.info(
                "helius.rate_limit_cleared",
                prior_trips=self._trips,
                message="Cooldown limit window elapsed — resuming Sentinel watchers",
            )
            # Soft reset trip counter slowly
            self._trips = max(0, self._trips - 1)
            self._until = 0.0
            return True
        return False

    async def wait_if_needed(self, *, label: str = "watcher") -> None:
        """Block until the cooldown ends (or return immediately if clear)."""
        self.clear_if_elapsed()
        while self.tripped:
            rem = self.remaining_sec
            logger.info(
                "helius.waiting_cooldown",
                label=label,
                remaining_sec=round(rem, 1),
            )
            await asyncio.sleep(min(max(rem, 1.0), 30.0))
            self.clear_if_elapsed()


# Process singleton
gate = RateLimitGate()
