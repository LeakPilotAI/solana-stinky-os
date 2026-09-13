from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

import stinky_core.evm_router_semantics as semantics
from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_implementation_registry import ImplementationFingerprintEntry
from stinky_core.evm_router_fingerprint import classify_router_implementation
from stinky_core.evm_router_swap import RouterSwapCallEvidence, _normalize_calldata

ROUTER = "0x" + "11" * 20
CALLER = "0x" + "22" * 20
DIGEST = "ab" * 32


def router_code(*, chain="base", address=ROUTER, block=100):
    return ContractCodeEvidence(
        chain=chain,
        chain_id=8453,
        address=address,
        contract_key=f"{chain}:{address}",
        block_number=block,
        byte_length=5,
        fingerprint_sha256=DIGEST,
        runtime_bytecode="0x6001600055",
        status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=(ContractCodeSource("provider-a", DIGEST, 5), ContractCodeSource("provider-b", DIGEST, 5)),
    )


def router_call(*, chain="base", router=ROUTER, block=100, code=None):
    return RouterSwapCallEvidence(
        chain=chain,
        router=router,
        caller=CALLER,
        block_number=block,
        calldata="0x12345678",
        value=0,
        router_code=code or router_code(chain=chain, address=router, block=block),
        successful_providers=("provider-a", "provider-b"),
        provider_evidence=(),
        agreed_result="0x",
        verdict="ROUTER_SWAP_CALL_QUORUM_SUCCEEDED",
        status="UNVERIFIED_ROUTER_SWAP_CALL_EVIDENCE",
        limitations=(),
    )


def registry_entry(*, family="REFERENCE_ROUTER", version="1", source="fixture"):
    return ImplementationFingerprintEntry(
        fingerprint_sha256=DIGEST,
        byte_length=5,
        contract_role="ROUTER",
        implementation_family=family,
        implementation_version=version,
        source_kind="TEST_PROVENANCE",
        source_reference=source,
        chains=("base",),
    )


def test_router_calldata_validation_preserves_canonical_hex():
    assert _normalize_calldata("0x12345678") == "0x12345678"
    assert _normalize_calldata("0xABCDEF1200") == "0xabcdef1200"


def test_router_calldata_validation_fails_closed():
    with pytest.raises(ValueError, match="4-byte selector"):
        _normalize_calldata("0x12")
    with pytest.raises(ValueError, match="valid hex"):
        _normalize_calldata("0x1234567z")
    with pytest.raises(ValueError, match="0x-prefixed"):
        _normalize_calldata("12345678")


def test_unknown_semantic_selector_stays_unresolved():
    result = semantics.decode_router_calldata(chain="base", calldata="0x12345678")
    assert result.status == "UNSUPPORTED_ROUTER_SELECTOR"
    assert result.signature is None


def test_supported_selector_without_required_abi_head_fails_closed():
    selector = next(iter(semantics._SUPPORTED))
    result = semantics.decode_router_calldata(chain="base", calldata="0x" + selector)
    assert result.status == "MALFORMED_SUPPORTED_ROUTER_CALLDATA"
    assert result.amount_in is None


def test_conservative_registry_contains_only_exact_input_v2_style_shapes():
    assert len(semantics._SUPPORTED) == 3
    families = {spec[1] for spec in semantics._SUPPORTED.values()}
    assert families == {
        "UNISWAP_V2_STYLE_EXACT_INPUT_TOKEN_TO_TOKEN",
        "UNISWAP_V2_STYLE_EXACT_INPUT_TOKEN_TO_NATIVE",
        "UNISWAP_V2_STYLE_EXACT_INPUT_NATIVE_TO_TOKEN",
    }


def test_router_exact_fingerprint_match_preserves_historical_identity():
    result = classify_router_implementation(router_call(), [registry_entry()])
    assert result.verdict == "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
    assert result.expected_role == "ROUTER"
    assert result.address == ROUTER
    assert result.block_number == 100
    assert result.matches[0].implementation_family == "REFERENCE_ROUTER"


def test_router_unknown_and_ambiguous_registry_evidence_fail_closed():
    unknown = classify_router_implementation(router_call(), [])
    assert unknown.verdict == "UNKNOWN_IMPLEMENTATION_FINGERPRINT"
    ambiguous = classify_router_implementation(
        router_call(),
        [registry_entry(family="REFERENCE_ROUTER", source="a"), registry_entry(family="OTHER_ROUTER", source="b")],
    )
    assert ambiguous.verdict == "AMBIGUOUS_IMPLEMENTATION_FINGERPRINT"


def test_router_code_identity_mismatches_fail_closed():
    with pytest.raises(ValueError, match="chain"):
        classify_router_implementation(router_call(code=router_code(chain="robinhood")), [])
    with pytest.raises(ValueError, match="address"):
        classify_router_implementation(router_call(code=router_code(address="0x" + "33" * 20)), [])
    with pytest.raises(ValueError, match="historical block"):
        classify_router_implementation(router_call(code=router_code(block=99)), [])


def test_router_registry_role_is_supported_without_weakening_other_role_validation():
    entry = registry_entry()
    assert entry.contract_role == "ROUTER"
    with pytest.raises(ValueError, match="FACTORY, POOL, or ROUTER"):
        ImplementationFingerprintEntry(DIGEST, 5, "UNKNOWN", "X", "1", "TEST", "ref")
