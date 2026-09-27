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

    @property
    def usable(self) -> bool:
        return (
            self.status == "VERIFIED"
            and self.route_found
            and self.out_amount_atomic is not None
            and self.out_amount_atomic > 0
            and self.price_impact_pct is not None
        )


def parse_quote(mint: str, input_lamports: int, payload: Any, *, observed_at: datetime | None = None) -> DepthQuoteObservation:
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
    return DepthQuoteObservation(mint, at, input_lamports, out, impact, True, "VERIFIED")


class JupiterDepthClient:
    """Observation-only GET client. No transaction-building endpoint exists here."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=12.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def quote_buy(self, mint: str, input_lamports: int) -> DepthQuoteObservation:
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
            return parse_quote(mint, input_lamports, response.json(), observed_at=at)
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
    error TEXT
);
"""
DEPTH_OBSERVATIONS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_depth_quote_mint_time ON depth_quote_observations (mint, observed_at DESC)",
)
DEPTH_OBSERVATIONS_INSERT = """
INSERT INTO depth_quote_observations (
    mint, observed_at, input_lamports, out_amount_atomic, price_impact_pct,
    route_found, status, source, error
) VALUES (
    :mint, :observed_at, :input_lamports, :out_amount_atomic, :price_impact_pct,
    :route_found, :status, :source, :error
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
    }
