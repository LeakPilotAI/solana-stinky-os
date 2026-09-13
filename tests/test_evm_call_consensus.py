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
    factory = "0x" + "11" * 20
    pool = "0x" + "44" * 20
    token0 = "0x" + "22" * 20
    token1 = "0x" + "33" * 20
    return DexPoolCandidate(
        "base", 8453, factory, "base:" + factory,
        pool, "base:" + pool,
        token0, "base:" + token0,
        token1, "base:" + token1,
        family, fee, 100,
        "0x" + "aa" * 32, "0x" + "bb" * 32, "0x1",
        "UNVERIFIED_DEX_POOL_CANDIDATE", ("rpc-a", "rpc-b"),
    )


def test_factory_lookup_shapes_and_strict_address_decode():
    v2 = build_factory_lookup(_pool())
    assert v2.startswith(V2_FACTORY_LOOKUP_SELECTOR)
    assert len(v2) == 10 + 64 + 64

    v3 = build_factory_lookup(_pool("V3_STYLE_POOL_CREATED", 3000))
    assert v3.startswith(V3_FACTORY_LOOKUP_SELECTOR)
    assert len(v3) == 10 + 64 + 64 + 64
    assert v3[-64:] == f"{3000:064x}"

    pool = "0x" + "44" * 20
    encoded = "0x" + "0" * 24 + pool[2:]
    assert decode_factory_address("base", encoded) == pool
    with pytest.raises(EvmRpcError):
        decode_factory_address("base", "0x1234")


def test_factory_lookup_rejects_unsupported_or_incomplete_shapes():
    with pytest.raises(ValueError, match="unsupported DEX pool event family"):
        build_factory_lookup(_pool("UNKNOWN"))
    with pytest.raises(ValueError, match="uint24 fee tier"):
        build_factory_lookup(_pool("V3_STYLE_POOL_CREATED", None))
