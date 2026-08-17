"""Live DexScreener lookups for slash commands."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from discord_bot.config import settings

logger = structlog.get_logger(__name__)


async def fetch_token_metrics(mint: str) -> dict[str, Any] | None:
    url = settings.dexscreener_token_url.format(mint=mint)
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        logger.warning("dex.fetch_failed", mint=mint, error=str(exc))
        return None

    pairs = data.get("pairs") or []
    if not pairs:
        return None
    sol = [p for p in pairs if p.get("chainId") == "solana"] or pairs

    def liq(p: dict[str, Any]) -> float:
        return float((p.get("liquidity") or {}).get("usd") or 0)

    best = max(sol, key=liq)
    vol = best.get("volume") or {}
    return {
        "name": (best.get("baseToken") or {}).get("name"),
        "symbol": (best.get("baseToken") or {}).get("symbol"),
        "price_usd": best.get("priceUsd"),
        "liquidity_usd": (best.get("liquidity") or {}).get("usd"),
        "volume_m5": vol.get("m5"),
        "volume_h1": vol.get("h1"),
        "volume_h24": vol.get("h24"),
        "pair_address": best.get("pairAddress"),
        "dex_id": best.get("dexId"),
        "url": best.get("url"),
        "fdv": best.get("fdv"),
        "market_cap": best.get("marketCap"),
    }
