from pathlib import Path
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_consensus import EvmConsensusObservation
from stinky_core.evm_dex_discovery import DexPoolCandidate
from stinky_core.evm_ingestion import EvmIngestedBlock, EvmLogSource
from stinky_core.evm_liquidity import observe_v2_reserves, observe_v3_liquidity
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
