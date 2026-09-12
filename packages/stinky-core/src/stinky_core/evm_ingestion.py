"""Consensus-anchored EVM block/log ingestion with explicit provenance.

Genesis accepts a block only after redundant RPC providers agree on the exact
block hash at a consensus-derived height. Logs are then fetched by that block
hash and must also agree across a quorum of distinct providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from .evm_consensus import EvmConsensusObservation, observe_consensus_head, provider_fingerprint
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError


@dataclass(frozen=True, slots=True)
class EvmBlockSource:
    provider: str
    block_hash: str


@dataclass(frozen=True, slots=True)
class EvmLogSource:
    provider: str
    digest: str
    log_count: int


@dataclass(frozen=True, slots=True)
class EvmIngestedBlock:
    chain: str
    chain_id: int
    block_number: int
    block_hash: str
    observed_at: str
    head_consensus: EvmConsensusObservation
    block_sources: tuple[EvmBlockSource, ...]
    logs: tuple[dict[str, Any], ...]
    log_sources: tuple[EvmLogSource, ...]


def _distinct(observers: Iterable[EvmReadOnlyRpc]) -> list[EvmReadOnlyRpc]:
    out: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        out.setdefault(provider_fingerprint(observer.rpc_url), observer)
    return list(out.values())


def _log_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("transactionHash") or ""),
        str(item.get("logIndex") or ""),
        str(item.get("address") or "").lower(),
    )


def _canonical_logs(logs: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(sorted((dict(item) for item in logs), key=_log_key))


def _logs_digest(logs: tuple[dict[str, Any], ...]) -> str:
    payload = json.dumps(logs, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def ingest_consensus_block(
    observers: Iterable[EvmReadOnlyRpc],
    *,
    confirmations: int = 2,
    min_quorum: int = 2,
    max_block_skew: int = 3,
) -> EvmIngestedBlock:
    """Ingest one confirmed EVM block and its logs using independent RPC quorum.

    No provider may create evidence alone. The candidate height is derived from
    the redundant head consensus, then providers must agree on the exact block
    hash and the canonicalized log set for that hash. Any unresolved disagreement
    fails closed instead of producing partial evidence.
    """
    if confirmations < 0:
        raise ValueError("confirmations must be non-negative")
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")

    providers = _distinct(observers)
    head = observe_consensus_head(
        providers,
        min_quorum=min_quorum,
        max_block_skew=max_block_skew,
    )
    target = head.canonical_block_number - confirmations
    if target < 0:
        raise EvmRpcError("consensus head is too young for requested confirmations")

    block_groups: dict[str, list[tuple[EvmReadOnlyRpc, dict[str, Any]]]] = {}
    for observer in providers:
        try:
            block = observer.get_block_by_number(target)
        except EvmRpcError:
            continue
        block_hash = str(block["hash"])
        block_groups.setdefault(block_hash, []).append((observer, block))

    qualifying_blocks = [
        (block_hash, rows)
        for block_hash, rows in block_groups.items()
        if len(rows) >= min_quorum
    ]
    if len(qualifying_blocks) != 1:
        raise EvmRpcError("exact block-hash consensus not reached")

    block_hash, block_rows = qualifying_blocks[0]
    block_sources = tuple(
        EvmBlockSource(provider=provider_fingerprint(observer.rpc_url), block_hash=block_hash)
        for observer, _ in block_rows
    )

    log_groups: dict[str, list[tuple[EvmReadOnlyRpc, tuple[dict[str, Any], ...]]]] = {}
    for observer, _ in block_rows:
        try:
            canonical = _canonical_logs(observer.get_logs_for_block(block_hash))
        except EvmRpcError:
            continue
        digest = _logs_digest(canonical)
        log_groups.setdefault(digest, []).append((observer, canonical))

    qualifying_logs = [
        (digest, rows)
        for digest, rows in log_groups.items()
        if len(rows) >= min_quorum
    ]
    if len(qualifying_logs) != 1:
        raise EvmRpcError("exact log-set consensus not reached")

    digest, log_rows = qualifying_logs[0]
    accepted_logs = log_rows[0][1]
    log_sources = tuple(
        EvmLogSource(
            provider=provider_fingerprint(observer.rpc_url),
            digest=digest,
            log_count=len(canonical),
        )
        for observer, canonical in log_rows
    )

    return EvmIngestedBlock(
        chain=head.chain,
        chain_id=head.chain_id,
        block_number=target,
        block_hash=block_hash,
        observed_at=datetime.now(timezone.utc).isoformat(),
        head_consensus=head,
        block_sources=block_sources,
        logs=accepted_logs,
        log_sources=log_sources,
    )
