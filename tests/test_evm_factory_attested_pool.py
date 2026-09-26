from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_factory_attested_pool import assess_factory_attested_pool_deployment
from stinky_core.evm_factory_evidence import FactoryRelationshipEvidence, FactoryRelationshipSource

FACTORY = "0x" + "11" * 20
POOL = "0x" + "22" * 20
OTHER = "0x" + "33" * 20


def rel(verdict, returned=POOL, sources=None):
    if sources is None:
        sources = (FactoryRelationshipSource("a", returned), FactoryRelationshipSource("b", returned)) if returned else ()
    return FactoryRelationshipEvidence(
        "base", FACTORY, POOL, "0x" + "44" * 20, "0x" + "55" * 20,
        "V2_STYLE_PAIR_CREATED", None, 123, None, returned, sources,
        verdict, "UNVERIFIED_FACTORY_RELATIONSHIP_EVIDENCE", (),
    )


def test_match_is_historical_factory_attestation():
    source = rel("FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL")
    result = assess_factory_attested_pool_deployment(source)
    assert result.relationship is source
    assert result.verdict == "FACTORY_HISTORICALLY_ATTESTS_POOL"
    assert result.block_number == 123
    assert "FACTORY_ATTESTATION_IS_NOT_EXTERNALLY_PINNED_DEPLOYMENT_PROVENANCE" in result.limitations


def test_known_conflict_is_explicit_conflict():
    result = assess_factory_attested_pool_deployment(
        rel("FACTORY_LOOKUP_CONFLICTS_WITH_DISCOVERED_POOL", OTHER)
    )
    assert result.verdict == "FACTORY_ATTESTED_POOL_RELATIONSHIP_CONFLICT"


def test_unknown_stays_unknown():
    result = assess_factory_attested_pool_deployment(
        rel("UNKNOWN_FACTORY_RELATIONSHIP", None, ())
    )
    assert result.verdict == "UNKNOWN_FACTORY_ATTESTED_POOL_DEPLOYMENT"


def test_inconsistent_match_fails_closed():
    evidence = rel(
        "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL",
        POOL,
        (FactoryRelationshipSource("a", OTHER),),
    )
    try:
        assess_factory_attested_pool_deployment(evidence)
    except ValueError:
        pass
    else:
        raise AssertionError("inconsistent factory relationship must fail closed")


@pytest.mark.parametrize("providers", [(), ("a",), ("a", "a"), ("a", ""), ("a", " "), ("a", "b", "")])
def test_match_requires_distinct_nonempty_provider_evidence(providers):
    relationship = rel("FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL", sources=tuple(
        FactoryRelationshipSource(provider, POOL) for provider in providers
    ))
    with pytest.raises(ValueError, match="distinct provider evidence"):
        assess_factory_attested_pool_deployment(relationship)


def test_repeated_provider_does_not_add_or_remove_independent_evidence():
    relationship = rel("FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL", sources=(
        FactoryRelationshipSource("a", POOL), FactoryRelationshipSource("b", POOL),
        FactoryRelationshipSource("a", POOL),
    ))
    result = assess_factory_attested_pool_deployment(relationship)
    assert result.verdict == "FACTORY_HISTORICALLY_ATTESTS_POOL"
    assert result.relationship is relationship


def test_one_contradictory_source_is_not_discarded_despite_two_matching_sources():
    relationship = rel("FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL", sources=(
        FactoryRelationshipSource("a", POOL), FactoryRelationshipSource("b", POOL),
        FactoryRelationshipSource("c", OTHER),
    ))
    with pytest.raises(ValueError, match="sources must return"):
        assess_factory_attested_pool_deployment(relationship)
