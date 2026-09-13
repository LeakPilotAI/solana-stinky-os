from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_rpc import EvmRpcError
from stinky_core.evm_sell_path import observe_transfer_path

TOKEN = "0x" + "11" * 20
HOLDER = "0x" + "22" * 20
RECIPIENT = "0x" + "33" * 20


class Chain:
    key = "base"
    chain_id = 8453


class FakeObserver:
    def __init__(self, name, *, succeed=True):
        self.rpc_url = f"https://{name}.example"
        self.chain = Chain()
        self.succeed = succeed
        self.calls = []

    def attest_chain(self):
        return self.chain.chain_id

    def _call(self, method, params):
        self.calls.append((method, params))
        if not self.succeed:
            raise EvmRpcError("RPC returned error for eth_call")
        return "0x01"


def test_transfer_path_requires_two_provider_successes_and_pins_holder_and_block():
    observers = [FakeObserver("a"), FakeObserver("b")]
    result = observe_transfer_path(
        observers,
        chain="base",
        token=TOKEN,
        holder=HOLDER,
        recipient=RECIPIENT,
        amount=123,
        block_number=456,
    )
    assert result.verdict == "TRANSFER_CALL_SUCCEEDED"
    assert len(result.successful_providers) == 2
    assert result.status == "UNVERIFIED_TRANSFER_PATH_SIMULATION_EVIDENCE"
    assert "DOES_NOT_PROVE_ROUTER_SELLABILITY" in result.limitations
    for observer in observers:
        method, params = observer.calls[0]
        assert method == "eth_call"
        assert params[0]["from"] == HOLDER
        assert params[0]["to"] == TOKEN
        assert params[1] == hex(456)


def test_provider_failure_remains_unknown_not_honeypot_verdict():
    result = observe_transfer_path(
        [FakeObserver("a"), FakeObserver("b", succeed=False)],
        chain="base",
        token=TOKEN,
        holder=HOLDER,
        recipient=RECIPIENT,
        amount=1,
        block_number=10,
    )
    assert result.verdict == "UNKNOWN_INSUFFICIENT_SUCCESS_EVIDENCE"
    assert {row.outcome for row in result.provider_evidence} == {"CALL_SUCCEEDED", "UNKNOWN_CALL_FAILURE"}
    assert "CALL_FAILURE_IS_NOT_A_HONEYPOT_VERDICT" in result.limitations


def test_duplicate_provider_cannot_satisfy_quorum():
    with pytest.raises(EvmRpcError, match="insufficient distinct RPC providers"):
        observe_transfer_path(
            [FakeObserver("a"), FakeObserver("a")],
            chain="base",
            token=TOKEN,
            holder=HOLDER,
            recipient=RECIPIENT,
            amount=1,
            block_number=10,
        )


def test_invalid_amount_and_identity_fail_closed():
    with pytest.raises(ValueError, match="amount must be positive"):
        observe_transfer_path([FakeObserver("a"), FakeObserver("b")], chain="base", token=TOKEN, holder=HOLDER, recipient=RECIPIENT, amount=0, block_number=10)
    with pytest.raises(ValueError, match="valid addresses"):
        observe_transfer_path([FakeObserver("a"), FakeObserver("b")], chain="base", token="bad", holder=HOLDER, recipient=RECIPIENT, amount=1, block_number=10)
