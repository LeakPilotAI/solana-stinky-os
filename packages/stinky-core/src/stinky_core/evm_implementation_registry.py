"""Exact runtime-bytecode implementation fingerprint registry.

Genesis never treats code presence or one hash match as proof that a DEX is safe.
This module only classifies quorum-backed ContractCodeEvidence against explicit,
provenance-bearing registry entries. Unknown, role-mismatched, chain-mismatched,
or conflicting registry evidence remains fail-closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_contract_code import ContractCodeEvidence

_ALLOWED_ROLES = frozenset({"FACTORY", "POOL"})


@dataclass(frozen=True, slots=True)
class ImplementationFingerprintEntry:
    fingerprint_sha256: str
    byte_length: int
    contract_role: str
    implementation_family: str
    implementation_version: str
    source_kind: str
    source_reference: str
    chains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        digest = self.fingerprint_sha256.lower()
        if len(digest) != 64:
            raise ValueError("fingerprint_sha256 must be 64 hex characters")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("fingerprint_sha256 must be 64 hex characters") from exc
        if self.byte_length <= 0:
            raise ValueError("byte_length must be positive")
        role = self.contract_role.upper()
        if role not in _ALLOWED_ROLES:
            raise ValueError("contract_role must be FACTORY or POOL")
        if not self.implementation_family.strip():
            raise ValueError("implementation_family is required")
        if not self.implementation_version.strip():
            raise ValueError("implementation_version is required")
        if not self.source_kind.strip() or not self.source_reference.strip():
            raise ValueError("registry provenance source is required")
        if len(set(self.chains)) != len(self.chains):
            raise ValueError("chains must not contain duplicates")
        object.__setattr__(self, "fingerprint_sha256", digest)
        object.__setattr__(self, "contract_role", role)
        object.__setattr__(self, "chains", tuple(sorted(self.chains)))


@dataclass(frozen=True, slots=True)
class ImplementationFingerprintMatch:
    implementation_family: str
    implementation_version: str
    contract_role: str
    source_kind: str
    source_reference: str
    chains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImplementationFingerprintEvidence:
    chain: str
    contract_key: str
    address: str
    block_number: int
    observed_fingerprint_sha256: str
    observed_byte_length: int
    expected_role: str
    matches: tuple[ImplementationFingerprintMatch, ...]
    verdict: str
    status: str
    limitations: tuple[str, ...]


def classify_implementation_fingerprint(
    evidence: ContractCodeEvidence,
    registry: Iterable[ImplementationFingerprintEntry],
    *,
    expected_role: str,
) -> ImplementationFingerprintEvidence:
    """Classify exact code evidence against explicit registry entries.

    A positive result means only that the observed historical runtime bytecode is an
    exact fingerprint match to an explicitly registered implementation record.
    It is not a safety, ownership, deployment, factory, liquidity, or execution verdict.
    """
    role = expected_role.upper()
    if role not in _ALLOWED_ROLES:
        raise ValueError("expected_role must be FACTORY or POOL")

    matched: list[ImplementationFingerprintMatch] = []
    seen: set[tuple[str, str, str, str, str, tuple[str, ...]]] = set()
    for entry in registry:
        if entry.contract_role != role:
            continue
        if entry.fingerprint_sha256 != evidence.fingerprint_sha256.lower():
            continue
        if entry.byte_length != evidence.byte_length:
            continue
        if entry.chains and evidence.chain not in entry.chains:
            continue
        key = (
            entry.implementation_family,
            entry.implementation_version,
            entry.contract_role,
            entry.source_kind,
            entry.source_reference,
            entry.chains,
        )
        if key in seen:
            continue
        seen.add(key)
        matched.append(
            ImplementationFingerprintMatch(
                implementation_family=entry.implementation_family,
                implementation_version=entry.implementation_version,
                contract_role=entry.contract_role,
                source_kind=entry.source_kind,
                source_reference=entry.source_reference,
                chains=entry.chains,
            )
        )

    identities = {(m.implementation_family, m.implementation_version, m.contract_role) for m in matched}
    if not matched:
        verdict = "UNKNOWN_IMPLEMENTATION_FINGERPRINT"
    elif len(identities) == 1:
        verdict = "EXACT_IMPLEMENTATION_FINGERPRINT_MATCH"
    else:
        verdict = "AMBIGUOUS_IMPLEMENTATION_FINGERPRINT"

    return ImplementationFingerprintEvidence(
        chain=evidence.chain,
        contract_key=evidence.contract_key,
        address=evidence.address,
        block_number=evidence.block_number,
        observed_fingerprint_sha256=evidence.fingerprint_sha256.lower(),
        observed_byte_length=evidence.byte_length,
        expected_role=role,
        matches=tuple(sorted(matched, key=lambda m: (m.implementation_family, m.implementation_version, m.source_reference))),
        verdict=verdict,
        status="UNVERIFIED_IMPLEMENTATION_FINGERPRINT_EVIDENCE",
        limitations=(
            "EXACT_HASH_MATCH_DOES_NOT_PROVE_DEPLOYMENT_PROVENANCE",
            "EXACT_HASH_MATCH_DOES_NOT_PROVE_FACTORY_POOL_RELATIONSHIP",
            "EXACT_HASH_MATCH_DOES_NOT_PROVE_LIQUIDITY_QUALITY",
            "EXACT_HASH_MATCH_DOES_NOT_PROVE_TOKEN_OR_DEX_SAFETY",
            "EXACT_HASH_MATCH_DOES_NOT_PROVE_SWAP_OR_SALE_SUCCESS",
            "REGISTRY_ACCURACY_DEPENDS_ON_EXPLICIT_SOURCE_PROVENANCE",
        ),
    )
