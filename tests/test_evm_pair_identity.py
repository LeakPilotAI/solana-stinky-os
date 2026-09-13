from pathlib import Path
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_pair_identity import observe_pair_token_identity, compare_pair_to_router_path
from stinky_core.evm_router_semantics import RouterCalldataSemantics
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError

POOL = "0x" + "44" * 20
T0 = "0x" + "22" * 20
T1 = "0x" + "33" * 20
OTHER = "0x" + "66" * 20


def pool():
    return DexPoolCandidate(
        "base", 8453, "0x" + "11" * 20, "base:" + "0x" + "11" * 20,
        POOL, "base:" + POOL, T0, "base:" + T0, T1, "base:" + T1,
        "V2_STYLE_PAIR_CREATED", None, 100, "0x" + "aa" * 32, "0x" + "bb" * 32,
        "0x1", "UNVERIFIED_DEX_POOL_CANDIDATE", ("rpc-a", "rpc-b"),
    )


def abi_address(address):
    return "0x" + "0" * 24 + address[2:]


def observer(url, token0=T0, token1=T1, malformed=False):
    def transport(_url, payload, timeout):
        req = json.loads(payload)
        method = req["method"]
        if method == "eth_chainId":
            result = "0x2105"
        elif method == "eth_getCode":
            result = "0x6001"
        elif method == "eth_call":
            data = req["params"][0]["data"]
            if malformed:
                result = "0x1234"
            elif data == "0x0dfe1681":
                result = abi_address(token0)
            elif data == "0xd21220a7":
                result = abi_address(token1)
            else:
                raise AssertionError(data)
        else:
            raise AssertionError(method)
        return {"jsonrpc": "2.0", "id": req["id"], "result": result}
    rpc = EvmReadOnlyRpc("base", transport=transport)
    rpc.rpc_url = url
    return rpc


def semantics(path, status="SUPPORTED_ROUTER_CALLDATA_SEMANTICS"):
    return RouterCalldataSemantics(
        "38ed1739", "sig", "family", 1, 1, tuple(path), OTHER, 999, status, (),
    )


def test_pair_identity_requires_matching_provider_quorum_and_preserves_block():
    evidence = observe_pair_token_identity(
        [observer("https://one.example"), observer("https://two.example")],
        pool(), block_number=123,
    )
    assert (evidence.observed_token0, evidence.observed_token1) == (T0, T1)
    assert evidence.block_number == 123
    assert evidence.discovery_consistency == "PAIR_TOKENS_MATCH_DISCOVERY_EVENT"
    assert len(evidence.sources) == 2
    assert evidence.pair_code.block_number == 123


def test_pair_identity_records_discovery_conflict_without_calling_pair_authentic():
    evidence = observe_pair_token_identity(
        [observer("https://one.example", T1, T0), observer("https://two.example", T1, T0)],
        pool(), block_number=123,
    )
    assert evidence.discovery_consistency == "PAIR_TOKENS_CONFLICT_WITH_DISCOVERY_EVENT"
    assert evidence.status == "UNVERIFIED_PAIR_TOKEN_IDENTITY_EVIDENCE"


def test_pair_identity_disagreement_and_malformed_evidence_fail_closed():
    with pytest.raises(EvmRpcError, match="identity quorum"):
        observe_pair_token_identity(
            [observer("https://one.example"), observer("https://two.example", T0, OTHER)],
            pool(), block_number=123,
        )
    with pytest.raises(EvmRpcError, match="identity quorum"):
        observe_pair_token_identity(
            [observer("https://one.example"), observer("https://two.example", malformed=True)],
            pool(), block_number=123,
        )


def test_duplicate_provider_cannot_satisfy_pair_identity_quorum():
    with pytest.raises(EvmRpcError, match="insufficient distinct"):
        observe_pair_token_identity(
            [observer("https://same.example"), observer("https://same.example")],
            pool(), block_number=123,
        )


def test_pair_path_consistency_matches_only_adjacent_hops():
    evidence = observe_pair_token_identity(
        [observer("https://one.example"), observer("https://two.example")],
        pool(), block_number=123,
    )
    matched = compare_pair_to_router_path(evidence, semantics((OTHER, T0, T1)))
    assert matched.verdict == "PAIR_MATCHES_ROUTER_PATH_HOP"
    assert matched.matching_hops == (1,)

    missing = compare_pair_to_router_path(evidence, semantics((T0, OTHER, T1)))
    assert missing.verdict == "PAIR_NOT_PRESENT_IN_ROUTER_PATH"


def test_unverified_router_semantics_stays_unknown():
    evidence = observe_pair_token_identity(
        [observer("https://one.example"), observer("https://two.example")],
        pool(), block_number=123,
    )
    result = compare_pair_to_router_path(evidence, semantics((), "UNSUPPORTED_ROUTER_SELECTOR"))
    assert result.verdict == "UNKNOWN_PATH_SEMANTICS"
