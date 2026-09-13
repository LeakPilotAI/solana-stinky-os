from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_proxy_authority import AddressEvidence, ProxyAuthorityEvidence
from stinky_core.evm_proxy_history import (
    ProxyAuthorityChange,
    alert_from_proxy_authority_change,
    build_proxy_authority_alerts,
    build_proxy_authority_change_history,
    derive_proxy_authority_changes,
)
from stinky_core.evm_rpc import EvmRpcError

CONTRACT = "base:0x" + "11" * 20
IMPL_A = "0x" + "22" * 20
IMPL_B = "0x" + "33" * 20
ADMIN_A = "0x" + "44" * 20
ADMIN_B = "0x" + "55" * 20
BEACON_A = "0x" + "66" * 20
BEACON_B = "0x" + "77" * 20
PROVIDERS = ("provider-a", "provider-b")


def evidence(address, status="QUORUM_EVIDENCE", providers=PROVIDERS):
    return AddressEvidence("source", address, "base:" + address, status, providers)


def snapshot(block, *, contract_key=CONTRACT, implementation=None, admin=None, owner=None, eip_impl=None, beacon=None, beacon_impl=None, eip_admin=None):
    return ProxyAuthorityEvidence(
        "base", contract_key, block, None, None, "NO_CANONICAL_EIP1167_PATTERN",
        implementation, admin, owner, eip_impl, beacon, beacon_impl, eip_admin,
        "UNVERIFIED_PROXY_AUTHORITY_EVIDENCE",
    )


def test_history_records_implementation_and_admin_address_changes():
    before = snapshot(100, eip_impl=evidence(IMPL_A), eip_admin=evidence(ADMIN_A))
    after = snapshot(200, eip_impl=evidence(IMPL_B), eip_admin=evidence(ADMIN_B))
    rows = derive_proxy_authority_changes(before, after)
    assert [(row.field, row.classification) for row in rows] == [
        ("eip1967_implementation", "ADDRESS_CHANGED"),
        ("eip1967_admin", "ADDRESS_CHANGED"),
    ]
    assert rows[0].before_providers == PROVIDERS
    assert rows[0].after_providers == PROVIDERS


def test_beacon_transition_preserves_both_beacon_and_resolved_implementation_history():
    rows = derive_proxy_authority_changes(
        snapshot(100, beacon=evidence(BEACON_A), beacon_impl=evidence(IMPL_A)),
        snapshot(150, beacon=evidence(BEACON_B), beacon_impl=evidence(IMPL_B)),
    )
    assert [(row.field, row.before_address, row.after_address) for row in rows] == [
        ("eip1967_beacon", BEACON_A, BEACON_B),
        ("beacon_implementation", IMPL_A, IMPL_B),
    ]


def test_evidence_appearance_and_disappearance_remain_descriptive_not_inferred():
    rows = derive_proxy_authority_changes(
        snapshot(100, eip_impl=None, eip_admin=evidence(ADMIN_A)),
        snapshot(101, eip_impl=evidence(IMPL_A), eip_admin=None),
    )
    assert [(row.field, row.classification) for row in rows] == [
        ("eip1967_implementation", "EVIDENCE_APPEARED"),
        ("eip1967_admin", "EVIDENCE_DISAPPEARED"),
    ]


def test_unchanged_addresses_do_not_create_fake_history_rows():
    before = snapshot(100, eip_impl=evidence(IMPL_A), eip_admin=evidence(ADMIN_A))
    after = snapshot(110, eip_impl=evidence(IMPL_A), eip_admin=evidence(ADMIN_A))
    assert derive_proxy_authority_changes(before, after) == ()


def test_selector_evidence_is_also_temporally_preserved():
    rows = derive_proxy_authority_changes(
        snapshot(100, implementation=evidence(IMPL_A), admin=evidence(ADMIN_A)),
        snapshot(120, implementation=evidence(IMPL_B), admin=evidence(ADMIN_B)),
    )
    assert [row.field for row in rows] == ["implementation_selector", "admin_selector"]


