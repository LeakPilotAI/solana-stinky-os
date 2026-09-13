from pathlib import Path
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_proxy_authority import (
    ADMIN_SELECTOR,
    EIP1967_ADMIN_SLOT,
    EIP1967_BEACON_SLOT,
    EIP1967_IMPLEMENTATION_SLOT,
    IMPLEMENTATION_SELECTOR,
    OWNER_SELECTOR,
    inspect_proxy_authority,
)
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError

ADDRESS = "0x" + "11" * 20
TARGET = "0x" + "22" * 20
OWNER = "0x" + "33" * 20
ADMIN = "0x" + "44" * 20
IMPL = "0x" + "55" * 20
BEACON = "0x" + "66" * 20
OTHER = "0x" + "77" * 20


def word(address):
    return "0x" + "0" * 24 + address[2:]


def code(runtime="0x60006000"):
    return ContractCodeEvidence(
        "base", 8453, ADDRESS, "base:" + ADDRESS, 100,
        (len(runtime) - 2) // 2, "a" * 64, runtime,
        "UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        (ContractCodeSource("one.example", "a" * 64, 2), ContractCodeSource("two.example", "a" * 64, 2)),
    )


def rpc(name, replies=None, storage=None):
    replies = replies or {}
    storage = storage or {}

    def transport(_url, payload, timeout):
        req = json.loads(payload)
        if req["method"] == "eth_chainId":
            result = "0x2105"
        elif req["method"] == "eth_call":
            call = req["params"][0]
            result = replies.get((call["to"], call["data"]), replies.get(call["data"], "0x"))
        elif req["method"] == "eth_getStorageAt":
            result = storage.get(req["params"][1], "0x" + "0" * 64)
        else:
            raise AssertionError(req["method"])
        return {"jsonrpc": "2.0", "id": req["id"], "result": result}

    out = EvmReadOnlyRpc("base", transport=transport)
    out.rpc_url = f"https://{name}.example"
    return out


def pair(replies=None, storage=None):
    return [rpc("one", replies, storage), rpc("two", replies, storage)]


def test_common_selectors_require_matching_quorum():
    replies = {IMPLEMENTATION_SELECTOR: word(IMPL), ADMIN_SELECTOR: word(ADMIN), OWNER_SELECTOR: word(OWNER)}
    result = inspect_proxy_authority(pair(replies), code())
    assert result.implementation.address == IMPL
    assert result.admin.address == ADMIN
    assert result.owner.address == OWNER


def test_eip1967_storage_requires_matching_quorum():
    storage = {EIP1967_IMPLEMENTATION_SLOT: word(IMPL), EIP1967_ADMIN_SLOT: word(ADMIN)}
    result = inspect_proxy_authority(pair(storage=storage), code())
    assert result.eip1967_implementation.address == IMPL
    assert result.eip1967_admin.address == ADMIN
    assert result.eip1967_beacon is None
    assert result.beacon_implementation is None


def test_eip1967_implementation_disagreement_is_not_promoted():
    result = inspect_proxy_authority([
        rpc("one", storage={EIP1967_IMPLEMENTATION_SLOT: word(IMPL)}),
        rpc("two", storage={EIP1967_IMPLEMENTATION_SLOT: word(ADMIN)}),
    ], code())
    assert result.eip1967_implementation is None


def test_beacon_slot_and_implementation_require_matching_quorum():
    storage = {EIP1967_BEACON_SLOT: word(BEACON)}
    replies = {(BEACON, IMPLEMENTATION_SELECTOR): word(IMPL)}
    result = inspect_proxy_authority(pair(replies, storage), code())
    assert result.eip1967_implementation is None
    assert result.eip1967_beacon.address == BEACON
    assert result.eip1967_beacon.status == "EIP1967_BEACON_SLOT_QUORUM_EVIDENCE"
    assert result.beacon_implementation.address == IMPL
    assert result.beacon_implementation.address_key == "base:" + IMPL
    assert result.beacon_implementation.status == "BEACON_IMPLEMENTATION_SELECTOR_QUORUM_EVIDENCE"


