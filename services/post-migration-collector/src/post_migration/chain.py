"""Chain data sources: Helius enhanced txs + DexScreener market snapshots.

v1.1 hardening:
  - Correct Helius base URL (api-mainnet.helius-rpc.com)
  - type=SWAP filter + higher limit
  - token-accounts activity for mint ATA path
  - Explicit empty/error counters in logs
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from post_migration.config import settings
from post_migration.models import MarketSnapshot, ObservedTrade
from post_migration.trade_parser import parse_helius_swap

logger = structlog.get_logger(__name__)

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"
# Enhanced Transactions history (legacy but still operational)
HELIUS_HISTORY = (
    "https://api-mainnet.helius-rpc.com/v0/addresses/{address}/transactions"
)


class ChainClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._http.aclose()

    def _rpc_url(self) -> str:
        if settings.helius_api_key:
            return f"https://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}"
        return settings.solana_rpc_url

    def _helius_history_urls(self, address: str) -> list[str]:
        if not settings.helius_api_key:
            return []
        key = settings.helius_api_key
        base = HELIUS_HISTORY.format(address=address)
        # Prefer SWAP; also a broader pull without type filter as fallback
        return [
            f"{base}?api-key={key}&limit=100&type=SWAP",
            f"{base}?api-key={key}&limit=100",
        ]

    async def fetch_trades_for_mint(
        self,
        mint: str,
        *,
        pool: str | None = None,
    ) -> list[ObservedTrade]:
        """Pull recent swap activity related to mint/pool via Helius."""
        trades: list[ObservedTrade] = []
        if not settings.helius_api_key:
            logger.warning("chain.no_helius_key")
            return trades

        addresses = [a for a in [pool, mint] if a]
        for address in addresses:
            urls = self._helius_history_urls(address)
            got_any = False
            for url in urls:
                try:
                    resp = await self._http.get(url)
                    if resp.status_code != 200:
                        logger.warning(
                            "chain.helius_history_http",
                            status=resp.status_code,
                            address=address[:12],
                            body=resp.text[:200],
                        )
                        continue
                    data = resp.json()
                    if not isinstance(data, list):
                        logger.warning(
                            "chain.helius_history_not_list",
                            address=address[:12],
                            type=type(data).__name__,
                        )
                        continue
                    logger.info(
                        "chain.helius_history_ok",
                        address=address[:12],
                        tx_count=len(data),
                    )
                    for tx in data:
                        if not isinstance(tx, dict):
                            continue
                        trades.extend(parse_helius_swap(tx, mint=mint))
                    got_any = True
                    # Prefer first successful URL (SWAP filter)
                    if data:
                        break
                except Exception as exc:
                    logger.warning(
                        "chain.helius_history_failed",
                        address=address[:12],
                        error=str(exc),
                    )
            if not got_any:
                logger.info("chain.helius_no_data", address=address[:12])

        # Deduplicate by (signature, wallet, side)
        seen: set[tuple[str, str, str]] = set()
        unique: list[ObservedTrade] = []
        for t in trades:
            key = (t.signature, t.wallet, t.side.value)
            if key in seen:
                continue
            seen.add(key)
            unique.append(t)
        unique.sort(key=lambda x: (x.traded_at, x.signature))
        n_buy = sum(1 for t in unique if t.side.value == "buy")
        n_sell = sum(1 for t in unique if t.side.value == "sell")
        logger.info(
            "chain.trades_parsed",
            mint=mint[:12],
            pool=(pool or "")[:12],
            trades=len(unique),
            buys=n_buy,
            sells=n_sell,
        )
        return unique

    async def fetch_market_snapshot(self, mint: str) -> MarketSnapshot | None:
        try:
            resp = await self._http.get(DEX_URL.format(mint=mint))
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception as exc:
            logger.warning("chain.dex_failed", mint=mint, error=str(exc))
            return None

        pairs: list[dict[str, Any]] = data.get("pairs") or []
        if not pairs:
            return None
        sol = [p for p in pairs if p.get("chainId") == "solana"] or pairs

        def liq(p: dict[str, Any]) -> float:
            return float((p.get("liquidity") or {}).get("usd") or 0)

        best = max(sol, key=liq)
        vol = best.get("volume") or {}
        return MarketSnapshot(
            mint=mint,
            captured_at=datetime.now(timezone.utc),
            price_usd=_f(best.get("priceUsd")),
            liquidity_usd=_f((best.get("liquidity") or {}).get("usd")),
            volume_m5_usd=_f(vol.get("m5")),
            volume_h1_usd=_f(vol.get("h1")),
            volume_h24_usd=_f(vol.get("h24")),
            fdv_usd=_f(best.get("fdv")),
            market_cap_usd=_f(best.get("marketCap")),
            pair_address=best.get("pairAddress"),
            dex_id=best.get("dexId"),
            source="dexscreener",
        )


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
