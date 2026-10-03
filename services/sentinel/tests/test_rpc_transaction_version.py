from __future__ import annotations

import pytest

from sentinel import rpc as rpc_module


@pytest.mark.asyncio
async def test_get_transaction_accepts_version_one(monkeypatch):
    client = rpc_module.SolanaRPC("https://rpc.invalid")
    seen: dict[str, object] = {}

    async def fake_call(method, params):
        seen["method"] = method
        seen["params"] = params
        return {"slot": 1}

    monkeypatch.setattr(client, "_call", fake_call)
    monkeypatch.setattr(rpc_module.settings, "skip_rpc_rescue_when_throttled", False)
    try:
        result = await client.get_transaction("sig-v1")
    finally:
        await client.close()

    assert result == {"slot": 1}
    assert seen["method"] == "getTransaction"
    params = seen["params"]
    assert params[1]["maxSupportedTransactionVersion"] == 1
