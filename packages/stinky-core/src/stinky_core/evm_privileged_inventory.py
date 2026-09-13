"""Read-only privileged/authority selector inventory from quorum-backed EVM bytecode.

A PUSH4 occurrence is only a bytecode selector candidate. Even a known selector does
not prove that the function is externally reachable, privileged, currently usable,
or malicious. This module intentionally records evidence without making those claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .evm_contract_code import ContractCodeEvidence
from .evm_rpc import EvmRpcError


KNOWN_AUTHORITY_SELECTORS = {
    "0x8da5cb5b": ("owner()", "OWNERSHIP", "AUTHORITY_READ"),
    "0xf851a440": ("admin()", "PROXY_ADMIN", "AUTHORITY_READ"),
    "0x5c60da1b": ("implementation()", "PROXY_IMPLEMENTATION", "AUTHORITY_READ"),
    "0xf2fde38b": ("transferOwnership(address)", "OWNERSHIP", "AUTHORITY_MUTATION"),
    "0x715018a6": ("renounceOwnership()", "OWNERSHIP", "AUTHORITY_MUTATION"),
    "0x8f283970": ("changeAdmin(address)", "PROXY_ADMIN", "AUTHORITY_MUTATION"),
    "0x3659cfe6": ("upgradeTo(address)", "PROXY_UPGRADE", "AUTHORITY_MUTATION"),
    "0x4f1ef286": ("upgradeToAndCall(address,bytes)", "PROXY_UPGRADE", "AUTHORITY_MUTATION"),
    "0x8456cb59": ("pause()", "PAUSE_CONTROL", "AUTHORITY_MUTATION"),
    "0x3f4ba83a": ("unpause()", "PAUSE_CONTROL", "AUTHORITY_MUTATION"),
    "0x2f2ff15d": ("grantRole(bytes32,address)", "ROLE_CONTROL", "AUTHORITY_MUTATION"),
    "0xd547741f": ("revokeRole(bytes32,address)", "ROLE_CONTROL", "AUTHORITY_MUTATION"),
    "0x91d14854": ("hasRole(bytes32,address)", "ROLE_CONTROL", "AUTHORITY_READ"),
    "0x248a9ca3": ("getRoleAdmin(bytes32)", "ROLE_CONTROL", "AUTHORITY_READ"),
}


@dataclass(frozen=True, slots=True)
class SelectorCandidate:
    selector: str
    offsets: tuple[int, ...]
    status: str


@dataclass(frozen=True, slots=True)
class PrivilegedSurfaceEvidence:
    selector: str
    signature: str
    category: str
    authority_effect: str
    offsets: tuple[int, ...]
    status: str


@dataclass(frozen=True, slots=True)
class PrivilegedAuthorityInventory:
    chain: str
    contract_key: str
    block_number: int
    code_fingerprint_sha256: str
    providers: tuple[str, ...]
    selector_candidates: tuple[SelectorCandidate, ...]
    privileged_surfaces: tuple[PrivilegedSurfaceEvidence, ...]
    status: str


def _validated_runtime(code: ContractCodeEvidence, min_quorum: int) -> bytes:
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    providers = {source.provider for source in code.sources}
    if len(providers) < min_quorum:
        raise EvmRpcError("contract code lacks independent quorum provenance")
    if any(
        source.fingerprint_sha256 != code.fingerprint_sha256 or source.byte_length != code.byte_length
        for source in code.sources
    ):
        raise EvmRpcError("contract-code source provenance disagrees with evidence")
    value = code.runtime_bytecode
    if not isinstance(value, str) or not value.startswith("0x") or len(value) % 2:
        raise EvmRpcError("invalid runtime bytecode evidence")
    try:
        raw = bytes.fromhex(value[2:])
    except ValueError as exc:
        raise EvmRpcError("invalid runtime bytecode evidence") from exc
    if len(raw) != code.byte_length or sha256(raw).hexdigest() != code.fingerprint_sha256:
        raise EvmRpcError("runtime bytecode does not match contract-code fingerprint")
    return raw


def _push4_candidates(raw: bytes) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    offset = 0
    while offset < len(raw):
        opcode = raw[offset]
        if opcode == 0x63 and offset + 4 < len(raw):
            selector = "0x" + raw[offset + 1:offset + 5].hex()
            found.setdefault(selector, []).append(offset)
            offset += 5
            continue
        if 0x60 <= opcode <= 0x7F:
            width = opcode - 0x5F
            offset += 1 + width
            continue
        offset += 1
    return found


def inventory_privileged_authority_surfaces(
    code: ContractCodeEvidence,
    *,
    min_quorum: int = 2,
) -> PrivilegedAuthorityInventory:
    """Inventory PUSH4 selector candidates without asserting callability or safety."""
    raw = _validated_runtime(code, min_quorum)
    found = _push4_candidates(raw)
    candidates = tuple(
        SelectorCandidate(selector, tuple(offsets), "BYTECODE_PUSH4_SELECTOR_CANDIDATE")
        for selector, offsets in sorted(found.items())
    )
    privileged = []
    for selector, offsets in sorted(found.items()):
        known = KNOWN_AUTHORITY_SELECTORS.get(selector)
        if known is None:
            continue
        signature, category, effect = known
        privileged.append(
            PrivilegedSurfaceEvidence(
                selector,
                signature,
                category,
                effect,
                tuple(offsets),
                "KNOWN_AUTHORITY_SELECTOR_BYTECODE_CANDIDATE",
            )
        )
    return PrivilegedAuthorityInventory(
        code.chain,
        code.contract_key,
        code.block_number,
        code.fingerprint_sha256,
        tuple(sorted({source.provider for source in code.sources})),
        candidates,
        tuple(privileged),
        "UNVERIFIED_PRIVILEGED_AUTHORITY_INVENTORY_EVIDENCE",
    )
