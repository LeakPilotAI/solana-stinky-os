from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_call_consensus import classify_exact_results
from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_factory_evidence import (
    V2_FACTORY_LOOKUP_SELECTOR,
    V3_FACTORY_LOOKUP_SELECTOR,
    build_factory_lookup,
    decode_factory_address,
)
from stinky_core.evm_rpc import EvmRpcError

FACTORY = "0x" + "11" * 20
POOL = "0x" + "44" * 20
T0 = "0x" + "22" * 20
T1 = "0x" + "33" * 20


def candidate(family="V2_STYLE_PAIR_CREATED", fee=None):
    return DexPoolCandidate(
        "base", 8453, FACTORY, "base:" + FACTORY,
        POOL, "base:" + POOL,
        T0, "base:" + T0,
        T1, "base:" + T1,
        family, fee, 100,
        "0x" + "aa" * 32,
        "0x" + "bb" * 32,
        "0x1", "UNVERIFIED_DEX_POOL_CANDIDATE", ("rpc-a", "rpc-b"),
    )


def abi_address(address):
    return "0x" + "0" * 24 + address[2:]


def test_v2_lookup_encoding_is_deterministic():
    data = build_factory_lookup(candidate())
    assert data.startswith(V2_FACTORY_LOOKUP_SELECTOR)
    assert len(data) == 10 + 64 + 64
    assert data[-40:] == T1[2:]


def test_v3_lookup_encoding_preserves_fee_tier():
    data = build_factory_lookup(candidate("V3_STYLE_POOL_CREATED", 3000))
    assert data.startswith(V3_FACTORY_LOOKUP_SELECTOR)
    assert len(data) == 10 + 64 + 64 + 64
    assert data[-64:] == f"{3000:064x}"


def test_factory_address_decode_is_strict_and_canonical():
    assert decode_factory_address("base", abi_address(POOL)) == POOL
    with pytest.raises(EvmRpcError, match="invalid factory address response"):
        decode_factory_address("base", "0x1234")
    with pytest.raises(EvmRpcError, match="canonical ABI"):
        decode_factory_address("base", "0x" + "01" + "00" * 31)


def test_unsupported_family_and_invalid_v3_fee_fail_closed():
    with pytest.raises(ValueError, match="unsupported DEX pool event family"):
        build_factory_lookup(candidate("UNKNOWN"))
    with pytest.raises(ValueError, match="uint24 fee tier"):
        build_factory_lookup(candidate("V3_STYLE_POOL_CREATED", None))


def test_factory_results_reuse_fail_closed_exact_result_consensus():
    agreed = classify_exact_results({abi_address(POOL): ("rpc-a", "rpc-b")})
    assert agreed.verdict == "EXACT_RESULT_QUORUM"
    assert agreed.agreed_result == abi_address(POOL)

    conflict = classify_exact_results({abi_address(POOL): ("rpc-a",), abi_address(T0): ("rpc-b",)})
    assert conflict.verdict == "RESULT_DISAGREEMENT"

    insufficient = classify_exact_results({abi_address(POOL): ("rpc-a",)})
    assert insufficient.verdict == "INSUFFICIENT_RESULT_EVIDENCE"
