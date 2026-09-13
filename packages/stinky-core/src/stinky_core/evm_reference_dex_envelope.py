"""Preserve reference-bundle provenance with composed DEX-family evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_contract_code import ContractCodeEvidence
from .evm_dex_family_composition import DexFamilyConsistencyEvidence, compose_dex_family_consistency
from .evm_factory_evidence import FactoryRelationshipEvidence
from .evm_family_composition import compose_factory_pool_family_consistency
from .evm_implementation_registry import ImplementationFingerprintEvidence
from .evm_reference_classification import classify_reference_bundle_component
from .evm_reference_materialization import ReferenceFingerprintBundle


@dataclass(frozen=True, slots=True)
class ReferenceDexEvidenceEnvelope:
    source_references: tuple[str, ...]
    chain_blocks: tuple[tuple[str, int], ...]
    factory_fingerprint: ImplementationFingerprintEvidence
    pool_fingerprint: ImplementationFingerprintEvidence
    router_fingerprint: ImplementationFingerprintEvidence
    dex_family: DexFamilyConsistencyEvidence
    status: str
    limitations: tuple[str, ...]


def compose_reference_dex_evidence_envelope(
    relationship: FactoryRelationshipEvidence,
    factory_code: ContractCodeEvidence,
    pool_code: ContractCodeEvidence,
    router_code: ContractCodeEvidence,
    bundle: ReferenceFingerprintBundle,
) -> ReferenceDexEvidenceEnvelope:
    """Classify one DEX snapshot and retain all component and bundle provenance."""
    if factory_code.address != relationship.factory_address:
        raise ValueError("factory code address does not match relationship")
    if pool_code.address != relationship.pool_address:
        raise ValueError("pool code address does not match relationship")
    components = (factory_code, pool_code, router_code)
    if any(item.chain != relationship.chain for item in components):
        raise ValueError("component code evidence must share relationship chain")
    if any(item.block_number != relationship.block_number for item in components):
        raise ValueError("component code evidence must share relationship historical block")

    factory = classify_reference_bundle_component(factory_code, bundle, expected_role="FACTORY")
    pool = classify_reference_bundle_component(pool_code, bundle, expected_role="POOL")
    router = classify_reference_bundle_component(router_code, bundle, expected_role="ROUTER")
    factory_pool = compose_factory_pool_family_consistency(relationship, factory, pool)
    dex_family = compose_dex_family_consistency(factory_pool, router)

    return ReferenceDexEvidenceEnvelope(
        source_references=bundle.source_references,
        chain_blocks=bundle.chain_blocks,
        factory_fingerprint=factory,
        pool_fingerprint=pool,
        router_fingerprint=router,
        dex_family=dex_family,
        status="UNVERIFIED_REFERENCE_DEX_EVIDENCE_ENVELOPE",
        limitations=(
            "REFERENCE_DEX_ENVELOPE_DOES_NOT_PROVE_DEPLOYMENT_PROVENANCE",
            "REFERENCE_DEX_ENVELOPE_DOES_NOT_PROVE_COMPONENT_AUTHENTICITY",
            "REFERENCE_DEX_ENVELOPE_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "REFERENCE_DEX_ENVELOPE_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
        ),
    )
