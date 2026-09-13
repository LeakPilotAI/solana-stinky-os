"""Fail-closed EVM pool-state evidence."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .evm_consensus import provider_fingerprint
from .evm_dex_discovery import DexPoolCandidate
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError

V2_GET_RESERVES_SELECTOR = "0x0902f1ac"
V3_LIQUIDITY_SELECTOR = "0x1a686502"

@dataclass(frozen=True, slots=True)
class PoolStateSource:
    provider: str
    response: str

@dataclass(frozen=True, slots=True)
class V2ReserveEvidence:
    chain: str
    pool_key: str
    pool_address: str
    block_number: int
    reserve0: int
    reserve1: int
    block_timestamp_last: int
    status: str
    sources: tuple[PoolStateSource, ...]

@dataclass(frozen=True, slots=True)
class V3LiquidityEvidence:
    chain: str
    pool_key: str
    pool_address: str
    block_number: int
    liquidity: int
    status: str
    sources: tuple[PoolStateSource, ...]

def _distinct(observers: Iterable[EvmReadOnlyRpc]) -> list[EvmReadOnlyRpc]:
    out: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        out.setdefault(provider_fingerprint(observer.rpc_url), observer)
    return list(out.values())

def _quorum_call(observers: Iterable[EvmReadOnlyRpc], pool: DexPoolCandidate, block_number: int, data: str, min_quorum: int) -> tuple[str, tuple[PoolStateSource, ...]]:
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    providers = _distinct(observers)
    if len(providers) < min_quorum:
        raise EvmRpcError("insufficient distinct RPC providers for pool-state quorum")
    groups: dict[str, list[PoolStateSource]] = {}
    for observer in providers:
        if observer.chain.key != pool.chain:
            continue
        try:
            response = observer.call_at_block(pool.pool_address, data, block_number)
        except EvmRpcError:
            continue
        groups.setdefault(response, []).append(PoolStateSource(provider_fingerprint(observer.rpc_url), response))
    qualifying = [(response, rows) for response, rows in groups.items() if len(rows) >= min_quorum]
    if len(qualifying) != 1:
        raise EvmRpcError("pool-state quorum not reached")
    response, rows = qualifying[0]
    return response, tuple(rows)

def _decode_words(response: str, count: int) -> list[int]:
    if not isinstance(response, str) or not response.startswith("0x"):
        raise EvmRpcError("invalid eth_call response")
    body = response[2:]
    if len(body) != 64 * count:
        raise EvmRpcError("unexpected eth_call response length")
    try:
        return [int(body[i:i+64], 16) for i in range(0, len(body), 64)]
    except ValueError as exc:
        raise EvmRpcError("invalid eth_call response") from exc

def observe_v2_reserves(observers: Iterable[EvmReadOnlyRpc], pool: DexPoolCandidate, *, block_number: int, min_quorum: int = 2) -> V2ReserveEvidence:
    response, sources = _quorum_call(observers, pool, block_number, V2_GET_RESERVES_SELECTOR, min_quorum)
    reserve0, reserve1, timestamp = _decode_words(response, 3)
    if reserve0 >= 2**112 or reserve1 >= 2**112 or timestamp >= 2**32:
        raise EvmRpcError("V2 reserve response exceeds ABI bounds")
    return V2ReserveEvidence(pool.chain, pool.pool_key, pool.pool_address, block_number, reserve0, reserve1, timestamp, "UNVERIFIED_V2_RESERVE_EVIDENCE", sources)

def observe_v3_liquidity(observers: Iterable[EvmReadOnlyRpc], pool: DexPoolCandidate, *, block_number: int, min_quorum: int = 2) -> V3LiquidityEvidence:
    response, sources = _quorum_call(observers, pool, block_number, V3_LIQUIDITY_SELECTOR, min_quorum)
    (liquidity,) = _decode_words(response, 1)
    if liquidity >= 2**128:
        raise EvmRpcError("V3 liquidity response exceeds ABI bounds")
    return V3LiquidityEvidence(pool.chain, pool.pool_key, pool.pool_address, block_number, liquidity, "UNVERIFIED_V3_LIQUIDITY_EVIDENCE", sources)
