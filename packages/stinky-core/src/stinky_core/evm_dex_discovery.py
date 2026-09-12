"""Fail-closed DEX pool-candidate discovery from consensus-backed EVM logs.

Genesis recognizes common Uniswap-style factory event shapes only as discovery
signals. A matching event does not prove that the emitting factory is genuine,
that the pool is safe, or that either token is legitimate. All results remain
UNVERIFIED until later factory, bytecode, liquidity, and authority analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evm_ingestion import EvmIngestedBlock
from .multichain_identity import asset_key, canonical_chain_address


V2_PAIR_CREATED_TOPIC = (
    "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
)
V3_POOL_CREATED_TOPIC = (
    "0x783cca1c0412dd0d695e784568c96f43a9f0e2c8f2fa0a9a76d07811e0e836e5"
)
_ZERO_ADDRESS = "0x" + "0" * 40


@dataclass(frozen=True, slots=True)
class DexPoolCandidate:
    chain: str
    chain_id: int
    factory_address: str
    factory_key: str
    pool_address: str
    pool_key: str
    token0_address: str
    token0_key: str
    token1_address: str
    token1_key: str
    event_family: str
    fee_tier: int | None
    first_seen_block: int
    block_hash: str
    transaction_hash: str
    log_index: str
    status: str
    evidence_providers: tuple[str, ...]


def _topic_address(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        return None
    body = value[2:]
    try:
        int(body, 16)
    except ValueError:
        return None
    if body[:24].lower() != "0" * 24:
        return None
    return "0x" + body[-40:].lower()


def _word_address(word: str) -> str | None:
    if len(word) != 64:
        return None
    try:
        int(word, 16)
    except ValueError:
        return None
    if word[:24].lower() != "0" * 24:
        return None
    return "0x" + word[-40:].lower()


def _words(data: Any, count: int) -> list[str] | None:
    if not isinstance(data, str) or not data.startswith("0x"):
        return None
    body = data[2:]
    if len(body) != 64 * count:
        return None
    try:
        int(body or "0", 16)
    except ValueError:
        return None
    return [body[offset : offset + 64] for offset in range(0, len(body), 64)]


def _canonical_required(chain: str, value: Any) -> str | None:
    address = canonical_chain_address(chain, value)
    if address is None or address == _ZERO_ADDRESS:
        return None
    return address


def _base_fields(block: EvmIngestedBlock, log: dict[str, Any]) -> tuple[str, str, str, str] | None:
    if str(log.get("blockHash") or "").lower() != block.block_hash.lower():
        return None
    factory = _canonical_required(block.chain, log.get("address"))
    tx_hash = str(log.get("transactionHash") or "")
    log_index = str(log.get("logIndex") or "")
    if factory is None or not tx_hash.startswith("0x") or len(tx_hash) != 66 or not log_index.startswith("0x"):
        return None
    try:
        int(tx_hash[2:], 16)
        int(log_index[2:], 16)
    except ValueError:
        return None
    return factory, asset_key(block.chain, factory) or "", tx_hash.lower(), log_index.lower()


def _parse_v2(block: EvmIngestedBlock, log: dict[str, Any]) -> DexPoolCandidate | None:
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 3:
        return None
    if str(topics[0]).lower() != V2_PAIR_CREATED_TOPIC:
        return None
    token0 = _canonical_required(block.chain, _topic_address(topics[1]))
    token1 = _canonical_required(block.chain, _topic_address(topics[2]))
    words = _words(log.get("data"), 2)
    base = _base_fields(block, log)
    if token0 is None or token1 is None or token0 == token1 or words is None or base is None:
        return None
    pool = _canonical_required(block.chain, _word_address(words[0]))
    if pool is None or pool in {token0, token1}:
        return None
    factory, factory_key, tx_hash, log_index = base
    return DexPoolCandidate(
        chain=block.chain,
        chain_id=block.chain_id,
        factory_address=factory,
        factory_key=factory_key,
        pool_address=pool,
        pool_key=asset_key(block.chain, pool) or "",
        token0_address=token0,
        token0_key=asset_key(block.chain, token0) or "",
        token1_address=token1,
        token1_key=asset_key(block.chain, token1) or "",
        event_family="V2_STYLE_PAIR_CREATED",
        fee_tier=None,
        first_seen_block=block.block_number,
        block_hash=block.block_hash,
        transaction_hash=tx_hash,
        log_index=log_index,
        status="UNVERIFIED_DEX_POOL_CANDIDATE",
        evidence_providers=(),
    )


def _parse_v3(block: EvmIngestedBlock, log: dict[str, Any]) -> DexPoolCandidate | None:
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 4:
        return None
    if str(topics[0]).lower() != V3_POOL_CREATED_TOPIC:
        return None
    token0 = _canonical_required(block.chain, _topic_address(topics[1]))
    token1 = _canonical_required(block.chain, _topic_address(topics[2]))
    fee_raw = topics[3]
    words = _words(log.get("data"), 2)
    base = _base_fields(block, log)
    if token0 is None or token1 is None or token0 == token1 or words is None or base is None:
        return None
    if not isinstance(fee_raw, str) or len(fee_raw) != 66 or not fee_raw.startswith("0x"):
        return None
    try:
        fee_tier = int(fee_raw, 16)
    except ValueError:
        return None
    if fee_tier < 0 or fee_tier > 0xFFFFFF:
        return None
    pool = _canonical_required(block.chain, _word_address(words[1]))
    if pool is None or pool in {token0, token1}:
        return None
    factory, factory_key, tx_hash, log_index = base
    return DexPoolCandidate(
        chain=block.chain,
        chain_id=block.chain_id,
        factory_address=factory,
        factory_key=factory_key,
        pool_address=pool,
        pool_key=asset_key(block.chain, pool) or "",
        token0_address=token0,
        token0_key=asset_key(block.chain, token0) or "",
        token1_address=token1,
        token1_key=asset_key(block.chain, token1) or "",
        event_family="V3_STYLE_POOL_CREATED",
        fee_tier=fee_tier,
        first_seen_block=block.block_number,
        block_hash=block.block_hash,
        transaction_hash=tx_hash,
        log_index=log_index,
        status="UNVERIFIED_DEX_POOL_CANDIDATE",
        evidence_providers=(),
    )


def discover_dex_pool_candidates(block: EvmIngestedBlock) -> tuple[DexPoolCandidate, ...]:
    """Return unverified V2/V3-style pool candidates from accepted quorum logs."""
    providers = tuple(sorted({source.provider for source in block.log_sources}))
    if len(providers) < 2:
        return ()

    found: dict[str, DexPoolCandidate] = {}
    for log in block.logs:
        if not isinstance(log, dict):
            continue
        candidate = _parse_v2(block, log) or _parse_v3(block, log)
        if candidate is None:
            continue
        candidate = DexPoolCandidate(
            **{**candidate.__dict__, "evidence_providers": providers}
        )
        found.setdefault(candidate.pool_key, candidate)

    return tuple(sorted(found.values(), key=lambda item: item.pool_key))