def test_direct_implementation_slot_takes_precedence_over_beacon():
    storage = {EIP1967_IMPLEMENTATION_SLOT: word(IMPL), EIP1967_BEACON_SLOT: word(BEACON)}
    replies = {(BEACON, IMPLEMENTATION_SELECTOR): word(OTHER)}
    result = inspect_proxy_authority(pair(replies, storage), code())
    assert result.eip1967_implementation.address == IMPL
    assert result.eip1967_beacon is None
    assert result.beacon_implementation is None


def test_beacon_slot_disagreement_fails_closed():
    result = inspect_proxy_authority([
        rpc("one", storage={EIP1967_BEACON_SLOT: word(BEACON)}),
        rpc("two", storage={EIP1967_BEACON_SLOT: word(OTHER)}),
    ], code())
    assert result.eip1967_beacon is None
    assert result.beacon_implementation is None


def test_beacon_implementation_disagreement_fails_closed():
    storage = {EIP1967_BEACON_SLOT: word(BEACON)}
    result = inspect_proxy_authority([
        rpc("one", {(BEACON, IMPLEMENTATION_SELECTOR): word(IMPL)}, storage),
        rpc("two", {(BEACON, IMPLEMENTATION_SELECTOR): word(OTHER)}, storage),
    ], code())
    assert result.eip1967_beacon.address == BEACON
    assert result.beacon_implementation is None


def test_malformed_beacon_implementation_is_not_promoted():
    storage = {EIP1967_BEACON_SLOT: word(BEACON)}
    result = inspect_proxy_authority(pair({(BEACON, IMPLEMENTATION_SELECTOR): "0x1234"}, storage), code())
    assert result.eip1967_beacon.address == BEACON
    assert result.beacon_implementation is None


def test_beacon_storage_and_call_are_historically_pinned():
    seen = []

    def transport(_url, payload, timeout):
        req = json.loads(payload)
        if req["method"] == "eth_chainId":
            result = "0x2105"
        elif req["method"] == "eth_getStorageAt":
            seen.append(("storage", req["params"][2]))
            result = word(BEACON) if req["params"][1] == EIP1967_BEACON_SLOT else "0x" + "0" * 64
        elif req["method"] == "eth_call":
            seen.append((req["params"][0]["to"], req["params"][1]))
            result = word(IMPL) if req["params"][0]["to"] == BEACON else "0x"
        else:
            raise AssertionError(req["method"])
        return {"jsonrpc": "2.0", "id": req["id"], "result": result}

    a = EvmReadOnlyRpc("base", transport=transport)
    b = EvmReadOnlyRpc("base", transport=transport)
    a.rpc_url, b.rpc_url = "https://one.example", "https://two.example"
    result = inspect_proxy_authority([a, b], code())
    assert result.eip1967_beacon.address == BEACON
    assert result.beacon_implementation.address == IMPL
    assert {block for _, block in seen} == {hex(code().block_number)}
    assert any(kind == BEACON for kind, _ in seen)


def test_canonical_eip1167_target_is_detected_only_as_pattern():
    runtime = "0x363d3d373d3d3d363d73" + TARGET[2:] + "5af43d82803e903d91602b57fd5bf3"
    result = inspect_proxy_authority(pair(), code(runtime))
    assert result.minimal_proxy_target == TARGET
    assert result.minimal_proxy_target_key == "base:" + TARGET
    assert result.minimal_proxy_status == "CANONICAL_EIP1167_RUNTIME_PATTERN"


def test_selector_disagreement_is_not_promoted():
    result = inspect_proxy_authority([
        rpc("one", {OWNER_SELECTOR: word(OWNER)}),
        rpc("two", {OWNER_SELECTOR: word(ADMIN)}),
    ], code())
    assert result.owner is None


def test_duplicate_provider_cannot_satisfy_quorum():
    with pytest.raises(EvmRpcError, match="insufficient distinct"):
        inspect_proxy_authority([rpc("same"), rpc("same")], code())


def test_contract_code_provenance_is_required():
    weak = ContractCodeEvidence(
        "base", 8453, ADDRESS, "base:" + ADDRESS, 100, 2, "a" * 64, "0x6000",
        "UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        (ContractCodeSource("one.example", "a" * 64, 2),),
    )
    with pytest.raises(EvmRpcError, match="independent quorum"):
        inspect_proxy_authority(pair(), weak)
