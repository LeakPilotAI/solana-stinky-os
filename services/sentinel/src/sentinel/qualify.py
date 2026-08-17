"""Canonical hard qualification for the fresh Pump migration universe.

A market enters the *migration observation* universe ONLY if:
  - pump mint suffix (when required)
  - allowed DEX (pump family)
  - global fees known + verified
  - global_fees_paid_sol >= MIN_GLOBAL_FEES_PAID_SOL (default 5.0 — hard ops floor)

Fail-closed. Unknown / unverified / low fees → REJECT.
Score, volume, smart money, liquidity MUST NOT override this gate.

For full opportunity admission (liquidity + volume + mcap + social + protocol),
use sentinel.filter_engine.StinkyFilterEngine / evaluate_admission().
This module remains the thin, early gate used at ALERT_CANDIDATE emit time
when only fees + dex are known.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Authoritative constant — keep in sync with STINKY_MIN_FEES_SOL / FilterConfig
# Hard ops floor. Override via STINKY_MIN_FEES_SOL.
MIN_GLOBAL_FEES_PAID_SOL = 5.0


@dataclass(frozen=True)
class QualifyResult:
    accepted: bool
    reason: str
    global_fees_paid_sol: float | None = None
    required: float = MIN_GLOBAL_FEES_PAID_SOL


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
    """Single authoritative *early* qualification function (fees + pump dex).

    Downstream systems (alerts, Discord, opportunity, dashboard qualified lists)
    MUST respect this result. Do not re-implement parallel gates.

    CRITICAL: If global_fees_paid_sol is unavailable or cannot be authoritatively
    verified, REJECT. Never treat missing fee data as passing.
    """
    required = float(min_fees_sol) if min_fees_sol is not None else MIN_GLOBAL_FEES_PAID_SOL
    mint_s = (mint or "").strip()
    if not mint_s:
        return QualifyResult(False, "INVALID_MIGRATION", required=required)

    if require_pump_mint_suffix and not mint_s.lower().endswith("pump"):
        return QualifyResult(False, "NOT_PUMP_MINT", required=required)

    denied = denied_dex_ids or {
        "meteora",
        "raydium",
        "orca",
        "phoenix",
        "lifinity",
        "saber",
        "aldrin",
        "fluxbeam",
        "pumpamm",
    }
    allowed = allowed_dex_ids or {"pumpswap", "pumpfun", "pump"}
    dex = (dex_id or "").strip().lower()
    if dex:
        if dex in denied or any(d in dex for d in denied):
            return QualifyResult(False, f"DEX_BLOCKED:{dex}", required=required)
        if allowed and not (dex in allowed or any(a in dex for a in allowed)):
            return QualifyResult(False, f"DEX_NOT_ALLOWED:{dex}", required=required)

    # Fail closed on verification
    if global_fees_verified is False:
        return QualifyResult(
            False, "GLOBAL_FEES_UNVERIFIED", global_fees_paid_sol=None, required=required
        )

    fees = _safe_float(global_fees_paid_sol)
    if fees is None:
        return QualifyResult(False, "GLOBAL_FEES_UNKNOWN", required=required)

    # Require explicit verified=True when a number is present
    if global_fees_verified is not True:
        return QualifyResult(
            False,
            "GLOBAL_FEES_UNVERIFIED",
            global_fees_paid_sol=fees,
            required=required,
        )

    # Strict floor with float epsilon
    if fees + 1e-9 < required:
        return QualifyResult(
            False,
            "LOW_GLOBAL_FEES",
            global_fees_paid_sol=fees,
            required=required,
        )

    return QualifyResult(
        True,
        "ok",
        global_fees_paid_sol=fees,
        required=required,
    )
