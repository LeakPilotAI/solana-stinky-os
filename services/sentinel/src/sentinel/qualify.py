"""Early qualification for the fresh Pump migration universe.

Thin wrapper around the canonical StinkyFilterEngine (early-gate config).
Do not reimplement fee / protocol logic here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel.filter_engine import (
    DEFAULT_MIN_GLOBAL_FEES_SOL,
    EARLY_GATE_CONFIG,
    FilterConfig,
    ReasonCode,
    evaluate_market,
)

MIN_GLOBAL_FEES_PAID_SOL = DEFAULT_MIN_GLOBAL_FEES_SOL


@dataclass(frozen=True)
class QualifyResult:
    accepted: bool
    reason: str
    global_fees_paid_sol: float | None = None
    required: float = MIN_GLOBAL_FEES_PAID_SOL


def qualify_fresh_pump_migration(
    *,
    mint: str | None,
    dex_id: str | None = None,
    global_fees_paid_sol: float | None = None,
    global_fees_verified: bool | None = None,
    min_fees_sol: float = MIN_GLOBAL_FEES_PAID_SOL,
    require_pump_mint_suffix: bool = True,
    allowed_dex_ids: set[str] | None = None,
    denied_dex_ids: set[str] | None = None,
) -> QualifyResult:
    """Early gate: mint + DEX + verified global fees. Fail closed.

    Downstream systems MUST respect this result. Intelligence cannot override it.
    """
    required = float(min_fees_sol) if min_fees_sol is not None else MIN_GLOBAL_FEES_PAID_SOL
    mint_s = (mint or "").strip()
    if not mint_s:
        return QualifyResult(False, ReasonCode.INVALID_MINT, required=required)

    if require_pump_mint_suffix and not mint_s.lower().endswith("pump"):
        return QualifyResult(False, ReasonCode.INVALID_MARKET_DATA, required=required)

    cfg = FilterConfig(
        min_global_fees_sol=required,
        require_liquidity=False,
        require_volume=False,
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
            "global_fees_sol": global_fees_paid_sol,
            "global_fees_verified": global_fees_verified,
            "migrated": True,
        },
        config=cfg,
    )
    reason = "ok" if decision.eligible else (decision.rejection_reason or ReasonCode.NOT_ELIGIBLE)
    fees = decision.normalized_metrics.get("global_fees_sol")
    try:
        fees_f = float(fees) if fees is not None else None
    except (TypeError, ValueError):
        fees_f = None
    return QualifyResult(
        accepted=decision.eligible,
        reason=reason,
        global_fees_paid_sol=fees_f,
        required=required,
    )
