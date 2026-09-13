from pathlib import Path
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_consensus import EvmConsensusObservation
from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_ingestion import EvmIngestedBlock, EvmLogSource
from stinky_core.evm_liquidity import PoolStateSource, V2ReserveEvidence, V3LiquidityEvidence, observe_v2_reserves, observe_v3_liquidity
from stinky_core.evm_liquidity_history import build_v2_reserve_change_history, build_v3_liquidity_change_history
from stinky_core.evm_pool_events import collect_pool_event_evidence
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError

POOL = "0x" + "44" * 20
BLOCK_HASH = "0x" + "ab" * 32
TX_HASH = "0x" + "cd" * 32


def pool(family="V2_STYLE_PAIR_CREATED"):
    return DexPoolCandidate(
        "base", 8453, "0x" + "11" * 20, "base:" + "0x" + "11" * 20,
        POOL, "base:" + POOL, "0x" + "22" * 20, "base:" + "0x" + "22" * 20,
        "0x" + "33" * 20, "base:" + "0x" + "33" * 20, family,
        3000 if family.startswith("V3") else None, 100, BLOCK_HASH, TX_HASH, "0x1",
        "UNVERIFIED_DEX_POOL_CANDIDATE", ("rpc-a", "rpc-b"),
    )


def observer(url, result):
    def transport(_url, payload, timeout):
        req = json.loads(payload)
        value = "0x2105" if req["method"] == "eth_chainId" else result
        return {"jsonrpc": "2.0", "id": req["id"], "result": value}
    rpc = EvmReadOnlyRpc("base", transport=transport)
    rpc.rpc_url = url
    return rpc


def words(*values):
    return "0x" + "".join(f"{value:064x}" for value in values)


def test_v2_reserves_require_two_distinct_matching_providers():
    evidence = observe_v2_reserves(
        [observer("https://one.example", words(10, 20, 30)), observer("https://two.example", words(10, 20, 30))],
        pool(), block_number=100,
    )
    assert (evidence.reserve0, evidence.reserve1, evidence.block_timestamp_last) == (10, 20, 30)
    assert evidence.status == "UNVERIFIED_V2_RESERVE_EVIDENCE"
    assert len(evidence.sources) == 2


def test_v3_liquidity_is_consensus_backed_but_unverified():
    evidence = observe_v3_liquidity(
        [observer("https://one.example", words(999)), observer("https://two.example", words(999))],
        pool("V3_STYLE_POOL_CREATED"), block_number=100,
    )
    assert evidence.liquidity == 999
    assert evidence.status == "UNVERIFIED_V3_LIQUIDITY_EVIDENCE"


def test_provider_disagreement_fails_closed():
    with pytest.raises(EvmRpcError, match="quorum"):
        observe_v2_reserves(
            [observer("https://one.example", words(10, 20, 30)), observer("https://two.example", words(11, 20, 30))],
            pool(), block_number=100,
        )


def test_duplicate_endpoint_cannot_satisfy_state_quorum():
    with pytest.raises(EvmRpcError, match="insufficient distinct"):
        observe_v2_reserves(
            [observer("https://same.example", words(10, 20, 30)), observer("https://same.example", words(10, 20, 30))],
            pool(), block_number=100,
        )


def test_pool_logs_are_retained_only_as_unclassified_quorum_evidence():
    head = EvmConsensusObservation("base", 8453, 102, 101, 102, 2, "now", ())
    block = EvmIngestedBlock(
        "base", 8453, 100, BLOCK_HASH, "now", head, (),
        ({"address": POOL, "blockHash": BLOCK_HASH, "transactionHash": TX_HASH, "logIndex": "0x1", "topics": ["0x" + "12" * 32], "data": "0x"},),
        (EvmLogSource("rpc-a", "d", 1), EvmLogSource("rpc-b", "d", 1)),
    )
    rows = collect_pool_event_evidence(block, [pool()])
    assert len(rows) == 1
    assert rows[0].status == "UNCLASSIFIED_POOL_EVENT_EVIDENCE"
    assert rows[0].evidence_providers == ("rpc-a", "rpc-b")


def state_sources():
    return (PoolStateSource("rpc-a", "0x"), PoolStateSource("rpc-b", "0x"))


def v2_state(block_number, reserve0, reserve1, pool_key=None):
    return V2ReserveEvidence("base", pool_key or "base:" + POOL, POOL, block_number, reserve0, reserve1, 1, "UNVERIFIED_V2_RESERVE_EVIDENCE", state_sources())


def v3_state(block_number, liquidity):
    return V3LiquidityEvidence("base", "base:" + POOL, POOL, block_number, liquidity, "UNVERIFIED_V3_LIQUIDITY_EVIDENCE", state_sources())


def test_v2_reserve_history_is_cautious_about_add_remove():
    rows = build_v2_reserve_change_history([v2_state(100, 10, 20), v2_state(101, 15, 30), v2_state(102, 12, 25)])
    assert [row.classification for row in rows] == ["POSSIBLE_LIQUIDITY_ADD", "POSSIBLE_LIQUIDITY_REMOVE"]
    assert all(row.status == "UNVERIFIED_V2_RESERVE_CHANGE_EVIDENCE" for row in rows)


def test_v2_mixed_change_is_not_promoted_to_add_or_remove():
    rows = build_v2_reserve_change_history([v2_state(100, 10, 20), v2_state(101, 15, 18)])
    assert rows[0].classification == "MIXED_RESERVE_CHANGE"


def test_v3_liquidity_history_records_direction_only():
    rows = build_v3_liquidity_change_history([v3_state(100, 1000), v3_state(101, 900), v3_state(102, 900)])
    assert [row.classification for row in rows] == ["LIQUIDITY_DECREASED", "NO_LIQUIDITY_CHANGE"]
    assert rows[0].liquidity_delta == -100


def test_history_rejects_cross_pool_or_backward_time():
    with pytest.raises(EvmRpcError, match="cross chains or pools"):
        build_v2_reserve_change_history([v2_state(100, 10, 20), v2_state(101, 12, 22, pool_key="base:other")])
    with pytest.raises(EvmRpcError, match="strictly increasing"):
        build_v2_reserve_change_history([v2_state(101, 10, 20), v2_state(100, 12, 22)])
