"""Fail-closed liquidity event classification and pool-state change history.

This module classifies only event shapes Genesis can decode deterministically.
State deltas are descriptive evidence, not proof that a change was benign,
permanent, or caused by a specific actor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .evm_dex_discovery import DexPoolCandidate
from .evm_ingestion import EvmIngestedBlock
from .evm_liquidity import V2ReserveEvidence, V3LiquidityEvidence
from .evm_rpc import EvmRpcError

V2_SYNC_TOPIC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"


@dataclass(frozen=True, slots=True)
class V2SyncEvidence:
    chain: str
    pool_key: str
    pool_address: str
    block_number: int
    block_hash: str
    transaction_hash: str
    log_index: str
    reserve0: int
    reserve1: int
    status: str
    evidence_providers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class V2ReserveChange:
    chain: str
    pool_key: str
    from_block: int
    to_block: int
    reserve0_before: int
    reserve0_after: int
    reserve1_before: int
    reserve1_after: int
    reserve0_delta: int
    reserve1_delta: int
    classification: str
    status: str


@dataclass(frozen=True, slots=True)
class V3LiquidityChange:
    chain: str
    pool_key: str
    from_block: int
    to_block: int
    liquidity_before: int
    liquidity_after: int
    liquidity_delta: int
    classification: str
    status: str


def _decode_sync_data(data: object) -> tuple[int, int] | None:
    if not isinstance(data, str) or not data.startswith("0x") or len(data) != 2 + 64 * 2:
        return None
    body = data[2:]
    try:
        reserve0 = int(body[:64], 16)
        reserve1 = int(body[64:], 16)
    except ValueError:
        return None
    if reserve0 >= 2**112 or reserve1 >= 2**112:
        return None
    return reserve0, reserve1


def classify_v2_sync_events(
    block: EvmIngestedBlock,
    pools: Iterable[DexPoolCandidate],
) -> tuple[V2SyncEvidence, ...]:
    """Classify canonical Uniswap-V2-style Sync logs from quorum-accepted logs."""
    providers = tuple(sorted({source.provider for source in block.log_sources}))
    if len(providers) < 2:
        return ()
    by_address = {
        pool.pool_address.lower(): pool
        for pool in pools
        if pool.chain == block.chain and pool.event_family == "V2_STYLE_PAIR_CREATED"
    }
    out: list[V2SyncEvidence] = []
    for log in block.logs:
        if not isinstance(log, dict):
            continue
        pool = by_address.get(str(log.get("address") or "").lower())
        if pool is None or str(log.get("blockHash") or "").lower() != block.block_hash.lower():
            continue
        topics = log.get("topics")
        if not isinstance(topics, list) or len(topics) != 1 or str(topics[0]).lower() != V2_SYNC_TOPIC:
            continue
        decoded = _decode_sync_data(log.get("data"))
        if decoded is None:
            continue
        tx_hash = str(log.get("transactionHash") or "").lower()
        log_index = str(log.get("logIndex") or "").lower()
        if not tx_hash.startswith("0x") or len(tx_hash) != 66 or not log_index.startswith("0x"):
            continue
        try:
            int(tx_hash[2:], 16)
            int(log_index[2:], 16)
        except ValueError:
            continue
        out.append(
            V2SyncEvidence(
                block.chain,
                pool.pool_key,
                pool.pool_address,
                block.block_number,
                block.block_hash,
                tx_hash,
                log_index,
                decoded[0],
                decoded[1],
                "CLASSIFIED_V2_SYNC_EVENT_EVIDENCE",
                providers,
            )
        )
    return tuple(sorted(out, key=lambda row: (row.pool_key, row.transaction_hash, row.log_index)))


def _require_same_ordered_pool(previous: object, current: object) -> None:
    if previous.chain != current.chain or previous.pool_key != current.pool_key:
        raise EvmRpcError("pool-state history cannot cross chains or pools")
    if current.block_number <= previous.block_number:
        raise EvmRpcError("pool-state history requires strictly increasing blocks")


def derive_v2_reserve_change(previous: V2ReserveEvidence, current: V2ReserveEvidence) -> V2ReserveChange:
    _require_same_ordered_pool(previous, current)
    delta0 = current.reserve0 - previous.reserve0
    delta1 = current.reserve1 - previous.reserve1
    if delta0 > 0 and delta1 > 0:
        classification = "POSSIBLE_LIQUIDITY_ADD"
    elif delta0 < 0 and delta1 < 0:
        classification = "POSSIBLE_LIQUIDITY_REMOVE"
    elif delta0 == 0 and delta1 == 0:
        classification = "NO_RESERVE_CHANGE"
    else:
        classification = "MIXED_RESERVE_CHANGE"
    return V2ReserveChange(
        current.chain, current.pool_key, previous.block_number, current.block_number,
        previous.reserve0, current.reserve0, previous.reserve1, current.reserve1,
        delta0, delta1, classification, "UNVERIFIED_V2_RESERVE_CHANGE_EVIDENCE",
    )


def derive_v3_liquidity_change(previous: V3LiquidityEvidence, current: V3LiquidityEvidence) -> V3LiquidityChange:
    _require_same_ordered_pool(previous, current)
    delta = current.liquidity - previous.liquidity
    classification = "LIQUIDITY_INCREASED" if delta > 0 else "LIQUIDITY_DECREASED" if delta < 0 else "NO_LIQUIDITY_CHANGE"
    return V3LiquidityChange(
        current.chain, current.pool_key, previous.block_number, current.block_number,
        previous.liquidity, current.liquidity, delta, classification,
        "UNVERIFIED_V3_LIQUIDITY_CHANGE_EVIDENCE",
    )


def build_v2_reserve_change_history(rows: Sequence[V2ReserveEvidence]) -> tuple[V2ReserveChange, ...]:
    if len(rows) < 2:
        return ()
    return tuple(derive_v2_reserve_change(rows[index - 1], rows[index]) for index in range(1, len(rows)))


def build_v3_liquidity_change_history(rows: Sequence[V3LiquidityEvidence]) -> tuple[V3LiquidityChange, ...]:
    if len(rows) < 2:
        return ()
    return tuple(derive_v3_liquidity_change(rows[index - 1], rows[index]) for index in range(1, len(rows)))
