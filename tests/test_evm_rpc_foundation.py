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
