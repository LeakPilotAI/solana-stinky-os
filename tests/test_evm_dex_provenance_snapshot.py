from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_dex_provenance_explanation import explain_dex_provenance
from stinky_core.evm_dex_provenance_interpretation import DexProvenanceInterpretation
import stinky_core.evm_dex_provenance_snapshot as snapshot_module
from stinky_core.evm_dex_provenance_snapshot import (
    snapshot_dex_provenance_explanation,
    snapshot_dex_provenance_from_record,
)


def explanation(category, profile_verdict, strict_verdict, pool_verdict, factory_verdict):
    profile = SimpleNamespace(
        verdict=profile_verdict,
        strict_lineage=SimpleNamespace(verdict=strict_verdict),
        pool_evidence_tier=SimpleNamespace(
            verdict=pool_verdict,
            factory_attestation=SimpleNamespace(verdict=factory_verdict),
        ),
    )
    return explain_dex_provenance(DexProvenanceInterpretation(profile, category, "DESCRIPTIVE", ()))


def test_snapshot_preserves_exact_explanation_and_transport_fields():
    source = explanation(
        "FACTORY_ATTESTED_BUT_NOT_STRICTLY_PINNED",
        "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY",
        "FACTORY_HISTORICALLY_ATTESTS_POOL",
    )
    result = snapshot_dex_provenance_explanation(source)
    assert result.explanation is source
    assert result.category == "FACTORY_ATTESTED_BUT_NOT_STRICTLY_PINNED"
    assert result.profile_verdict == "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE"
    assert result.strict_lineage_verdict == "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY"
    assert result.pool_evidence_tier_verdict == "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY"
    assert result.factory_attestation_verdict == "FACTORY_HISTORICALLY_ATTESTS_POOL"
    assert result.limitations is source.limitations


def test_unknown_and_conflict_remain_explicit():
    unknown = snapshot_dex_provenance_explanation(explanation(
        "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    ))
    conflict = snapshot_dex_provenance_explanation(explanation(
        "CONFLICTED_PROVENANCE",
        "DEX_PROVENANCE_CONFLICT",
        "REFERENCE_DEX_LINEAGE_IDENTITY_CONFLICT",
        "POOL_DEPLOYMENT_EVIDENCE_CONFLICT",
        "FACTORY_ATTESTED_POOL_RELATIONSHIP_CONFLICT",
    ))
    assert unknown.category == "UNKNOWN_OR_INSUFFICIENT_PROVENANCE"
    assert conflict.category == "CONFLICTED_PROVENANCE"


def test_snapshot_is_immutable():
    result = snapshot_dex_provenance_explanation(explanation(
        "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    ))
    with pytest.raises(FrozenInstanceError):
        result.category = "STRICT_PINNED_PROVENANCE"


def test_tampered_summary_fails_closed():
    source = explanation(
        "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    )
    bad = type(source)(source.interpretation, ("PROFILE_VERDICT=WRONG",), source.status, source.limitations)
    with pytest.raises(ValueError):
        snapshot_dex_provenance_explanation(bad)


def test_record_backed_snapshot_reuses_exact_explanation_and_one_shot_sources(monkeypatch):
    record = object()
    source_items = (SimpleNamespace(name="one"), SimpleNamespace(name="two"))
    produced = explanation(
        "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    )
    seen = []

    def compose(supplied_record, supplied_sources):
        seen.append((supplied_record, supplied_sources))
        return produced

    monkeypatch.setattr(snapshot_module, "explain_dex_provenance_from_record", compose)
    result = snapshot_dex_provenance_from_record(record, iter(source_items))

    assert seen == [(record, source_items)]
    assert result.explanation is produced
    assert result.category == "UNKNOWN_OR_INSUFFICIENT_PROVENANCE"
