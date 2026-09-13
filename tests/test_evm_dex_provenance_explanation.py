from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

import stinky_core.evm_dex_provenance_explanation as explanation_module
from stinky_core.evm_dex_provenance_explanation import (
    explain_dex_provenance,
    explain_dex_provenance_from_record,
)
from stinky_core.evm_dex_provenance_interpretation import DexProvenanceInterpretation


def item(category, profile_verdict, strict_verdict, pool_verdict, factory_verdict):
    profile = SimpleNamespace(
        verdict=profile_verdict,
        strict_lineage=SimpleNamespace(verdict=strict_verdict),
        pool_evidence_tier=SimpleNamespace(
            verdict=pool_verdict,
            factory_attestation=SimpleNamespace(verdict=factory_verdict),
        ),
    )
    return DexProvenanceInterpretation(profile, category, "DESCRIPTIVE", ())


def test_exact_evidence_is_summarized():
    source = item(
        "STRICT_PINNED_PROVENANCE",
        "STRICT_EXTERNALLY_PINNED_DEX_PROVENANCE_CONFIRMED",
        "REFERENCE_DEX_LINEAGE_IDENTITY_CONFIRMED",
        "EXTERNALLY_PINNED_POOL_DEPLOYMENT_MATCH",
        "FACTORY_HISTORICALLY_ATTESTS_POOL",
    )
    result = explain_dex_provenance(source)
    assert result.interpretation is source
    assert result.evidence_summary[1] == "STRICT_LINEAGE_VERDICT=REFERENCE_DEX_LINEAGE_IDENTITY_CONFIRMED"


def test_factory_attested_keeps_strict_unknown():
    result = explain_dex_provenance(item(
        "FACTORY_ATTESTED_BUT_NOT_STRICTLY_PINNED",
        "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY",
        "FACTORY_HISTORICALLY_ATTESTS_POOL",
    ))
    assert "STRICT_LINEAGE_VERDICT=UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY" in result.evidence_summary


def test_unknown_stays_unknown():
    result = explain_dex_provenance(item(
        "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    ))
    assert result.evidence_summary[0] == "PROFILE_VERDICT=UNKNOWN_DEX_PROVENANCE_PROFILE"


def test_mismatch_fails_closed():
    bad = item(
        "STRICT_PINNED_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    )
    try:
        explain_dex_provenance(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("mismatch must fail closed")


def test_record_backed_helper_reuses_same_record_and_source_tuple(monkeypatch):
    record = object()
    source_items = (SimpleNamespace(name="one"), SimpleNamespace(name="two"))
    profile = item(
        "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    ).provenance_profile
    seen = []

    def compose(supplied_record, supplied_sources):
        seen.append((supplied_record, supplied_sources))
        return profile

    monkeypatch.setattr(explanation_module, "compose_dex_provenance_profile_from_record", compose)
    result = explain_dex_provenance_from_record(record, iter(source_items))

    assert seen == [(record, source_items)]
    assert result.interpretation.provenance_profile is profile
    assert result.interpretation.category == "UNKNOWN_OR_INSUFFICIENT_PROVENANCE"
