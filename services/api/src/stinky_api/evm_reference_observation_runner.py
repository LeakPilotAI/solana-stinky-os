"""Read-only orchestration for complete reference DEX provenance observation.

The runner coordinates existing quorum-backed EVM primitives at one explicitly
selected historical block. It has no scheduling, signing, transaction, admission,
opportunity, or execution surface. Persistence occurs only after all required
component code and a non-UNKNOWN factory relationship have been observed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from stinky_api.dex_provenance_collection import (
    PersistedReferenceDexEvidence,
    compose_and_persist_dex_provenance_evidence,
)
from stinky_core.evm_call_consensus import observe_exact_call
from stinky_core.evm_contract_code import (
    ContractCodeEvidence,
    observe_contract_code,
    observe_factory_contract_code,
    observe_pool_contract_code,
)
from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_factory_evidence import (
    FactoryRelationshipEvidence,
    build_factory_lookup,
    classify_factory_relationship,
)
from stinky_core.evm_reference_fingerprints import DexReferenceContractSource
from stinky_core.evm_reference_materialization import (
    ReferenceFingerprintBundle,
    materialize_reference_fingerprint_bundle,
)
from stinky_core.evm_rpc import EvmReadOnlyRpc
from stinky_core.multichain_identity import canonical_chain_address


@dataclass(frozen=True, slots=True)
class ReferenceDexObservationRun:
    relationship: FactoryRelationshipEvidence
    factory_code: ContractCodeEvidence
    pool_code: ContractCodeEvidence
    router_code: ContractCodeEvidence
    bundle: ReferenceFingerprintBundle
    persisted: PersistedReferenceDexEvidence
    block_number: int
    status: str
    limitations: tuple[str, ...]


def _validate_inputs(
    pool: DexPoolCandidate,
    router_address: str,
    sources: tuple[DexReferenceContractSource, ...],
    block_number: int,
    min_quorum: int,
) -> str:
    if not isinstance(sources, tuple):
        raise ValueError("reference observation sources must be an immutable tuple")
    if not sources:
        raise ValueError("reference observation sources must not be empty")
    if not isinstance(block_number, int) or isinstance(block_number, bool) or block_number < 0:
        raise ValueError("block_number must be a non-negative integer")
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if any(source.chain != pool.chain for source in sources):
        raise ValueError("reference observation sources must share the pool chain")

    router = canonical_chain_address(pool.chain, router_address)
    if router is None:
        raise ValueError("router_address must be canonical for the pool chain")

    observed_component_addresses = {pool.factory_address, pool.pool_address, router}
    if any(source.address not in observed_component_addresses for source in sources):
        raise ValueError("reference source is outside the runner's observed DEX components")
    return router


def _require_known_relationship(
    relationship: FactoryRelationshipEvidence,
) -> FactoryRelationshipEvidence:
    if relationship.relationship == "UNKNOWN_FACTORY_RELATIONSHIP":
        raise ValueError("factory relationship evidence is unknown or insufficient")
    return relationship


def _source_evidence_for_sources(
    sources: tuple[DexReferenceContractSource, ...],
    factory_code: ContractCodeEvidence,
    pool_code: ContractCodeEvidence,
    router_code: ContractCodeEvidence,
) -> tuple[ContractCodeEvidence, ...]:
    evidence_by_address = {
        factory_code.address: factory_code,
        pool_code.address: pool_code,
        router_code.address: router_code,
    }
    try:
        return tuple(evidence_by_address[source.address] for source in sources)
    except KeyError as exc:
        raise ValueError("reference source has no observed component code evidence") from exc


async def observe_and_persist_reference_dex_evidence(
    session: AsyncSession,
    *,
    pool: DexPoolCandidate,
    router_address: str,
    sources: tuple[DexReferenceContractSource, ...],
    observers: Iterable[EvmReadOnlyRpc],
    block_number: int,
    min_quorum: int = 2,
) -> ReferenceDexObservationRun:
    """Observe one DEX candidate at one historical block and persist only if complete."""
    router = _validate_inputs(pool, router_address, sources, block_number, min_quorum)
    observer_tuple = tuple(observers)
    if len(observer_tuple) < min_quorum:
        raise ValueError("reference observation requires enough RPC observers")
    if any(observer.chain.key != pool.chain for observer in observer_tuple):
        raise ValueError("reference observation RPC chains must match the pool chain")

    factory_code = observe_factory_contract_code(
        observer_tuple,
        pool,
        block_number=block_number,
        min_quorum=min_quorum,
    )
    pool_code = observe_pool_contract_code(
        observer_tuple,
        pool,
        block_number=block_number,
        min_quorum=min_quorum,
    )
    router_code = observe_contract_code(
        observer_tuple,
        chain=pool.chain,
        address=router,
        block_number=block_number,
        min_quorum=min_quorum,
    )

    lookup = build_factory_lookup(pool)
    call_observation = observe_exact_call(
        observer_tuple,
        chain=pool.chain,
        target=pool.factory_address,
        calldata=lookup,
        block_number=block_number,
        min_quorum=min_quorum,
    )
    relationship = _require_known_relationship(
        classify_factory_relationship(pool, factory_code, call_observation)
    )

    source_evidence = _source_evidence_for_sources(
        sources,
        factory_code,
        pool_code,
        router_code,
    )
    bundle = materialize_reference_fingerprint_bundle(
        sources,
        source_evidence,
        expected_block_numbers={pool.chain: block_number},
    )

    persisted = await compose_and_persist_dex_provenance_evidence(
        session,
        relationship=relationship,
        factory_code=factory_code,
        pool_code=pool_code,
        router_code=router_code,
        bundle=bundle,
        sources=sources,
    )
    return ReferenceDexObservationRun(
        relationship=relationship,
        factory_code=factory_code,
        pool_code=pool_code,
        router_code=router_code,
        bundle=bundle,
        persisted=persisted,
        block_number=block_number,
        status="UNVERIFIED_REFERENCE_DEX_OBSERVATION_RUN",
        limitations=(
            "REFERENCE_OBSERVATION_RUN_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "REFERENCE_OBSERVATION_RUN_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "REFERENCE_OBSERVATION_RUN_DOES_NOT_PROVE_CURRENT_CODE_UNCHANGED",
            "REFERENCE_OBSERVATION_RUN_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
            "REFERENCE_OBSERVATION_RUN_IS_NOT_AN_ADMISSION_DECISION",
            "REFERENCE_OBSERVATION_RUN_IS_NOT_AN_EXECUTION_AUTHORIZATION",
        ),
    )
