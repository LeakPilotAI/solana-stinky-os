from hashlib import sha256
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_privileged_inventory import inventory_privileged_authority_surfaces
from stinky_core.evm_rpc import EvmRpcError
from stinky_core.evm_token_authority import assess_token_authority

ADDRESS = "0x" + "11" * 20
CONTRACT_KEY = "base:" + ADDRESS
PROVIDERS = ("provider-a", "provider-b")


def code(raw: bytes, *, providers=PROVIDERS, corrupt_source=False, corrupt_runtime=False):
    digest = sha256(raw).hexdigest()
    sources = []
    for index, provider in enumerate(providers):
        source_digest = ("0" * 64) if corrupt_source and index == 0 else digest
        sources.append(ContractCodeSource(provider, source_digest, len(raw)))
    runtime = "0x" + raw.hex()
    if corrupt_runtime:
        runtime = "0x6001"
    return ContractCodeEvidence(
        "base", 8453, ADDRESS, CONTRACT_KEY, 100, len(raw), digest, runtime,
        "UNVERIFIED_CONTRACT_CODE_EVIDENCE", tuple(sources),
    )


def test_known_authority_selectors_are_inventory_evidence_not_safety_claims():
    raw = bytes.fromhex("63f2fde38b14633659cfe614638456cb5914")
    result = inventory_privileged_authority_surfaces(code(raw))
    assert [(row.signature, row.category, row.authority_effect) for row in result.privileged_surfaces] == [
        ("upgradeTo(address)", "PROXY_UPGRADE", "AUTHORITY_MUTATION"),
        ("pause()", "PAUSE_CONTROL", "AUTHORITY_MUTATION"),
        ("transferOwnership(address)", "OWNERSHIP", "AUTHORITY_MUTATION"),
    ]
    assert all(row.status == "KNOWN_AUTHORITY_SELECTOR_BYTECODE_CANDIDATE" for row in result.privileged_surfaces)
    assert result.status == "UNVERIFIED_PRIVILEGED_AUTHORITY_INVENTORY_EVIDENCE"
    assert result.providers == PROVIDERS


def test_unknown_push4_is_retained_without_being_promoted_to_privileged_surface():
    result = inventory_privileged_authority_surfaces(code(bytes.fromhex("63deadbeef14")))
    assert [row.selector for row in result.selector_candidates] == ["0xdeadbeef"]
    assert result.privileged_surfaces == ()


def test_opcode_aware_scan_does_not_treat_selector_bytes_inside_push_data_as_opcode():
    raw = bytes.fromhex("6463f2fde38b00")
    result = inventory_privileged_authority_surfaces(code(raw))
    assert result.selector_candidates == ()
    assert result.privileged_surfaces == ()


def test_duplicate_selector_occurrences_are_collapsed_with_offsets():
    raw = bytes.fromhex("63f2fde38b1463f2fde38b14")
    result = inventory_privileged_authority_surfaces(code(raw))
    assert len(result.selector_candidates) == 1
    assert result.selector_candidates[0].offsets == (0, 6)
    assert result.privileged_surfaces[0].offsets == (0, 6)


def test_inventory_requires_independent_contract_code_provenance():
    with pytest.raises(EvmRpcError, match="independent quorum"):
        inventory_privileged_authority_surfaces(code(bytes.fromhex("63f2fde38b14"), providers=("provider-a",)))


def test_inventory_rejects_source_provenance_mismatch():
    with pytest.raises(EvmRpcError, match="source provenance disagrees"):
        inventory_privileged_authority_surfaces(code(bytes.fromhex("63f2fde38b14"), corrupt_source=True))


def test_inventory_rejects_runtime_fingerprint_mismatch():
    with pytest.raises(EvmRpcError, match="runtime bytecode does not match"):
        inventory_privileged_authority_surfaces(code(bytes.fromhex("63f2fde38b14"), corrupt_runtime=True))


def test_token_authority_classifies_supported_capabilities_only():
    raw = bytes.fromhex("6340c10f1914638456cb591463f2fde38b14632f2ff15d14")
    inventory = inventory_privileged_authority_surfaces(code(raw))
    result = assess_token_authority(inventory)
    assert {row.capability for row in result.capabilities} == {
        "SUPPLY_EXPANSION", "PAUSE_CONTROL", "OWNERSHIP_CONTROL", "ROLE_CONTROL"
    }
    assert all(row.status == "UNVERIFIED_TOKEN_AUTHORITY_SELECTOR_EVIDENCE" for row in result.capabilities)


def test_token_authority_keeps_nonstandard_control_families_unknown():
    inventory = inventory_privileged_authority_surfaces(code(bytes.fromhex("63deadbeef14")))
    result = assess_token_authority(inventory)
    assert result.capabilities == ()
    assert result.unresolved_families
    assert all(row.state == "UNKNOWN_NOT_ASSESSED" for row in result.unresolved_families)


def test_token_authority_rejects_inventory_without_provider_quorum():
    inventory = inventory_privileged_authority_surfaces(code(bytes.fromhex("6340c10f1914")))
    weak = type(inventory)(
        inventory.chain, inventory.contract_key, inventory.block_number,
        inventory.code_fingerprint_sha256, ("provider-a",), inventory.selector_candidates,
        inventory.privileged_surfaces, inventory.status,
    )
    with pytest.raises(EvmRpcError, match="independent provider quorum"):
        assess_token_authority(weak)
