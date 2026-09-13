from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_reference_deployment_identity import ReferenceDeploymentIdentityAssessment
from stinky_core.evm_reference_dex_authenticity import ReferenceDexAuthenticityAssessment
from stinky_core.evm_reference_dex_identity import ReferenceDexIdentityAssessment
from stinky_core.evm_reference_dex_lineage import compose_reference_dex_lineage
from stinky_core.evm_reference_source_alignment import ReferenceSourceAlignmentAssessment


def impl():
    return ReferenceDexAuthenticityAssessment(
        "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH",
        "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH",
        "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH",
        "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL",
        "DEX_IMPLEMENTATION_FAMILY_CONSISTENT",
        "REFERENCE_DEX_COMPONENTS_MATCH",
        "UNVERIFIED_REFERENCE_DEX_AUTHENTICITY_ASSESSMENT",
        (),
    )


def dep(role):
    return ReferenceDeploymentIdentityAssessment(
        "base", "0x" + "11" * 20, role, (),
        "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH",
        "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT", (),
    )


def identity(verdict="REFERENCE_DEX_IDENTITY_CONFIRMED"):
    return ReferenceDexIdentityAssessment(
        impl(), dep("FACTORY"), dep("POOL"), dep("ROUTER"), verdict,
        "UNVERIFIED_REFERENCE_DEX_IDENTITY_ASSESSMENT", (),
    )


def alignment(role, verdict="REFERENCE_SOURCE_LINEAGE_ALIGNED"):
    return ReferenceSourceAlignmentAssessment(
        role, (("UNISWAP_V2", "v1"),), (("UNISWAP_V2", "v1"),), verdict,
        "UNVERIFIED_REFERENCE_SOURCE_ALIGNMENT_ASSESSMENT", (),
    )


def test_full_confirmation_requires_all_component_lineages():
    result = compose_reference_dex_lineage(
        identity(), alignment("FACTORY"), alignment("POOL"), alignment("ROUTER")
    )
    assert result.verdict == "REFERENCE_DEX_LINEAGE_IDENTITY_CONFIRMED"


def test_missing_pool_lineage_keeps_dex_unknown():
    result = compose_reference_dex_lineage(
        identity(), alignment("FACTORY"),
        alignment("POOL", "UNKNOWN_REFERENCE_SOURCE_LINEAGE_ALIGNMENT"),
        alignment("ROUTER"),
    )
    assert result.verdict == "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY"


def test_known_lineage_conflict_outranks_unknown_identity():
    result = compose_reference_dex_lineage(
        identity("UNKNOWN_REFERENCE_DEX_IDENTITY"),
        alignment("FACTORY", "REFERENCE_SOURCE_LINEAGE_CONFLICT"),
        alignment("POOL", "UNKNOWN_REFERENCE_SOURCE_LINEAGE_ALIGNMENT"),
        alignment("ROUTER"),
    )
    assert result.verdict == "REFERENCE_DEX_LINEAGE_IDENTITY_CONFLICT"


def test_role_order_fails_closed():
    try:
        compose_reference_dex_lineage(
            identity(), alignment("ROUTER"), alignment("POOL"), alignment("FACTORY")
        )
    except ValueError:
        pass
    else:
        raise AssertionError("lineage role confusion must fail closed")


def test_positive_result_does_not_claim_safety():
    result = compose_reference_dex_lineage(
        identity(), alignment("FACTORY"), alignment("POOL"), alignment("ROUTER")
    )
    assert "DEX_LINEAGE_IDENTITY_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY" in result.limitations
    assert "DEX_LINEAGE_IDENTITY_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS" in result.limitations
