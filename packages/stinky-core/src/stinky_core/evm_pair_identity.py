"""Quorum-backed pair token identity and router-path consistency evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_consensus import provider_fingerprint
from .evm_contract_code import ContractCodeEvidence, observe_contract_code
from .evm_dex_discovery import DexPoolCandidate
from .evm_router_semantics import RouterCalldataSemantics
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError
from .multichain_identity import canonical_chain_address

TOKEN0_SELECTOR = "0x0dfe1681"
TOKEN1_SELECTOR = "0xd21220a7"


@dataclass(frozen=True, slots=True)
class PairTokenSource:
    provider: str
    token0: str
    token1: str


@dataclass(frozen=True, slots=True)
class PairTokenIdentityEvidence:
    chain: str
    pool_key: str
    pool_address: str
    block_number: int
    discovered_token0: str
    discovered_token1: str
    observed_token0: str
    observed_token1: str
    pair_code: ContractCodeEvidence
    sources: tuple[PairTokenSource, ...]
    discovery_consistency: str
    status: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PairPathConsistencyEvidence:
    chain: str
    pool_key: str
    block_number: int
    path: tuple[str, ...]
    matching_hops: tuple[int, ...]
    verdict: str
    status: str
    limitations: tuple[str, ...]


def _decode_address_response(chain: str, response: str) -> str:
    if not isinstance(response, str) or not response.startswith("0x") or len(response) != 66:
        raise EvmRpcError("invalid pair token address response")
    body = response[2:]
    try:
        int(body, 16)
    except ValueError as exc:
        raise EvmRpcError("invalid pair token address response") from exc
    if body[:24].lower() != "0" * 24:
        raise EvmRpcError("pair token address response is not canonical ABI address data")
    address = canonical_chain_address(chain, "0x" + body[-40:])
    if address is None:
        raise EvmRpcError("pair token address could not be canonicalized")
    return address


def observe_pair_token_identity(
    observers: Iterable[EvmReadOnlyRpc],
    pool: DexPoolCandidate,
    *,
    block_number: int,
    min_quorum: int = 2,
) -> PairTokenIdentityEvidence:
    """Observe token0/token1 directly from one discovered pool at a historical block."""
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if block_number < 0:
        raise ValueError("block_number must be non-negative")
    if pool.status != "UNVERIFIED_DEX_POOL_CANDIDATE":
        raise ValueError("unsupported pool candidate status")

    distinct: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        distinct.setdefault(provider_fingerprint(observer.rpc_url), observer)
    if len(distinct) < min_quorum:
        raise EvmRpcError("insufficient distinct RPC providers for pair identity quorum")

    pair_code = observe_contract_code(
        distinct.values(),
        chain=pool.chain,
        address=pool.pool_address,
        block_number=block_number,
        min_quorum=min_quorum,
    )

    groups: dict[tuple[str, str], list[PairTokenSource]] = {}
    for provider, observer in distinct.items():
        if observer.chain.key != pool.chain:
            continue
        try:
            observer.attest_chain()
            token0 = _decode_address_response(
                pool.chain,
                observer.call_at_block(pool.pool_address, TOKEN0_SELECTOR, block_number),
            )
            token1 = _decode_address_response(
                pool.chain,
                observer.call_at_block(pool.pool_address, TOKEN1_SELECTOR, block_number),
            )
        except EvmRpcError:
            continue
        if token0 == token1:
            continue
        row = PairTokenSource(provider, token0, token1)
        groups.setdefault((token0, token1), []).append(row)

    qualifying = [(identity, rows) for identity, rows in groups.items() if len(rows) >= min_quorum]
    if len(qualifying) != 1 or len(groups) != 1:
        raise EvmRpcError("pair token identity quorum not reached")

    (token0, token1), rows = qualifying[0]
    expected = (pool.token0_address, pool.token1_address)
    discovery_consistency = (
        "PAIR_TOKENS_MATCH_DISCOVERY_EVENT"
        if (token0, token1) == expected
        else "PAIR_TOKENS_CONFLICT_WITH_DISCOVERY_EVENT"
    )

    return PairTokenIdentityEvidence(
        chain=pool.chain,
        pool_key=pool.pool_key,
        pool_address=pool.pool_address,
        block_number=block_number,
        discovered_token0=pool.token0_address,
        discovered_token1=pool.token1_address,
        observed_token0=token0,
        observed_token1=token1,
        pair_code=pair_code,
        sources=tuple(sorted(rows, key=lambda row: row.provider)),
        discovery_consistency=discovery_consistency,
        status="UNVERIFIED_PAIR_TOKEN_IDENTITY_EVIDENCE",
        limitations=(
            "TOKEN_IDENTITY_MATCH_DOES_NOT_PROVE_FACTORY_AUTHENTICITY",
            "TOKEN_IDENTITY_MATCH_DOES_NOT_PROVE_POOL_IMPLEMENTATION_AUTHENTICITY",
            "TOKEN_IDENTITY_MATCH_DOES_NOT_PROVE_LIQUIDITY_QUALITY_OR_SAFETY",
        ),
    )


def compare_pair_to_router_path(
    pair: PairTokenIdentityEvidence,
    calldata: RouterCalldataSemantics,
) -> PairPathConsistencyEvidence:
    """Check whether the observed pair token set corresponds to one adjacent path hop."""
    if pair.status != "UNVERIFIED_PAIR_TOKEN_IDENTITY_EVIDENCE":
        raise ValueError("unsupported pair identity evidence status")
    if calldata.status != "SUPPORTED_ROUTER_CALLDATA_SEMANTICS":
        return PairPathConsistencyEvidence(
            pair.chain,
            pair.pool_key,
            pair.block_number,
            calldata.path,
            (),
            "UNKNOWN_PATH_SEMANTICS",
            "UNVERIFIED_PAIR_PATH_CONSISTENCY_EVIDENCE",
            ("ROUTER_CALLDATA_SEMANTICS_NOT_VERIFIED",),
        )

    observed = {pair.observed_token0, pair.observed_token1}
    matches: list[int] = []
    for index in range(len(calldata.path) - 1):
        if {calldata.path[index], calldata.path[index + 1]} == observed:
            matches.append(index)

    verdict = "PAIR_MATCHES_ROUTER_PATH_HOP" if matches else "PAIR_NOT_PRESENT_IN_ROUTER_PATH"
    return PairPathConsistencyEvidence(
        pair.chain,
        pair.pool_key,
        pair.block_number,
        calldata.path,
        tuple(matches),
        verdict,
        "UNVERIFIED_PAIR_PATH_CONSISTENCY_EVIDENCE",
        (
            "PATH_MATCH_DOES_NOT_PROVE_ROUTER_OR_PAIR_AUTHENTICITY",
            "PATH_MATCH_DOES_NOT_PROVE_SWAP_EXECUTION_OR_REAL_SALE_SUCCESS",
        ),
    )
