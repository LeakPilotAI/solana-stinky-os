from __future__ import annotations

import httpx
import pytest

from entity_resolver import chain_evidence


@pytest.mark.asyncio
async def test_deferred_wallet_skips_rpc_during_cooldown(monkeypatch):
    calls = 0
    now = 1000.0

    def fake_clock():
        return now

    async def fake_rpc(client, *, rpc_url, method, params):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(chain_evidence, "_clock", fake_clock)
    monkeypatch.setattr(chain_evidence, "_rpc", fake_rpc)
    chain_evidence._funding_wallet_deferred_until.clear()

    async with httpx.AsyncClient() as client:
        first = await chain_evidence.scan_recent_inbound_transfers(
            client,
            rpc_url="http://rpc.invalid",
            wallet="wallet-cooldown-a",
            signature_limit=50,
        )
        second = await chain_evidence.scan_recent_inbound_transfers(
            client,
            rpc_url="http://rpc.invalid",
            wallet="wallet-cooldown-a",
            signature_limit=50,
        )

    assert first.rpc_success is False
    assert second.rpc_success is False
    assert calls == 1
    assert chain_evidence._funding_wallet_deferred_until["wallet-cooldown-a"] == pytest.approx(
        1000.0 + chain_evidence.FUNDING_DEFERRED_WALLET_COOLDOWN_SEC
    )


@pytest.mark.asyncio
async def test_deferred_wallet_retries_after_cooldown(monkeypatch):
    calls = 0
    now = 2000.0

    def fake_clock():
        return now

    async def fake_rpc(client, *, rpc_url, method, params):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return []

    monkeypatch.setattr(chain_evidence, "_clock", fake_clock)
    monkeypatch.setattr(chain_evidence, "_rpc", fake_rpc)
    chain_evidence._funding_wallet_deferred_until.clear()

    async with httpx.AsyncClient() as client:
        first = await chain_evidence.scan_recent_inbound_transfers(
            client,
            rpc_url="http://rpc.invalid",
            wallet="wallet-cooldown-b",
            signature_limit=50,
        )
        assert first.rpc_success is False
        assert calls == 1

        now += chain_evidence.FUNDING_DEFERRED_WALLET_COOLDOWN_SEC - 1
        skipped = await chain_evidence.scan_recent_inbound_transfers(
            client,
            rpc_url="http://rpc.invalid",
            wallet="wallet-cooldown-b",
            signature_limit=50,
        )
        assert skipped.rpc_success is False
        assert calls == 1

        now += 2
        retried = await chain_evidence.scan_recent_inbound_transfers(
            client,
            rpc_url="http://rpc.invalid",
            wallet="wallet-cooldown-b",
            signature_limit=50,
        )

    assert retried.rpc_success is True
    assert calls == 2
    assert "wallet-cooldown-b" not in chain_evidence._funding_wallet_deferred_until
