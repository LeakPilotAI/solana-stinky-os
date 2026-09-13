"""Complete provenance-bearing reference DEX evidence record."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_contract_code import ContractCodeEvidence
from .evm_factory_evidence import FactoryRelationshipEvidence
from .evm_reference_dex_envelope import (
    ReferenceDexEvidenceEnvelope,
    compose_reference_dex_evidence_envelope,
)
from .evm_reference_materialization import ReferenceFingerprintBundle


@dataclass(frozen=True, slots=True)
class ReferenceDexEvidenceRecord:
    relationship: FactoryRelationshipEvidence
    envelope: ReferenceDexEvidenceEnvelope
    status: str
    limitations: tuple[str, ...]


def compose_reference_dex_evidence_record(
    relationship: FactoryRelationshipEvidence,
    factory_code: ContractCodeEvidence,
    pool_code: ContractCodeEvidence,
    router_code: ContractCodeEvidence,
    bundle: ReferenceFingerprintBundle,
) -> ReferenceDexEvidenceRecord:
    """Retain the exact relationship evidence alongside the #222 envelope."""
    envelope = compose_reference_dex_evidence_envelope(
        relationship,
        factory_code,
        pool_code,
        router_code,
        bundle,
    )
    return ReferenceDexEvidenceRecord(
        relationship=relationship,
        envelope=envelope,
        status="UNVERIFIED_REFERENCE_DEX_EVIDENCE_RECORD",
        limitations=(
            "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_DEPLOYMENT_PROVENANCE",
            "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_COMPONENT_AUTHENTICITY",
            "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "REFERENCE_DEX_RECORD_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
        ),
    )
