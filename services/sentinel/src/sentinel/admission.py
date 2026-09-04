"""Canonical admission decisions for Stinky OS.

All live paths (migration volume watch, high-volume discovery, and any
service that can import sentinel) MUST use evaluate_pump_quality() and
fetch_fees_for_admission() instead of re-implementing fee/dex/mint gates.

Policy (free-tier default):
  - mint ends with pump (when required)
  - pump-family dex only
  - volume floors applied by callers (50k runners / 100k trending)
  - Birdeye global fees OPTIONAL (require_global_fees=False): never block on 400/unknown
  - set STINKY_REQUIRE_GLOBAL_FEES=true to restore strict fee fail-closed

Fee fetch is vol-gated and cached so free/paid Birdeye CU is not wasted
on sub-threshold noise.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from sentinel.config import settings
from sentinel.qualify import MIN_GLOBAL_FEES_PAID_SOL, qualify_fresh_pump_migration

logger = structlog.get_logger(__name__)

# In-process cache: mint -> (fees_or_None, monotonic_expiry, status)
# status: "ok" | "unknown" | "denied"
_FEE_CACHE: dict[str, tuple[float | None, float, str]] = {}
_FEE_CACHE_TTL_OK = 900.0       # 15m when we have a number
_FEE_CACHE_TTL_UNKNOWN = 120.0  # 2m retry when 400/empty
_FEE_CACHE_TTL_DENIED = 600.0   # 10m on 401/403


@dataclass(frozen=True)
class AdmissionDecision:
    accepted: bool
    reason: str
    fees_sol: float | None
    fees_verified: bool
    min_fees_sol: float


def min_fees_floor() -> float:
    return float(getattr(settings, "min_fees_sol", MIN_GLOBAL_FEES_PAID_SOL) or MIN_GLOBAL_FEES_PAID_SOL)


def volume_floor_usd() -> float:
    return float(getattr(settings, "volume_threshold_usd", 50_000.0) or 50_000.0)


def _allowed_dexes() -> set[str]:
    raw = getattr(settings, "allowed_dex_ids", "pumpswap,pumpfun,pump") or ""
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _denied_dexes() -> set[str]:
    raw = getattr(settings, "denied_dex_ids", "meteora,raydium,orca") or ""
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def evaluate_pump_quality(
    *,
    mint: str,
    dex_id: str | None,
    fees_sol: float | None,
    min_fees_sol: float | None = None,
) -> AdmissionDecision:
    """Single structural quality decision (mint + dex + fees). Fail-closed."""
    required = float(min_fees_sol) if min_fees_sol is not None else min_fees_floor()
    fees_verified = (
        fees_sol is not None
        and fees_sol == fees_sol
        and fees_sol >= 0
    )
    require_fees = bool(getattr(settings, "require_global_fees", False))
    result = qualify_fresh_pump_migration(
        mint=mint,
        dex_id=dex_id,
        global_fees_paid_sol=fees_sol,
        global_fees_verified=True if fees_verified else None,
        min_fees_sol=required,
        require_pump_mint_suffix=bool(
            getattr(settings, "require_pump_mint_suffix", True)
        ),
        allowed_dex_ids=_allowed_dexes(),
        denied_dex_ids=_denied_dexes(),
        require_global_fees=require_fees,
    )
    reason = result.reason
    if reason == "LOW_GLOBAL_FEES" and result.global_fees_paid_sol is not None:
        reason = f"LOW_GLOBAL_FEES:{result.global_fees_paid_sol:.4f}<{result.required}"
    return AdmissionDecision(
        accepted=bool(result.accepted),
        reason=reason if not result.accepted else "ok",
        fees_sol=result.global_fees_paid_sol if result.accepted else fees_sol,
        fees_verified=fees_verified,
        min_fees_sol=required,
    )


def evaluate_alert_payload(payload: dict[str, Any]) -> AdmissionDecision:
    """Discord / consumer-side re-check of ALERT_CANDIDATE payload. Fail-closed."""
    mint = str(payload.get("mint") or "")
    dex_id = payload.get("dex_id")
    fees_raw = payload.get("fees_sol")
    if fees_raw is None:
        fees_raw = payload.get("global_fees_paid_sol")
        if fees_raw is None:
            fees_raw = payload.get("total_fees_sol")
    fees: float | None
    try:
        fees = float(fees_raw) if fees_raw is not None else None
        if fees is not None and (fees != fees or fees < 0):
            fees = None
    except (TypeError, ValueError):
        fees = None
    if payload.get("global_fees_verified") is False and bool(
        getattr(settings, "require_global_fees", False)
    ):
        return AdmissionDecision(
            accepted=False,
            reason="GLOBAL_FEES_UNVERIFIED",
            fees_sol=fees,
            fees_verified=False,
            min_fees_sol=min_fees_floor(),
        )
    return evaluate_pump_quality(mint=mint, dex_id=dex_id, fees_sol=fees)


def _cache_get(mint: str) -> tuple[bool, float | None]:
    row = _FEE_CACHE.get(mint)
    if not row:
        return False, None
    fees, exp, _status = row
    if time.monotonic() > exp:
        _FEE_CACHE.pop(mint, None)
        return False, None
    return True, fees


def _cache_set(mint: str, fees: float | None, status: str) -> None:
    if status == "ok":
        ttl = _FEE_CACHE_TTL_OK
    elif status == "denied":
        ttl = _FEE_CACHE_TTL_DENIED
    else:
        ttl = _FEE_CACHE_TTL_UNKNOWN
    _FEE_CACHE[mint] = (fees, time.monotonic() + ttl, status)


async def fetch_fees_for_admission(
    client: httpx.AsyncClient,
    mint: str,
    *,
    volume_m5_usd: float | None = None,
    force: bool = False,
) -> float | None:
    """Birdeye global fees with cache + optional volume pre-gate.

    If volume_m5_usd is provided and below the runner floor, skip the network
    call and return None (caller still fail-closes). Force bypasses the vol gate
    for explicit retries.
    """
    hit, cached = _cache_get(mint)
    if hit:
        return cached

    floor = volume_floor_usd()
    if (
        not force
        and volume_m5_usd is not None
        and volume_m5_usd + 1e-9 < floor
    ):
        logger.debug(
            "fees.skip_below_volume_floor",
            mint=mint,
            volume_m5_usd=round(float(volume_m5_usd), 2),
            floor=floor,
        )
        return None

    # Local import avoids circular import at module load
    from sentinel.volume import fetch_pump_fees_sol

    fees = await fetch_pump_fees_sol(client, mint)
    if fees is not None:
        _cache_set(mint, fees, "ok")
    else:
        _cache_set(mint, None, "unknown")
    return fees
