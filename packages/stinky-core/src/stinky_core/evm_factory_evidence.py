"""Historical factory relationship evidence helpers."""
from __future__ import annotations

from dataclasses import dataclass

from .evm_contract_code import ContractCodeEvidence
from .evm_dex_discovery import DexPoolCandidate
from .evm_rpc import EvmRpcError
from .multichain_identity import canonical_chain_address

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


def _address_word(address: str) -> str:
    return "0" * 24 + address[2:]


def decode_factory_address(chain: str, response: str) -> str:
    if not isinstance(response, str) or not response.startswith("0x") or len(response) != 66:
        raise EvmRpcError("invalid factory address response")
    body = response[2:]
    try:
        int(body, 16)
    except ValueError as exc:
        raise EvmRpcError("invalid factory address response") from exc
    if body[:24].lower() != "0" * 24:
        raise EvmRpcError("factory address response is not canonical ABI data")
    address = canonical_chain_address(chain, "0x" + body[-40:])
    if address is None:
        raise EvmRpcError("factory address response could not be canonicalized")
    return address


def build_factory_lookup(pool: DexPoolCandidate) -> str:
    token0 = canonical_chain_address(pool.chain, pool.token0_address)
    token1 = canonical_chain_address(pool.chain, pool.token1_address)
    if token0 is None or token1 is None or token0 == token1:
        raise ValueError("pool candidate tokens must be distinct canonical addresses")
    if pool.event_family == "V2_STYLE_PAIR_CREATED":
        return V2_FACTORY_LOOKUP_SELECTOR + _address_word(token0) + _address_word(token1)
    if pool.event_family == "V3_STYLE_POOL_CREATED":
        if pool.fee_tier is None or pool.fee_tier < 0 or pool.fee_tier > 0xFFFFFF:
            raise ValueError("V3 pool candidate requires valid uint24 fee tier")
        return V3_FACTORY_LOOKUP_SELECTOR + _address_word(token0) + _address_word(token1) + f"{pool.fee_tier:064x}"
    raise ValueError("unsupported DEX pool event family")
