from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import post_migration.chain as chain_module
from post_migration.chain import ChainClient


@pytest.mark.asyncio
async def test_public_rpc_reuses_successful_transaction_results(monkeypatch):
    client = object.__new__(ChainClient)
    client._rpc_trade_cache = {}

    calls: list[tuple[str, list[object]]] = []

    async def fake_rpc(method: str, params: list[object]):
        calls.append((method, params))
        if method == "getSignaturesForAddress":
            return [
                {"signature": "sig-a", "err": None},
                {"signature": "sig-b", "err": None},
            ]
        if method == "getTransaction":
            return {"transaction": {}, "meta": {}}
        raise AssertionError(method)

    client._rpc = fake_rpc
    monkeypatch.setattr(
        chain_module,
        "parse_rpc_json_parsed",
        lambda tx, *, mint: [],
    )

    await client._fetch_public_rpc("Mint111", pool="Pool111")
    await client._fetch_public_rpc("Mint111", pool="Pool111")

    methods = [method for method, _params in calls]
    assert methods.count("getSignaturesForAddress") == 2
    assert methods.count("getTransaction") == 2


@pytest.mark.asyncio
async def test_rpc_429_sets_shared_retry_after_cooldown(monkeypatch):
    class Response:
        status_code = 429
        headers = {"Retry-After": "17"}

    client = object.__new__(ChainClient)
    client._http = AsyncMock()
    client._http.post.return_value = Response()
    client._pace_rpc = AsyncMock()
    client._rpc_url = lambda: "https://example.invalid"

    monkeypatch.setattr(chain_module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(chain_module, "_rpc_cooldown_until", 0.0)

    result = await client._rpc("getTransaction", ["sig", {}])

    assert result is None
    assert chain_module._rpc_cooldown_until == 117.0


def test_rpc_default_pacing_stays_below_single_method_public_limit():
    assert chain_module._RPC_MIN_INTERVAL_SEC >= 0.25
