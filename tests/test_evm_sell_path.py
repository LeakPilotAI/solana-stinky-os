from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_rpc import EvmRpcError
from stinky_core.evm_sell_path import observe_router_pair_sell_prerequisites, observe_transfer_path

TOKEN = "0x" + "11" * 20
HOLDER = "0x" + "22" * 20
RECIPIENT = "0x" + "33" * 20
ROUTER = "0x" + "44" * 20
PAIR = "0x" + "55" * 20


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


class SellObserver:
    def __init__(self, name, *, allowance=10_000, allowance_fail=False, transfer_fail=False):
        self.rpc_url = f"https://{name}.example"
        self.chain = Chain()
        self.allowance = allowance
        self.allowance_fail = allowance_fail
        self.transfer_fail = transfer_fail
        self.calls = []

    def attest_chain(self):
        return self.chain.chain_id

    def _call(self, method, params):
        self.calls.append((method, params))
        data = params[0]["data"]
        if data.startswith("0xdd62ed3e"):
            if self.allowance_fail:
                raise EvmRpcError("allowance call failed")
            return "0x" + f"{self.allowance:064x}"
        if data.startswith("0xa9059cbb"):
            if self.transfer_fail:
                raise EvmRpcError("transfer call failed")
            return "0x01"
        raise AssertionError(f"unexpected calldata: {data}")


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


def test_router_pair_prerequisites_require_allowance_and_pair_transfer_quorum_at_same_block():
    observers = [SellObserver("a", allowance=500), SellObserver("b", allowance=500)]
    result = observe_router_pair_sell_prerequisites(
        observers,
        chain="base",
        token=TOKEN,
        holder=HOLDER,
        router=ROUTER,
        pair=PAIR,
        amount=123,
        block_number=789,
    )
    assert result.allowance == 500
    assert result.allowance_verdict == "STANDARD_ALLOWANCE_SUFFICIENT"
    assert result.transfer_path.verdict == "TRANSFER_CALL_SUCCEEDED"
    assert result.transfer_path.recipient == PAIR
    assert result.verdict == "STANDARD_SELL_PREREQUISITES_OBSERVED"
    assert result.status == "UNVERIFIED_ROUTER_PAIR_SELL_PATH_EVIDENCE"
    assert "DOES_NOT_EXECUTE_ROUTER_SWAP" in result.limitations
    for observer in observers:
        assert len(observer.calls) == 2
        allowance_call, transfer_call = observer.calls
        assert allowance_call[1][0]["from"] == HOLDER
        assert allowance_call[1][0]["to"] == TOKEN
        assert allowance_call[1][0]["data"].startswith("0xdd62ed3e")
        assert HOLDER[2:] in allowance_call[1][0]["data"]
        assert ROUTER[2:] in allowance_call[1][0]["data"]
        assert allowance_call[1][1] == hex(789)
        assert transfer_call[1][0]["from"] == HOLDER
        assert transfer_call[1][0]["data"].startswith("0xa9059cbb")
        assert PAIR[2:] in transfer_call[1][0]["data"]
        assert transfer_call[1][1] == hex(789)


def test_insufficient_standard_allowance_is_specific_not_honeypot_verdict():
    result = observe_router_pair_sell_prerequisites(
        [SellObserver("a", allowance=10), SellObserver("b", allowance=10)],
        chain="base",
        token=TOKEN,
        holder=HOLDER,
        router=ROUTER,
        pair=PAIR,
        amount=123,
        block_number=20,
    )
    assert result.allowance_verdict == "STANDARD_ALLOWANCE_INSUFFICIENT"
    assert result.verdict == "STANDARD_ALLOWANCE_INSUFFICIENT_FOR_AMOUNT"
    assert result.transfer_path.verdict == "TRANSFER_CALL_SUCCEEDED"
    assert "DOES_NOT_PROVE_REAL_SALE_SUCCESS" in result.limitations


def test_allowance_provider_disagreement_fails_closed_to_unknown():
    result = observe_router_pair_sell_prerequisites(
        [SellObserver("a", allowance=500), SellObserver("b", allowance=600), SellObserver("c", allowance=500)],
        chain="base",
        token=TOKEN,
        holder=HOLDER,
        router=ROUTER,
        pair=PAIR,
        amount=123,
        block_number=20,
    )
    assert result.allowance is None
    assert result.allowance_verdict == "UNKNOWN_ALLOWANCE_EVIDENCE"
    assert result.verdict == "UNKNOWN_INSUFFICIENT_SELL_PATH_EVIDENCE"


def test_pair_transfer_failure_remains_unknown_even_with_sufficient_allowance():
    result = observe_router_pair_sell_prerequisites(
        [SellObserver("a", allowance=500), SellObserver("b", allowance=500, transfer_fail=True)],
        chain="base",
        token=TOKEN,
        holder=HOLDER,
        router=ROUTER,
        pair=PAIR,
        amount=123,
        block_number=20,
    )
    assert result.allowance_verdict == "STANDARD_ALLOWANCE_SUFFICIENT"
    assert result.transfer_path.verdict == "UNKNOWN_INSUFFICIENT_SUCCESS_EVIDENCE"
    assert result.verdict == "UNKNOWN_INSUFFICIENT_SELL_PATH_EVIDENCE"


def test_router_pair_invalid_identity_and_duplicate_provider_fail_closed():
    observers = [SellObserver("a"), SellObserver("b")]
    with pytest.raises(ValueError, match="valid addresses"):
        observe_router_pair_sell_prerequisites(observers, chain="base", token=TOKEN, holder=HOLDER, router="bad", pair=PAIR, amount=1, block_number=1)
    with pytest.raises(EvmRpcError, match="insufficient distinct RPC providers"):
        observe_router_pair_sell_prerequisites([SellObserver("a"), SellObserver("a")], chain="base", token=TOKEN, holder=HOLDER, router=ROUTER, pair=PAIR, amount=1, block_number=1)
