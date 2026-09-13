"""Conservative deployment-identity assessment for pinned DEX references."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_contract_code import ContractCodeEvidence
from .evm_reference_fingerprints import DexReferenceContractSource
from .multichain_identity import canonical_chain_address

_ALLOWED_ROLES = frozenset({"FACTORY", "POOL", "ROUTER"})


@dataclass(frozen=True, slots=True)
class ReferenceDeploymentIdentityAssessment:
    chain: str
    address: str
    contract_role: str
    matching_source_references: tuple[str, ...]
    verdict: str
    status: str
    limitations: tuple[str, ...]


def assess_reference_deployment_address(
    chain: str,
    address: str,
    sources: Iterable[DexReferenceContractSource],
    *,
    expected_role: str,
) -> ReferenceDeploymentIdentityAssessment:
    """Compare one canonical chain/address identity with pinned deployment sources."""
    role = expected_role.upper()
    if role not in _ALLOWED_ROLES:
        raise ValueError("expected_role must be FACTORY, POOL, or ROUTER")
    canonical = canonical_chain_address(chain, address)
    if canonical is None:
        raise ValueError("deployment identity requires a canonical chain address")

    role_sources = tuple(
        source for source in sources
        if source.chain == chain and source.contract_role == role
    )
    exact = tuple(source for source in role_sources if source.address == canonical)

    if exact:
        verdict = "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"
    elif role_sources:
        verdict = "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT"
    else:
        verdict = "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"

    return ReferenceDeploymentIdentityAssessment(
        chain=chain,
        address=canonical,
        contract_role=role,
        matching_source_references=tuple(sorted(source.source_reference for source in exact)),
        verdict=verdict,
        status="UNVERIFIED_REFERENCE_DEPLOYMENT_IDENTITY_ASSESSMENT",
        limitations=(
            "DEPLOYMENT_IDENTITY_MATCH_DOES_NOT_PROVE_RUNTIME_IMPLEMENTATION_IDENTITY",
            "DEPLOYMENT_IDENTITY_MATCH_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED",
            "DEPLOYMENT_IDENTITY_MATCH_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "DEPLOYMENT_IDENTITY_MATCH_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "DEPLOYMENT_IDENTITY_MATCH_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
            "DEPLOYMENT_IDENTITY_DEPENDS_ON_PINNED_SOURCE_CATALOG_COVERAGE",
        ),
    )


def assess_reference_deployment_identity(
    evidence: ContractCodeEvidence,
    sources: Iterable[DexReferenceContractSource],
    *,
    expected_role: str,
) -> ReferenceDeploymentIdentityAssessment:
    """Backward-compatible wrapper around address-native deployment identity."""
    return assess_reference_deployment_address(
        evidence.chain,
        evidence.address,
        sources,
        expected_role=expected_role,
    )
