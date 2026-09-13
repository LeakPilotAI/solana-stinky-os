"""Pinned DEX deployment references for provenance-backed fingerprint entries.

Reference sources identify where a contract address/family mapping came from. They
never supply or guess runtime bytecode fingerprints. Fingerprints are admitted to
the implementation registry only after Genesis has quorum-backed historical
ContractCodeEvidence for the exact referenced chain address.
"""
from __future__ import annotations

from dataclasses import dataclass

from .evm_contract_code import ContractCodeEvidence
from .evm_implementation_registry import ImplementationFingerprintEntry
from .multichain_identity import canonical_chain_address

_ALLOWED_ROLES = frozenset({"FACTORY", "POOL", "ROUTER"})
_PINNED_UNISWAP_SDK_CORE_COMMIT = "baff6d3c78b09aa0b2f96148bc223b42a57fd28a"
_PINNED_UNISWAP_SDK_CORE_PATH = "src/addresses.ts"


@dataclass(frozen=True, slots=True)
class DexReferenceContractSource:
    chain: str
    address: str
    contract_role: str
    implementation_family: str
    implementation_version: str
    source_repository: str
    source_commit: str
    source_path: str
    source_locator: str

    def __post_init__(self) -> None:
        address = canonical_chain_address(self.chain, self.address)
        if address is None:
            raise ValueError("reference source must use a valid canonical chain address")
        role = self.contract_role.upper()
        if role not in _ALLOWED_ROLES:
            raise ValueError("contract_role must be FACTORY, POOL, or ROUTER")
        if not self.implementation_family.strip():
            raise ValueError("implementation_family is required")
        if not self.implementation_version.strip():
            raise ValueError("implementation_version is required")
        repository = self.source_repository.strip()
        if repository.count("/") != 1 or any(c.isspace() for c in repository):
            raise ValueError("source_repository must be owner/name")
        commit = self.source_commit.lower()
        if len(commit) != 40:
            raise ValueError("source_commit must be a 40-character git SHA")
        try:
            int(commit, 16)
        except ValueError as exc:
            raise ValueError("source_commit must be a 40-character git SHA") from exc
        if not self.source_path.strip() or not self.source_locator.strip():
            raise ValueError("source path and locator are required")
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "contract_role", role)
        object.__setattr__(self, "source_repository", repository)
        object.__setattr__(self, "source_commit", commit)
        object.__setattr__(self, "source_path", self.source_path.strip())
        object.__setattr__(self, "source_locator", self.source_locator.strip())

    @property
    def source_reference(self) -> str:
        return (
            f"github:{self.source_repository}@{self.source_commit}:"
            f"{self.source_path}#{self.source_locator}"
        )


def build_reference_fingerprint_entry(
    source: DexReferenceContractSource,
    evidence: ContractCodeEvidence,
) -> ImplementationFingerprintEntry:
    """Bind a pinned deployment reference to measured historical runtime code.

    The pinned source contributes contract identity/family provenance only. The
    fingerprint and byte length always come from quorum-backed Genesis evidence.
    """
    if evidence.status != "UNVERIFIED_CONTRACT_CODE_EVIDENCE":
        raise ValueError("reference fingerprints require contract code evidence")
    if evidence.chain != source.chain:
        raise ValueError("reference source and code evidence must share the chain")
    evidence_address = canonical_chain_address(evidence.chain, evidence.address)
    if evidence_address != source.address:
        raise ValueError("reference source address does not match code evidence")
    if evidence.block_number < 0:
        raise ValueError("contract code evidence block must be non-negative")

    return ImplementationFingerprintEntry(
        fingerprint_sha256=evidence.fingerprint_sha256,
        byte_length=evidence.byte_length,
        contract_role=source.contract_role,
        implementation_family=source.implementation_family,
        implementation_version=source.implementation_version,
        source_kind="PINNED_GITHUB_DEPLOYMENT_REFERENCE",
        source_reference=source.source_reference,
        chains=(source.chain,),
    )


BASE_UNISWAP_REFERENCE_SOURCES: tuple[DexReferenceContractSource, ...] = (
    DexReferenceContractSource(
        chain="base",
        address="0x8909dc15e40173ff4699343b6eb8132c65e18ec6",
        contract_role="FACTORY",
        implementation_family="UNISWAP_V2",
        implementation_version="UNSPECIFIED_BY_PINNED_SOURCE",
        source_repository="Uniswap/sdk-core",
        source_commit=_PINNED_UNISWAP_SDK_CORE_COMMIT,
        source_path=_PINNED_UNISWAP_SDK_CORE_PATH,
        source_locator="V2_FACTORY_ADDRESSES[ChainId.BASE]",
    ),
    DexReferenceContractSource(
        chain="base",
        address="0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        contract_role="ROUTER",
        implementation_family="UNISWAP_V2",
        implementation_version="UNSPECIFIED_BY_PINNED_SOURCE",
        source_repository="Uniswap/sdk-core",
        source_commit=_PINNED_UNISWAP_SDK_CORE_COMMIT,
        source_path=_PINNED_UNISWAP_SDK_CORE_PATH,
        source_locator="V2_ROUTER_ADDRESSES[ChainId.BASE]",
    ),
    DexReferenceContractSource(
        chain="base",
        address="0x33128a8fc17869897dce68ed026d694621f6fdfd",
        contract_role="FACTORY",
        implementation_family="UNISWAP_V3",
        implementation_version="UNSPECIFIED_BY_PINNED_SOURCE",
        source_repository="Uniswap/sdk-core",
        source_commit=_PINNED_UNISWAP_SDK_CORE_COMMIT,
        source_path=_PINNED_UNISWAP_SDK_CORE_PATH,
        source_locator="BASE_ADDRESSES.v3CoreFactoryAddress",
    ),
    DexReferenceContractSource(
        chain="base",
        address="0x2626664c2603336e57b271c5c0b26f421741e481",
        contract_role="ROUTER",
        implementation_family="UNISWAP_V3",
        implementation_version="UNSPECIFIED_BY_PINNED_SOURCE",
        source_repository="Uniswap/sdk-core",
        source_commit=_PINNED_UNISWAP_SDK_CORE_COMMIT,
        source_path=_PINNED_UNISWAP_SDK_CORE_PATH,
        source_locator="BASE_ADDRESSES.swapRouter02Address",
    ),
)
