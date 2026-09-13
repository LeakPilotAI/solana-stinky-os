"""Read-only proxy/authority evidence. No result here proves safety or control."""
from dataclasses import dataclass
from typing import Iterable
from .evm_consensus import provider_fingerprint
from .evm_contract_code import ContractCodeEvidence
from .evm_rpc import EvmReadOnlyRpc, EvmRpcError
from .multichain_identity import asset_key, canonical_chain_address

OWNER_SELECTOR = "0x8da5cb5b"
IMPLEMENTATION_SELECTOR = "0x5c60da1b"
ADMIN_SELECTOR = "0xf851a440"
_PFX = "363d3d373d3d3d363d73"
_SFX = "5af43d82803e903d91602b57fd5bf3"

@dataclass(frozen=True, slots=True)
class AddressEvidence:
    selector: str
    address: str
    address_key: str
    status: str
    providers: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ProxyAuthorityEvidence:
    chain: str
    contract_key: str
    block_number: int
    minimal_proxy_target: str | None
    minimal_proxy_target_key: str | None
    minimal_proxy_status: str
    implementation: AddressEvidence | None
    admin: AddressEvidence | None
    owner: AddressEvidence | None
    status: str


def _word_address(chain: str, value: str) -> str | None:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        return None
    body = value[2:]
    try:
        int(body, 16)
    except ValueError:
        return None
    if body[:24].lower() != "0" * 24 or int(body[-40:], 16) == 0:
        return None
    return canonical_chain_address(chain, "0x" + body[-40:])


def _eip1167(code: ContractCodeEvidence) -> str | None:
    body = code.runtime_bytecode[2:].lower()
    if len(body) != len(_PFX) + 40 + len(_SFX) or not body.startswith(_PFX) or not body.endswith(_SFX):
        return None
    return canonical_chain_address(code.chain, "0x" + body[len(_PFX):len(_PFX)+40])


def _selector(observers: Iterable[EvmReadOnlyRpc], code: ContractCodeEvidence, selector: str, label: str, quorum: int) -> AddressEvidence | None:
    unique = {}
    for rpc in observers:
        if rpc.chain.key == code.chain:
            unique.setdefault(provider_fingerprint(rpc.rpc_url), rpc)
    if len(unique) < quorum:
        raise EvmRpcError("insufficient distinct RPC providers for authority evidence")
    groups: dict[str, list[str]] = {}
    for provider, rpc in unique.items():
        try:
            address = _word_address(code.chain, rpc.call_at_block(code.address, selector, code.block_number))
        except EvmRpcError:
            continue
        if address:
            groups.setdefault(address, []).append(provider)
    matches = [(a, p) for a, p in groups.items() if len(p) >= quorum]
    if not matches:
        return None
    if len(matches) != 1:
        raise EvmRpcError("conflicting authority selector quorum")
    address, providers = matches[0]
    key = asset_key(code.chain, address)
    if key is None:
        raise EvmRpcError("authority identity could not be canonicalized")
    return AddressEvidence(selector, address, key, label, tuple(sorted(providers)))


def inspect_proxy_authority(observers: Iterable[EvmReadOnlyRpc], code: ContractCodeEvidence, *, min_quorum: int = 2) -> ProxyAuthorityEvidence:
    if min_quorum < 2:
        raise ValueError("min_quorum must be at least 2")
    if len({s.provider for s in code.sources}) < min_quorum:
        raise EvmRpcError("contract code lacks independent quorum provenance")
    target = _eip1167(code)
    return ProxyAuthorityEvidence(
        code.chain,
        code.contract_key,
        code.block_number,
        target,
        asset_key(code.chain, target) if target else None,
        "CANONICAL_EIP1167_RUNTIME_PATTERN" if target else "NO_CANONICAL_EIP1167_PATTERN",
        _selector(observers, code, IMPLEMENTATION_SELECTOR, "IMPLEMENTATION_SELECTOR_QUORUM_EVIDENCE", min_quorum),
        _selector(observers, code, ADMIN_SELECTOR, "ADMIN_SELECTOR_QUORUM_EVIDENCE", min_quorum),
        _selector(observers, code, OWNER_SELECTOR, "OWNER_SELECTOR_QUORUM_EVIDENCE", min_quorum),
        "UNVERIFIED_PROXY_AUTHORITY_EVIDENCE",
    )
