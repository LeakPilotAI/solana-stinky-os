from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_reference_deployment_identity import ReferenceDeploymentIdentityAssessment
from stinky_core.evm_reference_dex_authenticity import ReferenceDexAuthenticityAssessment
from stinky_core.evm_reference_dex_identity import compose_reference_dex_identity


def impl(verdict):
    return ReferenceDexAuthenticityAssessment("EXACT_IMPLEMENTATION_FINGERPRINT_MATCH", "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH", "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH", "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL", "DEX_IMPLEMENTATION_FAMILY_CONSISTENT", verdict, "UNVERIFIED_REFERENCE_DEX_AUTHENTICITY_ASSESSMENT", ())


def dep(role, verdict, address):
    return ReferenceDeploymentIdentityAssessment("base", address, role, (), verdict, "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT", ())


def test_full_confirmation_requires_all_deployment_matches():
    result = compose_reference_dex_identity(
        impl("REFERENCE_DEX_COMPONENTS_MATCH"),
        dep("FACTORY", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", "0x" + "11" * 20),
        dep("POOL", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", "0x" + "22" * 20),
        dep("ROUTER", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", "0x" + "33" * 20),
    )
    assert result.verdict == "REFERENCE_DEX_IDENTITY_CONFIRMED"


def test_unknown_pool_keeps_identity_unknown():
    result = compose_reference_dex_identity(
        impl("REFERENCE_DEX_COMPONENTS_MATCH"),
        dep("FACTORY", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", "0x" + "11" * 20),
        dep("POOL", "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", "0x" + "22" * 20),
        dep("ROUTER", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", "0x" + "33" * 20),
    )
    assert result.verdict == "UNKNOWN_REFERENCE_DEX_IDENTITY"


def test_known_conflict_outranks_unknown():
    result = compose_reference_dex_identity(
        impl("UNKNOWN_REFERENCE_DEX_AUTHENTICITY"),
        dep("FACTORY", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT", "0x" + "11" * 20),
        dep("POOL", "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", "0x" + "22" * 20),
        dep("ROUTER", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", "0x" + "33" * 20),
    )
    assert result.verdict == "REFERENCE_DEX_IDENTITY_CONFLICT"


def test_role_order_fails_closed():
    try:
        compose_reference_dex_identity(
            impl("REFERENCE_DEX_COMPONENTS_MATCH"),
            dep("ROUTER", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", "0x" + "33" * 20),
            dep("POOL", "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", "0x" + "22" * 20),
            dep("FACTORY", "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH", "0x" + "11" * 20),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("role confusion must fail closed")
