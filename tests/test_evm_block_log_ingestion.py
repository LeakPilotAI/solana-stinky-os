from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_ingestion import ingest_consensus_block
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError


BLOCK_HASH = "0x" + "ab" * 32
OTHER_HASH = "0x" + "cd" * 32
TX_HASH = "0x" + "11" * 32


def observer(chain, url, *, head=100, block_hash=BLOCK_HASH, logs=None):
    if logs is None:
        logs = [
            {
                "address": "0x" + "22" * 20,
                "blockHash": block_hash,
                "blockNumber": hex(98),
                "data": "0x",
                "logIndex": "0x0",
                "topics": [],
                "transactionHash": TX_HASH,
                "transactionIndex": "0x0",
                "removed": False,
            }
        ]

    chain_id = "0x2105" if chain == "base" else "0x1237"

    def transport(_url, payload, timeout):
        request = json.loads(payload)
        method = request["method"]
        if method == "eth_chainId":
            result = chain_id
        elif method == "eth_blockNumber":
            result = hex(head)
        elif method == "eth_getBlockByNumber":
            result = {"number": request["params"][0], "hash": block_hash}
        elif method == "eth_getLogs":
            result = logs
        else:
            raise AssertionError(f"unexpected method {method}")
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}

    rpc = EvmReadOnlyRpc(chain, transport=transport)
    rpc.rpc_url = url
    return rpc


def test_two_providers_ingest_same_confirmed_base_block_and_logs():
    result = ingest_consensus_block(
        [
            observer("base", "https://one.example/rpc?key=secret-a"),
            observer("base", "https://two.example/rpc?key=secret-b"),
        ],
        confirmations=2,
    )
    assert result.chain == "base"
    assert result.chain_id == 8453
    assert result.block_number == 98
    assert result.block_hash == BLOCK_HASH
    assert len(result.block_sources) == 2
    assert len(result.log_sources) == 2
    assert len(result.logs) == 1
    assert all("secret-" not in row.provider for row in result.block_sources)


def test_block_hash_disagreement_fails_closed():
    with pytest.raises(EvmRpcError, match="block-hash consensus"):
        ingest_consensus_block(
            [
                observer("base", "https://one.example", block_hash=BLOCK_HASH),
                observer("base", "https://two.example", block_hash=OTHER_HASH),
            ],
            confirmations=2,
        )


def test_log_set_disagreement_fails_closed():
    first = observer("base", "https://one.example")
    altered_logs = [
        {
            "address": "0x" + "33" * 20,
            "blockHash": BLOCK_HASH,
            "blockNumber": hex(98),
            "data": "0x01",
            "logIndex": "0x0",
            "topics": [],
            "transactionHash": TX_HASH,
            "transactionIndex": "0x0",
            "removed": False,
        }
    ]
    second = observer("base", "https://two.example", logs=altered_logs)
    with pytest.raises(EvmRpcError, match="log-set consensus"):
        ingest_consensus_block([first, second], confirmations=2)


def test_duplicate_provider_cannot_satisfy_ingestion_quorum():
    same_url = "https://same.example/rpc"
    with pytest.raises(EvmRpcError, match="insufficient distinct"):
        ingest_consensus_block(
            [observer("base", same_url), observer("base", same_url)],
            confirmations=2,
        )


def test_log_block_hash_mismatch_is_rejected_by_rpc_layer():
    bad_logs = [
        {
            "address": "0x" + "22" * 20,
            "blockHash": OTHER_HASH,
            "logIndex": "0x0",
            "transactionHash": TX_HASH,
        }
    ]
    with pytest.raises(EvmRpcError, match="log-set consensus"):
        ingest_consensus_block(
            [
                observer("base", "https://one.example", logs=bad_logs),
                observer("base", "https://two.example", logs=bad_logs),
            ],
            confirmations=2,
        )


def test_minimum_ingestion_quorum_cannot_be_weakened():
    with pytest.raises(ValueError, match="at least 2"):
        ingest_consensus_block([], min_quorum=1)
