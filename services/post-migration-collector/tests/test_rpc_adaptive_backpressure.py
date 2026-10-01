from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import post_migration.chain as chain_module
from post_migration.chain import ChainClient


@pytest.mark.asyncio
async def test_public_rpc_requests_transaction_version_one(monkeypatch):
    client = object.__new__(ChainClient)
    client._rpc_trade_cache = {}
    calls: list[tuple[str, list[object]]] = []

    async def fake_rpc(method: str, params: list[object]):
        calls.append((method, params))
        if method == "getSignaturesForAddress":
            return [{"signature": "sig-a", "err": None}]
        if method == "getTransaction":
            return {"transaction": {}, "meta": {}}
        raise AssertionError(method)

    client._rpc = fake_rpc
    monkeypatch.setattr(chain_module, "parse_rpc_json_parsed", lambda tx, *, mint: [])

    await client._fetch_public_rpc("Mint111", pool="Pool111")

    tx_params = next(params for method, params in calls if method == "getTransaction")
    assert tx_params[1]["maxSupportedTransactionVersion"] == 1


@pytest.mark.asyncio
async def test_rpc_429_without_retry_after_uses_adaptive_shared_backoff(monkeypatch):
    class Response:
        status_code = 429
        headers = {}

    client = object.__new__(ChainClient)
    client._http = AsyncMock()
    client._http.post.return_value = Response()
    client._pace_rpc = AsyncMock()
    client._rpc_url = lambda: "https://example.invalid"

    monkeypatch.setattr(chain_module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(chain_module, "_rpc_cooldown_until", 0.0)
    monkeypatch.setattr(chain_module, "_rpc_429_streak_by_method", {})

    assert await client._rpc("getTransaction", ["sig-a", {}]) is None
    assert chain_module._rpc_cooldown_until == 110.0
    assert await client._rpc("getTransaction", ["sig-b", {}]) is None
    assert chain_module._rpc_cooldown_until == 120.0
    assert chain_module._rpc_429_streak_by_method["getTransaction"] == 2


@pytest.mark.asyncio
async def test_rpc_429_fallback_backoff_is_capped(monkeypatch):
    class Response:
        status_code = 429
        headers = {}

    client = object.__new__(ChainClient)
    client._http = AsyncMock()
    client._http.post.return_value = Response()
    client._pace_rpc = AsyncMock()
    client._rpc_url = lambda: "https://example.invalid"

    monkeypatch.setattr(chain_module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(chain_module, "_rpc_cooldown_until", 0.0)
    monkeypatch.setattr(chain_module, "_rpc_429_streak_by_method", {"getTransaction": 4})

    assert await client._rpc("getTransaction", ["sig", {}]) is None
    assert chain_module._rpc_cooldown_until == 220.0


@pytest.mark.asyncio
async def test_rpc_success_resets_only_recovered_method_streak(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {"jsonrpc": "2.0", "result": []}

    client = object.__new__(ChainClient)
    client._http = AsyncMock()
    client._http.post.return_value = Response()
    client._pace_rpc = AsyncMock()
    client._rpc_url = lambda: "https://example.invalid"

    monkeypatch.setattr(
        chain_module,
        "_rpc_429_streak_by_method",
        {"getTransaction": 3, "getSignaturesForAddress": 2},
    )

    assert await client._rpc("getTransaction", ["sig", {}]) == []
    assert "getTransaction" not in chain_module._rpc_429_streak_by_method
    assert chain_module._rpc_429_streak_by_method["getSignaturesForAddress"] == 2
