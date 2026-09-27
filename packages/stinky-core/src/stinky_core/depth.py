"""Read-only executable-depth evidence from Jupiter quotes.

A quote is evidence, not an order and not proof of execution. This module only GETs
quotes; it never builds, signs, submits, or simulates transactions. Missing,
malformed, mismatched, or non-finite fields fail closed to UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any

import httpx

WSOL_MINT = "So11111111111111111111111111111111111111112"
JUPITER_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
SOURCE = "jupiter-swap-v1-keyless"
# Observation-quality bound only. This is not a trading threshold.
MAX_DEPTH_AGE_SEC = 120.0



@dataclass(frozen=True)
class DepthQuoteObservation:
    mint: str
    observed_at: datetime
    input_lamports: int
    out_amount_atomic: int | None
    price_impact_pct: float | None
    route_found: bool
    status: str
    source: str = SOURCE
    error: str | None = None
    quote_context_slot: int | None = None
    quote_time_taken_sec: float | None = None
    expected_pair_address: str | None = None
    expected_dex_id: str | None = None
    route_amm_keys: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return (
            self.status == "VERIFIED"
            and self.route_found
            and self.out_amount_atomic is not None
            and self.out_amount_atomic > 0
            and self.price_impact_pct is not None
        )


def depth_observation_is_fresh(
    obs: DepthQuoteObservation,
    *,
    as_of: datetime,
    max_age_sec: float = MAX_DEPTH_AGE_SEC,
) -> bool:
    """True only for VERIFIED evidence whose local receipt time is recent.

    Restart/hydration never refreshes observed_at. Future-dated, naive, invalid,
    UNKNOWN, or over-age evidence fails closed.
    """
    if not isinstance(obs, DepthQuoteObservation) or not obs.usable:
        return False
    if obs.observed_at.tzinfo is None or as_of.tzinfo is None:
        return False
    try:
        age = (as_of.astimezone(timezone.utc) - obs.observed_at.astimezone(timezone.utc)).total_seconds()
        bound = float(max_age_sec)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(age) and math.isfinite(bound) and bound >= 0 and 0 <= age <= bound


def depth_observation_matches_order(
    obs: DepthQuoteObservation, *, mint: str, input_lamports: int
) -> bool:
    """Prevent a quote for one mint/order size from satisfying another."""
    return (
        isinstance(obs, DepthQuoteObservation)
        and obs.usable
        and bool(mint)
        and obs.mint == mint
        and input_lamports > 0
        and obs.input_lamports == input_lamports
    )


def latest_depth_observation(
    observations: list[DepthQuoteObservation],
    *,
    mint: str,
    input_lamports: int,
    as_of: datetime,
) -> DepthQuoteObservation | None:
    """Return the latest applicable evidence, including negative/UNKNOWN evidence.

    Critically, this selects by identity/time before judging usability. A newer
    NO_ROUTE/provider failure therefore masks an older good quote rather than
    allowing stale-good fallback. Future-dated observations are ignored.
    """
    if not mint or input_lamports <= 0 or as_of.tzinfo is None:
        return None
    candidates: list[DepthQuoteObservation] = []
    for obs in observations:
        if not isinstance(obs, DepthQuoteObservation):
            continue
        if obs.mint != mint or obs.input_lamports != input_lamports:
            continue
        if obs.observed_at.tzinfo is None:
            continue
        try:
            if obs.observed_at.astimezone(timezone.utc) <= as_of.astimezone(timezone.utc):
                candidates.append(obs)
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda obs: obs.observed_at.astimezone(timezone.utc))


def latest_usable_depth_observation(
    observations: list[DepthQuoteObservation],
    *,
    mint: str,
    input_lamports: int,
    as_of: datetime,
    max_age_sec: float = MAX_DEPTH_AGE_SEC,
) -> DepthQuoteObservation | None:
    """Usable only when the *latest* applicable evidence is itself fresh/verified."""
    latest = latest_depth_observation(
        observations, mint=mint, input_lamports=input_lamports, as_of=as_of
    )
    if latest is None:
        return None
    if not depth_observation_matches_order(latest, mint=mint, input_lamports=input_lamports):
        return None
    if not depth_observation_is_fresh(latest, as_of=as_of, max_age_sec=max_age_sec):
        return None
    return latest


def parse_quote(mint: str, input_lamports: int, payload: Any, *, observed_at: datetime | None = None, expected_pair_address: str | None = None, expected_dex_id: str | None = None) -> DepthQuoteObservation:
    at = observed_at or datetime.now(timezone.utc)
    unknown = lambda err: DepthQuoteObservation(mint, at, input_lamports, None, None, False, "UNKNOWN", error=err)
    if not mint or input_lamports <= 0 or not isinstance(payload, dict):
        return unknown("INVALID_INPUT")
    if payload.get("inputMint") != WSOL_MINT or payload.get("outputMint") != mint:
        return unknown("QUOTE_IDENTITY_MISMATCH")
    try:
        quoted_in = int(payload.get("inAmount"))
        out = int(payload.get("outAmount"))
        impact = float(payload.get("priceImpactPct"))
    except (TypeError, ValueError):
        return unknown("MALFORMED_QUOTE")
    if quoted_in != input_lamports or out <= 0 or not math.isfinite(impact) or impact < 0:
        return unknown("MALFORMED_QUOTE")
    route = payload.get("routePlan")
    if not isinstance(route, list) or not route:
        return unknown("NO_ROUTE")
    try:
        context_slot = int(payload["contextSlot"])
        time_taken = float(payload["timeTaken"])
    except (KeyError, TypeError, ValueError):
        return unknown("MISSING_QUOTE_PROVENANCE")
    if context_slot <= 0 or not math.isfinite(time_taken) or time_taken < 0:
        return unknown("MALFORMED_QUOTE_PROVENANCE")
    route_amm_keys = tuple(
        str(step.get("swapInfo", {}).get("ammKey") or "").strip()
        for step in route if isinstance(step, dict)
    )
    route_amm_keys = tuple(key for key in route_amm_keys if key)
    # Route AMM identity is required only when binding a quote to a canonical
    # watched market. Generic quote parsing remains backwards-compatible.
    if expected_pair_address and not route_amm_keys:
        return DepthQuoteObservation(
            mint, at, input_lamports, None, None, False, "UNKNOWN",
            error="MISSING_ROUTE_PROVENANCE", quote_context_slot=context_slot,
            quote_time_taken_sec=time_taken, expected_pair_address=expected_pair_address,
            expected_dex_id=expected_dex_id,
        )
    if expected_pair_address and expected_pair_address not in route_amm_keys:
        return DepthQuoteObservation(
            mint, at, input_lamports, None, None, False, "UNKNOWN",
            error="EXPECTED_PAIR_NOT_IN_ROUTE", quote_context_slot=context_slot,
            quote_time_taken_sec=time_taken, expected_pair_address=expected_pair_address,
            expected_dex_id=expected_dex_id, route_amm_keys=route_amm_keys,
        )
    return DepthQuoteObservation(
        mint, at, input_lamports, out, impact, True, "VERIFIED",
        quote_context_slot=context_slot, quote_time_taken_sec=time_taken,
        expected_pair_address=expected_pair_address, expected_dex_id=expected_dex_id,
        route_amm_keys=route_amm_keys,
    )


class JupiterDepthClient:
    """Observation-only GET client. No transaction-building endpoint exists here."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=12.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def quote_buy(self, mint: str, input_lamports: int, *, expected_pair_address: str | None = None, expected_dex_id: str | None = None) -> DepthQuoteObservation:
        at = datetime.now(timezone.utc)
        if not mint or input_lamports <= 0:
            return parse_quote(mint, input_lamports, None, observed_at=at)
        try:
            response = await self._client.get(
                JUPITER_QUOTE_URL,
                params={
                    "inputMint": WSOL_MINT,
                    "outputMint": mint,
                    "amount": str(input_lamports),
                    "slippageBps": "50",
                    "swapMode": "ExactIn",
                },
            )
            if response.status_code != 200:
                return DepthQuoteObservation(
                    mint, at, input_lamports, None, None, False, "UNKNOWN",
                    error=f"HTTP_{response.status_code}",
                )
            return parse_quote(mint, input_lamports, response.json(), observed_at=at, expected_pair_address=expected_pair_address, expected_dex_id=expected_dex_id)
        except Exception as exc:
            return DepthQuoteObservation(
                mint, at, input_lamports, None, None, False, "UNKNOWN",
                error=type(exc).__name__,
            )


