"""Thin Solana RPC helpers (HTTP) with free-tier 429 awareness."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from sentinel.config import settings
from sentinel.rate_limit import gate, is_rate_limit_error

logger = structlog.get_logger(__name__)


class SolanaRPC:
    def __init__(
        self,
        rpc_url: str | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.rpc_url = rpc_url or self._resolve_rpc_url()
        self._public_url = settings.public_rpc_url
        self._client = httpx.AsyncClient(timeout=timeout)

    @staticmethod
    def _resolve_rpc_url() -> str:
        if settings.helius_api_key:
            return f"https://mainnet.helius-rpc.com/?api-key={settings.helius_api_key}"
        return settings.solana_rpc_url

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(self, url: str, method: str, params: list[Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        resp = await self._client.post(url, json=payload)
        if resp.status_code == 429:
            gate.trip("rpc_http_429")
            raise RuntimeError(f"HTTP 429 Too Many Requests for {method}")
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            err = body["error"]
            if is_rate_limit_error(err):
                gate.trip(f"rpc_body:{err}")
            raise RuntimeError(f"RPC error: {err}")
        return body.get("result")

    async def _call(self, method: str, params: list[Any] | None = None) -> Any:
        # Prefer waiting out cooldown rather than burning more free-tier credits
        if gate.tripped and settings.helius_api_key:
            await gate.wait_if_needed(label=f"rpc:{method}")
        try:
            return await self._post(self.rpc_url, method, params)
        except Exception as exc:
            if is_rate_limit_error(exc):
                gate.trip(str(exc))
            raise

    async def get_health(self) -> str:
        """Health check — public RPC by default so we don't spend Helius quota on boot."""
        url = (
            self._public_url
            if settings.use_public_health_check
            else self.rpc_url
        )
        try:
            result = await self._post(url, "getHealth")
            return str(result) if result else "ok"
        except Exception as exc:
            # Never trip the gate hard on public health failure alone
            logger.warning("rpc.health_failed", error=str(exc)[:200], url=url.split("?")[0])
            return "unavailable"

    async def get_transaction(self, signature: str) -> dict[str, Any] | None:
        if gate.tripped and settings.skip_rpc_rescue_when_throttled:
            logger.info(
                "rpc.skipped_throttled",
                method="getTransaction",
                remaining_sec=round(gate.remaining_sec, 1),
            )
            return None
        result = await self._call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": settings.commitment,
                },
            ],
        )
        return result

    async def get_signatures_for_address(
        self,
        address: str,
        *,
        limit: int = 20,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        if gate.tripped and settings.skip_rpc_history_when_throttled:
            logger.info(
                "rpc.skipped_throttled",
                method="getSignaturesForAddress",
                remaining_sec=round(gate.remaining_sec, 1),
            )
            return []
        opts: dict[str, Any] = {"limit": limit}
        if before:
            opts["before"] = before
        result = await self._call("getSignaturesForAddress", [address, opts])
        return result or []
