"""Conservative token-authority evidence derived from privileged selector inventory.

Selector presence is bytecode evidence only. It does not prove the function is
externally reachable, currently authorized, active, safe, or malicious.
"""
from __future__ import annotations

from dataclasses import dataclass

from .evm_privileged_inventory import PrivilegedAuthorityInventory
from .evm_rpc import EvmRpcError

TOKEN_CAPABILITY_SELECTORS = {
    "0x40c10f19": ("mint(address,uint256)", "SUPPLY_EXPANSION", "TOKEN_SUPPLY_MUTATION"),
    "0x8456cb59": ("pause()", "PAUSE_CONTROL", "TRANSFER_AVAILABILITY_MUTATION"),
    "0x3f4ba83a": ("unpause()", "PAUSE_CONTROL", "TRANSFER_AVAILABILITY_MUTATION"),
    "0xf2fde38b": ("transferOwnership(address)", "OWNERSHIP_CONTROL", "AUTHORITY_MUTATION"),
    "0x715018a6": ("renounceOwnership()", "OWNERSHIP_CONTROL", "AUTHORITY_MUTATION"),
    "0x2f2ff15d": ("grantRole(bytes32,address)", "ROLE_CONTROL", "AUTHORITY_MUTATION"),
    "0xd547741f": ("revokeRole(bytes32,address)", "ROLE_CONTROL", "AUTHORITY_MUTATION"),
}

UNRESOLVED_CAPABILITY_FAMILIES = (
    "BLACKLIST_WHITELIST_CONTROL",
    "TRADING_ENABLE_DISABLE_CONTROL",
    "TRANSFER_LIMIT_CONTROL",
    "WALLET_LIMIT_CONTROL",
    "BUY_SELL_LIMIT_CONTROL",
    "FEE_TAX_CONTROL",
)


@dataclass(frozen=True, slots=True)
class TokenAuthorityCapabilityEvidence:
    selector: str
    signature: str
    capability: str
    effect: str
    offsets: tuple[int, ...]
    status: str


@dataclass(frozen=True, slots=True)
class TokenAuthorityCoverage:
    family: str
    state: str
    reason: str


@dataclass(frozen=True, slots=True)
class TokenAuthorityAssessment:
    chain: str
    contract_key: str
    block_number: int
    code_fingerprint_sha256: str
    providers: tuple[str, ...]
    capabilities: tuple[TokenAuthorityCapabilityEvidence, ...]
    unresolved_families: tuple[TokenAuthorityCoverage, ...]
    status: str


def assess_token_authority(
    inventory: PrivilegedAuthorityInventory,
    *,
    min_quorum: int = 2,
) -> TokenAuthorityAssessment:
    """Classify supported token authority surfaces without inferring active control."""
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if inventory.status != "UNVERIFIED_PRIVILEGED_AUTHORITY_INVENTORY_EVIDENCE":
        raise EvmRpcError("token authority requires canonical privileged inventory evidence")
    if len(set(inventory.providers)) < min_quorum:
        raise EvmRpcError("token authority inventory lacks independent provider quorum")
    if len(inventory.code_fingerprint_sha256) != 64:
        raise EvmRpcError("token authority inventory lacks canonical code fingerprint")

    candidates = {row.selector: row for row in inventory.selector_candidates}
    capabilities: list[TokenAuthorityCapabilityEvidence] = []
    for selector, (signature, capability, effect) in sorted(TOKEN_CAPABILITY_SELECTORS.items()):
        candidate = candidates.get(selector)
        if candidate is None:
            continue
        if candidate.status != "BYTECODE_PUSH4_SELECTOR_CANDIDATE":
            raise EvmRpcError("token authority selector candidate status is not canonical")
        capabilities.append(
            TokenAuthorityCapabilityEvidence(
                selector,
                signature,
                capability,
                effect,
                candidate.offsets,
                "UNVERIFIED_TOKEN_AUTHORITY_SELECTOR_EVIDENCE",
            )
        )

    unresolved = tuple(
        TokenAuthorityCoverage(
            family,
            "UNKNOWN_NOT_ASSESSED",
            "NONSTANDARD_OR_UNSUPPORTED_SELECTOR_FAMILY",
        )
        for family in UNRESOLVED_CAPABILITY_FAMILIES
    )

    return TokenAuthorityAssessment(
        inventory.chain,
        inventory.contract_key,
        inventory.block_number,
        inventory.code_fingerprint_sha256,
        tuple(sorted(set(inventory.providers))),
        tuple(capabilities),
        unresolved,
        "UNVERIFIED_TOKEN_AUTHORITY_ASSESSMENT_EVIDENCE",
    )
