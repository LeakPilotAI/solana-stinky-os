"""Temporal change history and conservative alerts for EVM proxy authority evidence.

History rows and alerts describe differences between independently observed historical
snapshots. They do not prove an upgrade was malicious, intentional, successful, or
controlled by a particular actor.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Sequence

from .evm_proxy_authority import AddressEvidence, ProxyAuthorityEvidence
from .evm_rpc import EvmRpcError

_CHANGE_STATUS = "UNVERIFIED_PROXY_AUTHORITY_CHANGE_EVIDENCE"
_ALERT_STATUS = "UNVERIFIED_PROXY_AUTHORITY_ALERT_EVIDENCE"
_ALERT_TYPES = {
    "implementation_selector": "PROXY_IMPLEMENTATION_CHANGED",
    "eip1967_implementation": "PROXY_IMPLEMENTATION_CHANGED",
    "beacon_implementation": "BEACON_IMPLEMENTATION_CHANGED",
    "eip1967_beacon": "PROXY_BEACON_CHANGED",
    "admin_selector": "PROXY_ADMIN_CHANGED",
    "eip1967_admin": "PROXY_ADMIN_CHANGED",
    "owner_selector": "PROXY_OWNER_CHANGED",
}


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


@dataclass(frozen=True, slots=True)
class ProxyAuthorityAlert:
    alert_id: str
    chain: str
    contract_key: str
    from_block: int
    to_block: int
    alert_type: str
    field: str
    severity: str
    classification: str
    before_address: str | None
    after_address: str | None
    before_providers: tuple[str, ...]
    after_providers: tuple[str, ...]
    evidence_quality: str
    intent: str
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
        _CHANGE_STATUS,
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


def _require_provider_quorum(providers: tuple[str, ...], side: str) -> None:
    if len(set(providers)) < 2:
        raise EvmRpcError(f"proxy authority alert requires distinct provider quorum for {side} evidence")


def _validate_alert_change(change: ProxyAuthorityChange) -> None:
    if change.status != _CHANGE_STATUS:
        raise EvmRpcError("proxy authority alert requires canonical change evidence")
    if change.to_block <= change.from_block:
        raise EvmRpcError("proxy authority alert requires strictly increasing blocks")
    if change.field not in _ALERT_TYPES:
        raise EvmRpcError("unsupported proxy authority alert field")

    if change.classification == "ADDRESS_CHANGED":
        if change.before_address is None or change.after_address is None or change.before_address == change.after_address:
            raise EvmRpcError("ADDRESS_CHANGED requires distinct before and after addresses")
        _require_provider_quorum(change.before_providers, "before")
        _require_provider_quorum(change.after_providers, "after")
    elif change.classification == "EVIDENCE_APPEARED":
        if change.before_address is not None or change.after_address is None:
            raise EvmRpcError("EVIDENCE_APPEARED requires only after-address evidence")
        _require_provider_quorum(change.after_providers, "after")
    elif change.classification == "EVIDENCE_DISAPPEARED":
        if change.before_address is None or change.after_address is not None:
            raise EvmRpcError("EVIDENCE_DISAPPEARED requires only before-address evidence")
        _require_provider_quorum(change.before_providers, "before")
    else:
        raise EvmRpcError("unsupported proxy authority change classification")


def _alert_identifier(change: ProxyAuthorityChange, alert_type: str) -> str:
    material = "|".join((
        change.chain,
        change.contract_key,
        str(change.from_block),
        str(change.to_block),
        alert_type,
        change.field,
        change.classification,
        change.before_address or "",
        change.after_address or "",
    ))
    return "proxy-alert:" + sha256(material.encode("utf-8")).hexdigest()


def alert_from_proxy_authority_change(change: ProxyAuthorityChange) -> ProxyAuthorityAlert:
    """Convert validated temporal change evidence into one auditable alert record."""
    _validate_alert_change(change)
    alert_type = _ALERT_TYPES[change.field]
    two_sided = change.before_address is not None and change.after_address is not None
    return ProxyAuthorityAlert(
        _alert_identifier(change, alert_type),
        change.chain,
        change.contract_key,
        change.from_block,
        change.to_block,
        alert_type,
        change.field,
        "HIGH" if change.classification == "ADDRESS_CHANGED" else "MEDIUM",
        change.classification,
        change.before_address,
        change.after_address,
        tuple(sorted(set(change.before_providers))),
        tuple(sorted(set(change.after_providers))),
        "TWO_SIDED_QUORUM" if two_sided else "ONE_SIDED_QUORUM",
        "NOT_DETERMINED",
        _ALERT_STATUS,
    )


def build_proxy_authority_alerts(changes: Sequence[ProxyAuthorityChange]) -> tuple[ProxyAuthorityAlert, ...]:
    """Build deterministic, deduplicated alerts while retaining historical input order."""
    out: list[ProxyAuthorityAlert] = []
    seen: set[str] = set()
    for change in changes:
        alert = alert_from_proxy_authority_change(change)
        if alert.alert_id in seen:
            continue
        seen.add(alert.alert_id)
        out.append(alert)
    return tuple(out)
