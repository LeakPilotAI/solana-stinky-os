from __future__ import annotations

import httpx
import pytest

from entity_resolver import chain_evidence


@pytest.mark.asyncio
async def test_scan_stops_after_first_unavailable_transaction(monkeypatch):
    methods: list[str] = []

    async def fake_rpc(client, *, rpc_url, method, params):
        methods.append(method)
        if method == "getSignaturesForAddress":
            return [
                {"signature": "sig-1", "err": None},
                {"signature": "sig-2", "err": None},
                {"signature": "sig-3", "err": None},
            ]
        return None

    monkeypatch.setattr(chain_evidence, "_rpc", fake_rpc)
    chain_evidence._transaction_cache.clear()
    async with httpx.AsyncClient() as client:
        result = await chain_evidence.scan_recent_inbound_transfers(
            client,
            rpc_url="https://rpc.invalid",
            wallet="wallet-a",
            signature_limit=50,
        )

    assert result.rpc_success is False
    assert result.signatures_returned == 3
    assert result.signatures_examined == 0
    assert methods == ["getSignaturesForAddress", "getTransaction"]


@pytest.mark.asyncio
async def test_successful_transaction_lookup_is_cached(monkeypatch):
    calls = 0
    transaction = {
        "slot": 1,
        "blockTime": 1,
        "transaction": {"message": {"instructions": []}},
        "meta": {"innerInstructions": []},
    }

    async def fake_rpc(client, *, rpc_url, method, params):
        nonlocal calls
        calls += 1
        return transaction

    monkeypatch.setattr(chain_evidence, "_rpc", fake_rpc)
    chain_evidence._transaction_cache.clear()
    async with httpx.AsyncClient() as client:
        first = await chain_evidence.fetch_native_transfers(
            client, rpc_url="https://rpc.invalid", signature="sig-cache"
        )
        second = await chain_evidence.fetch_native_transfers(
            client, rpc_url="https://rpc.invalid", signature="sig-cache"
        )

    assert first.rpc_success is True
    assert first.cache_hit is False
    assert second.rpc_success is True
    assert second.cache_hit is True
    assert calls == 1
