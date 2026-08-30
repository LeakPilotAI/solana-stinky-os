"""Structural book fingerprints. Deterministic. Not a predictor until sample exists.

A fingerprint is a bucketed decision-time key plus a feature dict.
Exact key match is resemblance. Missing inputs stay U. Never guessed.
"""

from __future__ import annotations

from typing import Any, Mapping

FINGERPRINT_VERSION = "fingerprint-v1.1.0-book"


def _band_concentration(top4: float | None) -> str:
    if top4 is None:
        return "CU"
    if top4 >= 0.85:
        return "Ccrit"
    if top4 >= 0.70:
        return "Chigh"
    if top4 >= 0.55:
        return "Cmed"
    return "Clow"


def _band_diversity(uniq: int | None, vol: float | None) -> str:
    if uniq is None or vol is None:
        return "DU"
    if vol >= 150_000 and uniq < 6:
        return "Dcrit"
    if vol >= 150_000 and uniq < 12:
        return "Dlow"
    return "Dok"


def _band_smart(smart: int | None) -> str:
    if smart is None:
        return "SU"
    if smart >= 3:
        return "S3"
    if smart >= 1:
        return "S1"
    return "S0"


def _band_serial(launches: int | None) -> str:
    if launches is None:
        return "XU"
    if launches >= 40:
        return "Xhigh"
    if launches >= 15:
        return "Xmed"
    if launches >= 3:
        return "Xlow"
    return "X0"


def _band_liquidity(liq: float | None) -> str:
    if liq is None:
        return "LU"
    if liq < 5_000:
        return "Lthin"
    if liq < 40_000:
        return "Lok"
    return "Lsolid"


def _band_ratio(vol: float | None, liq: float | None) -> str:
    if vol is None or liq is None or liq <= 0:
        return "RU"
    r = vol / liq
    if r >= 20:
        return "Rhot"
    if r >= 5:
        return "Relev"
    return "Rok"


def _band_imbalance(imb: float | None) -> str:
    if imb is None:
        return "BU"
    if imb >= 0.92 or imb <= 0.08:
        return "Bskew"
    return "Bbal"


def _band_entity(links: int | None) -> str:
    if links is None:
        return "EU"
    if links >= 2:
        return "E2"
    if links >= 1:
        return "E1"
    return "E0"


def _band_synthetic(level: str | None) -> str:
    if not level or level == "UNKNOWN":
        return "YU"
    lv = str(level).upper()
    if lv in ("CRITICAL", "HIGH"):
        return "Yhigh"
    if lv == "MEDIUM":
        return "Ymed"
    if lv == "LOW":
        return "Ylow"
    return "YU"


def _band_rep(repeated_size_share: float | None) -> str:
    if repeated_size_share is None:
        return "PU"
    if repeated_size_share >= 0.55:
        return "Phigh"
    if repeated_size_share >= 0.35:
        return "Pmed"
    return "Plow"


def book_fingerprint(
    *,
    top4_wallet_volume_share: float | None = None,
    unique_wallets: int | None = None,
    volume_m5_usd: float | None = None,
    smart_wallet_count: int | None = None,
    creator_launches: int | None = None,
    repeated_size_share: float | None = None,
    liquidity_usd: float | None = None,
    buy_sell_imbalance: float | None = None,
    entity_link_count: int | None = None,
    synthetic_level: str | None = None,
) -> str:
    """Bucketed structural key. Same book → same key. Missing stays U, never guessed."""
    return "|".join(
        (
            _band_concentration(top4_wallet_volume_share),
            _band_diversity(unique_wallets, volume_m5_usd),
            _band_smart(smart_wallet_count),
            _band_serial(creator_launches),
            _band_rep(repeated_size_share),
            _band_liquidity(liquidity_usd),
            _band_ratio(volume_m5_usd, liquidity_usd),
            _band_imbalance(buy_sell_imbalance),
            _band_entity(entity_link_count),
            _band_synthetic(synthetic_level),
        )
    )


def fingerprint_features(
    *,
    top4_wallet_volume_share: float | None = None,
    unique_wallets: int | None = None,
    volume_m5_usd: float | None = None,
    smart_wallet_count: int | None = None,
    creator_launches: int | None = None,
    repeated_size_share: float | None = None,
    liquidity_usd: float | None = None,
    market_cap_usd: float | None = None,
    buy_sell_imbalance: float | None = None,
    entity_link_count: int | None = None,
    synthetic_level: str | None = None,
    meaningful_buyer_count: int | None = None,
) -> dict[str, Any]:
    """Decision-time feature dict stored with the key. None stays None."""
    ratio = None
    if volume_m5_usd is not None and liquidity_usd is not None and liquidity_usd > 0:
        ratio = volume_m5_usd / liquidity_usd
    return {
        "version": FINGERPRINT_VERSION,
        "market": {
            "volume_m5_usd": volume_m5_usd,
            "liquidity_usd": liquidity_usd,
            "market_cap_usd": market_cap_usd,
            "volume_liquidity_ratio": ratio,
            "buy_sell_imbalance": buy_sell_imbalance,
            "unique_wallets": unique_wallets,
        },
        "wallet": {
            "meaningful_buyer_count": meaningful_buyer_count,
            "known_edge_wallet_count": smart_wallet_count,
            "top4_wallet_volume_share": top4_wallet_volume_share,
        },
        "creator": {"launches": creator_launches},
        "entity": {"link_count": entity_link_count},
        "synthetic": {
            "level": synthetic_level,
            "repeated_size_share": repeated_size_share,
        },
        "key": book_fingerprint(
            top4_wallet_volume_share=top4_wallet_volume_share,
            unique_wallets=unique_wallets,
            volume_m5_usd=volume_m5_usd,
            smart_wallet_count=smart_wallet_count,
            creator_launches=creator_launches,
            repeated_size_share=repeated_size_share,
            liquidity_usd=liquidity_usd,
            buy_sell_imbalance=buy_sell_imbalance,
            entity_link_count=entity_link_count,
            synthetic_level=synthetic_level,
        ),
    }


def fingerprint_from_maps(
    activity: Mapping[str, Any] | None,
    wallets: Mapping[str, Any] | None,
    creator: Mapping[str, Any] | None,
) -> str:
    a = activity or {}
    w = wallets or {}
    c = creator or {}
    return book_fingerprint(
        top4_wallet_volume_share=a.get("top4_wallet_volume_share"),
        unique_wallets=a.get("unique_wallets"),
        volume_m5_usd=a.get("volume_m5_usd") if a.get("volume_m5_usd") is not None else a.get("volume_usd"),
        smart_wallet_count=w.get("smart_wallet_count"),
        creator_launches=c.get("launches") if c.get("launches") is not None else c.get("launch_count"),
        repeated_size_share=a.get("repeated_size_share"),
        liquidity_usd=a.get("liquidity_usd"),
        buy_sell_imbalance=a.get("buy_sell_imbalance"),
        entity_link_count=w.get("entity_link_count"),
        synthetic_level=a.get("synthetic_level"),
    )
