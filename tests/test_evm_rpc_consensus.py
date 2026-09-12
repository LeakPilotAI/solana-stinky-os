from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_consensus import observe_consensus_head, provider_fingerprint
from stinky_core.evm_rpc import EvmReadOnlyRpc, EvmRpcError


def observer(chain, url, chain_id_hex, block_hex):
    queue = [chain_id_hex, block_hex]

    def transport(_url, payload, timeout):
        request = json.loads(payload)
        return {"jsonrpc": "2.0", "id": request["id"], "result": queue.pop(0)}

    rpc = EvmReadOnlyRpc(chain, transport=transport)
    rpc.rpc_url = url
    return rpc


def failing_observer(chain, url):
    def transport(_url, payload, timeout):
        raise EvmRpcError("provider unavailable")

    rpc = EvmReadOnlyRpc(chain, transport=transport)
    rpc.rpc_url = url
    return rpc


def test_two_distinct_base_providers_reach_quorum_with_small_skew():
    result = observe_consensus_head(
        [
            observer("base", "https://one.example/rpc?key=secret-a", "0x2105", "0x64"),
            observer("base", "https://two.example/rpc?key=secret-b", "0x2105", "0x66"),
        ],
        min_quorum=2,
        max_block_skew=3,
    )
    assert result.chain == "base"
    assert result.chain_id == 8453
    assert result.canonical_block_number == 101
    assert result.min_block_number == 100
    assert result.max_block_number == 102
    assert result.quorum == 2
    assert len(result.sources) == 2
    assert all("secret-" not in source.provider for source in result.sources)


def test_same_endpoint_cannot_count_twice_toward_quorum():
    url = "https://same.example/rpc"
    with pytest.raises(EvmRpcError, match="insufficient distinct"):
        observe_consensus_head(
            [
                observer("base", url, "0x2105", "0x64"),
                observer("base", url, "0x2105", "0x64"),
            ]
        )


def test_large_head_disagreement_fails_closed():
    with pytest.raises(EvmRpcError, match="disagreement"):
        observe_consensus_head(
            [
                observer("robinhood", "https://a.example", "0x1237", "0x64"),
                observer("robinhood", "https://b.example", "0x1237", "0x70"),
            ],
            max_block_skew=3,
        )


def test_provider_failure_does_not_become_positive_evidence():
    with pytest.raises(EvmRpcError, match="quorum not reached"):
        observe_consensus_head(
            [
                observer("base", "https://good.example", "0x2105", "0x64"),
                failing_observer("base", "https://down.example"),
            ]
        )


def test_three_providers_can_tolerate_one_failure_if_two_agree():
    result = observe_consensus_head(
        [
            observer("base", "https://one.example", "0x2105", "0x64"),
            failing_observer("base", "https://down.example"),
            observer("base", "https://two.example", "0x2105", "0x65"),
        ],
        min_quorum=2,
    )
    assert result.quorum == 2
    assert result.canonical_block_number == 100


def test_provider_fingerprint_hides_credentials_but_is_stable():
    url = "https://rpc.example/path?api_key=super-secret"
    first = provider_fingerprint(url)
    second = provider_fingerprint(url)
    assert first == second
    assert first.startswith("rpc.example:")
    assert "super-secret" not in first


def test_minimum_quorum_cannot_be_weakened_below_two():
    with pytest.raises(ValueError, match="at least 2"):
        observe_consensus_head([], min_quorum=1)
