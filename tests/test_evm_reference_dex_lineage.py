from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

import stinky_core.evm_reference_dex_lineage as lineage_module
from stinky_core.evm_reference_deployment_identity import ReferenceDeploymentIdentityAssessment
from stinky_core.evm_reference_dex_authenticity import ReferenceDexAuthenticityAssessment
from stinky_core.evm_reference_dex_identity import ReferenceDexIdentityAssessment
from stinky_core.evm_reference_dex_lineage import (
    compose_reference_dex_lineage,
    compose_reference_dex_lineage_from_record,
)
from stinky_core.evm_reference_source_alignment import ReferenceSourceAlignmentAssessment


FACTORY = "0x" + "11" * 20
POOL = "0x" + "22" * 20
ROUTER = "0x" + "33" * 20


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


def dep(role, address=FACTORY, verdict="PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"):
    return ReferenceDeploymentIdentityAssessment(
        "base", address, role, (), verdict,
        "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT", (),
    )


def identity(verdict="REFERENCE_DEX_IDENTITY_CONFIRMED"):
    return ReferenceDexIdentityAssessment(
        impl(), dep("FACTORY", FACTORY), dep("POOL", POOL), dep("ROUTER", ROUTER), verdict,
        "UNVERIFIED_REFERENCE_DEX_IDENTITY_ASSESSMENT", (),
    )


def alignment(role, verdict="REFERENCE_SOURCE_LINEAGE_ALIGNED"):
    return ReferenceSourceAlignmentAssessment(
        role, (("UNISWAP_V2", "v1"),), (("UNISWAP_V2", "v1"),), verdict,
        "UNVERIFIED_REFERENCE_SOURCE_ALIGNMENT_ASSESSMENT", (),
    )


def fake_record():
    return SimpleNamespace(
        envelope=SimpleNamespace(
            factory_fingerprint=SimpleNamespace(expected_role="FACTORY", marker="factory"),
            pool_fingerprint=SimpleNamespace(expected_role="POOL", marker="pool"),
            router_fingerprint=SimpleNamespace(expected_role="ROUTER", marker="router"),
        )
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


def test_record_backed_helper_uses_exact_preserved_components(monkeypatch):
    record = fake_record()
    expected_identity = identity()
    seen = []

    monkeypatch.setattr(
        lineage_module,
        "compose_reference_dex_identity_from_record",
        lambda supplied_record, sources: expected_identity,
    )

    def assess(component, deployment, sources):
        seen.append((component, deployment, sources))
        return alignment(component.expected_role)

    monkeypatch.setattr(lineage_module, "assess_reference_source_alignment", assess)
    sources = (SimpleNamespace(source_reference="one"),)
    result = compose_reference_dex_lineage_from_record(record, sources)

    assert result.verdict == "REFERENCE_DEX_LINEAGE_IDENTITY_CONFIRMED"
    assert seen[0][0] is record.envelope.factory_fingerprint
    assert seen[1][0] is record.envelope.pool_fingerprint
    assert seen[2][0] is record.envelope.router_fingerprint
    assert seen[0][1] is expected_identity.factory_deployment
    assert seen[1][1] is expected_identity.pool_deployment
    assert seen[2][1] is expected_identity.router_deployment
    assert all(item[2] == sources for item in seen)


def test_record_backed_helper_preserves_unknown_pool(monkeypatch):
    record = fake_record()
    expected_identity = identity("UNKNOWN_REFERENCE_DEX_IDENTITY")
    monkeypatch.setattr(
        lineage_module,
        "compose_reference_dex_identity_from_record",
        lambda supplied_record, sources: expected_identity,
    )

    def assess(component, deployment, sources):
        if component.expected_role == "POOL":
            return alignment("POOL", "UNKNOWN_REFERENCE_SOURCE_LINEAGE_ALIGNMENT")
        return alignment(component.expected_role)

    monkeypatch.setattr(lineage_module, "assess_reference_source_alignment", assess)
    result = compose_reference_dex_lineage_from_record(record, ())
    assert result.pool_alignment.verdict == "UNKNOWN_REFERENCE_SOURCE_LINEAGE_ALIGNMENT"
    assert result.verdict == "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY"


def test_record_backed_helper_propagates_known_lineage_conflict(monkeypatch):
    record = fake_record()
    monkeypatch.setattr(
        lineage_module,
        "compose_reference_dex_identity_from_record",
        lambda supplied_record, sources: identity(),
    )

    def assess(component, deployment, sources):
        verdict = (
            "REFERENCE_SOURCE_LINEAGE_CONFLICT"
            if component.expected_role == "ROUTER"
            else "REFERENCE_SOURCE_LINEAGE_ALIGNED"
        )
        return alignment(component.expected_role, verdict)

    monkeypatch.setattr(lineage_module, "assess_reference_source_alignment", assess)
    result = compose_reference_dex_lineage_from_record(record, ())
    assert result.router_alignment.verdict == "REFERENCE_SOURCE_LINEAGE_CONFLICT"
    assert result.verdict == "REFERENCE_DEX_LINEAGE_IDENTITY_CONFLICT"
