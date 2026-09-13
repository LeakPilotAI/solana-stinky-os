"""Compose router implementation-family evidence with factory/pool family consistency."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_family_composition import FactoryPoolFamilyConsistencyEvidence
from .evm_implementation_registry import ImplementationFingerprintEvidence


@dataclass(frozen=True, slots=True)
class DexFamilyConsistencyEvidence:
    chain: str
    block_number: int
    factory_family: str | None
    pool_family: str | None
    router_family: str | None
    verdict: str
    status: str
    issues: tuple[str, ...]
    limitations: tuple[str, ...]


def _resolved_router_family(evidence: ImplementationFingerprintEvidence) -> str | None:
    if evidence.expected_role != "ROUTER":
        raise ValueError("router fingerprint evidence must have ROUTER role")
    if evidence.verdict != "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH":
        return None
    families = {match.implementation_family for match in evidence.matches}
    if len(families) != 1:
        return None
    return next(iter(families))


def compose_dex_family_consistency(
    factory_pool: FactoryPoolFamilyConsistencyEvidence,
    router_fingerprint: ImplementationFingerprintEvidence,
) -> DexFamilyConsistencyEvidence:
    """Combine already-resolved DEX implementation-family evidence."""
    if router_fingerprint.chain != factory_pool.chain:
        raise ValueError("router and factory/pool evidence must share chain")
    if router_fingerprint.block_number != factory_pool.block_number:
        raise ValueError("router and factory/pool evidence must share historical block")

    router_family = _resolved_router_family(router_fingerprint)
    issues: list[str] = []

    if factory_pool.verdict != "FACTORY_POOL_IMPLEMENTATION_FAMILY_CONSISTENT":
        verdict = "UNKNOWN_DEX_IMPLEMENTATION_FAMILY_CONSISTENCY"
        issues.append("FACTORY_POOL_FAMILY_NOT_CONFIRMED")
    elif router_family is None:
        verdict = "UNKNOWN_DEX_IMPLEMENTATION_FAMILY_CONSISTENCY"
        issues.append("ROUTER_IMPLEMENTATION_FAMILY_INCOMPLETE_OR_AMBIGUOUS")
    elif factory_pool.factory_family != factory_pool.pool_family:
        verdict = "UNKNOWN_DEX_IMPLEMENTATION_FAMILY_CONSISTENCY"
        issues.append("FACTORY_POOL_FAMILY_NOT_CONFIRMED")
    elif router_family == factory_pool.factory_family:
        verdict = "DEX_IMPLEMENTATION_FAMILY_CONSISTENT"
    else:
        verdict = "DEX_IMPLEMENTATION_FAMILY_CONFLICT"

    return DexFamilyConsistencyEvidence(
        chain=factory_pool.chain,
        block_number=factory_pool.block_number,
        factory_family=factory_pool.factory_family,
        pool_family=factory_pool.pool_family,
        router_family=router_family,
        verdict=verdict,
        status="UNVERIFIED_DEX_FAMILY_CONSISTENCY_EVIDENCE",
        issues=tuple(issues),
        limitations=(
            "DEX_FAMILY_CONSISTENCY_DOES_NOT_PROVE_DEPLOYMENT_PROVENANCE",
            "DEX_FAMILY_CONSISTENCY_DOES_NOT_PROVE_FACTORY_POOL_OR_ROUTER_AUTHENTICITY",
            "DEX_FAMILY_CONSISTENCY_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "DEX_FAMILY_CONSISTENCY_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "DEX_FAMILY_CONSISTENCY_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
        ),
    )
