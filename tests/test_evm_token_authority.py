from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_privileged_inventory import PrivilegedAuthorityInventory, SelectorCandidate
from stinky_core.evm_rpc import EvmRpcError
from stinky_core.evm_token_authority import assess_token_authority

FINGERPRINT = "a" * 64
PROVIDERS = ("provider-a", "provider-b")


def inv(selectors=(), providers=PROVIDERS, status="UNVERIFIED_PRIVILEGED_AUTHORITY_INVENTORY_EVIDENCE"):
    rows = tuple(SelectorCandidate(value, (index * 6,), "BYTECODE_PUSH4_SELECTOR_CANDIDATE") for index, value in enumerate(selectors))
    return PrivilegedAuthorityInventory("base", "base:0x" + "11" * 20, 100, FINGERPRINT, providers, rows, (), status)


def test_supported_token_authority_candidates_are_evidence_only():
    result = assess_token_authority(inv(("0x40c10f19", "0x8456cb59", "0xf2fde38b", "0x2f2ff15d")))
    assert {row.capability for row in result.capabilities} == {"SUPPLY_EXPANSION", "PAUSE_CONTROL", "OWNERSHIP_CONTROL", "ROLE_CONTROL"}
    assert all(row.status == "UNVERIFIED_TOKEN_AUTHORITY_SELECTOR_EVIDENCE" for row in result.capabilities)
    assert result.status == "UNVERIFIED_TOKEN_AUTHORITY_ASSESSMENT_EVIDENCE"


def test_nonstandard_control_families_remain_unknown():
    result = assess_token_authority(inv())
    assert result.capabilities == ()
    assert result.unresolved_families
    assert all(row.state == "UNKNOWN_NOT_ASSESSED" for row in result.unresolved_families)


def test_unknown_selector_is_not_promoted():
    assert assess_token_authority(inv(("0xdeadbeef",))).capabilities == ()


def test_requires_independent_provider_quorum():
    with pytest.raises(EvmRpcError, match="independent provider quorum"):
        assess_token_authority(inv(("0x40c10f19",), providers=("provider-a",)))


def test_rejects_noncanonical_inventory_status():
    with pytest.raises(EvmRpcError, match="canonical privileged inventory evidence"):
        assess_token_authority(inv(("0x40c10f19",), status="UNKNOWN"))
