"""Pure helpers and read-only observers for fail-closed exact-result consensus."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .evm_consensus import provider_fingerprint
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError


@dataclass(frozen=True, slots=True)
class ExactResultConsensus:
    agreed_result: str | None
    providers: tuple[str, ...]
    verdict: str


@dataclass(frozen=True, slots=True)
class ExactCallObservation:
    chain: str
    target: str
    block_number: int
    calldata: str
    consensus: ExactResultConsensus
    successful_results: tuple[tuple[str, str], ...]
    status: str


def classify_exact_results(
    result_providers: Mapping[str, tuple[str, ...] | list[str]],
    *,
    min_quorum: int = 2,
) -> ExactResultConsensus:
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")

    normalized: dict[str, tuple[str, ...]] = {}
    for result, providers in result_providers.items():
        unique = tuple(sorted(set(providers)))
        if unique:
            normalized[result] = unique

    qualifying = [(result, providers) for result, providers in normalized.items() if len(providers) >= min_quorum]
    if len(qualifying) == 1 and len(normalized) == 1:
        result, providers = qualifying[0]
        return ExactResultConsensus(result, providers, "EXACT_RESULT_QUORUM")
    if len(normalized) > 1:
        return ExactResultConsensus(None, (), "RESULT_DISAGREEMENT")
    return ExactResultConsensus(None, (), "INSUFFICIENT_RESULT_EVIDENCE")


def observe_exact_call(
    observers: Iterable[EvmReadOnlyRpc],
    *,
    chain: str,
    target: str,
    calldata: str,
    block_number: int,
    min_quorum: int = 2,
) -> ExactCallObservation:
    """Observe one historical eth_call across distinct providers and classify exact-result agreement."""
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if block_number < 0:
        raise ValueError("block_number must be non-negative")

    distinct: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        distinct.setdefault(provider_fingerprint(observer.rpc_url), observer)
    if len(distinct) < min_quorum:
        raise EvmRpcError("insufficient distinct RPC providers for exact-call observation")

    grouped: dict[str, list[str]] = {}
    rows: list[tuple[str, str]] = []
    for provider, observer in distinct.items():
        if observer.chain.key != chain:
            continue
        try:
            result = observer.call_at_block(target, calldata, block_number)
        except (EvmRpcError, ValueError):
            continue
        grouped.setdefault(result, []).append(provider)
        rows.append((provider, result))

    consensus = classify_exact_results(grouped, min_quorum=min_quorum)
    return ExactCallObservation(
        chain=chain,
        target=target,
        block_number=block_number,
        calldata=calldata,
        consensus=consensus,
        successful_results=tuple(sorted(rows)),
        status="UNVERIFIED_EXACT_CALL_OBSERVATION",
    )
