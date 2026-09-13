from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_implementation_registry import ImplementationFingerprintEntry
from stinky_core.evm_reference_classification import classify_reference_bundle_component
from stinky_core.evm_reference_materialization import ReferenceFingerprintBundle

ADDRESS = "0x" + "11" * 20
DIGEST = "a" * 64


def evidence(*, digest=DIGEST, block=100):
    return ContractCodeEvidence(
        chain="base",
        chain_id=8453,
        address=ADDRESS,
        contract_key="base:" + ADDRESS,
        block_number=block,
        byte_length=2,
        fingerprint_sha256=digest,
        runtime_bytecode="0x6001",
        status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=(
            ContractCodeSource("provider-a", digest, 2),
            ContractCodeSource("provider-b", digest, 2),
        ),
    )


def entry(*, family="UNISWAP_V3", version="1", role="ROUTER", source="source-a"):
    return ImplementationFingerprintEntry(
        fingerprint_sha256=DIGEST,
        byte_length=2,
        contract_role=role,
        implementation_family=family,
        implementation_version=version,
        source_kind="PINNED_GITHUB_DEPLOYMENT_REFERENCE",
        source_reference=source,
        chains=("base",),
    )


def bundle(entries, *, block=100, refs=None, status="UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE"):
    rows = tuple(entries)
    return ReferenceFingerprintBundle(
        entries=rows,
        source_references=tuple(refs if refs is not None else [row.source_reference for row in rows]),
        chain_blocks=(("base", block),),
        status=status,
        limitations=("REFERENCE_BUNDLE_DOES_NOT_PROVE_COMPONENT_AUTHENTICITY",),
    )


def test_exact_bundle_match_preserves_provenance_and_snapshot():
    result = classify_reference_bundle_component(
        evidence(), bundle((entry(),)), expected_role="ROUTER"
    )
    assert result.verdict == "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
    assert result.block_number == 100
    assert result.expected_role == "ROUTER"
    assert result.matches[0].implementation_family == "UNISWAP_V3"
    assert result.matches[0].source_reference == "source-a"


def test_unknown_code_stays_unknown():
    result = classify_reference_bundle_component(
        evidence(digest="b" * 64), bundle((entry(),)), expected_role="ROUTER"
    )
    assert result.verdict == "UNKNOWN_IMPLEMENTATION_FINGERPRINT"
    assert result.matches == ()


def test_conflicting_bundle_identities_stay_ambiguous():
    rows = (
        entry(family="UNISWAP_V3", source="source-a"),
        entry(family="OTHER_FAMILY", source="source-b"),
    )
    result = classify_reference_bundle_component(evidence(), bundle(rows), expected_role="ROUTER")
    assert result.verdict == "AMBIGUOUS_IMPLEMENTATION_FINGERPRINT"
    assert {match.implementation_family for match in result.matches} == {"UNISWAP_V3", "OTHER_FAMILY"}


def test_snapshot_chain_and_status_mismatches_fail_closed():
    with pytest.raises(ValueError, match="does not match reference bundle snapshot"):
        classify_reference_bundle_component(evidence(block=99), bundle((entry(),)), expected_role="ROUTER")

    missing_chain = ReferenceFingerprintBundle(
        entries=(entry(),),
        source_references=("source-a",),
        chain_blocks=(("robinhood", 100),),
        status="UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE",
        limitations=(),
    )
    with pytest.raises(ValueError, match="no historical block"):
        classify_reference_bundle_component(evidence(), missing_chain, expected_role="ROUTER")

    with pytest.raises(ValueError, match="status is not supported"):
        classify_reference_bundle_component(
            evidence(), bundle((entry(),), status="OTHER"), expected_role="ROUTER"
        )


def test_role_semantics_are_delegated_to_registry_classifier():
    result = classify_reference_bundle_component(
        evidence(), bundle((entry(role="FACTORY"),)), expected_role="ROUTER"
    )
    assert result.verdict == "UNKNOWN_IMPLEMENTATION_FINGERPRINT"

    with pytest.raises(ValueError, match="expected_role"):
        classify_reference_bundle_component(evidence(), bundle((entry(),)), expected_role="UNKNOWN")


def test_malformed_bundle_provenance_and_block_metadata_fail_closed():
    with pytest.raises(ValueError, match="provenance"):
        classify_reference_bundle_component(
            evidence(), bundle((entry(),), refs=("other-source",)), expected_role="ROUTER"
        )

    duplicate_refs = bundle((entry(source="same"),), refs=("same", "same"))
    with pytest.raises(ValueError, match="duplicate source references"):
        classify_reference_bundle_component(evidence(), duplicate_refs, expected_role="ROUTER")

    duplicate_chain = ReferenceFingerprintBundle(
        entries=(entry(),),
        source_references=("source-a",),
        chain_blocks=(("base", 100), ("base", 100)),
        status="UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE",
        limitations=(),
    )
    with pytest.raises(ValueError, match="duplicate chain block metadata"):
        classify_reference_bundle_component(evidence(), duplicate_chain, expected_role="ROUTER")
