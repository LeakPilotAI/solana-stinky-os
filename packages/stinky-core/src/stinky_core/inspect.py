"""Market activity inspector + synthetic / rug risk (deterministic V1).

Never invents wallets, volume, or evidence. Missing inputs stay UNKNOWN.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

INSPECT_VERSION = "inspect-v1.0.0"

LEVELS = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")


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


def _level(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


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
    model_version: str = INSPECT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "evidence": [e.to_dict() for e in self.evidence],
            "missing": list(self.missing),
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
    return MarketActivity(
        mint=(str(m["mint"]).strip() if m.get("mint") else None),
        volume_m5_usd=_f(m.get("volume_m5_usd") if m.get("volume_m5_usd") is not None else m.get("volume_usd")),
        liquidity_usd=_f(m.get("liquidity_usd")),
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
    """Build activity from observed trades. Does not invent missing fields."""
    rows = [t for t in (trades or []) if isinstance(t, Mapping)]
    buyers: set[str] = set()
    sellers: set[str] = set()
    sizes: list[float] = []
    vol_by_w: dict[str, float] = {}
    counts: dict[str, int] = {}
    creator_vol = 0.0
    total_vol = 0.0
    for t in rows:
        w = str(t.get("userAddress") or t.get("wallet") or "").strip()
        side = str(t.get("type") or t.get("side") or "").lower()
        amt = _f(t.get("amountSol") if t.get("amountSol") is not None else t.get("sol"))
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
        from collections import Counter

        bucket = Counter(round(s, 4) for s in sizes)
        rep = max(bucket.values()) / len(sizes)
    imb = None
    if txns_m5_buys is not None and txns_m5_sells is not None and (txns_m5_buys + txns_m5_sells) > 0:
        imb = txns_m5_buys / (txns_m5_buys + txns_m5_sells)
    elif buyers or sellers:
        tot = len(buyers) + len(sellers)
        imb = (len(buyers) / tot) if tot else None
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
        circular_pairs=None,
        buy_sell_imbalance=imb,
        trade_count=len(rows) if rows else None,
        median_trade_sol=(sorted(sizes)[len(sizes) // 2] if sizes else None),
        max_wallet_trades=max(counts.values()) if counts else None,
    )


def assess_synthetic(activity: MarketActivity) -> RiskResult:
    """Deterministic synthetic-activity risk. UNKNOWN if no flow evidence."""
    ev: list[Evidence] = []
    missing: list[str] = []
    score = 0.0
    used = 0

    def add(pts: float, signal: str, severity: str, value: Any, explanation: str) -> None:
        nonlocal score, used
        used += 1
        score += pts
        ev.append(Evidence(signal, severity, value, explanation))

    top4 = activity.top4_wallet_volume_share
    if top4 is None:
        missing.append("wallet_concentration")
    else:
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
        if vol >= 150_000 and uniq < 6:
            add(36, "low_wallet_diversity", "high", uniq, f"{uniq} unique wallets vs ${vol:,.0f} 5m volume")
        elif vol >= 150_000 and uniq < 12:
            add(18, "low_wallet_diversity", "medium", uniq, f"{uniq} unique wallets vs ${vol:,.0f} 5m volume")
        else:
            add(0, "wallet_diversity", "low", uniq, f"{uniq} unique wallets on observed book")

    rep = activity.repeated_size_share
    if rep is None:
        missing.append("trade_size_distribution")
    elif rep >= 0.55:
        add(24, "repetitive_trade_sizes", "high", round(rep, 4), f"{rep:.0%} of trades share the same size")
    elif rep >= 0.35:
        add(12, "repetitive_trade_sizes", "medium", round(rep, 4), f"{rep:.0%} of trades share the same size")

    circ = activity.circular_pairs
    if circ is None:
        missing.append("circular_activity")
    elif circ >= 3:
        add(22, "circular_activity", "high", circ, f"{circ} circular wallet pairs observed")
    elif circ >= 1:
        add(10, "circular_activity", "medium", circ, f"{circ} circular wallet pair(s) observed")

    mx = activity.max_wallet_trades
    tc = activity.trade_count
    if mx is None or tc is None or tc < 8:
        if "bot_like_frequency" not in missing:
            missing.append("bot_like_frequency")
    elif mx >= max(12, int(0.4 * tc)):
        add(16, "bot_like_frequency", "medium", mx, f"One wallet placed {mx} of {tc} observed trades")

    cl = activity.creator_linked_share
    if cl is None:
        missing.append("creator_linked_flow")
    elif cl >= 0.25:
        add(20, "creator_linked_activity", "high", round(cl, 4), f"Creator-linked wallets are {cl:.0%} of observed volume")

    imb = activity.buy_sell_imbalance
    if imb is None:
        missing.append("buy_sell_structure")
    elif imb >= 0.92 or imb <= 0.08:
        add(10, "abnormal_imbalance", "medium", round(imb, 4), f"Buy share {imb:.0%} of observed txns")

    if used == 0:
        return RiskResult(score=None, level="UNKNOWN", evidence=ev, missing=missing)
    return RiskResult(score=round(min(100.0, score), 1), level=_level(min(100.0, score)), evidence=ev, missing=missing)


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
    score = 0.0
    used = 0

    def add(pts: float, signal: str, severity: str, value: Any, explanation: str) -> None:
        nonlocal score, used
        used += 1
        score += pts
        ev.append(Evidence(signal, severity, value, explanation))

    liq = activity.liquidity_usd
    vol = activity.volume_m5_usd
    if liq is None:
        missing.append("liquidity")
    elif liq < 5_000 and vol is not None and vol >= 150_000:
        add(28, "thin_liquidity", "high", liq, f"Liquidity ${liq:,.0f} vs 5m volume ${vol:,.0f}")
    elif liq < 8_000:
        add(12, "thin_liquidity", "medium", liq, f"Liquidity ${liq:,.0f}")

    if creator_known is False or creator_known is None:
        missing.append("creator_history")
        if creator_known is False:
            add(8, "unknown_creator", "medium", None, "Creator has no stored history")
    if creator_launches is not None:
        if creator_launches >= 40:
            add(30, "serial_deployer", "high", creator_launches, f"Creator has {creator_launches} stored launches")
        elif creator_launches >= 15:
            add(16, "serial_deployer", "medium", creator_launches, f"Creator has {creator_launches} stored launches")
    if creator_runner_rate is not None and creator_launches and creator_launches >= 5:
        if creator_runner_rate < 0.08:
            add(14, "poor_creator_outcomes", "medium", round(creator_runner_rate, 3), "Low historical runner rate for creator")

    top4 = activity.top4_wallet_volume_share
    if top4 is not None and top4 >= 0.8:
        add(18, "holder_concentration", "high", round(top4, 4), "High early-book concentration")
    elif top4 is None:
        missing.append("holder_concentration")

    if synthetic is not None and synthetic.score is not None:
        if synthetic.level == "CRITICAL":
            add(24, "synthetic_overlap", "critical", synthetic.score, "Synthetic activity already CRITICAL")
        elif synthetic.level == "HIGH":
            add(12, "synthetic_overlap", "high", synthetic.score, "Synthetic activity HIGH")
    else:
        missing.append("synthetic")

    if used == 0:
        return RiskResult(score=None, level="UNKNOWN", evidence=ev, missing=missing)
    return RiskResult(score=round(min(100.0, score), 1), level=_level(min(100.0, score)), evidence=ev, missing=missing)
