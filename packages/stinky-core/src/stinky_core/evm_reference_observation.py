"""Read-only observation pipeline for pinned DEX reference catalogs."""
from __future__ import annotations

from typing import Iterable, Mapping

from .evm_contract_code import ContractCodeEvidence, observe_contract_code
from .evm_reference_fingerprints import DexReferenceContractSource
from .evm_reference_materialization import (
    ReferenceFingerprintBundle,
    materialize_reference_fingerprint_bundle,
)
from .evm_rpc import EvmReadOnlyRpc


def observe_reference_fingerprint_bundle(
    sources: Iterable[DexReferenceContractSource],
    observers_by_chain: Mapping[str, Iterable[EvmReadOnlyRpc]],
    *,
    block_numbers: Mapping[str, int],
    min_quorum: int = 2,
) -> ReferenceFingerprintBundle:
    """Observe every pinned reference at explicit historical blocks and materialize it.

    The caller must select one historical block for every source chain. Genesis does
    not infer a latest block here. Every source address is observed read-only through
    the existing exact contract-code quorum path, then the complete measurement set
    is handed unchanged to the #218 fail-closed materializer.
    """
    source_list = tuple(sources)
    if not source_list:
        raise ValueError("reference observation requires sources")
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")

    source_chains = {source.chain for source in source_list}
    blocks = dict(block_numbers)
    if set(blocks) != source_chains:
        raise ValueError("block map must cover reference chains exactly")
    if any(not isinstance(block, int) or isinstance(block, bool) or block < 0 for block in blocks.values()):
        raise ValueError("block numbers must be non-negative integers")

    observer_map = dict(observers_by_chain)
    if set(observer_map) != source_chains:
        raise ValueError("observer map must cover reference chains exactly")

    observers: dict[str, tuple[EvmReadOnlyRpc, ...]] = {}
    for chain, items in observer_map.items():
        rows = tuple(items)
        if len(rows) < min_quorum:
            raise ValueError("observer map must provide enough RPC observers per chain")
        if any(observer.chain.key != chain for observer in rows):
            raise ValueError("observer chain does not match observer map key")
        observers[chain] = rows

    evidence_items: list[ContractCodeEvidence] = []
    seen: set[tuple[str, str]] = set()
    for source in sorted(source_list, key=lambda item: item.source_reference):
        key = (source.chain, source.address)
        if key in seen:
            raise ValueError("duplicate reference source chain address")
        seen.add(key)
        evidence_items.append(
            observe_contract_code(
                observers[source.chain],
                chain=source.chain,
                address=source.address,
                block_number=blocks[source.chain],
                min_quorum=min_quorum,
            )
        )

    return materialize_reference_fingerprint_bundle(
        source_list,
        evidence_items,
        expected_block_numbers=blocks,
    )
