from __future__ import annotations

import pytest

from entity_resolver.chain_evidence import _parse_native_transfers, fetch_recent_inbound_transfers


def test_parse_native_transfers_accepts_only_system_transfers() -> None:
    result = {
        "slot": 123,
        "blockTime": 1_757_000_000,
        "transaction": {
            "message": {
                "instructions": [
                    {
                        "program": "system",
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "source": "SOURCE",
                                "destination": "DEST",
                                "lamports": 2_000_000_000,
                            },
                        },
                    },
                    {
                        "program": "spl-token",
                        "parsed": {
                            "type": "transfer",
                            "info": {"source": "SOURCE", "destination": "DEST", "amount": "9"},
                        },
                    },
                ]
            }
        },
        "meta": {"innerInstructions": []},
    }

    transfers = _parse_native_transfers(result, signature="SIG")

    assert transfers == [
        {
            "source_wallet": "SOURCE",
            "destination_wallet": "DEST",
            "amount_lamports": 2_000_000_000,
            "signature": "SIG",
            "slot": 123,
            "observed_at": 1_757_000_000,
            "evidence_basis": "direct_system_program_transfer",
        }
    ]


def test_parse_native_transfers_rejects_invalid_or_zero_amounts() -> None:
    result = {
        "transaction": {
            "message": {
                "instructions": [
                    {
                        "program": "system",
                        "parsed": {"type": "transfer", "info": {"source": "A", "destination": "B", "lamports": 0}},
                    },
                    {
                        "program": "system",
                        "parsed": {"type": "transfer", "info": {"source": "A", "destination": "B", "lamports": "bad"}},
                    },
                ]
            }
        },
        "meta": {"innerInstructions": []},
    }

    assert _parse_native_transfers(result, signature="SIG") == []


@pytest.mark.asyncio
async def test_recent_inbound_transfer_scan_is_bounded_at_50(monkeypatch) -> None:
    calls = []

    async def fake_rpc(client, *, rpc_url, method, params):
        calls.append((method, params))
        if method == "getSignaturesForAddress":
            return []
        raise AssertionError(method)

    monkeypatch.setattr("entity_resolver.chain_evidence._rpc", fake_rpc)

    class DummyClient:
        pass

    rows = await fetch_recent_inbound_transfers(
        DummyClient(),
        rpc_url="http://rpc",
        wallet="Wallet",
        signature_limit=500,
    )

    assert rows == []
    assert calls == [
        (
            "getSignaturesForAddress",
            ["Wallet", {"limit": 50, "commitment": "confirmed"}],
        )
    ]
