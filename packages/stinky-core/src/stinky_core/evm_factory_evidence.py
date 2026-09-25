"""Historical factory relationship evidence helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_call_consensus import ExactCallObservation
from .evm_consensus import provider_fingerprint
from .evm_contract_code import ContractCodeEvidence
from .evm_dex_discovery import DexPoolCandidate
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError, _is_hex_data
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
    returned_address: str | None
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


def _distinct_observers(observers: Iterable[EvmReadOnlyRpc]) -> dict[str, EvmReadOnlyRpc]:
    distinct: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        distinct.setdefault(provider_fingerprint(observer.rpc_url), observer)
    return distinct


def classify_factory_relationship(
    pool: DexPoolCandidate,
    factory_code: ContractCodeEvidence,
    observation: ExactCallObservation,
) -> FactoryRelationshipEvidence:
    if observation.chain != pool.chain or observation.target != pool.factory_address:
        raise ValueError("factory observation target does not match pool candidate")
    if observation.block_number != factory_code.block_number:
        raise ValueError("factory observation and code evidence must share a historical block")
    if (factory_code.chain, factory_code.chain_id, factory_code.address, factory_code.contract_key) != (
        pool.chain, pool.chain_id, pool.factory_address, pool.factory_key,
    ):
        raise ValueError("factory code identity does not match pool candidate")
    if not _is_hex_data(observation.calldata) or observation.calldata.lower() != build_factory_lookup(pool).lower():
        raise ValueError("factory observation calldata does not match pool lookup")

    if observation.consensus.agreed_result is None:
        return FactoryRelationshipEvidence(
            pool.chain, pool.factory_address, pool.pool_address,
            pool.token0_address, pool.token1_address, pool.event_family,
            pool.fee_tier, observation.block_number, factory_code, None, (),
            "UNKNOWN_FACTORY_RELATIONSHIP",
            "UNVERIFIED_FACTORY_RELATIONSHIP_EVIDENCE",
            (f"FACTORY_LOOKUP_{observation.consensus.verdict}",),
        )

    returned = decode_factory_address(pool.chain, observation.consensus.agreed_result)
    sources = tuple(
        FactoryRelationshipSource(provider, returned)
        for provider in observation.consensus.providers
    )
    if returned == pool.pool_address:
        relationship = "FACTORY_LOOKUP_MATCHES_DISCOVERED_POOL"
    elif returned == ZERO_ADDRESS:
        relationship = "FACTORY_LOOKUP_REPORTS_NO_POOL"
    else:
        relationship = "FACTORY_LOOKUP_CONFLICTS_WITH_DISCOVERED_POOL"

    return FactoryRelationshipEvidence(
        pool.chain, pool.factory_address, pool.pool_address,
        pool.token0_address, pool.token1_address, pool.event_family,
        pool.fee_tier, observation.block_number, factory_code, returned, sources,
        relationship, "UNVERIFIED_FACTORY_RELATIONSHIP_EVIDENCE",
        (
            "FACTORY_LOOKUP_DOES_NOT_PROVE_FACTORY_IMPLEMENTATION_AUTHENTICITY",
            "FACTORY_LOOKUP_DOES_NOT_PROVE_POOL_IMPLEMENTATION_AUTHENTICITY",
            "FACTORY_LOOKUP_DOES_NOT_PROVE_LIQUIDITY_QUALITY_OR_SAFETY",
        ),
    )
