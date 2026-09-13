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


def assess_reference_deployment_identity(
    evidence: ContractCodeEvidence,
    sources: Iterable[DexReferenceContractSource],
    *,
    expected_role: str,
) -> ReferenceDeploymentIdentityAssessment:
    """Compare an observed component address with pinned deployment identities.

    A positive result means only that the observed chain/address is explicitly named
    by the pinned source catalog for the requested role. Runtime implementation
    identity, current code, safety, liquidity, and execution behavior are separate.
    """
    role = expected_role.upper()
    if role not in _ALLOWED_ROLES:
        raise ValueError("expected_role must be FACTORY, POOL, or ROUTER")
    address = canonical_chain_address(evidence.chain, evidence.address)
    if address is None:
        raise ValueError("contract code evidence must use a canonical chain address")

    role_sources = tuple(source for source in sources if source.chain == evidence.chain and source.contract_role == role)
    exact = tuple(source for source in role_sources if source.address == address)

    if exact:
        verdict = "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_MATCH"
    elif role_sources:
        verdict = "PINNED_REFERENCE_DEPLOYMENT_IDENTITY_CONFLICT"
    else:
        verdict = "UNKNOWN_REFERENCE_DEPLOYMENT_IDENTITY"

    return ReferenceDeploymentIdentityAssessment(
        chain=evidence.chain,
        address=address,
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
