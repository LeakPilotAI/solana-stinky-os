from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

import stinky_core.evm_dex_provenance_profile as profile_module
from stinky_core.evm_dex_provenance_profile import compose_dex_provenance_profile, compose_dex_provenance_profile_from_record
from stinky_core.evm_pool_deployment_evidence_tier import PoolDeploymentEvidenceTierAssessment
from stinky_core.evm_reference_deployment_identity import ReferenceDeploymentIdentityAssessment
from stinky_core.evm_reference_dex_identity import ReferenceDexIdentityAssessment
from stinky_core.evm_reference_dex_lineage import ReferenceDexLineageAssessment

POOL = "0x" + "22" * 20


def pool_dep(verdict="PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"):
    return ReferenceDeploymentIdentityAssessment(
        "base", POOL, "POOL", (), verdict,
        "UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT", (),
    )


def strict(verdict="UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY"):
    identity = ReferenceDexIdentityAssessment(
        implementation=SimpleNamespace(),
        factory_deployment=SimpleNamespace(),
        pool_deployment=pool_dep(),
        router_deployment=SimpleNamespace(),
        verdict="UNKNOWN_REFERENCE_DEX_IDENTITY",
        status="UNVERIFIED_REFERENCE_DEX_IDENTITY_ASSESSMENT",
        limitations=(),
    )
    return ReferenceDexLineageAssessment(
        identity, SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), verdict,
        "UNVERIFIED_REFERENCE_DEX_LINEAGE_ASSESSMENT", (),
    )


def tier(verdict):
    return PoolDeploymentEvidenceTierAssessment(
        pool_dep(), SimpleNamespace(), "base", POOL, verdict, verdict,
        "UNVERIFIED_POOL_DEPLOYMENT_EVIDENCE_TIER_ASSESSMENT", (),
    )


def test_strict_confirmation_requires_externally_pinned_pool():
    result = compose_dex_provenance_profile(
        strict("REFERENCE_DEX_LINEAGE_IDENTITY_CONFIRMED"),
        tier("EXTERNALLY_PINNED_POOL_DEPLOYMENT_MATCH"),
    )
    assert result.verdict == "STRICT_EXTERNALLY_PINNED_DEX_PROVENANCE_CONFIRMED"


def test_factory_attested_only_never_upgrades_strict_identity():
    result = compose_dex_provenance_profile(
        strict(), tier("FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY")
    )
    assert result.verdict == "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE"
    assert "FACTORY_ATTESTED_POOL_EVIDENCE_DOES_NOT_UPGRADE_STRICT_DEX_IDENTITY" in result.limitations


def test_known_conflict_outranks_unknown():
    result = compose_dex_provenance_profile(
        strict("UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY"),
        tier("POOL_DEPLOYMENT_EVIDENCE_CONFLICT"),
    )
    assert result.verdict == "DEX_PROVENANCE_CONFLICT"


def test_unknown_inputs_remain_unknown():
    result = compose_dex_provenance_profile(
        strict(), tier("UNKNOWN_POOL_DEPLOYMENT_EVIDENCE")
    )
    assert result.verdict == "UNKNOWN_DEX_PROVENANCE_PROFILE"


def test_inconsistent_strict_confirmation_fails_closed():
    try:
        compose_dex_provenance_profile(
            strict("REFERENCE_DEX_LINEAGE_IDENTITY_CONFIRMED"),
            tier("FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY"),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("strict confirmation without pinned pool evidence must fail closed")


def test_record_backed_profile_reuses_same_record_and_sources(monkeypatch):
    record = object()
    sources = (SimpleNamespace(source_reference="one"),)
    expected_strict = strict()
    expected_tier = tier("FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY")
    seen = []

    def lineage(supplied_record, supplied_sources):
        seen.append(("lineage", supplied_record, supplied_sources))
        return expected_strict

    def pool(supplied_record, supplied_sources):
        seen.append(("pool", supplied_record, supplied_sources))
        return expected_tier

    monkeypatch.setattr(profile_module, "compose_reference_dex_lineage_from_record", lineage)
    monkeypatch.setattr(profile_module, "assess_pool_deployment_evidence_tier_from_record", pool)

    result = compose_dex_provenance_profile_from_record(record, sources)
    assert result.strict_lineage is expected_strict
    assert result.pool_evidence_tier is expected_tier
    assert seen == [("lineage", record, sources), ("pool", record, sources)]
