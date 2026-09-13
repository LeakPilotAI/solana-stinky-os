"""Temporal change history for read-only EVM proxy/authority evidence.

History rows describe differences between independently observed historical snapshots.
They do not prove an upgrade was malicious, intentional, successful, or controlled
by a particular actor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .evm_proxy_authority import AddressEvidence, ProxyAuthorityEvidence
from .evm_rpc import EvmRpcError


@dataclass(frozen=True, slots=True)
class ProxyAuthorityChange:
    chain: str
    contract_key: str
    from_block: int
    to_block: int
    field: str
    before_address: str | None
    after_address: str | None
    before_status: str | None
    after_status: str | None
    before_providers: tuple[str, ...]
    after_providers: tuple[str, ...]
    classification: str
    status: str


def _address(value: AddressEvidence | None) -> str | None:
    return value.address if value is not None else None


def _status(value: AddressEvidence | None) -> str | None:
    return value.status if value is not None else None


def _providers(value: AddressEvidence | None) -> tuple[str, ...]:
    return value.providers if value is not None else ()


def _require_same_ordered_contract(previous: ProxyAuthorityEvidence, current: ProxyAuthorityEvidence) -> None:
    if previous.chain != current.chain or previous.contract_key != current.contract_key:
        raise EvmRpcError("proxy history cannot cross chains or contracts")
    if current.block_number <= previous.block_number:
        raise EvmRpcError("proxy history requires strictly increasing blocks")


def _classification(before: str | None, after: str | None) -> str:
    if before == after:
        return "UNCHANGED"
    if before is None and after is not None:
        return "EVIDENCE_APPEARED"
    if before is not None and after is None:
        return "EVIDENCE_DISAPPEARED"
    return "ADDRESS_CHANGED"


def _change(
    previous: ProxyAuthorityEvidence,
    current: ProxyAuthorityEvidence,
    field: str,
    before: AddressEvidence | None,
    after: AddressEvidence | None,
) -> ProxyAuthorityChange | None:
    before_address = _address(before)
    after_address = _address(after)
    classification = _classification(before_address, after_address)
    if classification == "UNCHANGED":
        return None
    return ProxyAuthorityChange(
        current.chain,
        current.contract_key,
        previous.block_number,
        current.block_number,
        field,
        before_address,
        after_address,
        _status(before),
        _status(after),
        _providers(before),
        _providers(after),
        classification,
        "UNVERIFIED_PROXY_AUTHORITY_CHANGE_EVIDENCE",
    )


def derive_proxy_authority_changes(
    previous: ProxyAuthorityEvidence,
    current: ProxyAuthorityEvidence,
) -> tuple[ProxyAuthorityChange, ...]:
    """Return only fields whose quorum-backed address evidence changed."""
    _require_same_ordered_contract(previous, current)
    fields = (
        ("implementation_selector", previous.implementation, current.implementation),
        ("admin_selector", previous.admin, current.admin),
        ("owner_selector", previous.owner, current.owner),
        ("eip1967_implementation", previous.eip1967_implementation, current.eip1967_implementation),
        ("eip1967_admin", previous.eip1967_admin, current.eip1967_admin),
        ("eip1967_beacon", previous.eip1967_beacon, current.eip1967_beacon),
        ("beacon_implementation", previous.beacon_implementation, current.beacon_implementation),
    )
    out: list[ProxyAuthorityChange] = []
    for field, before, after in fields:
        row = _change(previous, current, field, before, after)
        if row is not None:
            out.append(row)
    return tuple(out)


def build_proxy_authority_change_history(
    rows: Sequence[ProxyAuthorityEvidence],
) -> tuple[ProxyAuthorityChange, ...]:
    """Build ordered temporal changes without sorting or inventing missing history."""
    if len(rows) < 2:
        return ()
    out: list[ProxyAuthorityChange] = []
    for index in range(1, len(rows)):
        out.extend(derive_proxy_authority_changes(rows[index - 1], rows[index]))
    return tuple(out)
