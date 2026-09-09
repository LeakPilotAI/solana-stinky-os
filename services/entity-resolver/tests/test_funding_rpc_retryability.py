from __future__ import annotations

import httpx
import pytest

from entity_resolver import chain_evidence, service
from entity_resolver.chain_evidence import FundingScanResult


@pytest.mark.asyncio
async def test_rpc_retries_http_429_once_then_succeeds(monkeypatch):
    calls = 0

    async def no_sleep(_delay):
        return None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": []})

    monkeypatch.setattr(chain_evidence.asyncio, "sleep", no_sleep)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await chain_evidence._rpc(
            client,
            rpc_url="https://rpc.invalid",
            method="getSignaturesForAddress",
            params=["wallet-a", {"limit": 50}],
        )

    assert result == []
    assert calls == 2


@pytest.mark.asyncio
async def test_failed_funding_scan_wallet_remains_retryable(monkeypatch):
    calls = 0

    async def fake_scan(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return FundingScanResult([], 50, 0, 0, False)
        return FundingScanResult([], 50, 3, 3, True)

    monkeypatch.setattr(service, "scan_recent_inbound_transfers", fake_scan)
    svc = service.EntityService()
    try:
        await svc._observe_wallet_funding("wallet-a")
        assert "wallet-a" not in svc._funding_scanned_wallets

        await svc._observe_wallet_funding("wallet-a")
        assert "wallet-a" in svc._funding_scanned_wallets
        assert calls == 2
    finally:
        await svc._http.aclose()
