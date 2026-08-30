"""Gate 1 wrapper: mint + protocol + 5m volume. Fees are not required."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel.filter_engine import (
    EARLY_GATE_CONFIG,
    GATE1_VOLUME_5M_USD,
    FilterConfig,
    ReasonCode,
    evaluate_market,
)

MIN_GLOBAL_FEES_PAID_SOL = 1.0  # optional evidence floor, not a gate


@dataclass(frozen=True)
class QualifyResult:
    accepted: bool
    reason: str
    global_fees_paid_sol: float | None = None
    volume_m5_usd: float | None = None
    required: float = GATE1_VOLUME_5M_USD


def qualify_fresh_pump_migration(
    *,
    mint: str | None,
    dex_id: str | None = None,
    volume_m5_usd: float | None = None,
    global_fees_paid_sol: float | None = None,
    global_fees_verified: bool | None = None,
    min_fees_sol: float = MIN_GLOBAL_FEES_PAID_SOL,
    min_volume_usd: float | None = None,
    require_pump_mint_suffix: bool = True,
    allowed_dex_ids: set[str] | None = None,
    denied_dex_ids: set[str] | None = None,
) -> QualifyResult:
    """Gate 1: mint + DEX + 5m volume. Unknown fees do not reject."""
    required = float(min_volume_usd if min_volume_usd is not None else GATE1_VOLUME_5M_USD)
    mint_s = (mint or "").strip()
    if not mint_s:
        return QualifyResult(False, ReasonCode.INVALID_MINT, required=required)

    if require_pump_mint_suffix and not mint_s.lower().endswith("pump"):
        return QualifyResult(False, ReasonCode.INVALID_MARKET_DATA, required=required)

    cfg = FilterConfig(
        min_volume_usd=required,
        require_fees=False,
        require_liquidity=False,
        require_market_cap=False,
        require_at_least_one_social=False,
        require_migrated=False,
        record_stats=EARLY_GATE_CONFIG.record_stats,
    )
    if allowed_dex_ids:
        cfg.allowed_protocols = frozenset(
            a.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
            for a in allowed_dex_ids
        )
        cfg.reject_unknown_protocol = True
    if denied_dex_ids:
        cfg.denied_protocols = frozenset(
            a.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
            for a in denied_dex_ids
        ) | cfg.denied_protocols

    decision = evaluate_market(
        {
            "mint": mint_s,
            "protocol": dex_id,
            "dex_id": dex_id,
            "volume_usd": volume_m5_usd,
            "global_fees_sol": global_fees_paid_sol,
            "global_fees_verified": global_fees_verified,
            "migrated": True,
        },
        config=cfg,
    )
    reason = "ok" if decision.eligible else (decision.rejection_reason or ReasonCode.NOT_ELIGIBLE)
    fees = decision.normalized_metrics.get("global_fees_sol")
    vol = decision.normalized_metrics.get("volume_usd")
    try:
        fees_f = float(fees) if fees is not None else None
    except (TypeError, ValueError):
        fees_f = None
    try:
        vol_f = float(vol) if vol is not None else None
    except (TypeError, ValueError):
        vol_f = None
    return QualifyResult(
        accepted=decision.eligible,
        reason=reason,
        global_fees_paid_sol=fees_f,
        volume_m5_usd=vol_f,
        required=required,
    )
