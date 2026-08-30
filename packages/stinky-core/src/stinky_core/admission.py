"""StinkyFilterEngine — canonical market eligibility (volume-first-v1.0.0).

FAIL CLOSED. Gate 1 happens BEFORE scoring.
Score cannot override a failed Gate 1 (protocol / mint / volume / migrated).

Gate 1 = investigation trigger, NOT a buy signal.
Unknown global fees do NOT reject. FeeResolver remains optional evidence.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterable, Mapping

FILTER_VERSION = "volume-first-v1.0.0"

DEFAULT_MIN_GLOBAL_FEES_SOL = 1.0
DEFAULT_MIN_LIQUIDITY_USD = 8.0
DEFAULT_MIN_VOLUME_USD = 150_000.0
GATE1_VOLUME_5M_USD = 150_000.0
GATE1_VOLUME_CALIBRATION_MAX_USD = 200_000.0
DEFAULT_MIN_MARKET_CAP_USD = 31_333.0
DEFAULT_REQUIRE_AT_LEAST_ONE_SOCIAL = False
ALERT_MIN_SCORE = 55.0
ALERT_MIN_MEANINGFUL_BUYERS = 3

# Exact product protocol map (Axiom-parity). True = allowed, False = disabled.
CANONICAL_PROTOCOLS: dict[str, bool] = {
    "raydium": False,
    "pump": True,
    "pumpfun": True,
    "pumpswap": True,
    "pump.fun": True,
    "mayhem": True,
    "pumpamm": False,
    "launchlab": True,
    "virtualcurve": True,
    "launchacoin": True,
    "bonk": True,
    "bonkers": True,
    "boop": True,
    "surge": True,
    "meteoraamm": False,
    "meteoraammv2": False,
    "meteora": False,
    "moonshot": True,
    "moonshotapp": True,
    "heaven": True,
    "daosfun": True,
    "candle": True,
    "sugar": True,
    "jupiterstudio": True,
    "bags": True,
    "soar": True,
    "printr": True,
    "liquida": True,
    "liquidaf": True,
    "liquidaffamm": True,
    "riserich": True,
    "stonkfun": True,
    "pve": True,
    "orca": False,
    "wavebreak": True,
    "phoenix": False,
    "lifinity": False,
    "saber": False,
    "aldrin": False,
    "fluxbeam": False,
}

DEFAULT_ALLOWED_PROTOCOLS: frozenset[str] = frozenset(
    k for k, v in CANONICAL_PROTOCOLS.items() if v
)
DEFAULT_DENIED_PROTOCOLS: frozenset[str] = frozenset(
    k for k, v in CANONICAL_PROTOCOLS.items() if not v
)


class ReasonCode:
    FEES_BELOW_MIN = "FEES_BELOW_MIN"
    FEES_UNKNOWN = "FEES_UNKNOWN"
    LIQUIDITY_BELOW_MIN = "LIQUIDITY_BELOW_MIN"
    LIQUIDITY_UNKNOWN = "LIQUIDITY_UNKNOWN"
    VOLUME_BELOW_MIN = "VOLUME_BELOW_MIN"
    VOLUME_UNKNOWN = "VOLUME_UNKNOWN"
    MARKET_CAP_BELOW_MIN = "MARKET_CAP_BELOW_MIN"
    MARKET_CAP_UNKNOWN = "MARKET_CAP_UNKNOWN"
    PROTOCOL_DISABLED = "PROTOCOL_DISABLED"
    PROTOCOL_UNKNOWN = "PROTOCOL_UNKNOWN"
    NO_SOCIAL = "NO_SOCIAL"
    DEX_PAID = "DEX_PAID"
    NOT_MIGRATED = "NOT_MIGRATED"
    INVALID_MARKET_DATA = "INVALID_MARKET_DATA"
    SYNTHETIC_ACTIVITY_SUSPECTED = "SYNTHETIC_ACTIVITY_SUSPECTED"
    INVALID_MINT = "INVALID_MINT"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    SCORE_UNKNOWN = "SCORE_UNKNOWN"
    SCORE_BELOW_MIN = "SCORE_BELOW_MIN"
    MEANINGFUL_BUYERS_BELOW_MIN = "MEANINGFUL_BUYERS_BELOW_MIN"
    INSPECTION_INCOMPLETE = "INSPECTION_INCOMPLETE"
    RISK_CRITICAL = "RISK_CRITICAL"
    INTELLIGENCE_INSUFFICIENT = "INTELLIGENCE_INSUFFICIENT"


REASON_PRIORITY: tuple[str, ...] = (
    ReasonCode.INVALID_MARKET_DATA,
    ReasonCode.INVALID_MINT,
    ReasonCode.NOT_MIGRATED,
    ReasonCode.PROTOCOL_UNKNOWN,
    ReasonCode.PROTOCOL_DISABLED,
    ReasonCode.DEX_PAID,
    ReasonCode.FEES_UNKNOWN,
    ReasonCode.FEES_BELOW_MIN,
    ReasonCode.LIQUIDITY_UNKNOWN,
    ReasonCode.LIQUIDITY_BELOW_MIN,
    ReasonCode.VOLUME_UNKNOWN,
    ReasonCode.VOLUME_BELOW_MIN,
    ReasonCode.MARKET_CAP_UNKNOWN,
    ReasonCode.MARKET_CAP_BELOW_MIN,
    ReasonCode.NO_SOCIAL,
    ReasonCode.SYNTHETIC_ACTIVITY_SUSPECTED,
)


@dataclass(frozen=True)
class FilterMetric:
    name: str
    actual: Any
    required: Any
    unit: str
    passed: bool
    reason: str | None = None
    source: str | None = None
    confidence: float | None = None


@dataclass
class FilterStats:
    """Process-level observability for the canonical gate."""

    markets_seen: int = 0
    markets_rejected: int = 0
    markets_eligible: int = 0
    fee_unknown_count: int = 0
    fee_below_min_count: int = 0
    alerts_generated: int = 0
    alerts_rejected: int = 0
    duplicate_alerts: int = 0
    buyer_capture_success: int = 0
    buyer_capture_failures: int = 0
    attribution_unknown: int = 0
    entity_resolution_events: int = 0
    rejection_reason_counts: dict[str, int] = field(default_factory=dict)
    trade_source_distribution: dict[str, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_decision(self, eligible: bool, reason_codes: Iterable[str]) -> None:
        with self._lock:
            self.markets_seen += 1
            if eligible:
                self.markets_eligible += 1
            else:
                self.markets_rejected += 1
                for code in reason_codes:
                    self.rejection_reason_counts[code] = (
                        self.rejection_reason_counts.get(code, 0) + 1
                    )
                    if code == ReasonCode.FEES_UNKNOWN:
                        self.fee_unknown_count += 1
                    elif code == ReasonCode.FEES_BELOW_MIN:
                        self.fee_below_min_count += 1

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            cur = getattr(self, name, None)
            if isinstance(cur, int):
                setattr(self, name, cur + n)

    def inc_trade_source(self, source: str, n: int = 1) -> None:
        with self._lock:
            self.trade_source_distribution[source] = (
                self.trade_source_distribution.get(source, 0) + n
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "markets_seen": self.markets_seen,
                "markets_rejected": self.markets_rejected,
                "markets_eligible": self.markets_eligible,
                "fee_unknown_count": self.fee_unknown_count,
                "fee_below_min_count": self.fee_below_min_count,
                "alerts_generated": self.alerts_generated,
                "alerts_rejected": self.alerts_rejected,
                "duplicate_alerts": self.duplicate_alerts,
                "buyer_capture_success": self.buyer_capture_success,
                "buyer_capture_failures": self.buyer_capture_failures,
                "attribution_unknown": self.attribution_unknown,
                "entity_resolution_events": self.entity_resolution_events,
                "rejection_reason_counts": dict(self.rejection_reason_counts),
                "trade_source_distribution": dict(self.trade_source_distribution),
            }

    def reset(self) -> None:
        with self._lock:
            self.markets_seen = 0
            self.markets_rejected = 0
            self.markets_eligible = 0
            self.fee_unknown_count = 0
            self.fee_below_min_count = 0
            self.alerts_generated = 0
            self.alerts_rejected = 0
            self.duplicate_alerts = 0
            self.buyer_capture_success = 0
            self.buyer_capture_failures = 0
            self.attribution_unknown = 0
            self.entity_resolution_events = 0
            self.rejection_reason_counts = {}
            self.trade_source_distribution = {}


filter_stats = FilterStats()


@dataclass(frozen=True)
class FilterDecision:
    """Canonical eligibility result. `eligible` is the product field; `accepted` is an alias."""

    accepted: bool
    eligible: bool
    filter_version: str
    evaluated_at: str
    mint: str | None
    protocol: str | None
    failed_filters: list[dict[str, Any]] = field(default_factory=list)
    passed_filters: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    rejection_reason: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    normalized_metrics: dict[str, Any] = field(default_factory=dict)
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Public alias matching the product API.
EligibilityResult = FilterDecision


def clamp_gate1_volume(v: float | None) -> float:
    """Default 150k. Configurable up to 200k. Invalid → default. Never fabricate."""
    if v is None:
        return GATE1_VOLUME_5M_USD
    try:
        f = float(v)
    except (TypeError, ValueError):
        return GATE1_VOLUME_5M_USD
    if not math.isfinite(f) or f <= 0:
        return GATE1_VOLUME_5M_USD
    return min(f, GATE1_VOLUME_CALIBRATION_MAX_USD)


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f < 0:
        return None
    return f


def _norm_protocol(raw: str | None) -> str:
    return (
        (raw or "")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )


def _has_verified_social(
    *,
    twitter: str | None = None,
    website: str | None = None,
    telegram: str | None = None,
    tiktok: str | None = None,
    socials: dict[str, Any] | None = None,
) -> bool:
    placeholders = {
        "",
        "none",
        "null",
        "n/a",
        "na",
        "-",
        "http://",
        "https://",
        "http://x.com",
        "https://x.com",
        "http://twitter.com",
        "https://twitter.com",
        "http://t.me",
        "https://t.me",
    }

    def ok(v: Any) -> bool:
        if v is None:
            return False
        s = str(v).strip().lower()
        if s in placeholders:
            return False
        if s.startswith("http") and len(s) < 12:
            return False
        return len(s) >= 3

    if ok(twitter) or ok(website) or ok(telegram) or ok(tiktok):
        return True
    if isinstance(socials, dict):
        for key in ("twitter", "website", "telegram", "tiktok", "x", "discord"):
            if ok(socials.get(key)):
                return True
    return False


def _pick_primary(codes: list[str]) -> str | None:
    if not codes:
        return None
    for p in REASON_PRIORITY:
        if p in codes:
            return p
    return codes[0]


@dataclass
class FilterConfig:
    filter_version: str = FILTER_VERSION
    min_global_fees_sol: float = DEFAULT_MIN_GLOBAL_FEES_SOL
    min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD
    min_volume_usd: float = DEFAULT_MIN_VOLUME_USD
    min_market_cap_usd: float = DEFAULT_MIN_MARKET_CAP_USD
    require_at_least_one_social: bool = DEFAULT_REQUIRE_AT_LEAST_ONE_SOCIAL
    require_pump_mint_suffix: bool = False  # Axiom mustEndInPump = false
    allowed_protocols: frozenset[str] = DEFAULT_ALLOWED_PROTOCOLS
    denied_protocols: frozenset[str] = DEFAULT_DENIED_PROTOCOLS
    reject_unknown_protocol: bool = True
    require_liquidity: bool = False
    require_volume: bool = True
    require_market_cap: bool = False
    require_fees: bool = False
    require_migrated: bool = True
    reject_dex_paid: bool = False
    record_stats: bool = True


GATE1_CONFIG = FilterConfig()

EARLY_GATE_CONFIG = FilterConfig(
    require_liquidity=False,
    require_volume=False,
    require_market_cap=False,
    require_at_least_one_social=False,
    require_migrated=False,
    require_fees=False,
)

# Optional legacy profile — not the default.
LEGACY_FEE_GATE_CONFIG = FilterConfig(
    filter_version="axiom-parity-v1.0.0",
    min_volume_usd=100_000.0,
    require_fees=True,
    require_liquidity=True,
    require_market_cap=True,
    require_at_least_one_social=True,
    require_migrated=True,
)


class StinkyFilterEngine:
    """Single canonical admission engine. All opportunity / alert paths MUST use this."""

    def __init__(self, config: FilterConfig | None = None) -> None:
        self.config = config or FilterConfig()

    def evaluate(
        self,
        *,
        mint: str | None,
        protocol: str | None = None,
        dex_id: str | None = None,
        global_fees_sol: float | None = None,
        global_fees_verified: bool | None = None,
        global_fees_source: str | None = None,
        global_fees_timestamp: str | None = None,
        global_fees_confidence: float | None = None,
        global_fees_raw: Any = None,
        liquidity_usd: float | None = None,
        volume_usd: float | None = None,
        market_cap_usd: float | None = None,
        twitter: str | None = None,
        website: str | None = None,
        telegram: str | None = None,
        tiktok: str | None = None,
        socials: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        migrated: bool | None = None,
        tab: str | None = None,
        dex_paid: bool | None = None,
    ) -> FilterDecision:
        cfg = self.config
        now = datetime.now(timezone.utc).isoformat()
        mint_s = (mint or "").strip() or None
        proto_raw = protocol or dex_id
        proto = _norm_protocol(proto_raw)

        failed: list[FilterMetric] = []
        passed: list[FilterMetric] = []
        codes: list[str] = []
        metrics: dict[str, Any] = {
            "mint": mint_s,
            "protocol": proto or None,
            "global_fees_sol": None,
            "liquidity_usd": None,
            "volume_usd": None,
            "market_cap_usd": None,
            "social_verified": False,
            "migrated": migrated,
            "dex_paid": dex_paid,
            "fees_source": global_fees_source,
            "fees_verified": global_fees_verified,
        }
        prov = dict(provenance or {})
        if global_fees_source:
            prov["global_fees_source"] = global_fees_source
        if global_fees_timestamp:
            prov["global_fees_timestamp"] = global_fees_timestamp
        if global_fees_confidence is not None:
            prov["global_fees_confidence"] = global_fees_confidence
        if global_fees_raw is not None:
            prov["global_fees_raw"] = global_fees_raw
        prov["fee_metric"] = "global_fees_sol"
        prov["fee_substitutes_forbidden"] = True

        def fail(
            name: str, actual: Any, required: Any, unit: str, reason: str, **kw: Any
        ) -> None:
            failed.append(
                FilterMetric(
                    name=name,
                    actual=actual,
                    required=required,
                    unit=unit,
                    passed=False,
                    reason=reason,
                    **kw,
                )
            )
            if reason not in codes:
                codes.append(reason)

        def ok(name: str, actual: Any, required: Any, unit: str, **kw: Any) -> None:
            passed.append(
                FilterMetric(
                    name=name,
                    actual=actual,
                    required=required,
                    unit=unit,
                    passed=True,
                    **kw,
                )
            )

        if not mint_s:
            fail("mint", None, "non-empty", "str", ReasonCode.INVALID_MINT)
            return self._finish(False, mint_s, proto, failed, passed, metrics, prov, now, codes)

        if cfg.require_pump_mint_suffix and not mint_s.lower().endswith("pump"):
            fail("mint_suffix", mint_s[-8:], "…pump", "str", ReasonCode.INVALID_MARKET_DATA)

        # Migration tab
        tab_n = (tab or "").strip().lower() if tab else None
        is_migrated: bool | None
        if migrated is True or tab_n == "migrated":
            is_migrated = True
        elif migrated is False or (tab_n is not None and tab_n != "migrated"):
            is_migrated = False
        else:
            is_migrated = None
        metrics["migrated"] = is_migrated
        if cfg.require_migrated:
            if is_migrated is True:
                ok("migrated", True, True, "bool")
            else:
                fail(
                    "migrated",
                    is_migrated,
                    True,
                    "bool",
                    ReasonCode.NOT_MIGRATED,
                )

        # Protocol
        denied_hit = False
        if proto:
            for d in cfg.denied_protocols:
                if d and (d == proto or d in proto):
                    # Avoid "pump" matching "pumpamm": denied keys must be explicit.
                    if d == "pump" and proto in ("pumpswap", "pumpfun", "pump.fun"):
                        continue
                    denied_hit = True
                    break
        if denied_hit:
            fail("protocol", proto, "not in denied", "str", ReasonCode.PROTOCOL_DISABLED)
        elif cfg.reject_unknown_protocol:
            if not proto:
                fail("protocol", None, "known allowed", "str", ReasonCode.PROTOCOL_UNKNOWN)
            else:
                allowed_hit = False
                for a in cfg.allowed_protocols:
                    if not a:
                        continue
                    if a == proto or proto == a or proto.startswith(a) or a.startswith(proto):
                        allowed_hit = True
                        break
                    # "pump" is a prefix of many names; only exact-family hits
                    if a == "pump" and proto in ("pump", "pumpfun", "pumpswap", "pump.fun"):
                        allowed_hit = True
                        break
                if not allowed_hit:
                    fail("protocol", proto, "allowlist", "str", ReasonCode.PROTOCOL_DISABLED)
                else:
                    ok("protocol", proto, "allowlist", "str")
        elif proto:
            ok("protocol", proto, "optional", "str")

        # dexPaid
        if cfg.reject_dex_paid and dex_paid is True:
            fail("dex_paid", True, False, "bool", ReasonCode.DEX_PAID)
        elif dex_paid is False or dex_paid is None:
            ok("dex_paid", dex_paid, False, "bool")

        # GLOBAL FEES — optional intelligence evidence. Unknown does not reject Gate 1.
        fees = _safe_float(global_fees_sol)
        metrics["global_fees_sol"] = fees
        if cfg.require_fees:
            if global_fees_verified is False:
                fail(
                    "global_fees",
                    global_fees_sol,
                    cfg.min_global_fees_sol,
                    "SOL",
                    ReasonCode.FEES_UNKNOWN,
                    source=global_fees_source,
                    confidence=global_fees_confidence,
                )
            elif fees is None:
                fail(
                    "global_fees",
                    global_fees_sol,
                    cfg.min_global_fees_sol,
                    "SOL",
                    ReasonCode.FEES_UNKNOWN
                    if global_fees_sol is None or global_fees_verified is not True
                    else ReasonCode.INVALID_MARKET_DATA,
                    source=global_fees_source,
                    confidence=global_fees_confidence,
                )
            elif global_fees_verified is not True:
                fail(
                    "global_fees",
                    fees,
                    cfg.min_global_fees_sol,
                    "SOL",
                    ReasonCode.FEES_UNKNOWN,
                    source=global_fees_source,
                    confidence=global_fees_confidence,
                )
            elif fees + 1e-9 < float(cfg.min_global_fees_sol):
                fail(
                    "global_fees",
                    fees,
                    cfg.min_global_fees_sol,
                    "SOL",
                    ReasonCode.FEES_BELOW_MIN,
                    source=global_fees_source,
                    confidence=global_fees_confidence,
                )
            else:
                ok(
                    "global_fees",
                    fees,
                    cfg.min_global_fees_sol,
                    "SOL",
                    source=global_fees_source,
                    confidence=global_fees_confidence,
                )
                metrics["fee_signal"] = "positive"
        else:
            if global_fees_verified is True and fees is not None:
                if fees + 1e-9 >= float(cfg.min_global_fees_sol):
                    ok(
                        "global_fees",
                        fees,
                        cfg.min_global_fees_sol,
                        "SOL",
                        source=global_fees_source,
                        confidence=global_fees_confidence,
                    )
                    metrics["fee_signal"] = "positive"
                else:
                    metrics["fee_signal"] = "negative"
                    prov["fee_negative_evidence"] = True
            else:
                metrics["fee_signal"] = "unavailable"
                metrics["fees_verified"] = False if global_fees_verified is not True else metrics.get("fees_verified")

        if cfg.require_liquidity:
            liq = _safe_float(liquidity_usd)
            metrics["liquidity_usd"] = liq
            if liq is None:
                fail(
                    "liquidity",
                    liquidity_usd,
                    cfg.min_liquidity_usd,
                    "USD",
                    ReasonCode.LIQUIDITY_UNKNOWN
                    if liquidity_usd is None
                    else ReasonCode.INVALID_MARKET_DATA,
                )
            elif liq + 1e-9 < float(cfg.min_liquidity_usd):
                fail(
                    "liquidity",
                    liq,
                    cfg.min_liquidity_usd,
                    "USD",
                    ReasonCode.LIQUIDITY_BELOW_MIN,
                )
            else:
                ok("liquidity", liq, cfg.min_liquidity_usd, "USD")
        else:
            metrics["liquidity_usd"] = _safe_float(liquidity_usd)

        if cfg.require_volume:
            vol = _safe_float(volume_usd)
            metrics["volume_usd"] = vol
            if vol is None:
                fail(
                    "volume",
                    volume_usd,
                    cfg.min_volume_usd,
                    "USD",
                    ReasonCode.VOLUME_UNKNOWN
                    if volume_usd is None
                    else ReasonCode.INVALID_MARKET_DATA,
                )
            elif vol + 1e-9 < float(cfg.min_volume_usd):
                fail(
                    "volume", vol, cfg.min_volume_usd, "USD", ReasonCode.VOLUME_BELOW_MIN
                )
            else:
                ok("volume", vol, cfg.min_volume_usd, "USD")

        if cfg.require_market_cap:
            mcap = _safe_float(market_cap_usd)
            metrics["market_cap_usd"] = mcap
            if mcap is None:
                fail(
                    "market_cap",
                    market_cap_usd,
                    cfg.min_market_cap_usd,
                    "USD",
                    ReasonCode.MARKET_CAP_UNKNOWN
                    if market_cap_usd is None
                    else ReasonCode.INVALID_MARKET_DATA,
                )
            elif mcap + 1e-9 < float(cfg.min_market_cap_usd):
                fail(
                    "market_cap",
                    mcap,
                    cfg.min_market_cap_usd,
                    "USD",
                    ReasonCode.MARKET_CAP_BELOW_MIN,
                )
            else:
                ok("market_cap", mcap, cfg.min_market_cap_usd, "USD")
        else:
            metrics["market_cap_usd"] = _safe_float(market_cap_usd)

        social_ok = _has_verified_social(
            twitter=twitter,
            website=website,
            telegram=telegram,
            tiktok=tiktok,
            socials=socials,
        )
        metrics["social_verified"] = social_ok
        if cfg.require_at_least_one_social:
            if not social_ok:
                fail("social", False, True, "bool", ReasonCode.NO_SOCIAL)
            else:
                ok("social", True, True, "bool")

        eligible = len(failed) == 0
        return self._finish(eligible, mint_s, proto, failed, passed, metrics, prov, now, codes)

    def _finish(
        self,
        eligible: bool,
        mint: str | None,
        protocol: str | None,
        failed: list[FilterMetric],
        passed: list[FilterMetric],
        metrics: dict[str, Any],
        provenance: dict[str, Any],
        evaluated_at: str,
        codes: list[str],
    ) -> FilterDecision:
        primary = None if eligible else _pick_primary(codes)
        decision = FilterDecision(
            accepted=eligible,
            eligible=eligible,
            filter_version=self.config.filter_version,
            evaluated_at=evaluated_at,
            mint=mint,
            protocol=protocol,
            failed_filters=[asdict(f) for f in failed],
            passed_filters=[asdict(p) for p in passed],
            metrics=metrics,
            provenance=provenance,
            rejection_reason=primary,
            reason_codes=list(codes),
            normalized_metrics=dict(metrics),
            source_metadata=dict(provenance),
        )
        if self.config.record_stats:
            filter_stats.record_decision(eligible, codes)
        return decision


def _from_mapping(market: Mapping[str, Any], key: str, *alts: str) -> Any:
    if key in market and market[key] is not None:
        return market[key]
    for a in alts:
        if a in market and market[a] is not None:
            return market[a]
    return None


def evaluate_market(
    market: Mapping[str, Any],
    *,
    config: FilterConfig | None = None,
) -> FilterDecision:
    """Canonical public API: evaluate_market(market) -> EligibilityResult."""
    socials = market.get("socials")
    if not isinstance(socials, dict):
        socials = None
    provenance = market.get("provenance") or market.get("source_metadata")
    if not isinstance(provenance, dict):
        provenance = None
    migrated = market.get("migrated")
    if migrated is None and str(market.get("tab") or "").lower() == "migrated":
        migrated = True
    engine = StinkyFilterEngine(config)
    return engine.evaluate(
        mint=_from_mapping(market, "mint", "tokenAddress", "address"),
        protocol=_from_mapping(market, "protocol", "dex_id", "dexId"),
        dex_id=_from_mapping(market, "dex_id", "dexId"),
        global_fees_sol=_from_mapping(
            market, "global_fees_sol", "fees_sol", "global_fees_paid_sol", "fees"
        ),
        global_fees_verified=_from_mapping(
            market, "global_fees_verified", "fees_verified"
        ),
        global_fees_source=_from_mapping(market, "global_fees_source", "fees_source"),
        global_fees_timestamp=_from_mapping(
            market, "global_fees_timestamp", "fees_observed_at"
        ),
        global_fees_confidence=_from_mapping(market, "global_fees_confidence"),
        global_fees_raw=_from_mapping(market, "global_fees_raw"),
        liquidity_usd=_from_mapping(market, "liquidity_usd", "liquidity"),
        volume_usd=_from_mapping(
            market, "volume_usd", "volume_m5_usd", "volume_5m_usd", "volume"
        ),
        market_cap_usd=_from_mapping(market, "market_cap_usd", "marketCap", "fdv_usd", "mcap_usd"),
        twitter=_from_mapping(market, "twitter"),
        website=_from_mapping(market, "website"),
        telegram=_from_mapping(market, "telegram"),
        tiktok=_from_mapping(market, "tiktok"),
        socials=socials,
        provenance=provenance,
        migrated=migrated if isinstance(migrated, bool) else None,
        tab=_from_mapping(market, "tab"),
        dex_paid=_from_mapping(market, "dex_paid", "dexPaid"),
    )


def evaluate_gate1(
    market: Mapping[str, Any],
    *,
    min_volume_usd: float | None = None,
) -> FilterDecision:
    """Gate 1: protocol + mint + migrated + 5m volume. Fees are not required."""
    cfg = FilterConfig(
        min_volume_usd=clamp_gate1_volume(
            min_volume_usd if min_volume_usd is not None else GATE1_VOLUME_5M_USD
        ),
    )
    return evaluate_market(market, config=cfg)


def evaluate_admission(
    *,
    mint: str | None,
    protocol: str | None = None,
    dex_id: str | None = None,
    global_fees_sol: float | None = None,
    global_fees_verified: bool | None = None,
    global_fees_source: str | None = None,
    global_fees_timestamp: str | None = None,
    global_fees_confidence: float | None = None,
    global_fees_raw: Any = None,
    liquidity_usd: float | None = None,
    volume_usd: float | None = None,
    market_cap_usd: float | None = None,
    twitter: str | None = None,
    website: str | None = None,
    telegram: str | None = None,
    tiktok: str | None = None,
    socials: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    migrated: bool | None = True,
    tab: str | None = "migrated",
    dex_paid: bool | None = None,
    config: FilterConfig | None = None,
) -> FilterDecision:
    """Kwargs entry point. Defaults assume a migrated-tab candidate.

    `migrated=True` / `tab='migrated'` is the product default for opportunity paths.
    Unknown migration still fails closed when the caller passes migrated=None and tab=None
    with a config that require_migrated=True.
    """
    engine = StinkyFilterEngine(config)
    return engine.evaluate(
        mint=mint,
        protocol=protocol,
        dex_id=dex_id,
        global_fees_sol=global_fees_sol,
        global_fees_verified=global_fees_verified,
        global_fees_source=global_fees_source,
        global_fees_timestamp=global_fees_timestamp,
        global_fees_confidence=global_fees_confidence,
        global_fees_raw=global_fees_raw,
        liquidity_usd=liquidity_usd,
        volume_usd=volume_usd,
        market_cap_usd=market_cap_usd,
        twitter=twitter,
        website=website,
        telegram=telegram,
        tiktok=tiktok,
        socials=socials,
        provenance=provenance,
        migrated=migrated,
        tab=tab,
        dex_paid=dex_paid,
    )


def can_alert(
    decision: FilterDecision,
    *,
    score: Any = None,
    meaningful_buyers: Any = None,
    min_score: float = ALERT_MIN_SCORE,
    min_meaningful_buyers: int = ALERT_MIN_MEANINGFUL_BUYERS,
    inspection_complete: bool = False,
    synthetic_level: str | None = None,
    rug_level: str | None = None,
    has_intelligence: bool = False,
) -> tuple[bool, str | None]:
    """Intelligence gate. MUST NOT run unless Gate 1 already passed.

    Gate 1 is not an alert. Alert requires completed inspection, acceptable
    risk, meaningful intelligence, and score >= threshold.
    """
    if not decision.eligible:
        filter_stats.inc("alerts_rejected")
        return False, decision.rejection_reason or ReasonCode.NOT_ELIGIBLE
    if not inspection_complete:
        filter_stats.inc("alerts_rejected")
        return False, ReasonCode.INSPECTION_INCOMPLETE
    if (synthetic_level or "").upper() == "CRITICAL" or (rug_level or "").upper() == "CRITICAL":
        filter_stats.inc("alerts_rejected")
        return False, ReasonCode.RISK_CRITICAL
    if score is None:
        filter_stats.inc("alerts_rejected")
        return False, ReasonCode.SCORE_UNKNOWN
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        filter_stats.inc("alerts_rejected")
        return False, ReasonCode.INVALID_MARKET_DATA
    if score_f + 1e-9 < float(min_score):
        filter_stats.inc("alerts_rejected")
        return False, ReasonCode.SCORE_BELOW_MIN
    if not has_intelligence:
        mb: int | None
        try:
            mb = int(meaningful_buyers) if meaningful_buyers is not None else None
        except (TypeError, ValueError):
            mb = None
        if mb is None or mb < int(min_meaningful_buyers):
            filter_stats.inc("alerts_rejected")
            return False, ReasonCode.INTELLIGENCE_INSUFFICIENT
    filter_stats.inc("alerts_generated")
    return True, None
