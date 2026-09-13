from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_implementation_registry import (
    ImplementationFingerprintEvidence,
    ImplementationFingerprintMatch,
)
from stinky_core.evm_reference_deployment_identity import ReferenceDeploymentIdentityAssessment
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource
from stinky_core.evm_reference_source_alignment import assess_reference_source_alignment

ADDRESS = "0x" + "11" * 20
REF = "github:Uniswap/sdk-core@" + "a" * 40 + ":src/addresses.ts#factory"


def impl(family="UNISWAP_V2", version="v1", verdict="EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"):
    match = ImplementationFingerprintMatch(family, version, "FACTORY", "PINNED_GITHUB_DEPLOYMENT_REFERENCE", REF, ("base",))
    matches = (match,) if verdict == "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH" else ()
    return ImplementationFingerprintEvidence(
        "base", f"base:{ADDRESS}", ADDRESS, 123, "a" * 64, 2, "FACTORY",
        matches, verdict, "UNVERIFIED_IMPLEMENTATION_FINGERPRINT_EVIDENCE", (),
    )


def dep(verdict="PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", refs=(REF,)):
    return ReferenceDeploymentIdentityAssessment(
        "base", ADDRESS, "FACTORY", refs, verdict,
        "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT", (),
    )


def source(family="UNISWAP_V2", version="v1"):
    return DexReferenceContractSource(
        "base", ADDRESS, "FACTORY", family, version,
        "Uniswap/sdk-core", "a" * 40, "src/addresses.ts", "factory",
    )


def test_matching_lineage_is_aligned():
    result = assess_reference_source_alignment(impl(), dep(), (source(),))
    assert result.verdict == "REFERENCE_SOURCE_LINEAGE_ALIGNED"
    assert result.implementation_lineages == (("UNISWAP_V2", "v1"),)
    assert result.deployment_lineages == (("UNISWAP_V2", "v1"),)


def test_mixed_family_lineage_is_conflict():
    result = assess_reference_source_alignment(impl(), dep(), (source("UNISWAP_V3", "v1"),))
    assert result.verdict == "REFERENCE_SOURCE_LINEAGE_CONFLICT"


def test_missing_deployment_provenance_stays_unknown():
    result = assess_reference_source_alignment(
        impl(), dep("UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", ()), ()
    )
    assert result.verdict == "UNKNOWN_REFERENCE_SOURCE_LINEAGE_ALIGNMENT"


def test_known_deployment_conflict_outranks_unknown_implementation():
    result = assess_reference_source_alignment(
        impl(verdict="UNKNOWN_IMPLEMENTATION_FINGERPRINT"),
        dep("PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT", ()),
        (),
    )
    assert result.verdict == "REFERENCE_SOURCE_LINEAGE_CONFLICT"


def test_identity_mismatch_fails_closed():
    wrong = ReferenceDeploymentIdentityAssessment(
        "base", "0x" + "22" * 20, "FACTORY", (REF,),
        "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH",
        "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT", (),
    )
    try:
        assess_reference_source_alignment(impl(), wrong, (source(),))
    except ValueError as exc:
        assert "address" in str(exc)
    else:
        raise AssertionError("mismatched component identity must fail closed")
