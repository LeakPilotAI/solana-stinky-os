from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_consensus import EvmConsensusObservation, RpcEvidenceSource
from stinky_core.evm_dex_discovery import (
    V2_PAIR_CREATED_TOPIC,
    V3_POOL_CREATED_TOPIC,
    discover_dex_pool_candidates,
)
from stinky_core.evm_ingestion import EvmIngestedBlock, EvmLogSource


BLOCK_HASH = "0x" + "ab" * 32
TX_HASH = "0x" + "cd" * 32
FACTORY = "0x" + "11" * 20
TOKEN0 = "0x" + "22" * 20
TOKEN1 = "0x" + "33" * 20
POOL = "0x" + "44" * 20


def topic_address(address):
    return "0x" + "0" * 24 + address[2:]


def word_address(address):
    return "0" * 24 + address[2:]


def uint_word(value):
    return f"{value:064x}"


def block(logs, providers=("rpc-a", "rpc-b"), chain="base", chain_id=8453):
    head = EvmConsensusObservation(
        chain=chain,
        chain_id=chain_id,
        canonical_block_number=102,
        min_block_number=101,
        max_block_number=102,
        quorum=2,
        observed_at="2026-09-12T00:00:00+00:00",
        sources=(
            RpcEvidenceSource(provider="rpc-a", block_number=101),
            RpcEvidenceSource(provider="rpc-b", block_number=102),
        ),
    )
    return EvmIngestedBlock(
        chain=chain,
        chain_id=chain_id,
        block_number=100,
        block_hash=BLOCK_HASH,
        observed_at="2026-09-12T00:00:01+00:00",
        head_consensus=head,
        block_sources=(),
        logs=tuple(logs),
        log_sources=tuple(EvmLogSource(provider=p, digest="d", log_count=len(logs)) for p in providers),
    )


def v2_log(**overrides):
    item = {
        "address": FACTORY,
        "blockHash": BLOCK_HASH,
        "transactionHash": TX_HASH,
        "logIndex": "0x1",
        "topics": [V2_PAIR_CREATED_TOPIC, topic_address(TOKEN0), topic_address(TOKEN1)],
        "data": "0x" + word_address(POOL) + uint_word(7),
    }
    item.update(overrides)
    return item


def v3_log(**overrides):
    item = {
        "address": FACTORY,
        "blockHash": BLOCK_HASH,
        "transactionHash": TX_HASH,
        "logIndex": "0x2",
        "topics": [
            V3_POOL_CREATED_TOPIC,
            topic_address(TOKEN0),
            topic_address(TOKEN1),
            "0x" + uint_word(3000),
        ],
        "data": "0x" + uint_word(60) + word_address(POOL),
    }
    item.update(overrides)
    return item


def test_v2_style_pair_created_becomes_unverified_pool_candidate():
    result = discover_dex_pool_candidates(block([v2_log()]))
    assert len(result) == 1
    candidate = result[0]
    assert candidate.event_family == "V2_STYLE_PAIR_CREATED"
    assert candidate.status == "UNVERIFIED_DEX_POOL_CANDIDATE"
    assert candidate.factory_key == f"base:{FACTORY}"
    assert candidate.pool_key == f"base:{POOL}"
    assert candidate.token0_key == f"base:{TOKEN0}"
    assert candidate.token1_key == f"base:{TOKEN1}"
    assert candidate.evidence_providers == ("rpc-a", "rpc-b")
    assert candidate.fee_tier is None


def test_v3_style_pool_created_extracts_fee_but_remains_unverified():
    result = discover_dex_pool_candidates(block([v3_log()]))
    assert len(result) == 1
    candidate = result[0]
    assert candidate.event_family == "V3_STYLE_POOL_CREATED"
    assert candidate.fee_tier == 3000
    assert candidate.status == "UNVERIFIED_DEX_POOL_CANDIDATE"


def test_same_addresses_are_chain_scoped():
    base = discover_dex_pool_candidates(block([v2_log()], chain="base", chain_id=8453))[0]
    robinhood = discover_dex_pool_candidates(block([v2_log()], chain="robinhood", chain_id=4663))[0]
    assert base.pool_key == f"base:{POOL}"
    assert robinhood.pool_key == f"robinhood:{POOL}"
    assert base.pool_key != robinhood.pool_key


def test_single_provider_provenance_fails_closed():
    assert discover_dex_pool_candidates(block([v2_log()], providers=("rpc-a",))) == ()


def test_wrong_block_hash_is_rejected():
    assert discover_dex_pool_candidates(block([v2_log(blockHash="0x" + "ff" * 32)])) == ()


def test_zero_or_identical_tokens_are_rejected():
    zero = "0x" + "00" * 20
    assert discover_dex_pool_candidates(
        block([v2_log(topics=[V2_PAIR_CREATED_TOPIC, topic_address(zero), topic_address(TOKEN1)])])
    ) == ()
    assert discover_dex_pool_candidates(
        block([v2_log(topics=[V2_PAIR_CREATED_TOPIC, topic_address(TOKEN0), topic_address(TOKEN0)])])
    ) == ()


def test_malformed_event_shape_is_not_promoted():
    malformed = v2_log(data="0x1234")
    assert discover_dex_pool_candidates(block([malformed])) == ()


def test_matching_event_does_not_claim_verified_factory_or_pool():
    candidate = discover_dex_pool_candidates(block([v2_log()]))[0]
    assert "VERIFIED" not in candidate.status.replace("UNVERIFIED", "")
    assert candidate.status == "UNVERIFIED_DEX_POOL_CANDIDATE"
