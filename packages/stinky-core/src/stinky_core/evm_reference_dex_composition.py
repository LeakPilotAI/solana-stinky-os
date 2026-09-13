"""Compose DEX family evidence from one measured reference bundle."""
from __future__ import annotations

from .evm_contract_code import ContractCodeEvidence
from .evm_dex_family_composition import compose_dex_family_consistency
from .evm_factory_evidence import FactoryRelationshipEvidence
from .evm_family_composition import compose_factory_pool_family_consistency
from .evm_reference_classification import classify_reference_bundle_component
from .evm_reference_materialization import ReferenceFingerprintBundle


def compose_reference_bundle_dex_family(
    relationship: FactoryRelationshipEvidence,
    factory_code: ContractCodeEvidence,
    pool_code: ContractCodeEvidence,
    router_code: ContractCodeEvidence,
    bundle: ReferenceFingerprintBundle,
):
    """Classify FACTORY/POOL/ROUTER from one bundle and compose existing verdicts."""
    if factory_code.address != relationship.factory_address:
        raise ValueError("factory code address does not match relationship")
    if pool_code.address != relationship.pool_address:
        raise ValueError("pool code address does not match relationship")
    if any(item.chain != relationship.chain for item in (factory_code, pool_code, router_code)):
        raise ValueError("component code evidence must share relationship chain")
    if any(item.block_number != relationship.block_number for item in (factory_code, pool_code, router_code)):
        raise ValueError("component code evidence must share relationship historical block")

    factory = classify_reference_bundle_component(factory_code, bundle, expected_role="FACTORY")
    pool = classify_reference_bundle_component(pool_code, bundle, expected_role="POOL")
    router = classify_reference_bundle_component(router_code, bundle, expected_role="ROUTER")
    factory_pool = compose_factory_pool_family_consistency(relationship, factory, pool)
    return compose_dex_family_consistency(factory_pool, router)
