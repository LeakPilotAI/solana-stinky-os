"""Historical factory relationship evidence helpers."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_contract_code import ContractCodeEvidence

V2_FACTORY_LOOKUP_SELECTOR = "0xe6a43905"
V3_FACTORY_LOOKUP_SELECTOR = "0x1698ee82"
ZERO_ADDRESS = "0x" + "0" * 40


@dataclass(frozen=True, slots=True)
class FactoryRelationshipSource:
    provider: str
    returned_address: str


@dataclass(frozen=True, slots=True)
class FactoryRelationshipEvidence:
    chain: str
    factory_address: str
    pool_address: str
    token0_address: str
    token1_address: str
    event_family: str
    fee_tier: int | None
    block_number: int
    factory_code: ContractCodeEvidence
    returned_address: str
    sources: tuple[FactoryRelationshipSource, ...]
    relationship: str
    status: str
    limitations: tuple[str, ...]
