from __future__ import annotations

import httpx
import pytest

from entity_resolver import chain_evidence


@pytest.mark.asyncio
async def test_rpc_honors_retry_after_for_http_429(monkeypatch):
    sleeps: list[float] = []
    calls = 0

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json={"error": "Too many requests for a specific RPC call"},
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": []})

    monkeypatch.setattr(chain_evidence.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(chain_evidence, "_rpc_last_request_at", {})
    monkeypatch.setattr(chain_evidence, "_rpc_cooldown_until", {})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await chain_evidence._rpc(
            client,
            rpc_url="https://rpc.invalid",
            method="getSignaturesForAddress",
            params=["wallet-a", {"limit": 50}],
        )

    assert result == []
    assert calls == 2
    assert any(delay >= 3.0 for delay in sleeps)


@pytest.mark.asyncio
async def test_rpc_paces_repeated_calls_for_same_method(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": []})

    monkeypatch.setattr(chain_evidence.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(chain_evidence, "_rpc_last_request_at", {"getSignaturesForAddress": chain_evidence._clock()})
    monkeypatch.setattr(chain_evidence, "_rpc_cooldown_until", {})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await chain_evidence._rpc(
            client,
            rpc_url="https://rpc.invalid",
            method="getSignaturesForAddress",
            params=["wallet-a", {"limit": 50}],
        )

    assert result == []
    assert any(delay > 0 for delay in sleeps)
    assert chain_evidence.RPC_MIN_METHOD_INTERVAL_SEC >= 0.25
