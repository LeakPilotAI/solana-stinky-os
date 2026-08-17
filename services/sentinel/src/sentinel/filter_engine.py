"""StinkyFilterEngine — canonical admission control (axiom-parity-v1.0.0).

FAIL CLOSED. Filtering happens BEFORE scoring.
Score, volume heuristics, smart-money, or UI convenience MUST NOT override a failed hard gate.

Invariants (never violate):
  - global_fees_verified is False or fees missing  → REJECT
  - global_fees_sol < min (default 5.0)           → REJECT
  - liquidity_usd < min (default 8)               → REJECT
  - volume_usd < min (default 100_000)            → REJECT
  - market_cap_usd < min (default 31_333)         → REJECT
  - no verified social when required              → REJECT
  - unsupported / unknown protocol                → REJECT
  - failed hard filter                            → score cannot override
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

FILTER_VERSION = "axiom-parity-v1.0.0"

# ---------------------------------------------------------------------------
# Hard gate defaults (Axiom migrated-tab parity). Override via settings / env.
# ---------------------------------------------------------------------------
DEFAULT_MIN_GLOBAL_FEES_SOL = 5.0
DEFAULT_MIN_LIQUIDITY_USD = 8.0
DEFAULT_MIN_VOLUME_USD = 100_000.0
DEFAULT_MIN_MARKET_CAP_USD = 31_333.0
DEFAULT_REQUIRE_AT_LEAST_ONE_SOCIAL = True

# Protocol allowlist (normalized lowercase). Unknown → REJECT.
DEFAULT_ALLOWED_PROTOCOLS: frozenset[str] = frozenset(
    {
        "pump",
        "pumpfun",
        "pumpswap",
        "pump.fun",
        "mayhem",
        "launchlab",
        "virtualcurve",
        "launchacoin",
        "bonk",
        "bonkers",
        "boop",
        "surge",
        "moonshot",
        "moonshotapp",
        "heaven",
        "daosfun",
        "candle",
        "sugar",
        "jupiterstudio",
        "bags",
        "soar",
        "printr",
        "liquidaf",
        "liquidaffamm",
        "riserich",
        "stonkfun",
        "pve",
        "wavebreak",
    }
)

DEFAULT_DENIED_PROTOCOLS: frozenset[str] = frozenset(
    {
        "raydium",
        "pumpamm",
        "meteora",
        "meteoraamm",
        "meteoraammv2",
        "orca",
        "phoenix",
        "lifinity",
        "saber",
        "aldrin",
        "fluxbeam",
    }
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


@dataclass(frozen=True)
class FilterDecision:
    accepted: bool
    filter_version: str
    evaluated_at: str
    mint: str | None
    protocol: str | None
    failed_filters: list[dict[str, Any]] = field(default_factory=list)
    passed_filters: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f < 0:  # NaN or negative
        return None
    return f


def _norm_protocol(raw: str | None) -> str:
    return (raw or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _has_verified_social(
    *,
    twitter: str | None = None,
    website: str | None = None,
    telegram: str | None = None,
    tiktok: str | None = None,
    socials: dict[str, Any] | None = None,
) -> bool:
    """At least one non-empty, non-placeholder social presence."""
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


@dataclass
class FilterConfig:
    """Runtime thresholds for axiom-parity (or future profiles)."""

    filter_version: str = FILTER_VERSION
    min_global_fees_sol: float = DEFAULT_MIN_GLOBAL_FEES_SOL
    min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD
    min_volume_usd: float = DEFAULT_MIN_VOLUME_USD
    min_market_cap_usd: float = DEFAULT_MIN_MARKET_CAP_USD
    require_at_least_one_social: bool = DEFAULT_REQUIRE_AT_LEAST_ONE_SOCIAL
    require_pump_mint_suffix: bool = False  # Axiom does not require mustEndInPump
    allowed_protocols: frozenset[str] = DEFAULT_ALLOWED_PROTOCOLS
    denied_protocols: frozenset[str] = DEFAULT_DENIED_PROTOCOLS
    # When True, protocol must be known and allowed. Unknown → REJECT.
    reject_unknown_protocol: bool = True


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
        # Fees — THE critical gate
        global_fees_sol: float | None = None,
        global_fees_verified: bool | None = None,
        global_fees_source: str | None = None,
        global_fees_timestamp: str | None = None,
        global_fees_confidence: float | None = None,
        global_fees_raw: Any = None,
        # Market metrics (USD)
        liquidity_usd: float | None = None,
        volume_usd: float | None = None,
        market_cap_usd: float | None = None,
        # Social
        twitter: str | None = None,
        website: str | None = None,
        telegram: str | None = None,
        tiktok: str | None = None,
        socials: dict[str, Any] | None = None,
        # Optional provenance bag
        provenance: dict[str, Any] | None = None,
    ) -> FilterDecision:
        cfg = self.config
        now = datetime.now(timezone.utc).isoformat()
        mint_s = (mint or "").strip() or None
        proto_raw = protocol or dex_id
        proto = _norm_protocol(proto_raw)

        failed: list[FilterMetric] = []
        passed: list[FilterMetric] = []
        metrics: dict[str, Any] = {
            "mint": mint_s,
            "protocol": proto or None,
            "global_fees_sol": None,
            "liquidity_usd": None,
            "volume_usd": None,
            "market_cap_usd": None,
            "social_verified": False,
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

        def fail(name: str, actual: Any, required: Any, unit: str, reason: str, **kw: Any) -> None:
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

        # --- Mint ---
        if not mint_s:
            fail("mint", None, "non-empty", "str", "INVALID_MINT")
            return self._decision(
                False, mint_s, proto, failed, passed, metrics, prov, now, "INVALID_MINT"
            )

        if cfg.require_pump_mint_suffix and not mint_s.lower().endswith("pump"):
            fail("mint_suffix", mint_s[-8:], "…pump", "str", "NOT_PUMP_MINT")
            return self._decision(
                False, mint_s, proto, failed, passed, metrics, prov, now, "NOT_PUMP_MINT"
            )

        # --- Protocol ---
        if proto and any(d in proto for d in cfg.denied_protocols):
            fail("protocol", proto, "not in denied", "str", "PROTOCOL_NOT_ALLOWED")
            return self._decision(
                False, mint_s, proto, failed, passed, metrics, prov, now, "PROTOCOL_NOT_ALLOWED"
            )

        if cfg.reject_unknown_protocol:
            if not proto:
                fail("protocol", None, "known allowed", "str", "UNKNOWN_PROTOCOL")
                return self._decision(
                    False, mint_s, proto, failed, passed, metrics, prov, now, "UNKNOWN_PROTOCOL"
                )
            allowed_hit = any(a in proto or proto in a for a in cfg.allowed_protocols)
            if not allowed_hit:
                fail("protocol", proto, "allowlist", "str", "PROTOCOL_NOT_ALLOWED")
                return self._decision(
                    False, mint_s, proto, failed, passed, metrics, prov, now, "PROTOCOL_NOT_ALLOWED"
                )
            ok("protocol", proto, "allowlist", "str")
        elif proto:
            ok("protocol", proto, "optional", "str")

        # --- GLOBAL FEES (most important) ---
        # If unavailable or cannot be authoritatively verified → REJECT.
        if global_fees_verified is False:
            fail(
                "global_fees",
                global_fees_sol,
                cfg.min_global_fees_sol,
                "SOL",
                "GLOBAL_FEES_UNVERIFIED",
                source=global_fees_source,
                confidence=global_fees_confidence,
            )
            return self._decision(
                False,
                mint_s,
                proto,
                failed,
                passed,
                metrics,
                prov,
                now,
                "GLOBAL_FEES_UNVERIFIED",
            )

        fees = _safe_float(global_fees_sol)
        metrics["global_fees_sol"] = fees
        if fees is None:
            # Missing / malformed / negative / NaN → REJECT (never treat as pass)
            fail(
                "global_fees",
                global_fees_sol,
                cfg.min_global_fees_sol,
                "SOL",
                "GLOBAL_FEES_UNVERIFIED"
                if global_fees_verified is not True
                else "GLOBAL_FEES_UNKNOWN",
                source=global_fees_source,
                confidence=global_fees_confidence,
            )
            reason = (
                "GLOBAL_FEES_UNVERIFIED"
                if global_fees_verified is not True
                else "GLOBAL_FEES_UNKNOWN"
            )
            # Explicit: missing fees always reject even if verified flag is accidentally True
            if fees is None:
                reason = "GLOBAL_FEES_UNKNOWN" if global_fees_sol is None else "GLOBAL_FEES_INVALID"
            return self._decision(
                False, mint_s, proto, failed, passed, metrics, prov, now, reason
            )

        # Require explicit verification when we have a number
        if global_fees_verified is not True:
            fail(
                "global_fees",
                fees,
                cfg.min_global_fees_sol,
                "SOL",
                "GLOBAL_FEES_UNVERIFIED",
                source=global_fees_source,
                confidence=global_fees_confidence,
            )
            return self._decision(
                False,
                mint_s,
                proto,
                failed,
                passed,
                metrics,
                prov,
                now,
                "GLOBAL_FEES_UNVERIFIED",
            )

        if fees + 1e-9 < float(cfg.min_global_fees_sol):
            fail(
                "global_fees",
                fees,
                cfg.min_global_fees_sol,
                "SOL",
                "GLOBAL_FEES_BELOW_MINIMUM",
                source=global_fees_source,
                confidence=global_fees_confidence,
            )
            return self._decision(
                False,
                mint_s,
                proto,
                failed,
                passed,
                metrics,
                prov,
                now,
                "GLOBAL_FEES_BELOW_MINIMUM",
            )

        ok(
            "global_fees",
            fees,
            cfg.min_global_fees_sol,
            "SOL",
            source=global_fees_source,
            confidence=global_fees_confidence,
        )

        # --- Liquidity ---
        liq = _safe_float(liquidity_usd)
        metrics["liquidity_usd"] = liq
        if liq is None:
            fail("liquidity", liquidity_usd, cfg.min_liquidity_usd, "USD", "LIQUIDITY_UNKNOWN")
            return self._decision(
                False, mint_s, proto, failed, passed, metrics, prov, now, "LIQUIDITY_UNKNOWN"
            )
        if liq + 1e-9 < float(cfg.min_liquidity_usd):
            fail(
                "liquidity",
                liq,
                cfg.min_liquidity_usd,
                "USD",
                "LIQUIDITY_BELOW_MINIMUM",
            )
            return self._decision(
                False,
                mint_s,
                proto,
                failed,
                passed,
                metrics,
                prov,
                now,
                "LIQUIDITY_BELOW_MINIMUM",
            )
        ok("liquidity", liq, cfg.min_liquidity_usd, "USD")

        # --- Volume ---
        vol = _safe_float(volume_usd)
        metrics["volume_usd"] = vol
        if vol is None:
            fail("volume", volume_usd, cfg.min_volume_usd, "USD", "VOLUME_UNKNOWN")
            return self._decision(
                False, mint_s, proto, failed, passed, metrics, prov, now, "VOLUME_UNKNOWN"
            )
        if vol + 1e-9 < float(cfg.min_volume_usd):
            fail("volume", vol, cfg.min_volume_usd, "USD", "VOLUME_BELOW_MINIMUM")
            return self._decision(
                False, mint_s, proto, failed, passed, metrics, prov, now, "VOLUME_BELOW_MINIMUM"
            )
        ok("volume", vol, cfg.min_volume_usd, "USD")

        # --- Market cap ---
        mcap = _safe_float(market_cap_usd)
        metrics["market_cap_usd"] = mcap
        if mcap is None:
            fail(
                "market_cap",
                market_cap_usd,
                cfg.min_market_cap_usd,
                "USD",
                "MARKET_CAP_UNKNOWN",
            )
            return self._decision(
                False, mint_s, proto, failed, passed, metrics, prov, now, "MARKET_CAP_UNKNOWN"
            )
        if mcap + 1e-9 < float(cfg.min_market_cap_usd):
            fail(
                "market_cap",
                mcap,
                cfg.min_market_cap_usd,
                "USD",
                "MARKET_CAP_BELOW_MINIMUM",
            )
            return self._decision(
                False,
                mint_s,
                proto,
                failed,
                passed,
                metrics,
                prov,
                now,
                "MARKET_CAP_BELOW_MINIMUM",
            )
        ok("market_cap", mcap, cfg.min_market_cap_usd, "USD")

        # --- Social ---
        social_ok = _has_verified_social(
            twitter=twitter,
            website=website,
            telegram=telegram,
            tiktok=tiktok,
            socials=socials,
        )
        metrics["social_verified"] = social_ok
        if cfg.require_at_least_one_social and not social_ok:
            fail("social", False, True, "bool", "SOCIAL_REQUIREMENT_FAILED")
            return self._decision(
                False,
                mint_s,
                proto,
                failed,
                passed,
                metrics,
                prov,
                now,
                "SOCIAL_REQUIREMENT_FAILED",
            )
        if cfg.require_at_least_one_social:
            ok("social", True, True, "bool")

        return self._decision(True, mint_s, proto, failed, passed, metrics, prov, now, None)

    def _decision(
        self,
        accepted: bool,
        mint: str | None,
        protocol: str | None,
        failed: list[FilterMetric],
        passed: list[FilterMetric],
        metrics: dict[str, Any],
        provenance: dict[str, Any],
        evaluated_at: str,
        rejection_reason: str | None,
    ) -> FilterDecision:
        return FilterDecision(
            accepted=accepted,
            filter_version=self.config.filter_version,
            evaluated_at=evaluated_at,
            mint=mint,
            protocol=protocol,
            failed_filters=[asdict(f) for f in failed],
            passed_filters=[asdict(p) for p in passed],
            metrics=metrics,
            provenance=provenance,
            rejection_reason=rejection_reason,
        )


def evaluate_admission(
    *,
    mint: str | None,
    protocol: str | None = None,
    dex_id: str | None = None,
    global_fees_sol: float | None = None,
    global_fees_verified: bool | None = None,
    global_fees_source: str | None = None,
    liquidity_usd: float | None = None,
    volume_usd: float | None = None,
    market_cap_usd: float | None = None,
    twitter: str | None = None,
    website: str | None = None,
    telegram: str | None = None,
    tiktok: str | None = None,
    socials: dict[str, Any] | None = None,
    config: FilterConfig | None = None,
) -> FilterDecision:
    """Public entry point for all admission checks."""
    engine = StinkyFilterEngine(config)
    return engine.evaluate(
        mint=mint,
        protocol=protocol,
        dex_id=dex_id,
        global_fees_sol=global_fees_sol,
        global_fees_verified=global_fees_verified,
        global_fees_source=global_fees_source,
        liquidity_usd=liquidity_usd,
        volume_usd=volume_usd,
        market_cap_usd=market_cap_usd,
        twitter=twitter,
        website=website,
        telegram=telegram,
        tiktok=tiktok,
        socials=socials,
    )
