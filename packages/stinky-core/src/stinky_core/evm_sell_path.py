"""Read-only holder transfer preflight for EVM honeypot/sell-path evidence.

A successful historical eth_call is evidence that one ERC-20 transfer call completed
under the observed state. It is not proof that a router swap, approval flow, pair
transfer, or real sale would succeed. Provider failures remain UNKNOWN rather than
being promoted to a honeypot verdict because transport errors and EVM reverts are not
reliably distinguishable at this layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_consensus import provider_fingerprint
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError
from .multichain_identity import asset_key, canonical_chain_address

TRANSFER_SELECTOR = "a9059cbb"


@dataclass(frozen=True, slots=True)
class TransferPathProviderEvidence:
    provider: str
    outcome: str


@dataclass(frozen=True, slots=True)
class TransferPathEvidence:
    chain: str
    token_key: str
    block_number: int
    holder: str
    recipient: str
    amount: int
    successful_providers: tuple[str, ...]
    provider_evidence: tuple[TransferPathProviderEvidence, ...]
    verdict: str
    status: str
    limitations: tuple[str, ...]


def _encode_transfer(recipient: str, amount: int) -> str:
    if amount <= 0:
        raise ValueError("amount must be positive")
    return "0x" + TRANSFER_SELECTOR + ("0" * 24) + recipient[2:] + f"{amount:064x}"


def observe_transfer_path(
    observers: Iterable[EvmReadOnlyRpc],
    *,
    chain: str,
    token: str,
    holder: str,
    recipient: str,
    amount: int,
    block_number: int,
    min_quorum: int = 2,
) -> TransferPathEvidence:
    """Require independent historical eth_call success for one holder transfer path."""
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if block_number < 0:
        raise ValueError("block_number must be non-negative")
    token_address = canonical_chain_address(chain, token)
    holder_address = canonical_chain_address(chain, holder)
    recipient_address = canonical_chain_address(chain, recipient)
    if token_address is None or holder_address is None or recipient_address is None:
        raise ValueError("token, holder, and recipient must be valid addresses for the requested chain")
    calldata = _encode_transfer(recipient_address, amount)

    distinct: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        distinct.setdefault(provider_fingerprint(observer.rpc_url), observer)
    if len(distinct) < min_quorum:
        raise EvmRpcError("insufficient distinct RPC providers for transfer-path quorum")

    rows: list[TransferPathProviderEvidence] = []
    successes: list[str] = []
    for provider, observer in distinct.items():
        if observer.chain.key != chain:
            continue
        try:
            observer.attest_chain()
            result = observer._call(
                "eth_call",
                [{"to": token_address, "from": holder_address, "data": calldata}, hex(block_number)],
            )
            if not isinstance(result, str) or not result.startswith("0x") or len(result) % 2:
                raise EvmRpcError("invalid eth_call response")
            int(result[2:] or "0", 16)
        except (EvmRpcError, ValueError):
            rows.append(TransferPathProviderEvidence(provider, "UNKNOWN_CALL_FAILURE"))
            continue
        rows.append(TransferPathProviderEvidence(provider, "CALL_SUCCEEDED"))
        successes.append(provider)

    verdict = "TRANSFER_CALL_SUCCEEDED" if len(successes) >= min_quorum else "UNKNOWN_INSUFFICIENT_SUCCESS_EVIDENCE"
    token_key = asset_key(chain, token_address)
    if token_key is None:
        raise EvmRpcError("token identity could not be canonicalized")
    return TransferPathEvidence(
        chain,
        token_key,
        block_number,
        holder_address,
        recipient_address,
        amount,
        tuple(sorted(successes)),
        tuple(sorted(rows, key=lambda row: row.provider)),
        verdict,
        "UNVERIFIED_TRANSFER_PATH_SIMULATION_EVIDENCE",
        (
            "DOES_NOT_PROVE_ROUTER_SELLABILITY",
            "DOES_NOT_PROVE_APPROVAL_FLOW",
            "DOES_NOT_PROVE_PAIR_TRANSFER_BEHAVIOR",
            "CALL_FAILURE_IS_NOT_A_HONEYPOT_VERDICT",
        ),
    )
