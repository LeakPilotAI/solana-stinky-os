from pathlib import Path
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_contract_code import ContractCodeEvidence, ContractCodeSource
from stinky_core.evm_proxy_authority import (
    EIP1967_ADMIN_SLOT,
    EIP1967_IMPLEMENTATION_SLOT,
    _eip1167,
    inspect_proxy_authority,
)
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError

ADDRESS = "0x" + "11" * 20
TARGET = "0x" + "22" * 20
OWNER = "0x" + "33" * 20
ADMIN = "0x" + "44" * 20
IMPL = "0x" + "55" * 20


def word(address):
    return "0x" + "0" * 24 + address[2:]


def code(runtime="0x60006000"):
    return ContractCodeEvidence(
        "base", 8453, ADDRESS, "base:" + ADDRESS, 100,
        (len(runtime) - 2) // 2, "a" * 64, runtime,
        "UNVERIFIED_CONTRACT_CODE_EVIDENCE",
        (ContractCodeSource("one.example", "a" * 64, 2), ContractCodeSource("two.example", "a" * 64, 2)),
    )


def rpc(url, replies=None, storage=None):
    replies = replies or {}
    storage = storage or {}

    def transport(_url, payload, timeout):
        req = json.loads(payload)
        if req["method"] == "eth_chainId":
            result = "0x2105"
        elif req["method"] == "eth_call":
            result = replies.get(req["params"][0]["data"], "0x")
        elif req["method"] == "eth_getStorageAt":
            result = storage.get(req["params"][1], "0x" + "0" * 64)
        else:
            raise AssertionError(f"unexpected RPC method: {req['method']}")
        return {"jsonrpc": "2.0", "id": req["id"], "result": result}

    out = EvmReadOnlyRpc("base", transport=transport)
    out.rpc_url = url
    return out


def test_common_selectors_require_matching_quorum():
    replies = {"0x5c60da1b": word(IMPL), "0xf851a440": word(ADMIN), "0x8da5cb5b": word(OWNER)}
    result = inspect_proxy_authority([rpc("https://one.example", replies), rpc("https://two.example", replies)], code())
    assert result.implementation.address == IMPL
    assert result.admin.address == ADMIN
    assert result.owner.address == OWNER
    assert result.status == "UNVERIFIED_PROXY_AUTHORITY_EVIDENCE"


def test_eip1967_storage_requires_matching_quorum():
    storage = {
        EIP1967_IMPLEMENTATION_SLOT: word(IMPL),
        EIP1967_ADMIN_SLOT: word(ADMIN),
    }
    result = inspect_proxy_authority(
        [rpc("https://one.example", storage=storage), rpc("https://two.example", storage=storage)],
        code(),
    )
    assert result.eip1967_implementation.address == IMPL
    assert result.eip1967_implementation.status == "EIP1967_IMPLEMENTATION_SLOT_QUORUM_EVIDENCE"
    assert result.eip1967_admin.address == ADMIN
    assert result.eip1967_admin.status == "EIP1967_ADMIN_SLOT_QUORUM_EVIDENCE"


def test_eip1967_storage_disagreement_is_not_promoted():
    one = rpc("https://one.example", storage={EIP1967_IMPLEMENTATION_SLOT: word(IMPL)})
    two = rpc("https://two.example", storage={EIP1967_IMPLEMENTATION_SLOT: word(ADMIN)})
    result = inspect_proxy_authority([one, two], code())
    assert result.eip1967_implementation is None


def test_storage_read_is_pinned_to_contract_evidence_block():
    seen = []

    def transport(_url, payload, timeout):
        req = json.loads(payload)
        if req["method"] == "eth_chainId":
            result = "0x2105"
        elif req["method"] == "eth_call":
            result = "0x"
        elif req["method"] == "eth_getStorageAt":
            seen.append(req["params"][2])
            result = word(IMPL) if req["params"][1] == EIP1967_IMPLEMENTATION_SLOT else "0x" + "0" * 64
        else:
            raise AssertionError(f"unexpected RPC method: {req['method']}")
        return {"jsonrpc": "2.0", "id": req["id"], "result": result}

    a = EvmReadOnlyRpc("base", transport=transport)
    b = EvmReadOnlyRpc("base", transport=transport)
    a.rpc_url = "https://one.example"
    b.rpc_url = "https://two.example"
    result = inspect_proxy_authority([a, b], code())
    assert result.eip1967_implementation.address == IMPL
    assert seen and set(seen) == {hex(code().block_number)}


def test_canonical_eip1167_target_is_detected_only_as_pattern():
    runtime = "0x363d3d373d3d363d73" + TARGET[2:] + "5af43d82803e903d91602b57fd5bf3"
    evidence = code(runtime)
    assert evidence.runtime_bytecode == runtime
    assert _eip1167(evidence) == TARGET
    result = inspect_proxy_authority([rpc("https://one.example"), rpc("https://two.example")], evidence)
    assert result.minimal_proxy_target == TARGET
    assert result.minimal_proxy_status == "CANONICAL_EIP1167_RUNTIME_PATTERN"


def test_selector_disagreement_is_not_promoted():
    a = rpc("https://one.example", {"0x8da5cb5b": word(OWNER)})
    b = rpc("https://two.example", {"0x8da5cb5b": word(ADMIN)})
    result = inspect_proxy_authority([a, b], code())
    assert result.owner is None


def test_duplicate_provider_cannot_satisfy_quorum():
    replies = {"0x8da5cb5b": word(OWNER)}
    with pytest.raises(EvmRpcError, match="insufficient distinct"):
        inspect_proxy_authority([rpc("https://same.example", replies), rpc("https://same.example", replies)], code())


def test_contract_code_provenance_is_required():
    weak = ContractCodeEvidence("base", 8453, ADDRESS, "base:" + ADDRESS, 100, 2, "a" * 64, "0x6000", "UNVERIFIED_CONTRACT_CODE_EVIDENCE", (ContractCodeSource("one.example", "a" * 64, 2),))
    with pytest.raises(EvmRpcError, match="independent quorum"):
        inspect_proxy_authority([rpc("https://one.example"), rpc("https://two.example")], weak)
