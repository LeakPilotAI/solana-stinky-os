"""Read-only EVM holder and router/pair sell-path evidence.

Genesis never submits a transaction from this module. A successful historical eth_call
is only evidence about the exact call and state observed at one block. Even when a
standard ERC-20 allowance and a holder-to-pair transfer preflight both succeed, that
does not prove a router swap, transferFrom path, pair swap, output amount, tax behavior,
or real sale would succeed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .evm_consensus import provider_fingerprint
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError
from .multichain_identity import asset_key, canonical_chain_address

TRANSFER_SELECTOR = "a9059cbb"
ALLOWANCE_SELECTOR = "dd62ed3e"


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


@dataclass(frozen=True, slots=True)
class AllowanceProviderEvidence:
    provider: str
    outcome: str
    allowance: int | None


@dataclass(frozen=True, slots=True)
class RouterPairSellPathEvidence:
    chain: str
    token_key: str
    block_number: int
    holder: str
    router: str
    pair: str
    amount: int
    allowance: int | None
    allowance_providers: tuple[str, ...]
    allowance_evidence: tuple[AllowanceProviderEvidence, ...]
    transfer_path: TransferPathEvidence
    allowance_verdict: str
    verdict: str
    status: str
    limitations: tuple[str, ...]


def _encode_transfer(recipient: str, amount: int) -> str:
    if amount <= 0:
        raise ValueError("amount must be positive")
    return "0x" + TRANSFER_SELECTOR + ("0" * 24) + recipient[2:] + f"{amount:064x}"


def _encode_allowance(holder: str, router: str) -> str:
    return "0x" + ALLOWANCE_SELECTOR + ("0" * 24) + holder[2:] + ("0" * 24) + router[2:]


def _distinct(observers: Iterable[EvmReadOnlyRpc]) -> dict[str, EvmReadOnlyRpc]:
    distinct: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        distinct.setdefault(provider_fingerprint(observer.rpc_url), observer)
    return distinct


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

    distinct = _distinct(observers)
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


def observe_router_pair_sell_prerequisites(
    observers: Iterable[EvmReadOnlyRpc],
    *,
    chain: str,
    token: str,
    holder: str,
    router: str,
    pair: str,
    amount: int,
    block_number: int,
    min_quorum: int = 2,
) -> RouterPairSellPathEvidence:
    """Observe standard allowance plus holder-to-pair transfer prerequisites.

    This does not execute or emulate a router swap. It only asks whether the historical
    state shows enough standard ERC-20 allowance for ``router`` and whether an
    independent holder ``transfer(pair, amount)`` preflight succeeds at the same block.
    """
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if block_number < 0:
        raise ValueError("block_number must be non-negative")
    if amount <= 0:
        raise ValueError("amount must be positive")

    token_address = canonical_chain_address(chain, token)
    holder_address = canonical_chain_address(chain, holder)
    router_address = canonical_chain_address(chain, router)
    pair_address = canonical_chain_address(chain, pair)
    if None in (token_address, holder_address, router_address, pair_address):
        raise ValueError("token, holder, router, and pair must be valid addresses for the requested chain")
    assert token_address is not None
    assert holder_address is not None
    assert router_address is not None
    assert pair_address is not None

    distinct = _distinct(observers)
    if len(distinct) < min_quorum:
        raise EvmRpcError("insufficient distinct RPC providers for router/pair sell-path quorum")

    allowance_data = _encode_allowance(holder_address, router_address)
    allowance_rows: list[AllowanceProviderEvidence] = []
    valid_allowances: dict[int, list[str]] = {}
    for provider, observer in distinct.items():
        if observer.chain.key != chain:
            continue
        try:
            observer.attest_chain()
            result = observer._call(
                "eth_call",
                [{"to": token_address, "from": holder_address, "data": allowance_data}, hex(block_number)],
            )
            if not isinstance(result, str) or not result.startswith("0x") or len(result) != 66:
                raise EvmRpcError("invalid allowance eth_call response")
            allowance = int(result[2:], 16)
        except (EvmRpcError, ValueError):
            allowance_rows.append(AllowanceProviderEvidence(provider, "UNKNOWN_CALL_FAILURE", None))
            continue
        allowance_rows.append(AllowanceProviderEvidence(provider, "ALLOWANCE_OBSERVED", allowance))
        valid_allowances.setdefault(allowance, []).append(provider)

    allowance: int | None = None
    allowance_providers: tuple[str, ...] = ()
    qualifying = [(value, providers) for value, providers in valid_allowances.items() if len(providers) >= min_quorum]
    if len(qualifying) == 1 and len(valid_allowances) == 1:
        allowance, providers = qualifying[0]
        allowance_providers = tuple(sorted(providers))
        allowance_verdict = "STANDARD_ALLOWANCE_SUFFICIENT" if allowance >= amount else "STANDARD_ALLOWANCE_INSUFFICIENT"
    else:
        allowance_verdict = "UNKNOWN_ALLOWANCE_EVIDENCE"

    transfer_path = observe_transfer_path(
        distinct.values(),
        chain=chain,
        token=token_address,
        holder=holder_address,
        recipient=pair_address,
        amount=amount,
        block_number=block_number,
        min_quorum=min_quorum,
    )

    if allowance_verdict == "STANDARD_ALLOWANCE_SUFFICIENT" and transfer_path.verdict == "TRANSFER_CALL_SUCCEEDED":
        verdict = "STANDARD_SELL_PREREQUISITES_OBSERVED"
    elif allowance_verdict == "STANDARD_ALLOWANCE_INSUFFICIENT":
        verdict = "STANDARD_ALLOWANCE_INSUFFICIENT_FOR_AMOUNT"
    else:
        verdict = "UNKNOWN_INSUFFICIENT_SELL_PATH_EVIDENCE"

    token_key = asset_key(chain, token_address)
    if token_key is None:
        raise EvmRpcError("token identity could not be canonicalized")
    return RouterPairSellPathEvidence(
        chain,
        token_key,
        block_number,
        holder_address,
        router_address,
        pair_address,
        amount,
        allowance,
        allowance_providers,
        tuple(sorted(allowance_rows, key=lambda row: row.provider)),
        transfer_path,
        allowance_verdict,
        verdict,
        "UNVERIFIED_ROUTER_PAIR_SELL_PATH_EVIDENCE",
        (
            "DOES_NOT_PROVE_ROUTER_AUTHENTICITY",
            "DOES_NOT_PROVE_PAIR_AUTHENTICITY",
            "DOES_NOT_EXECUTE_ROUTER_SWAP",
            "DOES_NOT_PROVE_TRANSFER_FROM_PATH",
            "DOES_NOT_PROVE_PAIR_SWAP_EXECUTION",
            "DOES_NOT_PROVE_OUTPUT_AMOUNT_OR_TAXES",
            "DOES_NOT_PROVE_REAL_SALE_SUCCESS",
        ),
    )