def test_history_builds_only_between_adjacent_observed_snapshots():
    rows = build_proxy_authority_change_history([
        snapshot(100, eip_impl=evidence(IMPL_A)),
        snapshot(150, eip_impl=evidence(IMPL_B)),
        snapshot(200, eip_impl=evidence(IMPL_A)),
    ])
    assert [(row.from_block, row.to_block) for row in rows] == [(100, 150), (150, 200)]


def test_history_rejects_cross_contract_and_non_monotonic_time():
    with pytest.raises(EvmRpcError, match="cross chains or contracts"):
        derive_proxy_authority_changes(snapshot(100), snapshot(101, contract_key="base:other"))
    with pytest.raises(EvmRpcError, match="strictly increasing"):
        derive_proxy_authority_changes(snapshot(101), snapshot(100))


def test_single_snapshot_cannot_invent_history():
    assert build_proxy_authority_change_history([snapshot(100, eip_impl=evidence(IMPL_A))]) == ()


def test_changed_implementation_becomes_high_review_alert_without_intent_claim():
    change = derive_proxy_authority_changes(
        snapshot(100, eip_impl=evidence(IMPL_A)),
        snapshot(200, eip_impl=evidence(IMPL_B)),
    )[0]
    alert = alert_from_proxy_authority_change(change)
    assert alert.alert_type == "PROXY_IMPLEMENTATION_CHANGED"
    assert alert.severity == "HIGH"
    assert alert.evidence_quality == "TWO_SIDED_QUORUM"
    assert alert.intent == "NOT_DETERMINED"
    assert alert.status == "UNVERIFIED_PROXY_AUTHORITY_ALERT_EVIDENCE"


def test_appearance_is_medium_review_alert_and_deduplicates():
    change = derive_proxy_authority_changes(
        snapshot(100), snapshot(200, eip_impl=evidence(IMPL_A))
    )[0]
    alert = alert_from_proxy_authority_change(change)
    assert alert.severity == "MEDIUM"
    assert alert.evidence_quality == "ONE_SIDED_QUORUM"
    assert build_proxy_authority_alerts([change, change]) == (alert,)


def test_beacon_owner_and_beacon_implementation_have_distinct_alert_types():
    changes = derive_proxy_authority_changes(
        snapshot(100, owner=evidence(ADMIN_A), beacon=evidence(BEACON_A), beacon_impl=evidence(IMPL_A)),
        snapshot(200, owner=evidence(ADMIN_B), beacon=evidence(BEACON_B), beacon_impl=evidence(IMPL_B)),
    )
    assert [row.alert_type for row in build_proxy_authority_alerts(changes)] == [
        "PROXY_OWNER_CHANGED", "PROXY_BEACON_CHANGED", "BEACON_IMPLEMENTATION_CHANGED"
    ]


def test_alert_rejects_non_quorum_change_evidence():
    row = ProxyAuthorityChange(
        "base", CONTRACT, 100, 200, "eip1967_implementation",
        IMPL_A, IMPL_B, "before", "after", ("one",), PROVIDERS,
        "ADDRESS_CHANGED", "UNVERIFIED_PROXY_AUTHORITY_CHANGE_EVIDENCE",
    )
    with pytest.raises(EvmRpcError, match="quorum"):
        alert_from_proxy_authority_change(row)


def test_alert_rejects_inconsistent_address_change():
    row = ProxyAuthorityChange(
        "base", CONTRACT, 100, 200, "eip1967_implementation",
        IMPL_A, IMPL_A, "before", "after", PROVIDERS, PROVIDERS,
        "ADDRESS_CHANGED", "UNVERIFIED_PROXY_AUTHORITY_CHANGE_EVIDENCE",
    )
    with pytest.raises(EvmRpcError, match="distinct before and after"):
        alert_from_proxy_authority_change(row)
