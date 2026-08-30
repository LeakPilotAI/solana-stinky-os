"""Market activity inspector + synthetic / rug risk (deterministic V1).

Never invents wallets, volume, or evidence. Missing inputs stay UNKNOWN.
LOW is not the default: insufficient coverage cannot collapse into 'safe'.
A single weak/clean indicator is not enough to claim LOW.
HIGH/CRITICAL requires ≥2 independent risk families — one heuristic is not synthetic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from stinky_core.pools import is_rankable_wallet

INSPECT_VERSION = "inspect-v1.2.0-independent"

LEVELS = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")

# Independent flow signals. LOW requires enough of these observed.
_SYNTHETIC_SIGNALS = (
    "wallet_concentration",
    "wallet_diversity",
    "trade_size_distribution",
    "circular_activity",
    "bot_like_frequency",
    "creator_linked_flow",
    "buy_sell_structure",
    "temporal_clustering",
)
_LOW_MIN_OBSERVED = 3
_LOW_REQUIRES_ANY = ("wallet_concentration", "wallet_diversity")
_HIGH_MIN_FAMILIES = 2

_SIGNAL_FAMILY = {
    "wallet_concentration": "concentration",
    "low_wallet_diversity": "diversity",
    "wallet_diversity": "diversity",
    "repetitive_trade_sizes": "repetition",
    "trade_size_distribution": "repetition",
    "circular_activity": "circular",
    "bot_like_frequency": "bot",
    "creator_linked_activity": "creator",
    "creator_linked_flow": "creator",
    "abnormal_imbalance": "imbalance",
    "buy_sell_structure": "imbalance",
    "temporal_clustering": "timing",
    "repeated_intervals": "timing",
    "thin_liquidity": "liquidity",
    "serial_deployer": "serial",
    "poor_creator_outcomes": "creator_outcomes",
    "holder_concentration": "concentration",
    "synthetic_overlap": "synthetic",
    "unknown_creator": "creator_history",
}


def _f(v: Any) -> float | None:
    if v is None or v is True or v is False:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x < 0:  # noqa: PLR0124
        return None
    return x


def _i(v: Any) -> int | None:
    if v is None or v is True or v is False:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n


def _level_from_score(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


def _level_fail_closed(score: float | None, evidence: list[Evidence]) -> str:
    """Severity of findings wins over a low summed score.

    A HIGH-severity concentration hit must not collapse to LOW because other
    signals were missing. Clean/low-only readings still require coverage.
    """
    sevs = {e.severity for e in evidence}
    if "critical" in sevs:
        scored = _level_from_score(score)
        return "CRITICAL" if scored == "CRITICAL" else "HIGH"
    if "high" in sevs:
        return "HIGH"
    if "medium" in sevs:
        return "MEDIUM" if (score or 0) < 60 else _level_from_score(score)
    return _level_from_score(score)


def _independent_families(evidence: list[Evidence]) -> set[str]:
    fams: set[str] = set()
    for e in evidence:
        if e.severity in ("medium", "high", "critical"):
            fams.add(_SIGNAL_FAMILY.get(e.signal, e.signal))
    return fams


def _cap_unconfirmed_high(level: str, families: set[str]) -> str:
    """One heuristic is not HIGH/CRITICAL synthetic or rug."""
    if level in ("HIGH", "CRITICAL") and len(families) < _HIGH_MIN_FAMILIES:
        return "MEDIUM"
    return level


@dataclass
class Evidence:
    signal: str
    severity: str
    value: Any
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskResult:
    score: float | None
    level: str
    evidence: list[Evidence] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    confidence: float | None = None
    coverage: dict[str, bool] = field(default_factory=dict)
    source: str = "observed"
    independent_families: list[str] = field(default_factory=list)
    model_version: str = INSPECT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.level,
            "score": self.score,
            "level": self.level,
            "confidence": self.confidence,
            "evidence": [e.to_dict() for e in self.evidence],
            "missing": list(self.missing),
            "coverage": dict(self.coverage),
            "source": self.source,
            "independent_families": list(self.independent_families),
            "data_coverage": round(
                (sum(1 for v in self.coverage.values() if v) / len(self.coverage)) if self.coverage else 0.0,
                2,
            ),
            "model_version": self.model_version,
        }


@dataclass
class MarketActivity:
    mint: str | None = None
    volume_m5_usd: float | None = None
    liquidity_usd: float | None = None
    market_cap_usd: float | None = None
    txns_m5_buys: int | None = None
    txns_m5_sells: int | None = None
    unique_buyers: int | None = None
    unique_sellers: int | None = None
    unique_wallets: int | None = None
    top_wallet_volume_share: float | None = None
    top4_wallet_volume_share: float | None = None
    repeated_size_share: float | None = None
    creator_linked_share: float | None = None
    circular_pairs: int | None = None
    buy_sell_imbalance: float | None = None
    trade_count: int | None = None
    median_trade_sol: float | None = None
    max_wallet_trades: int | None = None
    duplicate_trades_dropped: int = 0
    pool_wallets_dropped: int = 0
    repeated_interval_share: float | None = None
    temporal_burst: float | None = None
    volume_liquidity_ratio: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def market_activity_from_mapping(raw: Mapping[str, Any] | None) -> MarketActivity:
    m = raw or {}
    buys = _i(m.get("txns_m5_buys") if m.get("txns_m5_buys") is not None else m.get("buys_m5"))
    sells = _i(m.get("txns_m5_sells") if m.get("txns_m5_sells") is not None else m.get("sells_m5"))
    imb = _f(m.get("buy_sell_imbalance"))
    if imb is None and buys is not None and sells is not None and (buys + sells) > 0:
        imb = buys / (buys + sells)
    uniq = _i(m.get("unique_wallets"))
    if uniq is None:
        ub = _i(m.get("unique_buyers"))
        us = _i(m.get("unique_sellers"))
        if ub is not None and us is not None:
            uniq = max(ub, us)
        elif ub is not None:
            uniq = ub
    vol = _f(m.get("volume_m5_usd") if m.get("volume_m5_usd") is not None else m.get("volume_usd"))
    liq = _f(m.get("liquidity_usd"))
    ratio = None
    if vol is not None and liq is not None and liq > 0:
        ratio = vol / liq
    return MarketActivity(
        mint=(str(m["mint"]).strip() if m.get("mint") else None),
        volume_m5_usd=vol,
        liquidity_usd=liq,
        market_cap_usd=_f(m.get("market_cap_usd") if m.get("market_cap_usd") is not None else m.get("mcap_usd")),
        txns_m5_buys=buys,
        txns_m5_sells=sells,
        unique_buyers=_i(m.get("unique_buyers")),
        unique_sellers=_i(m.get("unique_sellers")),
        unique_wallets=uniq,
        top_wallet_volume_share=_f(m.get("top_wallet_volume_share")),
        top4_wallet_volume_share=_f(m.get("top4_wallet_volume_share")),
        repeated_size_share=_f(m.get("repeated_size_share")),
        creator_linked_share=_f(m.get("creator_linked_share")),
        circular_pairs=_i(m.get("circular_pairs")),
        buy_sell_imbalance=imb,
        trade_count=_i(m.get("trade_count")),
        median_trade_sol=_f(m.get("median_trade_sol")),
        max_wallet_trades=_i(m.get("max_wallet_trades")),
        repeated_interval_share=_f(m.get("repeated_interval_share")),
        temporal_burst=_f(m.get("temporal_burst")),
        volume_liquidity_ratio=_f(m.get("volume_liquidity_ratio")) if m.get("volume_liquidity_ratio") is not None else ratio,
    )


def activity_from_trades(
    *,
    mint: str | None,
    trades: list[Mapping[str, Any]] | None,
    volume_m5_usd: float | None = None,
    liquidity_usd: float | None = None,
    market_cap_usd: float | None = None,
    txns_m5_buys: int | None = None,
    txns_m5_sells: int | None = None,
    creator: str | None = None,
) -> MarketActivity:
    """Build activity from observed trades. Dedupes + drops pool/program wallets."""
    raw_rows = [t for t in (trades or []) if isinstance(t, Mapping)]
    seen: set[tuple[str, str, str]] = set()
    rows: list[Mapping[str, Any]] = []
    dupes = 0
    pools = 0
    for t in raw_rows:
        w = str(t.get("userAddress") or t.get("wallet") or "").strip()
        if w and not is_rankable_wallet(w):
            pools += 1
            continue
        sig = str(t.get("signature") or t.get("tx") or "").strip()
        side = str(t.get("type") or t.get("side") or "").lower()
        if sig:
            key = (sig, w, side)
            if key in seen:
                dupes += 1
                continue
            seen.add(key)
        rows.append(t)

    buyers: set[str] = set()
    sellers: set[str] = set()
    sizes: list[float] = []
    vol_by_w: dict[str, float] = {}
    counts: dict[str, int] = {}
    creator_vol = 0.0
    total_vol = 0.0
    times: list[float] = []
    for t in rows:
        w = str(t.get("userAddress") or t.get("wallet") or "").strip()
        side = str(t.get("type") or t.get("side") or "").lower()
        amt = _f(t.get("amountSol") if t.get("amountSol") is not None else t.get("sol"))
        ts = _f(t.get("timestamp") if t.get("timestamp") is not None else t.get("blockTime") if t.get("blockTime") is not None else t.get("block_time") if t.get("block_time") is not None else t.get("time"))
        if ts is not None:
            times.append(ts)
        if w:
            counts[w] = counts.get(w, 0) + 1
            if side in ("buy", "bought"):
                buyers.add(w)
            elif side in ("sell", "sold"):
                sellers.add(w)
        if amt is not None:
            sizes.append(amt)
            total_vol += amt
            if w:
                vol_by_w[w] = vol_by_w.get(w, 0.0) + amt
                if creator and w == creator:
                    creator_vol += amt
    uniq = set(buyers) | set(sellers) | set(vol_by_w)
    top1 = top4 = None
    if vol_by_w and total_vol > 0:
        ranked = sorted(vol_by_w.values(), reverse=True)
        top1 = ranked[0] / total_vol
        top4 = sum(ranked[:4]) / total_vol
    rep = None
    if sizes:
        bucket = Counter(round(s, 4) for s in sizes)
        rep = max(bucket.values()) / len(sizes)
    imb = None
    if txns_m5_buys is not None and txns_m5_sells is not None and (txns_m5_buys + txns_m5_sells) > 0:
        imb = txns_m5_buys / (txns_m5_buys + txns_m5_sells)
    elif buyers or sellers:
        tot = len(buyers) + len(sellers)
        imb = (len(buyers) / tot) if tot else None
    both = buyers & sellers
    circ_n = len(both) if rows else None
    interval_share = None
    burst = None
    if len(times) >= 8:
        times.sort()
        deltas = [round(times[i + 1] - times[i], 2) for i in range(len(times) - 1)]
        if deltas:
            interval_share = max(Counter(deltas).values()) / len(deltas)
            window = times[-1] - times[0]
            burst = (len(times) / window) if window > 0 else None
    ratio = None
    if volume_m5_usd is not None and liquidity_usd is not None and liquidity_usd > 0:
        ratio = volume_m5_usd / liquidity_usd
    return MarketActivity(
        mint=mint,
        volume_m5_usd=volume_m5_usd,
        liquidity_usd=liquidity_usd,
        market_cap_usd=market_cap_usd,
        txns_m5_buys=txns_m5_buys,
        txns_m5_sells=txns_m5_sells,
        unique_buyers=len(buyers) if rows else None,
        unique_sellers=len(sellers) if rows else None,
        unique_wallets=len(uniq) if rows else None,
        top_wallet_volume_share=top1,
        top4_wallet_volume_share=top4,
        repeated_size_share=rep,
        creator_linked_share=(creator_vol / total_vol) if creator and total_vol > 0 else None,
        circular_pairs=circ_n,
        buy_sell_imbalance=imb,
        trade_count=len(rows) if rows else None,
        median_trade_sol=(sorted(sizes)[len(sizes) // 2] if sizes else None),
        max_wallet_trades=max(counts.values()) if counts else None,
        duplicate_trades_dropped=dupes,
        pool_wallets_dropped=pools,
        repeated_interval_share=interval_share,
        temporal_burst=burst,
        volume_liquidity_ratio=ratio,
    )


def assess_synthetic(activity: MarketActivity) -> RiskResult:
    """Deterministic synthetic-activity risk.

    UNKNOWN if no flow evidence, or if the only readings are clean/weak and
    coverage is too thin to support LOW. HIGH/CRITICAL needs ≥2 independent
    risk families. A single concentrated holder is not automatically synthetic.
    """
    ev: list[Evidence] = []
    missing: list[str] = []
    coverage: dict[str, bool] = {k: False for k in _SYNTHETIC_SIGNALS}
    score = 0.0

    def add(pts: float, signal: str, severity: str, value: Any, explanation: str) -> None:
        nonlocal score
        score += pts
        ev.append(Evidence(signal, severity, value, explanation))

    top4 = activity.top4_wallet_volume_share
    if top4 is None:
        missing.append("wallet_concentration")
    else:
        coverage["wallet_concentration"] = True
        if top4 >= 0.85:
            add(42, "wallet_concentration", "critical", round(top4, 4), f"{top4:.0%} of observed volume from 4 wallets")
        elif top4 >= 0.70:
            add(28, "wallet_concentration", "high", round(top4, 4), f"{top4:.0%} of observed volume from 4 wallets")
        elif top4 >= 0.55:
            add(14, "wallet_concentration", "medium", round(top4, 4), f"{top4:.0%} of observed volume from 4 wallets")
        else:
            add(0, "wallet_concentration", "low", round(top4, 4), f"Top-4 volume share {top4:.0%}")

    uniq = activity.unique_wallets
    vol = activity.volume_m5_usd
    if uniq is None or vol is None:
        missing.append("wallet_diversity")
    else:
        coverage["wallet_diversity"] = True
        if vol >= 150_000 and uniq < 6:
            add(36, "low_wallet_diversity", "high", uniq, f"{uniq} unique wallets vs ${vol:,.0f} 5m volume")
        elif vol >= 150_000 and uniq < 12:
            add(18, "low_wallet_diversity", "medium", uniq, f"{uniq} unique wallets vs ${vol:,.0f} 5m volume")
        else:
            add(0, "wallet_diversity", "low", uniq, f"{uniq} unique wallets on observed book")

    rep = activity.repeated_size_share
    if rep is None:
        missing.append("trade_size_distribution")
    else:
        coverage["trade_size_distribution"] = True
        if rep >= 0.55:
            add(24, "repetitive_trade_sizes", "high", round(rep, 4), f"{rep:.0%} of trades share the same size")
        elif rep >= 0.35:
            add(12, "repetitive_trade_sizes", "medium", round(rep, 4), f"{rep:.0%} of trades share the same size")
        else:
            add(0, "trade_size_distribution", "low", round(rep, 4), f"Repeated-size share {rep:.0%}")

    circ = activity.circular_pairs
    if circ is None:
        missing.append("circular_activity")
    else:
        coverage["circular_activity"] = True
        if circ >= 3:
            add(22, "circular_activity", "high", circ, f"{circ} circular wallet pairs observed")
        elif circ >= 1:
            add(10, "circular_activity", "medium", circ, f"{circ} circular wallet pair(s) observed")
        else:
            add(0, "circular_activity", "low", circ, "No circular pairs in observed set")

    mx = activity.max_wallet_trades
    tc = activity.trade_count
    if mx is None or tc is None or tc < 8:
        missing.append("bot_like_frequency")
    else:
        coverage["bot_like_frequency"] = True
        if mx >= max(12, int(0.4 * tc)):
            add(16, "bot_like_frequency", "medium", mx, f"One wallet placed {mx} of {tc} observed trades")
        else:
            add(0, "bot_like_frequency", "low", mx, f"Max wallet trades {mx} of {tc}")

    cl = activity.creator_linked_share
    if cl is None:
        missing.append("creator_linked_flow")
    else:
        coverage["creator_linked_flow"] = True
        if cl >= 0.25:
            add(20, "creator_linked_activity", "high", round(cl, 4), f"Creator-linked wallets are {cl:.0%} of observed volume")
        else:
            add(0, "creator_linked_flow", "low", round(cl, 4), f"Creator-linked share {cl:.0%}")

    imb = activity.buy_sell_imbalance
    if imb is None:
        missing.append("buy_sell_structure")
    else:
        coverage["buy_sell_structure"] = True
        if imb >= 0.92 or imb <= 0.08:
            add(10, "abnormal_imbalance", "medium", round(imb, 4), f"Buy share {imb:.0%} of observed txns")
        else:
            add(0, "buy_sell_structure", "low", round(imb, 4), f"Buy share {imb:.0%}")

    interval = activity.repeated_interval_share
    if interval is None:
        missing.append("temporal_clustering")
    else:
        coverage["temporal_clustering"] = True
        if interval >= 0.55:
            add(18, "repeated_intervals", "high", round(interval, 4), f"{interval:.0%} of observed trades share the same interval")
        elif interval >= 0.35:
            add(10, "repeated_intervals", "medium", round(interval, 4), f"{interval:.0%} of observed trades share the same interval")
        else:
            add(0, "temporal_clustering", "low", round(interval, 4), f"Repeated-interval share {interval:.0%}")

    observed_n = sum(1 for v in coverage.values() if v)
    conf = round(min(0.9, 0.15 * observed_n), 2) if observed_n else None
    risk_hits = [e for e in ev if e.severity in ("medium", "high", "critical")]
    families = _independent_families(ev)

    if observed_n == 0:
        return RiskResult(
            score=None, level="UNKNOWN", evidence=ev, missing=missing,
            confidence=None, coverage=coverage, independent_families=sorted(families),
        )

    if risk_hits:
        lvl = _cap_unconfirmed_high(_level_fail_closed(min(100.0, score), ev), families)
        return RiskResult(
            score=round(min(100.0, score), 1),
            level=lvl,
            evidence=ev,
            missing=missing,
            confidence=conf,
            coverage=coverage,
            independent_families=sorted(families),
        )

    core_ok = any(coverage.get(k) for k in _LOW_REQUIRES_ANY)
    if observed_n < _LOW_MIN_OBSERVED or not core_ok:
        return RiskResult(
            score=None,
            level="UNKNOWN",
            evidence=ev,
            missing=missing,
            confidence=None,
            coverage=coverage,
            independent_families=sorted(families),
        )
    return RiskResult(
        score=round(min(100.0, score), 1),
        level="LOW",
        evidence=ev,
        missing=missing,
        confidence=conf,
        coverage=coverage,
        independent_families=sorted(families),
    )


def assess_rug(
    activity: MarketActivity,
    *,
    creator_launches: int | None = None,
    creator_runner_rate: float | None = None,
    creator_known: bool | None = None,
    synthetic: RiskResult | None = None,
) -> RiskResult:
    ev: list[Evidence] = []
    missing: list[str] = []
    coverage: dict[str, bool] = {
        "liquidity": False,
        "creator_history": False,
        "holder_concentration": False,
        "synthetic": False,
    }
    score = 0.0

    def add(pts: float, signal: str, severity: str, value: Any, explanation: str) -> None:
        nonlocal score
        score += pts
        ev.append(Evidence(signal, severity, value, explanation))

    liq = activity.liquidity_usd
    vol = activity.volume_m5_usd
    if liq is None:
        missing.append("liquidity")
    else:
        coverage["liquidity"] = True
        if liq < 5_000 and vol is not None and vol >= 150_000:
            add(28, "thin_liquidity", "high", liq, f"Liquidity ${liq:,.0f} vs 5m volume ${vol:,.0f}")
        elif liq < 8_000:
            add(12, "thin_liquidity", "medium", liq, f"Liquidity ${liq:,.0f}")

    if creator_known is True:
        coverage["creator_history"] = True
    else:
        missing.append("creator_history")

    if creator_launches is not None:
        coverage["creator_history"] = True
        if creator_launches >= 40:
            add(30, "serial_deployer", "high", creator_launches, f"Creator has {creator_launches} stored launches")
        elif creator_launches >= 15:
            add(16, "serial_deployer", "medium", creator_launches, f"Creator has {creator_launches} stored launches")
    if creator_runner_rate is not None and creator_launches and creator_launches >= 5:
        coverage["creator_history"] = True
        if creator_runner_rate < 0.08:
            add(14, "poor_creator_outcomes", "medium", round(creator_runner_rate, 3), "Low historical runner rate for creator")

    top4 = activity.top4_wallet_volume_share
    if top4 is not None:
        coverage["holder_concentration"] = True
        if top4 >= 0.8:
            add(18, "holder_concentration", "high", round(top4, 4), "High early-book concentration")
    else:
        missing.append("holder_concentration")

    if synthetic is not None and synthetic.level not in (None, "UNKNOWN"):
        coverage["synthetic"] = True
        if synthetic.level == "CRITICAL":
            add(24, "synthetic_overlap", "critical", synthetic.score, "Synthetic activity already CRITICAL")
        elif synthetic.level == "HIGH":
            add(12, "synthetic_overlap", "high", synthetic.score, "Synthetic activity HIGH")
    else:
        missing.append("synthetic")

    observed_n = sum(1 for v in coverage.values() if v)
    conf = round(min(0.85, 0.2 * observed_n), 2) if observed_n else None
    risk_hits = [e for e in ev if e.severity in ("medium", "high", "critical")]
    families = _independent_families(ev)
    if not risk_hits:
        return RiskResult(
            score=None, level="UNKNOWN", evidence=ev, missing=missing,
            confidence=None, coverage=coverage, source="observed",
            independent_families=sorted(families),
        )
    lvl = _cap_unconfirmed_high(_level_fail_closed(min(100.0, score), ev), families)
    return RiskResult(
        score=round(min(100.0, score), 1),
        level=lvl,
        evidence=ev,
        missing=missing,
        confidence=conf,
        coverage=coverage,
        independent_families=sorted(families),
    )
