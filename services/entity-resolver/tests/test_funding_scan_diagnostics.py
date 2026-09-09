from __future__ import annotations

import httpx
import pytest

from entity_resolver import chain_evidence


@pytest.mark.asyncio
async def test_scan_diagnostics_preserve_zero_result_coverage(monkeypatch):
    calls = []

    async def fake_rpc(client, *, rpc_url, method, params):
        calls.append((method, params))
        if method == "getSignaturesForAddress":
            return [
                {"signature": "sig-ok", "err": None},
                {"signature": "sig-failed", "err": {"InstructionError": [0, "x"]}},
            ]
        return None

    async def fake_fetch_native_transfers(client, *, rpc_url, signature):
        return []

    monkeypatch.setattr(chain_evidence, "_rpc", fake_rpc)
    monkeypatch.setattr(chain_evidence, "fetch_native_transfers", fake_fetch_native_transfers)

    async with httpx.AsyncClient() as client:
        result = await chain_evidence.scan_recent_inbound_transfers(
            client,
            rpc_url="http://rpc.invalid",
            wallet="wallet-a",
            signature_limit=500,
        )

    assert result.transfers == []
    assert result.signatures_requested == 50
    assert result.signatures_returned == 2
    assert result.signatures_examined == 1
    assert result.rpc_success is True
    assert calls[0][0] == "getSignaturesForAddress"
    assert calls[0][1][1]["limit"] == 50


@pytest.mark.asyncio
async def test_scan_diagnostics_report_signature_list_rpc_failure(monkeypatch):
    async def fake_rpc(client, *, rpc_url, method, params):
        return None

    monkeypatch.setattr(chain_evidence, "_rpc", fake_rpc)

    async with httpx.AsyncClient() as client:
        result = await chain_evidence.scan_recent_inbound_transfers(
            client,
            rpc_url="http://rpc.invalid",
            wallet="wallet-a",
            signature_limit=50,
        )

    assert result.transfers == []
    assert result.signatures_requested == 50
    assert result.signatures_returned == 0
    assert result.signatures_examined == 0
    assert result.rpc_success is False
