from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError, resolve_rpc_url


def scripted(*results):
    queue = list(results)

    def transport(url, payload, timeout):
        request = json.loads(payload)
        result = queue.pop(0)
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}

    return transport


def test_robinhood_head_requires_chain_id_4663():
    rpc = EvmReadOnlyRpc("robinhood", transport=scripted("0x1237", "0x2a"))
    head = rpc.observe_head()
    assert head.chain == "robinhood"
    assert head.chain_id == 4663
    assert head.block_number == 42


def test_base_head_requires_chain_id_8453():
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105", "0x64"))
    head = rpc.observe_head()
    assert head.chain_id == 8453
    assert head.block_number == 100


def test_wrong_rpc_chain_fails_closed_before_block_evidence():
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x1"))
    with pytest.raises(EvmRpcError, match="chain ID mismatch"):
        rpc.block_number()


def test_rpc_error_and_malformed_result_fail_closed():
    def errored(url, payload, timeout):
        request = json.loads(payload)
        return {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -1}}

    with pytest.raises(EvmRpcError, match="RPC returned error"):
        EvmReadOnlyRpc("base", transport=errored).attest_chain()

    with pytest.raises(EvmRpcError, match="invalid chain id"):
        EvmReadOnlyRpc("base", transport=scripted("8453")).attest_chain()


def test_unknown_and_solana_are_not_accepted_as_evm():
    with pytest.raises(EvmRpcError):
        EvmReadOnlyRpc("unknown")
    with pytest.raises(EvmRpcError):
        EvmReadOnlyRpc("solana")


def test_rpc_override_must_be_https(monkeypatch):
    monkeypatch.setenv("BASE_RPC_URL", "http://localhost:8545")
    with pytest.raises(EvmRpcError, match="trusted HTTPS"):
        resolve_rpc_url("base")


def test_client_has_no_transaction_submission_surface():
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105"))
    assert not hasattr(rpc, "send_transaction")
    assert not hasattr(rpc, "send_raw_transaction")
    with pytest.raises(EvmRpcError, match="not allowed"):
        rpc._call("eth_sendRawTransaction", ["0xdeadbeef"])


@pytest.mark.parametrize("value", [
    "0x02105", "0x21_05", "0x2105 ", "0x2105\n", " 0x2105", "0x+2105",
    "0x-2105", "0x", "0X2105", "0xg", 8453, True, None,
])
def test_malformed_quantity_chain_identity_rejected_before_head_read(value):
    calls = []
    def transport(url, body, timeout):
        request = json.loads(body)
        calls.append(request["method"])
        return {"jsonrpc": "2.0", "id": request["id"], "result": value}
    with pytest.raises(EvmRpcError, match="invalid chain id response"):
        EvmReadOnlyRpc("base", transport=transport).observe_head()
    assert calls == ["eth_chainId"]


@pytest.mark.parametrize("value", ["0x00", "0x01", "0x1_0", "0x10 ", "0x10\n", "0x-1", "0x", False])
@pytest.mark.parametrize("method", ["block_number", "observe_head", "get_block_by_number"])
def test_malformed_block_quantities_fail_closed(value, method):
    result = {"number": value, "hash": "0x" + "11" * 32} if method == "get_block_by_number" else value
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105", result))
    with pytest.raises(EvmRpcError, match="invalid block number response"):
        getattr(rpc, method)(16) if method == "get_block_by_number" else getattr(rpc, method)()


@pytest.mark.parametrize("quantity,expected", [("0x0", 0), ("0x1", 1), ("0xaF", 175), ("0xABCDEF", 11259375)])
def test_valid_canonical_quantities_preserve_exact_values(quantity, expected):
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105", quantity))
    assert rpc.block_number() == expected


BAD_WORDS = ["0x" + "z" * 64, "0x1_" + "0" * 62, "0x" + "0" * 63 + " ",
             "0x" + "0" * 63 + "\n", "0x" + "00" * 31, "0x" + "00" * 33, None]


@pytest.mark.parametrize("value", BAD_WORDS)
@pytest.mark.parametrize("method", ["get_block_by_number", "storage_at_block"])
def test_malformed_hash_and_storage_response_rejected(value, method):
    result = {"number": "0x10", "hash": value} if method == "get_block_by_number" else value
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105", result))
    with pytest.raises(EvmRpcError):
        if method == "get_block_by_number":
            rpc.get_block_by_number(16)
        else:
            rpc.storage_at_block("0x" + "11" * 20, "0x" + "00" * 32, 16)


@pytest.mark.parametrize("value", BAD_WORDS)
@pytest.mark.parametrize("method", ["get_logs_for_block", "storage_at_block"])
def test_invalid_hash_or_slot_input_rejected_before_rpc(value, method):
    def forbidden(*args):
        pytest.fail("invalid caller data reached RPC")
    rpc = EvmReadOnlyRpc("base", transport=forbidden)
    with pytest.raises(ValueError):
        if method == "get_logs_for_block":
            rpc.get_logs_for_block(value)
        else:
            rpc.storage_at_block("0x" + "11" * 20, value, 16)


