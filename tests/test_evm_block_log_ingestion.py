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


@pytest.mark.parametrize("malformed", ["0x" + "z" * 64, "0x1_" + "0" * 62, "0x" + "0" * 63 + " "])
def test_matching_malformed_hashes_cannot_create_consensus_evidence(malformed):
    with pytest.raises(EvmRpcError, match="block-hash consensus"):
        ingest_consensus_block([
            observer("base", "https://one.example", block_hash=malformed),
            observer("base", "https://two.example", block_hash=malformed),
        ])


def test_malformed_hash_provider_does_not_change_valid_downstream_quorum():
    result = ingest_consensus_block([
        observer("base", "https://bad.example", block_hash="0x" + "z" * 64),
        observer("base", "https://one.example"),
        observer("base", "https://two.example"),
    ], min_quorum=2)
    assert result.block_hash == BLOCK_HASH
    assert len(result.block_sources) == 2
    assert all(not source.provider.startswith("bad.example:") for source in result.block_sources)


def complete_log(**changes):
    return {"address": "0x" + "22" * 20, "blockHash": BLOCK_HASH, "blockNumber": "0x62",
            "data": "0x", "logIndex": "0x0", "topics": [], "transactionHash": TX_HASH,
            "transactionIndex": "0x0", "removed": False, **changes}


@pytest.mark.parametrize("field", ["address", "blockHash", "blockNumber", "data", "logIndex",
                                    "topics", "transactionHash", "transactionIndex", "removed"])
def test_missing_historical_log_provenance_cannot_form_quorum(field):
    log = complete_log()
    del log[field]
    with pytest.raises(EvmRpcError, match="log-set consensus"):
        ingest_consensus_block([observer("base", f"https://{name}.example", logs=[log]) for name in ("a", "b")])


@pytest.mark.parametrize("changes", [
    {"address": "0x" + "z" * 40}, {"transactionHash": "0x12"},
    {"blockNumber": "0x63"}, {"blockNumber": None}, {"blockNumber": "0x062"},
    {"logIndex": "0x0_0"}, {"logIndex": None}, {"transactionIndex": True},
    {"removed": True}, {"removed": 0}, {"removed": "false"},
    {"data": "0x12_3"}, {"topics": ["0x12"]}, {"topics": {}},
])
def test_malformed_or_wrong_block_logs_cannot_form_quorum(changes):
    log = complete_log(**changes)
    with pytest.raises(EvmRpcError, match="log-set consensus"):
        ingest_consensus_block([observer("base", f"https://{name}.example", logs=[log]) for name in ("a", "b")])


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_log_index_rejected_instead_of_counted_twice(conflict):
    first = complete_log()
    second = complete_log(transactionHash=OTHER_HASH) if conflict else dict(first)
    with pytest.raises(EvmRpcError, match="duplicate log index"):
        observer("base", "https://a.example", logs=[first, second]).get_logs_for_block(BLOCK_HASH)


def test_invalid_provider_response_is_not_partially_salvaged():
    good = complete_log()
    bad = complete_log(logIndex="0x1", data="0xzz")
    with pytest.raises(EvmRpcError, match="log-set consensus"):
        ingest_consensus_block([
            observer("base", "https://a.example", logs=[good, bad]),
            observer("base", "https://b.example", logs=[good]),
        ])


def test_valid_logs_preserved_and_bad_provider_excluded_from_downstream_quorum():
    log = complete_log(data="0xAb", topics=[OTHER_HASH], provider_extension="preserved")
    observers = [observer("base", f"https://{name}.example", logs=[log]) for name in ("a", "b")]
    observers.append(observer("base", "https://bad.example", logs=[complete_log(removed=True)]))
    result = ingest_consensus_block(observers)
    assert result.logs == (log,)
    assert len(result.log_sources) == 2
    assert all(not source.provider.startswith("bad.example:") for source in result.log_sources)


def test_empty_historical_log_quorum_remains_valid():
    result = ingest_consensus_block([observer("base", f"https://{name}.example", logs=[]) for name in ("a", "b")])
    assert result.logs == ()
    assert len(result.log_sources) == 2


@pytest.mark.parametrize("expected", [-1, True, "98"])
def test_invalid_expected_block_rejected_before_rpc(expected):
    def forbidden(*args):
        pytest.fail("invalid expected block reached RPC")
    rpc = EvmReadOnlyRpc("base", transport=forbidden)
    with pytest.raises(ValueError, match="non-negative integer"):
        rpc.get_logs_for_block(BLOCK_HASH, expected_block_number=expected)


def test_valid_legacy_hash_only_lookup_retains_original_records():
    logs = [complete_log()]
    rpc = observer("base", "https://a.example", logs=logs)
    assert rpc.get_logs_for_block(BLOCK_HASH) is logs
