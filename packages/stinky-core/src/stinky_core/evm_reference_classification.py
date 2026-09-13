"""Classify component code against a measured reference fingerprint bundle."""
from __future__ import annotations

from .evm_contract_code import ContractCodeEvidence
from .evm_implementation_registry import (
    ImplementationFingerprintEvidence,
    classify_implementation_fingerprint,
)
from .evm_reference_materialization import ReferenceFingerprintBundle


def classify_reference_bundle_component(
    evidence: ContractCodeEvidence,
    bundle: ReferenceFingerprintBundle,
    *,
    expected_role: str,
) -> ImplementationFingerprintEvidence:
    """Classify one candidate component against one historical reference snapshot.

    The bundle is accepted only when it is the canonical unverified materialized
    reference-bundle type and contains exactly one historical block for the
    candidate chain. Candidate code must be observed at that same block. Matching
    and ambiguity behavior is then delegated unchanged to the implementation
    fingerprint classifier so match provenance remains canonical.
    """
    if bundle.status != "UNVERIFIED_REFERENCE_FINGERPRINT_BUNDLE":
        raise ValueError("reference bundle status is not supported for classification")

    chain_blocks: dict[str, int] = {}
    for chain, block_number in bundle.chain_blocks:
        if chain in chain_blocks:
            raise ValueError("reference bundle contains duplicate chain block metadata")
        if not isinstance(block_number, int) or isinstance(block_number, bool) or block_number < 0:
            raise ValueError("reference bundle block numbers must be non-negative integers")
        chain_blocks[chain] = block_number

    if evidence.chain not in chain_blocks:
        raise ValueError("reference bundle has no historical block for evidence chain")
    if evidence.block_number != chain_blocks[evidence.chain]:
        raise ValueError("candidate evidence block does not match reference bundle snapshot")

    entry_references = {entry.source_reference for entry in bundle.entries}
    bundle_references = set(bundle.source_references)
    if len(bundle_references) != len(bundle.source_references):
        raise ValueError("reference bundle contains duplicate source references")
    if entry_references != bundle_references:
        raise ValueError("reference bundle provenance does not match materialized entries")

    return classify_implementation_fingerprint(
        evidence,
        bundle.entries,
        expected_role=expected_role,
    )
