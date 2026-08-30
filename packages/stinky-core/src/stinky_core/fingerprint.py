"""Structural book fingerprints. Deterministic. Not a predictor until sample exists."""

from __future__ import annotations

from typing import Any, Mapping


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


def book_fingerprint(
    *,
    top4_wallet_volume_share: float | None = None,
    unique_wallets: int | None = None,
    volume_m5_usd: float | None = None,
    smart_wallet_count: int | None = None,
    creator_launches: int | None = None,
    repeated_size_share: float | None = None,
) -> str:
    """Bucketed structural key. Same book → same key. Missing stays U, never guessed."""
    rep = "RU"
    if repeated_size_share is not None:
        rep = "Rhigh" if repeated_size_share >= 0.55 else "Rlow"
    return "|".join(
        (
            _band_concentration(top4_wallet_volume_share),
            _band_diversity(unique_wallets, volume_m5_usd),
            _band_smart(smart_wallet_count),
            _band_serial(creator_launches),
            rep,
        )
    )


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
    )
