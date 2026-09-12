"""Redundant EVM observation consensus with explicit evidence provenance.

Genesis treats infrastructure as untrusted evidence. This module requires a
quorum of distinct read-only RPC observers, records where each observation came
from, and fails closed when providers disagree beyond configured tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from statistics import median
from typing import Iterable
from urllib.parse import urlsplit

from .evm_rpc import EvmReadOnlyRpc, EvmRpcError, EvmRpcObservation


@dataclass(frozen=True, slots=True)
class RpcEvidenceSource:
    provider: str
    block_number: int


@dataclass(frozen=True, slots=True)
class EvmConsensusObservation:
    chain: str
    chain_id: int
    canonical_block_number: int
    min_block_number: int
    max_block_number: int
    quorum: int
    observed_at: str
    sources: tuple[RpcEvidenceSource, ...]


def provider_fingerprint(url: str) -> str:
    """Return a stable provider label without leaking API keys/query strings."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "unknown").lower()
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{host}:{digest}"


def _collect_distinct(observers: Iterable[EvmReadOnlyRpc]) -> list[EvmReadOnlyRpc]:
    distinct: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        distinct.setdefault(provider_fingerprint(observer.rpc_url), observer)
    return list(distinct.values())


def observe_consensus_head(
    observers: Iterable[EvmReadOnlyRpc],
    *,
    min_quorum: int = 2,
    max_block_skew: int = 3,
) -> EvmConsensusObservation:
    """Observe a chain head from independent providers and fail closed on disagreement.

    Providers are deduplicated by endpoint fingerprint so the same RPC cannot count
    twice toward quorum. Individual provider failures do not become positive evidence;
    at least ``min_quorum`` successful, distinct providers must independently attest
    the same configured chain and remain within ``max_block_skew`` blocks.
    """
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if max_block_skew < 0:
        raise ValueError("max_block_skew must be non-negative")

    candidates = _collect_distinct(observers)
    if len(candidates) < min_quorum:
        raise EvmRpcError("insufficient distinct RPC providers for consensus")

    successes: list[EvmRpcObservation] = []
    source_rows: list[RpcEvidenceSource] = []
    expected_chain: str | None = None
    expected_chain_id: int | None = None

    for observer in candidates:
        try:
            observation = observer.observe_head()
        except EvmRpcError:
            continue
        if expected_chain is None:
            expected_chain = observation.chain
            expected_chain_id = observation.chain_id
        elif observation.chain != expected_chain or observation.chain_id != expected_chain_id:
            raise EvmRpcError("RPC providers attested different chains")
        successes.append(observation)
        source_rows.append(
            RpcEvidenceSource(
                provider=provider_fingerprint(observation.rpc_url),
                block_number=observation.block_number,
            )
        )

    if len(successes) < min_quorum:
        raise EvmRpcError("RPC consensus quorum not reached")

    blocks = [item.block_number for item in successes]
    low = min(blocks)
    high = max(blocks)
    if high - low > max_block_skew:
        raise EvmRpcError(
            f"RPC head disagreement exceeds skew tolerance: {low}..{high}"
        )

    canonical = int(median(blocks))
    return EvmConsensusObservation(
        chain=expected_chain or "",
        chain_id=int(expected_chain_id or 0),
        canonical_block_number=canonical,
        min_block_number=low,
        max_block_number=high,
        quorum=len(successes),
        observed_at=datetime.now(timezone.utc).isoformat(),
        sources=tuple(source_rows),
    )