DEPTH_OBSERVATIONS_DDL = """
CREATE TABLE IF NOT EXISTS depth_quote_observations (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    input_lamports BIGINT NOT NULL,
    out_amount_atomic NUMERIC,
    price_impact_pct DOUBLE PRECISION,
    route_found BOOLEAN NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    error TEXT,
    quote_context_slot BIGINT,
    quote_time_taken_sec DOUBLE PRECISION,
    expected_pair_address TEXT,
    expected_dex_id TEXT,
    route_amm_keys TEXT
);
"""
DEPTH_OBSERVATIONS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_depth_quote_mint_time ON depth_quote_observations (mint, observed_at DESC)",
)
DEPTH_OBSERVATIONS_INSERT = """
INSERT INTO depth_quote_observations (
    mint, observed_at, input_lamports, out_amount_atomic, price_impact_pct,
    route_found, status, source, error, quote_context_slot, quote_time_taken_sec,
    expected_pair_address, expected_dex_id, route_amm_keys
) VALUES (
    :mint, :observed_at, :input_lamports, :out_amount_atomic, :price_impact_pct,
    :route_found, :status, :source, :error, :quote_context_slot, :quote_time_taken_sec,
    :expected_pair_address, :expected_dex_id, :route_amm_keys
)
"""


def depth_persist_params(obs: DepthQuoteObservation) -> dict[str, Any]:
    """Append-only SQL parameters; UNKNOWN observations are evidence too."""
    return {
        "mint": obs.mint,
        "observed_at": obs.observed_at,
        "input_lamports": obs.input_lamports,
        "out_amount_atomic": obs.out_amount_atomic,
        "price_impact_pct": obs.price_impact_pct,
        "route_found": obs.route_found,
        "status": obs.status,
        "source": obs.source,
        "error": obs.error,
        "quote_context_slot": obs.quote_context_slot,
        "quote_time_taken_sec": obs.quote_time_taken_sec,
        "expected_pair_address": obs.expected_pair_address,
        "expected_dex_id": obs.expected_dex_id,
        "route_amm_keys": ",".join(obs.route_amm_keys),
    }
