from pathlib import Path
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_call_consensus import classify_exact_results, observe_exact_call
from stinky_core.evm_contract_code import ContractCodeEvidence
from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_factory_evidence import (
    V2_FACTORY_LOOKUP_SELECTOR,
    V3_FACTORY_LOOKUP_SELECTOR,
    build_factory_lookup,
    classify_factory_relationship,
    decode_factory_address,
)
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError

FACTORY = "0x" + "11" * 20
POOL = "0x" + "44" * 20
T0 = "0x" + "22" * 20
T1 = "0x" + "33" * 20
OTHER = "0x" + "66" * 20


def test_exact_result_quorum():
    out = classify_exact_results({"0x01": ["a", "b"]})
    assert out.agreed_result == "0x01"
    assert out.providers == ("a", "b")
    assert out.verdict == "EXACT_RESULT_QUORUM"


def test_result_disagreement_fails_closed():
    out = classify_exact_results({"0x01": ["a"], "0x02": ["b"]})
    assert out.agreed_result is None
    assert out.providers == ()
    assert out.verdict == "RESULT_DISAGREEMENT"


def test_insufficient_and_duplicate_evidence_fail_closed():
    out = classify_exact_results({"0x01": ["a", "a"]})
    assert out.verdict == "INSUFFICIENT_RESULT_EVIDENCE"
    with pytest.raises(ValueError, match="min_quorum"):
        classify_exact_results({"0x01": ["a"]}, min_quorum=1)


def _pool(family="V2_STYLE_PAIR_CREATED", fee=None):
    return DexPoolCandidate(
        "base", 8453, FACTORY, "base:" + FACTORY,
        POOL, "base:" + POOL,
        T0, "base:" + T0,
        T1, "base:" + T1,
        family, fee, 100,
        "0x" + "aa" * 32, "0x" + "bb" * 32, "0x1",
        "UNVERIFIED_DEX_POOL_CANDIDATE", ("rpc-a", "rpc-b"),
    )


def _abi_address(address):
    return "0x" + "0" * 24 + address[2:]


def _observer(url, result=None, fail=False):
    def transport(_url, payload, timeout):
        req = json.loads(payload)
        if req["method"] == "eth_chainId":
            value = "0x2105"
        elif req["method"] == "eth_call":
            if fail:
                return {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -1}}
            value = result
        else:
            raise AssertionError(req["method"])
        return {"jsonrpc": "2.0", "id": req["id"], "result": value}
    rpc = EvmReadOnlyRpc("base", transport=transport)
    rpc.rpc_url = url
    return rpc


def _code(block=123):
    return ContractCodeEvidence(
        "base", 8453, FACTORY, "base:" + FACTORY, block,
        2, "f" * 64, "0x6001", "UNVERIFIED_CONTRACT_CODE_EVIDENCE", (),
    )


def test_factory_lookup_shapes_and_strict_address_decode():
    v2 = build_factory_lookup(_pool())
    assert v2.startswith(V2_FACTORY_LOOKUP_SELECTOR)
    assert len(v2) == 10 + 64 + 64

    v3 = build_factory_lookup(_pool("V3_STYLE_POOL_CREATED", 3000))
    assert v3.startswith(V3_FACTORY_LOOKUP_SELECTOR)
    assert len(v3) == 10 + 64 + 64 + 64
    assert v3[-64:] == f"{3000:064x}"

    encoded = _abi_address(POOL)
    assert decode_factory_address("base", encoded) == POOL
    with pytest.raises(EvmRpcError):
        decode_factory_address("base", "0x1234")


def test_factory_lookup_rejects_unsupported_or_incomplete_shapes():
    with pytest.raises(ValueError, match="unsupported DEX pool event family"):
        build_factory_lookup(_pool("UNKNOWN"))
    with pytest.raises(ValueError, match="uint24 fee tier"):
        build_factory_lookup(_pool("V3_STYLE_POOL_CREATED", None))


def test_exact_call_observation_preserves_block_and_provider_quorum():
    obs = observe_exact_call(
        [_observer("https://one.example", _abi_address(POOL)), _observer("https://two.example", _abi_address(POOL))],
        chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
    )
    assert obs.block_number == 123
    assert obs.target == FACTORY
    assert obs.consensus.verdict == "EXACT_RESULT_QUORUM"
    assert obs.consensus.providers == ("one.example", "two.example")


def test_exact_call_disagreement_failure_and_duplicates_fail_closed():
    disagreement = observe_exact_call(
        [_observer("https://one.example", _abi_address(POOL)), _observer("https://two.example", _abi_address(OTHER))],
        chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
    )
    assert disagreement.consensus.verdict == "RESULT_DISAGREEMENT"

    insufficient = observe_exact_call(
        [_observer("https://one.example", _abi_address(POOL)), _observer("https://two.example", fail=True)],
        chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
    )
    assert insufficient.consensus.verdict == "INSUFFICIENT_RESULT_EVIDENCE"

    with pytest.raises(EvmRpcError, match="insufficient distinct"):
        observe_exact_call(
            [_observer("https://same.example", _abi_address(POOL)), _observer("https://same.example", _abi_address(POOL))],
            chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
        )


def test_factory_relationship_classifier_match_no_pool_conflict_and_unknown():
    matched_obs = observe_exact_call(
        [_observer("https://one.example", _abi_address(POOL)), _observer("https://two.example", _abi_address(POOL))],
        chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
    )
    matched = classify_factory_relationship(_pool(), _code(), matched_obs)
    assert matched.relationship == "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL"
    assert matched.returned_address == POOL

    zero_obs = observe_exact_call(
        [_observer("https://one.example", _abi_address("0x" + "0" * 40)), _observer("https://two.example", _abi_address("0x" + "0" * 40))],
        chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
    )
    assert classify_factory_relationship(_pool(), _code(), zero_obs).relationship == "FACTORY_LOOKUP_REPORTS_NO_POOL"

    conflict_obs = observe_exact_call(
        [_observer("https://one.example", _abi_address(OTHER)), _observer("https://two.example", _abi_address(OTHER))],
        chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
    )
    assert classify_factory_relationship(_pool(), _code(), conflict_obs).relationship == "FACTORY_LOOKUP_CONFLICTS_WITH_DISCOVERED_POOL"

    unknown_obs = observe_exact_call(
        [_observer("https://one.example", _abi_address(POOL)), _observer("https://two.example", _abi_address(OTHER))],
        chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
    )
    unknown = classify_factory_relationship(_pool(), _code(), unknown_obs)
    assert unknown.relationship == "UNKNOWN_FACTORY_RELATIONSHIP"
    assert unknown.returned_address is None


def test_factory_relationship_requires_same_target_and_block():
    obs = observe_exact_call(
        [_observer("https://one.example", _abi_address(POOL)), _observer("https://two.example", _abi_address(POOL))],
        chain="base", target=FACTORY, calldata=build_factory_lookup(_pool()), block_number=123,
    )
    with pytest.raises(ValueError, match="historical block"):
        classify_factory_relationship(_pool(), _code(block=124), obs)
