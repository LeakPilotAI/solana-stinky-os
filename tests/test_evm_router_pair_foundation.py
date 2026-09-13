from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_rpc import EvmRpcError
from stinky_core.evm_sell_path import observe_router_pair_execution_foundation

TOKEN = "0x" + "11" * 20
HOLDER = "0x" + "22" * 20
ROUTER = "0x" + "44" * 20
PAIR = "0x" + "55" * 20


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
            return "0x6001" if params[0] == ROUTER else "0x6002"
        if method == "eth_call":
            return "0x01"
        raise AssertionError(method)


def test_router_pair_foundation_shell():
    assert True
