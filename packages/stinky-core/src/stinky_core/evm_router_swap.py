"""Read-only historical router call evidence.

This module never signs or submits a transaction. It observes whether independent
RPC providers agree that one exact caller-supplied router calldata payload succeeds
at one historical block. The calldata is intentionally opaque so Genesis does not
pretend one hard-coded ABI covers every DEX/router implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_consensus import provider_fingerprint
from .evm_contract_code import ContractCodeEvidence, observe_contract_code
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError
from .multichain_identity import canonical_chain_address


@dataclass(frozen=True, slots=True)
class RouterCallProviderEvidence:
    provider: str
    outcome: str
    result: str | None


@dataclass(frozen=True, slots=True)
class RouterSwapCallEvidence:
    chain: str
    router: str
    caller: str
    block_number: int
    calldata: str
    value: int
    router_code: ContractCodeEvidence
    successful_providers: tuple[str, ...]
    provider_evidence: tuple[RouterCallProviderEvidence, ...]
    agreed_result: str | None
    verdict: str
    status: str
    limitations: tuple[str, ...]


def _normalize_calldata(calldata: str) -> str:
    if not isinstance(calldata, str) or not calldata.startswith("0x"):
        raise ValueError("calldata must be 0x-prefixed hex")
    if len(calldata) < 10 or len(calldata) % 2:
        raise ValueError("calldata must include at least a 4-byte selector and complete bytes")
    try:
        int(calldata[2:], 16)
    except ValueError as exc:
        raise ValueError("calldata must be valid hex") from exc
    return calldata.lower()


def observe_router_swap_call(
    observers: Iterable[EvmReadOnlyRpc],
    *,
    chain: str,
    router: str,
    caller: str,
    calldata: str,
    block_number: int,
    value: int = 0,
    min_quorum: int = 2,
) -> RouterSwapCallEvidence:
    """Observe one exact historical router eth_call with provider agreement.

    Positive evidence means distinct providers agreed that this exact call returned
    the exact same result at the supplied block. It does not prove the router is an
    approved/authentic DEX component, that state-changing execution would succeed,
    that token transfers/taxes match expectations, or that a real sell would settle.
    """
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if block_number < 0:
        raise ValueError("block_number must be non-negative")
    if value < 0:
        raise ValueError("value must be non-negative")

    router_address = canonical_chain_address(chain, router)
    caller_address = canonical_chain_address(chain, caller)
    if router_address is None or caller_address is None:
        raise ValueError("router and caller must be valid addresses for the requested chain")
    data = _normalize_calldata(calldata)

    distinct: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        distinct.setdefault(provider_fingerprint(observer.rpc_url), observer)
    if len(distinct) < min_quorum:
        raise EvmRpcError("insufficient distinct RPC providers for router-call quorum")

    router_code = observe_contract_code(
        distinct.values(),
        chain=chain,
        address=router_address,
        block_number=block_number,
        min_quorum=min_quorum,
    )

    rows: list[RouterCallProviderEvidence] = []
    groups: dict[str, list[str]] = {}
    for provider, observer in distinct.items():
        if observer.chain.key != chain:
            continue
        call = {"to": router_address, "from": caller_address, "data": data}
        if value:
            call["value"] = hex(value)
        try:
            observer.attest_chain()
            result = observer._call("eth_call", [call, hex(block_number)])
            if not isinstance(result, str) or not result.startswith("0x") or len(result) % 2:
                raise EvmRpcError("invalid router eth_call response")
            int(result[2:] or "0", 16)
            result = result.lower()
        except (EvmRpcError, ValueError):
            rows.append(RouterCallProviderEvidence(provider, "UNKNOWN_CALL_FAILURE", None))
            continue
        rows.append(RouterCallProviderEvidence(provider, "ROUTER_CALL_SUCCEEDED", result))
        groups.setdefault(result, []).append(provider)

    qualifying = [(result, providers) for result, providers in groups.items() if len(providers) >= min_quorum]
    agreed_result: str | None = None
    successful_providers: tuple[str, ...] = ()
    if len(qualifying) == 1 and len(groups) == 1:
        agreed_result, providers = qualifying[0]
        successful_providers = tuple(sorted(providers))
        verdict = "ROUTER_SWAP_CALL_QUORUM_SUCCEEDED"
    elif len(groups) > 1:
        verdict = "UNKNOWN_ROUTER_CALL_DISAGREEMENT"
    else:
        verdict = "UNKNOWN_INSUFFICIENT_ROUTER_CALL_EVIDENCE"

    return RouterSwapCallEvidence(
        chain=chain,
        router=router_address,
        caller=caller_address,
        block_number=block_number,
        calldata=data,
        value=value,
        router_code=router_code,
        successful_providers=successful_providers,
        provider_evidence=tuple(sorted(rows, key=lambda row: row.provider)),
        agreed_result=agreed_result,
        verdict=verdict,
        status="UNVERIFIED_ROUTER_SWAP_CALL_EVIDENCE",
        limitations=(
            "CALLDATA_IS_OPAQUE_AND_NOT_SEMANTICALLY_VERIFIED",
            "CONTRACT_CODE_PRESENCE_DOES_NOT_PROVE_ROUTER_AUTHENTICITY",
            "ETH_CALL_SUCCESS_DOES_NOT_PROVE_STATE_CHANGING_TRANSACTION_SUCCESS",
            "DOES_NOT_PROVE_PAIR_AUTHENTICITY_OR_PAIR_SWAP_EXECUTION",
            "DOES_NOT_PROVE_TOKEN_TAX_OR_TRANSFER_BEHAVIOR",
            "DOES_NOT_PROVE_OUTPUT_AMOUNT_OR_REAL_SALE_SUCCESS",
            "CALL_FAILURE_IS_NOT_A_HONEYPOT_VERDICT",
        ),
    )