@pytest.mark.parametrize("value", ["0x12_3", "0x12 3", "0x123 ", "0x123\n", "0xzz", "0x1", None])
def test_invalid_call_data_response_rejected(value):
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105", value))
    with pytest.raises(EvmRpcError, match="invalid eth_call response"):
        rpc.call_at_block("0x" + "11" * 20, "0x12345678", 16)


@pytest.mark.parametrize("value", ["0x1234_678", "0x1234567 ", "0x1234567\n", "0x1234567z", "0x1234", None])
def test_invalid_calldata_rejected_before_rpc(value):
    def forbidden(*args):
        pytest.fail("invalid calldata reached RPC")
    rpc = EvmReadOnlyRpc("base", transport=forbidden)
    with pytest.raises(ValueError, match="hex calldata"):
        rpc.call_at_block("0x" + "11" * 20, value, 16)


@pytest.mark.parametrize("value", ["0x", "0x00", "0xAbCd"])
def test_valid_call_data_preserves_historical_request_and_lowercase_response(value):
    requests = []
    def transport(url, body, timeout):
        req = json.loads(body)
        requests.append(req)
        return {"jsonrpc": "2.0", "id": req["id"], "result": "0x2105" if req["method"] == "eth_chainId" else value}
    rpc = EvmReadOnlyRpc("base", transport=transport)
    assert rpc.call_at_block("0x" + "11" * 20, "0xABCD1234", 16) == value.lower()
    assert requests[-1]["params"] == [{"to": "0x" + "11" * 20, "data": "0xabcd1234"}, "0x10"]


def test_valid_mixed_case_hash_and_storage_data_preserve_contracts():
    word = "0x" + "aB" * 32
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105", {"number": "0x10", "hash": word}))
    assert rpc.get_block_by_number(16)["hash"] == word
    log = {"blockHash": word, "blockNumber": "0x10", "address": "0x" + "aB" * 20,
           "transactionHash": word, "transactionIndex": "0x0", "logIndex": "0x0",
           "removed": False, "topics": [word], "data": "0xaB"}
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105", [log]))
    assert rpc.get_logs_for_block(word) == [log]
    rpc = EvmReadOnlyRpc("base", transport=scripted("0x2105", word))
    assert rpc.storage_at_block("0x" + "11" * 20, word, 16) == word.lower()


@pytest.mark.parametrize("response", [
    None, [], "invalid", True,
    {"jsonrpc": "2.0", "id": True, "result": "0x2105"},
    {"jsonrpc": "2.0", "id": "1", "result": "0x2105"},
    {"jsonrpc": "2.0", "id": None, "result": "0x2105"},
    {"jsonrpc": "2.0", "result": "0x2105"},
    {"jsonrpc": "1.0", "id": 1, "result": "0x2105"},
    {"jsonrpc": 2.0, "id": 1, "result": "0x2105"},
    {"jsonrpc": "2.0", "id": 2, "result": "0x2105"},
    {"jsonrpc": "2.0", "id": 1.5, "result": "0x2105"},
    {"jsonrpc": "2.0", "id": 1},
    {"jsonrpc": "2.0", "id": 1, "error": None, "result": "0x2105"},
    {"jsonrpc": "2.0", "id": 1, "error": {}, "result": "0x2105"},
])
def test_malformed_response_envelopes_fail_before_head_evidence(response):
    requests = []
    def transport(url, body, timeout):
        requests.append(json.loads(body))
        return response
    with pytest.raises(EvmRpcError):
        EvmReadOnlyRpc("base", transport=transport).observe_head()
    assert len(requests) == 1 and requests[0]["method"] == "eth_chainId"


@pytest.mark.parametrize("error", [None, {}, {"code": -32000, "message": "SYNTHETIC_SECRET", "data": "https://rpc.example/SECRET"}])
def test_remote_error_presence_fails_closed_without_echoing_remote_data(error):
    rpc = EvmReadOnlyRpc("base", transport=lambda *args: {"jsonrpc": "2.0", "id": 1, "error": error})
    with pytest.raises(EvmRpcError, match="RPC returned error for eth_chainId") as failure:
        rpc.attest_chain()
    assert "SECRET" not in str(failure.value)


@pytest.mark.parametrize("floating_ids", [False, True])
def test_response_ids_track_request_sequence_with_equivalent_json_numbers(floating_ids):
    requests = []
    def transport(url, body, timeout):
        request = json.loads(body)
        requests.append(request)
        return {"jsonrpc": "2.0", "id": float(request["id"]) if floating_ids else request["id"],
                "result": "0x2105" if request["method"] == "eth_chainId" else "0x10"}
    rpc = EvmReadOnlyRpc("base", transport=transport)
    assert rpc.observe_head().block_number == 16
    assert [request["id"] for request in requests] == [1, 2]


def test_replayed_response_id_rejected_on_later_read():
    rpc = EvmReadOnlyRpc("base", transport=lambda *args: {"jsonrpc": "2.0", "id": 1, "result": "0x2105"})
    with pytest.raises(EvmRpcError, match="envelope mismatch"):
        rpc.observe_head()
