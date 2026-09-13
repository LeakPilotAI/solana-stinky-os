from pathlib import Path
import hashlib
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import (
    observe_contract_code,
    observe_factory_contract_code,
    observe_pool_contract_code,
)
from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_implementation_registry import (
    ImplementationFingerprintEntry,
    classify_implementation_fingerprint,
)
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError

FACTORY = "0x" + "11" * 20
POOL = "0x" + "44" * 20
TOKEN0 = "0x" + "22" * 20
TOKEN1 = "0x" + "33" * 20
CODE = "0x6001600055"


def observer(url, code=CODE, chain="base"):
    chain_id = "0x2105" if chain == "base" else "0x1237"

    def transport(_url, payload, timeout):
        request = json.loads(payload)
        result = chain_id if request["method"] == "eth_chainId" else code
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}

    rpc = EvmReadOnlyRpc(chain, transport=transport)
    rpc.rpc_url = url
    return rpc


def pool():
    return DexPoolCandidate(
        "base", 8453,
        FACTORY, "base:" + FACTORY,
        POOL, "base:" + POOL,
        TOKEN0, "base:" + TOKEN0,
        TOKEN1, "base:" + TOKEN1,
        "V2_STYLE_PAIR_CREATED", None,
        100, "0x" + "ab" * 32, "0x" + "cd" * 32, "0x1",
        "UNVERIFIED_DEX_POOL_CANDIDATE", ("rpc-a", "rpc-b"),
    )


def code_evidence(address=POOL):
    return observe_contract_code(
        [observer("https://one.example"), observer("https://two.example")],
        chain="base", address=address, block_number=100,
    )


def registry_entry(evidence, *, role="POOL", family="REFERENCE_V2", version="1", chains=("base",), source="fixture-a", byte_length=None):
    return ImplementationFingerprintEntry(
        fingerprint_sha256=evidence.fingerprint_sha256,
        byte_length=evidence.byte_length if byte_length is None else byte_length,
        contract_role=role,
        implementation_family=family,
        implementation_version=version,
        source_kind="TEST_PROVENANCE",
        source_reference=source,
        chains=chains,
    )


def test_exact_code_quorum_produces_unverified_fingerprint_evidence():
    evidence = code_evidence()
    expected = hashlib.sha256(bytes.fromhex(CODE[2:])).hexdigest()
    assert evidence.contract_key == "base:" + POOL
    assert evidence.fingerprint_sha256 == expected
    assert evidence.byte_length == 5
    assert evidence.status == "UNVERIFIED_CONTRACT_CODE_EVIDENCE"
    assert len(evidence.sources) == 2


def test_duplicate_provider_cannot_satisfy_code_quorum():
    with pytest.raises(EvmRpcError, match="insufficient distinct"):
        observe_contract_code(
            [observer("https://same.example"), observer("https://same.example")],
            chain="base", address=POOL, block_number=100,
        )


def test_disagreeing_code_fails_closed():
    with pytest.raises(EvmRpcError, match="quorum"):
        observe_contract_code(
            [observer("https://one.example", "0x6001"), observer("https://two.example", "0x6002")],
            chain="base", address=POOL, block_number=100,
        )


def test_empty_code_is_not_promoted_to_contract_evidence():
    with pytest.raises(EvmRpcError, match="quorum"):
        observe_contract_code(
            [observer("https://one.example", "0x"), observer("https://two.example", "0x")],
            chain="base", address=POOL, block_number=100,
        )


def test_factory_and_pool_helpers_preserve_candidate_identity():
    observers = [observer("https://one.example"), observer("https://two.example")]
    factory = observe_factory_contract_code(observers, pool(), block_number=100)
    pool_code = observe_pool_contract_code(observers, pool(), block_number=100)
    assert factory.contract_key == "base:" + FACTORY
    assert pool_code.contract_key == "base:" + POOL


