from pathlib import Path
from types import SimpleNamespace
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_dex_provenance_explanation import explain_dex_provenance
from stinky_core.evm_dex_provenance_interpretation import DexProvenanceInterpretation
from stinky_core.evm_dex_provenance_response import serialize_dex_provenance_snapshot
from stinky_core.evm_dex_provenance_snapshot import snapshot_dex_provenance_explanation


def snapshot(category, profile_verdict, strict_verdict, pool_verdict, factory_verdict):
    profile = SimpleNamespace(
        verdict=profile_verdict,
        strict_lineage=SimpleNamespace(verdict=strict_verdict),
        pool_evidence_tier=SimpleNamespace(
            verdict=pool_verdict,
            factory_attestation=SimpleNamespace(verdict=factory_verdict),
        ),
    )
    explanation = explain_dex_provenance(
        DexProvenanceInterpretation(profile, category, "DESCRIPTIVE", ())
    )
    return snapshot_dex_provenance_explanation(explanation)


def test_serializer_returns_only_stable_json_compatible_fields():
    source = snapshot(
        "FACTORY_ATTESTED_BUT_NOT_STRICTLY_PINNED",
        "FACTORY_ATTESTED_POOL_WITH_UNCONFIRMED_STRICT_DEX_PROVENANCE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "FACTORY_ATTESTED_POOL_DEPLOYMENT_ONLY",
        "FACTORY_HISTORICALLY_ATTESTS_POOL",
    )
    result = serialize_dex_provenance_snapshot(source)

    assert result == {
        "category": source.category,
        "profile_verdict": source.profile_verdict,
        "strict_lineage_verdict": source.strict_lineage_verdict,
        "pool_evidence_tier_verdict": source.pool_evidence_tier_verdict,
        "factory_attestation_verdict": source.factory_attestation_verdict,
        "status": source.status,
        "limitations": list(source.limitations),
    }
    json.dumps(result)
    assert "explanation" not in result


def test_serializer_preserves_unknown_and_conflict_strings_exactly():
    unknown = serialize_dex_provenance_snapshot(snapshot(
        "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    ))
    conflict = serialize_dex_provenance_snapshot(snapshot(
        "CONFLICTED_PROVENANCE",
        "DEX_PROVENANCE_CONFLICT",
        "REFERENCE_DEX_LINEAGE_IDENTITY_CONFLICT",
        "POOL_DEPLOYMENT_EVIDENCE_CONFLICT",
        "FACTORY_ATTESTED_POOL_RELATIONSHIP_CONFLICT",
    ))

    assert unknown["category"] == "UNKNOWN_OR_INSUFFICIENT_PROVENANCE"
    assert unknown["profile_verdict"] == "UNKNOWN_DEX_PROVENANCE_PROFILE"
    assert conflict["category"] == "CONFLICTED_PROVENANCE"
    assert conflict["profile_verdict"] == "DEX_PROVENANCE_CONFLICT"


def test_serializer_does_not_mutate_snapshot_or_share_limitations_container():
    source = snapshot(
        "UNKNOWN_OR_INSUFFICIENT_PROVENANCE",
        "UNKNOWN_DEX_PROVENANCE_PROFILE",
        "UNKNOWN_REFERENCE_DEX_LINEAGE_IDENTITY",
        "UNKNOWN_POOL_DEPLOYMENT_EVIDENCE",
        "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT",
    )
    original_limitations = source.limitations
    result = serialize_dex_provenance_snapshot(source)
    result["limitations"].append("MUTATED_RESPONSE_ONLY")

    assert source.limitations is original_limitations
    assert "MUTATED_RESPONSE_ONLY" not in source.limitations
