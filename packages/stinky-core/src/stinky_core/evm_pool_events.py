"""Preserve consensus-backed pool logs without pretending to know their meaning."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .evm_dex_discovery import DexPoolCandidate
from .evm_ingestion import EvmIngestedBlock

@dataclass(frozen=True, slots=True)
class PoolEventEvidence:
    chain: str
    pool_key: str
    pool_address: str
    block_number: int
    block_hash: str
    transaction_hash: str
    log_index: str
    topic0: str
    status: str
    evidence_providers: tuple[str, ...]

def collect_pool_event_evidence(block: EvmIngestedBlock, pools: Iterable[DexPoolCandidate]) -> tuple[PoolEventEvidence, ...]:
    providers = tuple(sorted({source.provider for source in block.log_sources}))
    if len(providers) < 2:
        return ()
    by_address = {p.pool_address.lower(): p for p in pools if p.chain == block.chain}
    out: list[PoolEventEvidence] = []
    for log in block.logs:
        if not isinstance(log, dict):
            continue
        pool = by_address.get(str(log.get("address") or "").lower())
        if pool is None or str(log.get("blockHash") or "").lower() != block.block_hash.lower():
            continue
        topics = log.get("topics")
        tx_hash = str(log.get("transactionHash") or "")
        log_index = str(log.get("logIndex") or "")
        if not isinstance(topics, list) or not topics or not isinstance(topics[0], str):
            continue
        topic0 = topics[0]
        if not topic0.startswith("0x") or len(topic0) != 66 or not tx_hash.startswith("0x") or len(tx_hash) != 66 or not log_index.startswith("0x"):
            continue
        try:
            int(topic0[2:], 16); int(tx_hash[2:], 16); int(log_index[2:], 16)
        except ValueError:
            continue
        out.append(PoolEventEvidence(block.chain, pool.pool_key, pool.pool_address, block.block_number, block.block_hash, tx_hash.lower(), log_index.lower(), topic0.lower(), "UNCLASSIFIED_POOL_EVENT_EVIDENCE", providers))
    return tuple(sorted(out, key=lambda row: (row.pool_key, row.transaction_hash, row.log_index)))
