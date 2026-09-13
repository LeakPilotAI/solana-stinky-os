"""Consensus-backed EVM contract-code evidence and deterministic fingerprints.

Code presence is not proof that a contract is safe, verified, or an authentic DEX
factory. Genesis records exact historical runtime bytecode only after distinct RPC
providers agree, then derives a neutral SHA-256 fingerprint for later similarity
and scam-memory analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from .evm_consensus import provider_fingerprint
from .evm_dex_discovery import DexPoolCandidate
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError
from .multichain_identity import asset_key, canonical_chain_address


@dataclass(frozen=True, slots=True)
class ContractCodeSource:
    provider: str
    fingerprint_sha256: str
    byte_length: int


@dataclass(frozen=True, slots=True)
class ContractCodeEvidence:
    chain: str
    chain_id: int
    address: str
    contract_key: str
    block_number: int
    byte_length: int
    fingerprint_sha256: str
    runtime_bytecode: str
    status: str
    sources: tuple[ContractCodeSource, ...]


def _distinct(observers: Iterable[EvmReadOnlyRpc]) -> list[EvmReadOnlyRpc]:
    out: dict[str, EvmReadOnlyRpc] = {}
    for observer in observers:
        out.setdefault(provider_fingerprint(observer.rpc_url), observer)
    return list(out.values())


def _fingerprint(code: str) -> tuple[str, int]:
    raw = bytes.fromhex(code[2:])
    return sha256(raw).hexdigest(), len(raw)


def _get_code_at_block(observer: EvmReadOnlyRpc, address: str, block_number: int) -> str:
    observer.attest_chain()
    result = observer._call("eth_getCode", [address, hex(block_number)])
    if not isinstance(result, str) or not result.startswith("0x") or len(result) % 2:
        raise EvmRpcError("invalid eth_getCode response")
    try:
        int(result[2:] or "0", 16)
    except ValueError as exc:
        raise EvmRpcError("invalid eth_getCode response") from exc
    return result.lower()


def observe_contract_code(
    observers: Iterable[EvmReadOnlyRpc],
    *,
    chain: str,
    address: str,
    block_number: int,
    min_quorum: int = 2,
) -> ContractCodeEvidence:
    """Observe runtime bytecode at one historical block and require exact quorum."""
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if block_number < 0:
        raise ValueError("block_number must be non-negative")
    canonical = canonical_chain_address(chain, address)
    if canonical is None:
        raise ValueError("address must be valid for the requested chain")

    providers = _distinct(observers)
    if len(providers) < min_quorum:
        raise EvmRpcError("insufficient distinct RPC providers for contract-code quorum")

    groups: dict[str, list[ContractCodeSource]] = {}
    chain_id: int | None = None
    for observer in providers:
        if observer.chain.key != chain:
            continue
        try:
            code = _get_code_at_block(observer, canonical, block_number)
        except EvmRpcError:
            continue
        if code == "0x":
            continue
        digest, byte_length = _fingerprint(code)
        groups.setdefault(code, []).append(
            ContractCodeSource(
                provider=provider_fingerprint(observer.rpc_url),
                fingerprint_sha256=digest,
                byte_length=byte_length,
            )
        )
        chain_id = observer.chain.chain_id

    qualifying = [(code, rows) for code, rows in groups.items() if len(rows) >= min_quorum]
    if len(qualifying) != 1:
        raise EvmRpcError("contract-code quorum not reached")
    code, rows = qualifying[0]
    digest, byte_length = _fingerprint(code)
    if chain_id is None:
        raise EvmRpcError("contract-code chain evidence missing")

    key = asset_key(chain, canonical)
    if key is None:
        raise EvmRpcError("contract identity could not be canonicalized")

    return ContractCodeEvidence(
        chain=chain,
        chain_id=chain_id,
        address=canonical,
        contract_key=key,
        block_number=block_number,
        byte_length=byte_length,
        fingerprint_sha256=digest,
        runtime_bytecode=code,
        status="UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        sources=tuple(sorted(rows, key=lambda row: row.provider)),
    )


def observe_factory_contract_code(
    observers: Iterable[EvmReadOnlyRpc],
    pool: DexPoolCandidate,
    *,
    block_number: int,
    min_quorum: int = 2,
) -> ContractCodeEvidence:
    """Observe the candidate factory code without claiming factory authenticity."""
    evidence = observe_contract_code(
        observers,
        chain=pool.chain,
        address=pool.factory_address,
        block_number=block_number,
        min_quorum=min_quorum,
    )
    if evidence.contract_key != pool.factory_key:
        raise EvmRpcError("factory contract identity mismatch")
    return evidence


def observe_pool_contract_code(
    observers: Iterable[EvmReadOnlyRpc],
    pool: DexPoolCandidate,
    *,
    block_number: int,
    min_quorum: int = 2,
) -> ContractCodeEvidence:
    """Observe the candidate pool code without claiming pool authenticity."""
    evidence = observe_contract_code(
        observers,
        chain=pool.chain,
        address=pool.pool_address,
        block_number=block_number,
        min_quorum=min_quorum,
    )
    if evidence.contract_key != pool.pool_key:
        raise EvmRpcError("pool contract identity mismatch")
    return evidence
