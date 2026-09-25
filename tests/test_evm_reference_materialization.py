from pathlib import Path
from dataclasses import replace
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import observe_contract_code
from stinky_core.evm_reference_fingerprints import BASE_UNISWAP_REFERENCE_SOURCES
from stinky_core.evm_reference_materialization import materialize_reference_fingerprint_bundle
from stinky_core.evm_rpc import EvmReadOnlyRpc

CODE = "0x6001600055"


def observer(url, code=CODE):
    def transport(_url, payload, timeout):
        request = json.loads(payload)
        result = "0x2105" if request["method"] == "eth_chainId" else code
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}

    rpc = EvmReadOnlyRpc("base", transport=transport)
    rpc.rpc_url = url
    return rpc


def evidence(address, block=100):
    return observe_contract_code(
        [observer("https://one.example"), observer("https://two.example")],
        chain="base",
        address=address,
        block_number=block,
    )


def all_evidence(block=100):
    return tuple(evidence(source.address, block) for source in BASE_UNISWAP_REFERENCE_SOURCES)


def test_materializes_complete_pinned_catalog_deterministically():
    bundle = materialize_reference_fingerprint_bundle(
        BASE_UNISWAP_REFERENCE_SOURCES,
        reversed(all_evidence()),
        expected_block_numbers={"base": 100},
    )
    assert len(bundle.entries) == len(BASE_UNISWAP_REFERENCE_SOURCES) == 4
    assert bundle.chain_blocks == (("base", 100),)
    assert bundle.source_references == tuple(sorted(bundle.source_references))
    assert all(entry.source_kind == "PINNED_GITHUB_DEPLOYMENT_REFERENCE" for entry in bundle.entries)
    assert bundle.status == "UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE"
    assert "REFERENCE_BUNDLE_DOES_NOT_PROVE_COMPONENT_AUTHENTICITY" in bundle.limitations


def test_missing_and_unexpected_evidence_fail_closed():
    items = all_evidence()
    with pytest.raises(ValueError, match="missing contract code evidence"):
        materialize_reference_fingerprint_bundle(BASE_UNISWAP_REFERENCE_SOURCES, items[:-1])

    unexpected = evidence("0x" + "aa" * 20)
    with pytest.raises(ValueError, match="unexpected contract code evidence"):
        materialize_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            items + (unexpected,),
        )


def test_duplicate_source_and_evidence_identities_fail_closed():
    source = BASE_UNISWAP_REFERENCE_SOURCES[0]
    item = evidence(source.address)
    with pytest.raises(ValueError, match="duplicate reference source"):
        materialize_reference_fingerprint_bundle((source, source), (item,))
    with pytest.raises(ValueError, match="duplicate contract code evidence"):
        materialize_reference_fingerprint_bundle((source,), (item, item))


def test_mixed_time_and_stale_evidence_fail_closed():
    items = list(all_evidence())
    items[-1] = replace(items[-1], block_number=99)
    with pytest.raises(ValueError, match="one historical block per chain"):
        materialize_reference_fingerprint_bundle(BASE_UNISWAP_REFERENCE_SOURCES, items)

    with pytest.raises(ValueError, match="stale for expected historical block"):
        materialize_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            all_evidence(block=99),
            expected_block_numbers={"base": 100},
        )


def test_expected_block_map_must_cover_reference_chains_exactly():
    with pytest.raises(ValueError, match="cover reference chains exactly"):
        materialize_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            all_evidence(),
            expected_block_numbers={},
        )
    with pytest.raises(ValueError, match="non-negative integers"):
        materialize_reference_fingerprint_bundle(
            BASE_UNISWAP_REFERENCE_SOURCES,
            all_evidence(),
            expected_block_numbers={"base": -1},
        )


@pytest.mark.parametrize("commit", ["1_" + "2" * 38, " " + "1" * 39, "1" * 39 + " ", "+" + "1" * 39, "0x" + "1" * 38, "g" * 40, "1" * 39, "1" * 41])
def test_pinned_source_rejects_malformed_commit_on_create_and_hydrate(commit):
    from stinky_core.evm_dex_provenance_codec import encode_reference_sources, decode_reference_sources
    source = BASE_UNISWAP_REFERENCE_SOURCES[0]
    with pytest.raises(ValueError, match="source_commit"):
        replace(source, source_commit=commit)
    encoded = list(encode_reference_sources((source,)))
    encoded[0]["value"]["fields"]["source_commit"] = commit
    with pytest.raises(ValueError, match="source_commit"):
        decode_reference_sources(encoded)


def test_pinned_source_accepts_equivalent_commit_case_and_leading_zero():
    source = BASE_UNISWAP_REFERENCE_SOURCES[0]
    for commit in (source.source_commit.upper(), "0" + "Ab" * 19 + "1"):
        normalized = replace(source, source_commit=commit)
        assert normalized.source_commit == commit.lower()
        assert normalized.source_reference == replace(source, source_commit=commit.lower()).source_reference
