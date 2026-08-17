"""Success Learning — label tokens and attribute early-buyer edge.

Pure / deterministic. Replays from market_snapshots + migration_buyers.
Does not invent narratives (ADR-005).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence


# Thresholds (USD) — measured market_snapshots only
MEGA_MCAP = 1_000_000.0
RUNNER_MCAP = 500_000.0
MEGA_VOL_M5 = 250_000.0
RUNNER_VOL_M5 = 100_000.0
MID_VOL_M5 = 50_000.0
MIN_SNAPSHOTS = 2


@dataclass(frozen=True, slots=True)
class TokenOutcome:
    mint: str
    label: str
    peak_volume_m5_usd: float | None
    peak_liquidity_usd: float | None
    peak_market_cap_usd: float | None
    peak_price_usd: float | None
    snapshots_n: int
    migration_at: datetime | None
    hours_observed: float | None
    notes: str


@dataclass(frozen=True, slots=True)
class WalletEarlySuccess:
    wallet: str
    early_entries: int
    early_on_mega: int
    early_on_runner: int
    early_on_mid: int
    early_on_fade: int
    early_on_unknown: int
    success_rate: float | None
    sample_size: int
    last_success_at: datetime | None
    last_fade_at: datetime | None


def label_token_from_peaks(
    *,
    mint: str,
    peak_volume_m5: float | None,
    peak_liquidity: float | None,
    peak_mcap: float | None,
    peak_price: float | None,
    snapshots_n: int,
    migration_at: datetime | None = None,
    evaluated_at: datetime | None = None,
) -> TokenOutcome:
    """Assign outcome label from measured peaks only."""
    vol = float(peak_volume_m5) if peak_volume_m5 is not None else None
    mcap = float(peak_mcap) if peak_mcap is not None else None
    liq = float(peak_liquidity) if peak_liquidity is not None else None
    price = float(peak_price) if peak_price is not None else None

    hours = None
    if migration_at is not None:
        end = evaluated_at or datetime.now(timezone.utc)
        if migration_at.tzinfo is None:
            migration_at = migration_at.replace(tzinfo=timezone.utc)
        hours = max(0.0, (end - migration_at).total_seconds() / 3600.0)

    if snapshots_n < MIN_SNAPSHOTS and (vol is None or vol <= 0) and mcap is None:
        return TokenOutcome(
            mint=mint,
            label="unknown",
            peak_volume_m5_usd=vol,
            peak_liquidity_usd=liq,
            peak_market_cap_usd=mcap,
            peak_price_usd=price,
            snapshots_n=snapshots_n,
            migration_at=migration_at,
            hours_observed=hours,
            notes="insufficient snapshots",
        )

    if (mcap is not None and mcap >= MEGA_MCAP) or (vol is not None and vol >= MEGA_VOL_M5):
        label = "mega_runner"
        notes = f"mcap={mcap} vol_m5={vol}"
    elif (mcap is not None and mcap >= RUNNER_MCAP) or (vol is not None and vol >= RUNNER_VOL_M5):
        label = "runner"
        notes = f"mcap={mcap} vol_m5={vol}"
    elif vol is not None and vol >= MID_VOL_M5:
        label = "mid"
        notes = f"vol_m5={vol}"
    elif snapshots_n >= MIN_SNAPSHOTS:
        label = "fade"
        notes = f"peak stayed thin vol_m5={vol} mcap={mcap}"
    else:
        label = "unknown"
        notes = "thin data"

    return TokenOutcome(
        mint=mint,
        label=label,
        peak_volume_m5_usd=vol,
        peak_liquidity_usd=liq,
        peak_market_cap_usd=mcap,
        peak_price_usd=price,
        snapshots_n=snapshots_n,
        migration_at=migration_at,
        hours_observed=hours,
        notes=notes,
    )


def aggregate_wallet_early_success(
    rows: Sequence[dict[str, Any]],
) -> list[WalletEarlySuccess]:
    """rows: {wallet, label, bought_at} for early buyers joined to token_outcomes."""
    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        w = r.get("wallet")
        if not w:
            continue
        b = buckets.setdefault(
            w,
            {
                "early_entries": 0,
                "mega": 0,
                "runner": 0,
                "mid": 0,
                "fade": 0,
                "unknown": 0,
                "last_success": None,
                "last_fade": None,
            },
        )
        lab = (r.get("label") or "unknown").lower()
        b["early_entries"] += 1
        if lab == "mega_runner":
            b["mega"] += 1
            b["last_success"] = r.get("bought_at") or b["last_success"]
        elif lab == "runner":
            b["runner"] += 1
            b["last_success"] = r.get("bought_at") or b["last_success"]
        elif lab == "mid":
            b["mid"] += 1
        elif lab == "fade":
            b["fade"] += 1
            b["last_fade"] = r.get("bought_at") or b["last_fade"]
        else:
            b["unknown"] += 1

    out: list[WalletEarlySuccess] = []
    for w, b in buckets.items():
        decided = b["mega"] + b["runner"] + b["mid"] + b["fade"]
        rate = None
        if decided > 0:
            rate = (b["mega"] + b["runner"]) / decided
        out.append(
            WalletEarlySuccess(
                wallet=w,
                early_entries=b["early_entries"],
                early_on_mega=b["mega"],
                early_on_runner=b["runner"],
                early_on_mid=b["mid"],
                early_on_fade=b["fade"],
                early_on_unknown=b["unknown"],
                success_rate=rate,
                sample_size=decided,
                last_success_at=b["last_success"],
                last_fade_at=b["last_fade"],
            )
        )
    return out
