import pytest

import stinky_api.dex_provenance as provenance_api
from stinky_api.dex_provenance import (
    DexProvenanceEvidenceBundle,
    read_dex_provenance_response,
)


class Provider:
    def __init__(self, bundle):
        self.bundle = bundle
        self.calls = []

    async def load(self, *, chain: str, pool_address: str):
        self.calls.append((chain, pool_address))
        return self.bundle


@pytest.mark.asyncio
async def test_read_boundary_delegates_exact_record_and_sources(monkeypatch):
    record = object()
    sources = (object(), object())
    provider = Provider(DexProvenanceEvidenceBundle(record=record, sources=sources))
    expected = {"category": "UNKNOWN_OR_INSUFFICIENT_PROVENANCE", "limitations": []}
    calls = []

    def fake_serialize(actual_record, actual_sources):
        calls.append((actual_record, actual_sources))
        return expected

    monkeypatch.setattr(provenance_api, "serialize_dex_provenance_from_record", fake_serialize)

    result = await read_dex_provenance_response(
        provider,
        chain=" base ",
        pool_address=" 0xPool ",
    )

    assert provider.calls == [("base", "0xPool")]
    assert calls == [(record, sources)]
    assert result is expected


@pytest.mark.asyncio
async def test_missing_evidence_fails_closed():
    provider = Provider(None)

    with pytest.raises(LookupError, match="evidence unavailable"):
        await read_dex_provenance_response(
            provider,
            chain="base",
            pool_address="0xPool",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chain", "pool_address", "message"),
    [
        ("", "0xPool", "chain required"),
        ("base", "", "pool_address required"),
    ],
)
async def test_missing_request_identity_fails_closed(chain, pool_address, message):
    provider = Provider(None)

    with pytest.raises(ValueError, match=message):
        await read_dex_provenance_response(
            provider,
            chain=chain,
            pool_address=pool_address,
        )

    assert provider.calls == []


@pytest.mark.asyncio
async def test_mutable_source_collection_is_rejected():
    bundle = DexProvenanceEvidenceBundle(record=object(), sources=(object(),))
    object.__setattr__(bundle, "sources", [object()])
    provider = Provider(bundle)

    with pytest.raises(ValueError, match="immutable tuple"):
        await read_dex_provenance_response(
            provider,
            chain="base",
            pool_address="0xPool",
        )