def test_wrong_chain_observers_do_not_contribute():
    with pytest.raises(EvmRpcError, match="quorum"):
        observe_contract_code(
            [observer("https://one.example", chain="robinhood"), observer("https://two.example", chain="robinhood")],
            chain="base", address=POOL, block_number=100,
        )


def test_code_presence_does_not_claim_factory_authenticity():
    evidence = observe_factory_contract_code(
        [observer("https://one.example"), observer("https://two.example")],
        pool(), block_number=100,
    )
    assert evidence.status == "UNVERIFIED_CONTRACT_CODE_EVIDENCE"


def test_exact_registry_match_preserves_historical_code_identity_without_claiming_safety():
    evidence = code_evidence()
    result = classify_implementation_fingerprint(
        evidence,
        [registry_entry(evidence)],
        expected_role="POOL",
    )
    assert result.verdict == "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
    assert result.contract_key == evidence.contract_key
    assert result.block_number == 100
    assert result.observed_fingerprint_sha256 == evidence.fingerprint_sha256
    assert len(result.matches) == 1
    assert result.matches[0].implementation_family == "REFERENCE_V2"
    assert result.status == "UNVERIFIED_IMPLEMENTATION_FINGERPRINT_EVIDENCE"
    assert "EXACT_HASH_MATCH_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY" in result.limitations


def test_unknown_role_chain_and_byte_length_mismatches_stay_unknown():
    evidence = code_evidence()
    empty = classify_implementation_fingerprint(evidence, [], expected_role="POOL")
    wrong_role = classify_implementation_fingerprint(
        evidence, [registry_entry(evidence, role="FACTORY")], expected_role="POOL"
    )
    wrong_chain = classify_implementation_fingerprint(
        evidence, [registry_entry(evidence, chains=("robinhood",))], expected_role="POOL"
    )
    wrong_length = classify_implementation_fingerprint(
        evidence, [registry_entry(evidence, byte_length=evidence.byte_length + 1)], expected_role="POOL"
    )
    assert empty.verdict == "UNKNOWN_IMPLEMENTATION_FINGERPRINT"
    assert wrong_role.verdict == "UNKNOWN_IMPLEMENTATION_FINGERPRINT"
    assert wrong_chain.verdict == "UNKNOWN_IMPLEMENTATION_FINGERPRINT"
    assert wrong_length.verdict == "UNKNOWN_IMPLEMENTATION_FINGERPRINT"


def test_duplicate_registry_source_is_deduplicated_but_conflicting_identity_is_ambiguous():
    evidence = code_evidence()
    same = registry_entry(evidence, source="same-source")
    deduped = classify_implementation_fingerprint(evidence, [same, same], expected_role="POOL")
    assert deduped.verdict == "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
    assert len(deduped.matches) == 1

    conflict = classify_implementation_fingerprint(
        evidence,
        [
            registry_entry(evidence, family="REFERENCE_V2", version="1", source="source-a"),
            registry_entry(evidence, family="OTHER_FAMILY", version="9", source="source-b"),
        ],
        expected_role="POOL",
    )
    assert conflict.verdict == "AMBIGUOUS_IMPLEMENTATION_FINGERPRINT"
    assert len(conflict.matches) == 2


def test_registry_entry_validation_fails_closed_on_bad_metadata():
    evidence = code_evidence()
    with pytest.raises(ValueError, match="64 hex"):
        ImplementationFingerprintEntry("bad", evidence.byte_length, "POOL", "F", "1", "SOURCE", "ref")
    with pytest.raises(ValueError, match="positive"):
        ImplementationFingerprintEntry(evidence.fingerprint_sha256, 0, "POOL", "F", "1", "SOURCE", "ref")
    with pytest.raises(ValueError, match="FACTORY or POOL"):
        registry_entry(evidence, role="ROUTER")
    with pytest.raises(ValueError, match="provenance"):
        ImplementationFingerprintEntry(evidence.fingerprint_sha256, evidence.byte_length, "POOL", "F", "1", "", "")
    with pytest.raises(ValueError, match="expected_role"):
        classify_implementation_fingerprint(evidence, [], expected_role="ROUTER")
