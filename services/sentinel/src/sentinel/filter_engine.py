"""Re-export the canonical StinkyFilterEngine (stinky_core.admission).

All opportunity / alert paths MUST import evaluate_admission / evaluate_market
from here or from stinky_core.admission. Do not reimplement the gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from stinky_core.admission import *  # noqa: F401,F403
except ImportError:  # pragma: no cover - path bootstrap for unsynced installs
    _CORE = Path(__file__).resolve().parents[4] / "packages" / "stinky-core" / "src"
    if str(_CORE) not in sys.path:
        sys.path.insert(0, str(_CORE))
    from stinky_core.admission import *  # noqa: F401,F403

from stinky_core.admission import (
    ALERT_MIN_MEANINGFUL_BUYERS,
    ALERT_MIN_SCORE,
    CANONICAL_PROTOCOLS,
    DEFAULT_ALLOWED_PROTOCOLS,
    DEFAULT_DENIED_PROTOCOLS,
    DEFAULT_MIN_GLOBAL_FEES_SOL,
    DEFAULT_MIN_LIQUIDITY_USD,
    DEFAULT_MIN_MARKET_CAP_USD,
    DEFAULT_MIN_VOLUME_USD,
    DEFAULT_REQUIRE_AT_LEAST_ONE_SOCIAL,
    EARLY_GATE_CONFIG,
    FILTER_VERSION,
    EligibilityResult,
    FilterConfig,
    FilterDecision,
    FilterMetric,
    ReasonCode,
    StinkyFilterEngine,
    can_alert,
    evaluate_admission,
    evaluate_market,
    filter_stats,
)

__all__ = [
    "ALERT_MIN_MEANINGFUL_BUYERS",
    "ALERT_MIN_SCORE",
    "CANONICAL_PROTOCOLS",
    "DEFAULT_ALLOWED_PROTOCOLS",
    "DEFAULT_DENIED_PROTOCOLS",
    "DEFAULT_MIN_GLOBAL_FEES_SOL",
    "DEFAULT_MIN_LIQUIDITY_USD",
    "DEFAULT_MIN_MARKET_CAP_USD",
    "DEFAULT_MIN_VOLUME_USD",
    "DEFAULT_REQUIRE_AT_LEAST_ONE_SOCIAL",
    "EARLY_GATE_CONFIG",
    "FILTER_VERSION",
    "EligibilityResult",
    "FilterConfig",
    "FilterDecision",
    "FilterMetric",
    "ReasonCode",
    "StinkyFilterEngine",
    "can_alert",
    "evaluate_admission",
    "evaluate_market",
    "filter_stats",
]
