"""Chain data sources for post-migration buyer capture.

Free-first order (no paid quota required):
  1. pump.fun swap-api v2 trades  (wallets + buy/sell + SOL, no key)
  2. public Solana RPC jsonParsed (pool signatures + getTransaction)
  3. Helius enhanced txs ONLY if STINKY_ENABLE_HELIUS=true and not throttled

DexScreener remains the market snapshot source (volume/liq).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from post_migration.config import settings
from post_migration.models import MarketSnapshot, ObservedTrade
from post_migration.trade_parser import (
    parse_helius_swap,
    parse_pump_v2_trade,
    parse_rpc_json_parsed,
)

logger = structlog.get_logger(__name__)

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"
PUMP_V2_TRADES = "https://swap-api.pump.fun/v2/coins/{mint}/trades"
HELIUS_HISTORY = (
    "https://api-mainnet.helius-rpc.com/v0/addresses/{address}/transactions"
)
_HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 StinkyOS/free-buyer-capture",
}

_helius_cooldown_until = 0.0
_HELIUS_SOFT_COOLDOWN_SEC = 90.0
_HELIUS_HARD_COOLDOWN_SEC = 1800.0

_pump_lock = asyncio.Lock()
_pump_next_ok = 0.0
_PUMP_MIN_INTERVAL_SEC = 0.25

_rpc_lock = asyncio.Lock()
_rpc_next_ok = 0.0
_RPC_MIN_INTERVAL_SEC = 0.15


def helius_throttled() -> bool:
    return time.monotonic() < _helius_cooldown_until


def helius_enabled() -> bool:
    return bool(settings.enable_helius and settings.helius_api_key)


def clear_helius_cooldown() -> None:
    global _helius_cooldown_until
    _helius_cooldown_until = 0.0


def _mark_helius_throttled(
    reason: str,
    status: int | None = None,
    *,
    hard: bool = False,
) -> None:
    global _helius_cooldown_until
    sec = _HELIUS_HARD_COOLDOWN_SEC if hard else _HELIUS_SOFT_COOLDOWN_SEC
    _helius_cooldown_until = time.monotonic() + sec
    logger.warning(
        "chain.helius_throttled",
        reason=reason,
        status=status,
        hard=hard,
        cooldown_sec=int(sec),
    )


def _dedupe(trades: list[ObservedTrade]) -> list[ObservedTrade]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[ObservedTrade] = []
    for t in trades:
        key = (t.signature, t.wallet, t.side.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    unique.sort(key=lambda x: (x.traded_at, x.signature))
    return unique


class ChainClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0, headers=_HTTP_HEADERS)

    async def close(self) -> None:
        await self._http.aclose()

    def _rpc_url(self) -> str:
        # Never route JSON-RPC through Helius unless explicitly enabled.
        if helius_enabled():
            return f"https://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}"
        return settings.solana_rpc_url

    async def fetch_trades_for_mint(
        self,
        mint: str,
        *,
        pool: str | None = None,
    ) -> list[ObservedTrade]:
        trades = await self._fetch_pump_v2(mint)
        source = "pump.v2"
        if not trades:
            trades = await self._fetch_public_rpc(mint, pool=pool)
            source = "rpc"
        if not trades and helius_enabled() and not helius_throttled():
            trades = await self._fetch_helius(mint, pool=pool)
            source = "helius"

        unique = _dedupe(trades)
        n_buy = sum(1 for t in unique if t.side.value == "buy")
        n_sell = sum(1 for t in unique if t.side.value == "sell")
        logger.info(
            "chain.trades_parsed",
            mint=mint[:12],
            pool=(pool or "")[:12],
            source=source,
            trades=len(unique),
            buys=n_buy,
            sells=n_sell,
        )
        return unique

    async def _pace_pump(self) -> None:
        global _pump_next_ok
        async with _pump_lock:
            now = time.monotonic()
            wait = _pump_next_ok - now
            if wait > 0:
                await asyncio.sleep(wait)
            _pump_next_ok = time.monotonic() + _PUMP_MIN_INTERVAL_SEC

    async def _pace_rpc(self) -> None:
        global _rpc_next_ok
        async with _rpc_lock:
            now = time.monotonic()
            wait = _rpc_next_ok - now
            if wait > 0:
                await asyncio.sleep(wait)
            _rpc_next_ok = time.monotonic() + _RPC_MIN_INTERVAL_SEC

    async def _fetch_pump_v2(self, mint: str) -> list[ObservedTrade]:
        trades: list[ObservedTrade] = []
        cursor: str | None = None
        pages = max(1, int(settings.pump_trade_pages))
        limit = max(20, int(settings.pump_trade_limit))
        for page in range(pages):
            await self._pace_pump()
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            url = PUMP_V2_TRADES.format(mint=mint)
            try:
                resp = await self._http.get(url, params=params)
            except Exception as exc:
                logger.warning("chain.pump_v2_failed", mint=mint[:12], error=str(exc)[:200])
                break
            if resp.status_code == 429:
                logger.warning("chain.pump_v2_rate_limited", mint=mint[:12], page=page)
                await asyncio.sleep(2.0)
                break
            if resp.status_code != 200:
                logger.warning(
                    "chain.pump_v2_http",
                    mint=mint[:12],
                    status=resp.status_code,
                    body=(resp.text or "")[:120],
                )
                break
            try:
                data = resp.json()
            except Exception:
                break
            rows = data.get("trades") if isinstance(data, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            for raw in rows:
                if isinstance(raw, dict):
                    t = parse_pump_v2_trade(raw, mint=mint)
                    if t:
                        trades.append(t)
            pag = data.get("pagination") if isinstance(data, dict) else None
            has_more = bool(isinstance(pag, dict) and pag.get("hasMore"))
            cursor = str(pag.get("nextCursor")) if isinstance(pag, dict) and pag.get("nextCursor") else None
            logger.info(
                "chain.pump_v2_ok",
                mint=mint[:12],
                page=page,
                rows=len(rows),
                parsed=len(trades),
                has_more=has_more,
            )
            if not has_more or not cursor:
                break
        return trades

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        await self._pace_rpc()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            resp = await self._http.post(self._rpc_url(), json=payload)
        except Exception as exc:
            logger.warning("chain.rpc_failed", method=method, error=str(exc)[:200])
            return None
        if resp.status_code == 429:
            logger.warning("chain.rpc_rate_limited", method=method)
            await asyncio.sleep(1.5)
            return None
        if resp.status_code != 200:
            logger.warning("chain.rpc_http", method=method, status=resp.status_code)
            return None
        try:
            body = resp.json()
        except Exception:
            return None
        if not isinstance(body, dict):
            return None
        if body.get("error"):
            logger.warning("chain.rpc_error", method=method, error=str(body.get("error"))[:160])
            return None
        return body.get("result")

    async def _fetch_public_rpc(
        self,
        mint: str,
        *,
        pool: str | None,
    ) -> list[ObservedTrade]:
        address = pool if pool and pool != mint else mint
        sigs = await self._rpc(
            "getSignaturesForAddress",
            [address, {"limit": max(5, int(settings.rpc_sig_limit))}],
        )
        if not isinstance(sigs, list) or not sigs:
            logger.info("chain.rpc_no_signatures", mint=mint[:12], address=address[:12])
            return []
        trades: list[ObservedTrade] = []
        pulled = 0
        for row in sigs:
            if not isinstance(row, dict) or row.get("err"):
                continue
            sig = row.get("signature")
            if not sig:
                continue
            tx = await self._rpc(
                "getTransaction",
                [
                    sig,
                    {
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0,
                        "commitment": settings.commitment,
                    },
                ],
            )
            pulled += 1
            if not isinstance(tx, dict):
                continue
            trades.extend(parse_rpc_json_parsed(tx, mint=mint))
            if pulled >= int(settings.rpc_sig_limit):
                break
        if trades:
            logger.info(
                "chain.rpc_ok",
                mint=mint[:12],
                sigs=len(sigs),
                pulled=pulled,
                parsed=len(trades),
            )
        return trades

    def _helius_history_url(self, address: str) -> str | None:
        if not helius_enabled():
            return None
        base = HELIUS_HISTORY.format(address=address)
        return f"{base}?api-key={settings.helius_api_key}&limit=100&type=SWAP"

    async def _fetch_helius(
        self,
        mint: str,
        *,
        pool: str | None,
    ) -> list[ObservedTrade]:
        trades: list[ObservedTrade] = []
        addresses: list[str] = []
        if pool and pool != mint:
            addresses.append(pool)
        addresses.append(mint)
        for address in addresses:
            if helius_throttled():
                break
            url = self._helius_history_url(address)
            if not url:
                continue
            try:
                resp = await self._http.get(url)
                body = (resp.text or "")[:120]
                body_l = body.lower()
                hard_out = "max usage" in body_l or "usage reached" in body_l
                if resp.status_code == 429 or hard_out:
                    _mark_helius_throttled(
                        "max_usage" if hard_out else "http_429",
                        resp.status_code,
                        hard=hard_out,
                    )
                    logger.warning(
                        "chain.helius_history_http",
                        status=resp.status_code,
                        address=address[:12],
                        hard=hard_out,
                    )
                    break
                if resp.status_code != 200:
                    logger.warning(
                        "chain.helius_history_http",
                        status=resp.status_code,
                        address=address[:12],
                    )
                    continue
                data = resp.json()
                if not isinstance(data, list):
                    continue
                logger.info(
                    "chain.helius_history_ok",
                    address=address[:12],
                    tx_count=len(data),
                )
                for tx in data:
                    if isinstance(tx, dict):
                        trades.extend(parse_helius_swap(tx, mint=mint))
                if data:
                    break
            except Exception as exc:
                logger.warning(
                    "chain.helius_history_failed",
                    address=address[:12],
                    error=str(exc)[:200],
                )
        return trades

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
