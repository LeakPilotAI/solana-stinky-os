from __future__ import annotations

import httpx
import pytest

from entity_resolver.chain_evidence import FundingScanResult
from entity_resolver import funding_scan_runner


@pytest.mark.asyncio
async def test_runner_returns_zero_result_diagnostics(monkeypatch):
    expected = FundingScanResult([], 50, 7, 7, True)

    async def fake_scan(*args, **kwargs):
        return expected

    monkeypatch.setattr(funding_scan_runner, "scan_recent_inbound_transfers", fake_scan)
    async with httpx.AsyncClient() as client:
        result = await funding_scan_runner.run_funding_scan(
            client,
            rpc_url="http://rpc.invalid",
            wallet="wallet-a",
            signature_limit=50,
        )
    assert result is expected
