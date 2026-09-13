"""Deterministic materialization of pinned DEX reference fingerprints."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .evm_contract_code import ContractCodeEvidence
from .evm_implementation_registry import ImplementationFingerprintEntry
from .evm_reference_fingerprints import (
    DexReferenceContractSource,
    build_reference_fingerprint_entry,
)
from .multichain_identity import canonical_chain_address


@dataclass(frozen=True, slots=True)
class ReferenceFingerprintBundle:
    entries: tuple[ImplementationFingerprintEntry, ...]
    source_references: tuple[str, ...]
    chain_blocks: tuple[tuple[str, int], ...]
    status: str
    limitations: tuple[str, ...]


def _source_key(source: DexReferenceContractSource) -> tuple[str, str]:
    return source.chain, source.address


def _evidence_key(evidence: ContractCodeEvidence) -> tuple[str, str]:
    address = canonical_chain_address(evidence.chain, evidence.address)
    if address is None:
        raise ValueError("contract code evidence must use a canonical chain address")
    return evidence.chain, address


def materialize_reference_fingerprint_bundle(
    sources: Iterable[DexReferenceContractSource],
    evidence_items: Iterable[ContractCodeEvidence],
    *,
    expected_block_numbers: Mapping[str, int] | None = None,
) -> ReferenceFingerprintBundle:
    """Bind a complete pinned source set to one measured snapshot per chain.

    Every requested source must have exactly one matching code observation, no
    unexpected observations are accepted, and all observations on a chain must
    share one historical block. Optional expected block numbers can pin the
    materialization to an externally selected historical snapshot.
    """
    source_list = tuple(sources)
    evidence_list = tuple(evidence_items)
    if not source_list:
        raise ValueError("reference fingerprint materialization requires sources")

    source_by_key: dict[tuple[str, str], DexReferenceContractSource] = {}
    for source in source_list:
        key = _source_key(source)
        if key in source_by_key:
            raise ValueError("duplicate reference source chain address")
        source_by_key[key] = source

    evidence_by_key: dict[tuple[str, str], ContractCodeEvidence] = {}
    for evidence in evidence_list:
        key = _evidence_key(evidence)
        if key in evidence_by_key:
            raise ValueError("duplicate contract code evidence chain address")
        evidence_by_key[key] = evidence

    source_keys = set(source_by_key)
    evidence_keys = set(evidence_by_key)
    missing = source_keys - evidence_keys
    unexpected = evidence_keys - source_keys
    if missing:
        raise ValueError("missing contract code evidence for reference source")
    if unexpected:
        raise ValueError("unexpected contract code evidence outside reference sources")

    block_sets: dict[str, set[int]] = {}
    for evidence in evidence_list:
        block_sets.setdefault(evidence.chain, set()).add(evidence.block_number)
    if any(len(blocks) != 1 for blocks in block_sets.values()):
        raise ValueError("reference evidence must use one historical block per chain")

    chain_blocks = {chain: next(iter(blocks)) for chain, blocks in block_sets.items()}
    source_chains = {source.chain for source in source_list}
    if set(chain_blocks) != source_chains:
        raise ValueError("reference source and evidence chains must match exactly")

    if expected_block_numbers is not None:
        expected = dict(expected_block_numbers)
        if set(expected) != source_chains:
            raise ValueError("expected block map must cover reference chains exactly")
        if any(not isinstance(block, int) or isinstance(block, bool) or block < 0 for block in expected.values()):
            raise ValueError("expected block numbers must be non-negative integers")
        for chain, observed_block in chain_blocks.items():
            if observed_block != expected[chain]:
                raise ValueError("reference evidence is stale for expected historical block")

    ordered_sources = sorted(source_list, key=lambda item: item.source_reference)
    entries = tuple(
        build_reference_fingerprint_entry(source, evidence_by_key[_source_key(source)])
        for source in ordered_sources
    )

    return ReferenceFingerprintBundle(
        entries=entries,
        source_references=tuple(source.source_reference for source in ordered_sources),
        chain_blocks=tuple(sorted(chain_blocks.items())),
        status="UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE",
        limitations=(
            "REFERENCE_BUNDLE_DOES_NOT_PROVE_DEPLOYMENT_PROVENANCE",
            "REFERENCE_BUNDLE_DOES_NOT_PROVE_COMPONENT_AUTHENTICITY",
            "REFERENCE_BUNDLE_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "REFERENCE_BUNDLE_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
        ),
    )
