from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

import stinky_core.evm_pool_deployment_evidence_tier as tier_module
from stinky_core.evm_factory_attested_pool import FactoryAttestedPoolDeploymentEvidence
from stinky_core.evm_pool_deployment_evidence_tier import (
    assess_pool_deployment_evidence_tier,
    assess_pool_deployment_evidence_tier_from_record,
)
from stinky_core.evm_reference_deployment_identity import ReferenceDeploymentIdentityAssessment

POOL = "0x" + "22" * 20
FACTORY = "0x" + "11" * 20


def pinned(verdict, address=POOL, role="POOL"):
    refs = ("github:Example/dex@" + "a" * 40 + ":addresses#pool",) if verdict == "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH" else ()
    return ReferenceDeploymentIdentityAssessment(
        "base", address, role, refs, verdict,
        "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT", (),
    )


def attested(verdict, address=POOL, relationship=None):
    return FactoryAttestedPoolDeploymentEvidence(
        relationship, "base", FACTORY, address, 123, verdict,
        "UNVERIFIED_FACTORY_ATTESTED_POOL_DEPLOYMENT_EVIDENCE", (),
    )


def test_externally_pinned_pool_is_strongest_tier():
    result = assess_pool_deployment_evidence_tier(
        pinned("PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"),
        attested("FACTORY_HISTORICALLY_ATTESTS_POOL"),
    )
    assert result.tier == "EXTERNALLY_PINNED_POOL_DEPLOYMENT"
    assert result.verdict == "EXTERNALLY_PINNED_POOL_DEPLOYMENT_MATCH"


def test_factory_attested_only_stays_distinct_from_pinned_provenance():
    result = assess_pool_deployment_evidence_tier(
        pinned("UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"),
        attested("FACTORY_HISTORICALLY_ATTESTS_POOL"),
    )
    assert result.tier == "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY"
    assert result.verdict == "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY"
    assert "FACTORY_ATTESTATION_IS_NOT_EXTERNALLY_PINNED_DEPLOYMENT_PROVENANCE" in result.limitations


def test_known_conflict_outranks_other_evidence():
    result = assess_pool_deployment_evidence_tier(
        pinned("PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"),
        attested("FACTORY_ATTESTED_POOL_RELATIONSHIP_CONFLICT"),
    )
    assert result.verdict == "POOL_DEPLOYMENT_EVIDENCE_CONFLICT"


def test_unknown_sources_remain_unknown():
    result = assess_pool_deployment_evidence_tier(
        pinned("UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"),
        attested("UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT"),
    )
    assert result.verdict == "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE"


def test_chain_address_and_role_mismatch_fail_closed():
    for deployment, factory in (
        (pinned("UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", role="ROUTER"), attested("UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT")),
        (pinned("UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY", address="0x" + "33" * 20), attested("UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT")),
    ):
        try:
            assess_pool_deployment_evidence_tier(deployment, factory)
        except ValueError:
            pass
        else:
            raise AssertionError("mismatched pool evidence must fail closed")


def test_record_backed_helper_uses_preserved_pool_and_relationship(monkeypatch):
    relationship = object()
    record = SimpleNamespace(
        relationship=relationship,
        envelope=SimpleNamespace(
            pool_fingerprint=SimpleNamespace(chain="base", address=POOL),
        ),
    )
    expected_pinned = pinned("UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY")
    expected_attested = attested("FACTORY_HISTORICALLY_ATTESTS_POOL", relationship=relationship)
    calls = {}

    def fake_pinned(chain, address, sources, *, expected_role):
        calls["pinned"] = (chain, address, sources, expected_role)
        return expected_pinned

    def fake_attested(value):
        calls["relationship"] = value
        return expected_attested

    monkeypatch.setattr(tier_module, "assess_reference_deployment_address", fake_pinned)
    monkeypatch.setattr(tier_module, "assess_factory_attested_pool_deployment", fake_attested)

    result = assess_pool_deployment_evidence_tier_from_record(record, ("source-a", "source-b"))
    assert calls["pinned"] == ("base", POOL, ("source-a", "source-b"), "POOL")
    assert calls["relationship"] is relationship
    assert result.pinned_deployment is expected_pinned
    assert result.factory_attestation is expected_attested
    assert result.verdict == "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY"


def test_record_backed_helper_preserves_unknown_without_pinned_pool_source(monkeypatch):
    relationship = object()
    record = SimpleNamespace(
        relationship=relationship,
        envelope=SimpleNamespace(
            pool_fingerprint=SimpleNamespace(chain="base", address=POOL),
        ),
    )
    monkeypatch.setattr(
        tier_module,
        "assess_reference_deployment_address",
        lambda *args, **kwargs: pinned("UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"),
    )
    monkeypatch.setattr(
        tier_module,
        "assess_factory_attested_pool_deployment",
        lambda value: attested("UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT", relationship=value),
    )
    result = assess_pool_deployment_evidence_tier_from_record(record, ())
    assert result.verdict == "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE"
