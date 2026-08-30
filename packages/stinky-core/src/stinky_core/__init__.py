"""Stinky OS Core – shared events, transport, quality, admission, identity."""

__version__ = "0.1.0"

from stinky_core.admission import (
    ALERT_MIN_MEANINGFUL_BUYERS,
    ALERT_MIN_SCORE,
    CANONICAL_PROTOCOLS,
    EARLY_GATE_CONFIG,
    FILTER_VERSION,
    EligibilityResult,
    FilterConfig,
    FilterDecision,
    FilterStats,
    ReasonCode,
    StinkyFilterEngine,
    can_alert,
    evaluate_admission,
    evaluate_market,
    filter_stats,
)
from stinky_core.fees import (
    RESOLVER_VERSION as FEE_RESOLVER_VERSION,
    FeeObservation,
    FeeResolver,
    FeeStatus,
    coerce_fees_verified,
)
from stinky_core.identity import AlertLedger, UniqueMintIndex, alert_candidate_key, canonical_mint

__all__ = [
    "__version__",
    "ALERT_MIN_MEANINGFUL_BUYERS",
    "ALERT_MIN_SCORE",
    "CANONICAL_PROTOCOLS",
    "EARLY_GATE_CONFIG",
    "FILTER_VERSION",
    "FEE_RESOLVER_VERSION",
    "EligibilityResult",
    "FilterConfig",
    "FilterDecision",
    "FilterStats",
    "ReasonCode",
    "StinkyFilterEngine",
    "FeeObservation",
    "FeeResolver",
    "FeeStatus",
    "can_alert",
    "coerce_fees_verified",
    "evaluate_admission",
    "evaluate_market",
    "filter_stats",
    "AlertLedger",
    "UniqueMintIndex",
    "alert_candidate_key",
    "canonical_mint",
]

try:  # 3.11+ event types (StrEnum). Optional on 3.10 test runners.
    from stinky_core.events.base import Event, EventType, EventEnvelope
    from stinky_core.transport.base import EventTransport, EventProducer, EventConsumer

    __all__ += [
        "Event",
        "EventType",
        "EventEnvelope",
        "EventTransport",
        "EventProducer",
        "EventConsumer",
    ]
except ImportError:
    pass
