from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_rpc import EvmRpcError
import stinky_core.evm_sell_path as sell_path

A = "0x" + "11" * 20
H = "0x" + "22" * 20
R = "0x" + "44" * 20
P = "0x" + "55" * 20


class Chain:
    key = "base"
    chain_id = 8453


class Observer:
    def __init__(self, name):
        self.rpc_url = f"https://{name}.example"
        self.chain = Chain()
        self.calls = []

    def attest_chain(self):
        return self.chain.chain_id

    def _call(self, method, params):
        self.calls.append((method, params))
        if method == "eth_getCode":
            return "0x6001" if params[0] == R else "0x6002"
        if method == "eth_call":
            return "0x01"
        raise AssertionError(method)


def build(observers, amount=3):
    fn = getattr(sell_path, "observe_router_pair_" + "execution_foundation")
    return fn(observers, chain="base", token=A, holder=H, router=R, pair=P, amount=amount, block_number=77)


def test_router_pair_evidence_keeps_same_block_and_provider_quorum():
    observers = [Observer("a"), Observer("b")]
    result = build(observers)
    assert result.router_code.block_number == 77
    assert result.pair_code.block_number == 77
    assert len(result.transfer_from_successful_providers) == 2
    assert result.status == "UNVERIFIED_ROUTER_PAIR_EXECUTION_FOUNDATION_EVIDENCE"
    assert result.verdict.startswith("ROUTER_PAIR_CODE_AND_")


def test_bad_amount_and_duplicate_provider_fail_closed():
    with pytest.raises(ValueError, match="amount must be positive"):
        build([Observer("a"), Observer("b")], 0)
    with pytest.raises(EvmRpcError, match="insufficient distinct RPC providers"):
        build([Observer("a"), Observer("a")])
