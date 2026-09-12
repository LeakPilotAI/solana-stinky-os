from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "stinky-core" / "src"))

from stinky_core.evm_consensus import EvmConsensusObservation, RpcEvidenceSource
from stinky_core.evm_ingestion import EvmIngestedBlock, EvmLogSource
from stinky_core.evm_token_discovery import ERC20_TRANSFER_TOPIC, discover_erc20_candidates


def block_with_logs(chain="base", chain_id=8453, logs=(), providers=("one:aaa", "two:bbb")):
    block_hash = "0x" + "ab" * 32
    head = EvmConsensusObservation(
        chain=chain,
        chain_id=chain_id,
        canonical_block_number=101,
        min_block_number=100,
        max_block_number=102,
        quorum=2,
        observed_at="2026-09-12T00:00:00+00:00",
        sources=(
            RpcEvidenceSource(provider="one:aaa", block_number=100),
            RpcEvidenceSource(provider="two:bbb", block_number=102),
        ),
    )
    return EvmIngestedBlock(
        chain=chain,
        chain_id=chain_id,
        block_number=99,
        block_hash=block_hash,
        observed_at="2026-09-12T00:00:01+00:00",
        head_consensus=head,
        block_sources=(),
        logs=tuple(logs),
        log_sources=tuple(
            EvmLogSource(provider=provider, digest="digest", log_count=len(logs))
            for provider in providers
        ),
    )


def erc20_transfer(address, *, block_hash=None):
    return {
        "address": address,
        "blockHash": block_hash or "0x" + "ab" * 32,
        "transactionHash": "0x" + "cd" * 32,
        "logIndex": "0x0",
        "topics": [
            ERC20_TRANSFER_TOPIC,
            "0x" + "00" * 12 + "11" * 20,
            "0x" + "00" * 12 + "22" * 20,
        ],
        "data": "0x" + "00" * 31 + "01",
    }


def test_discovers_chain_scoped_unverified_base_candidate():
    address = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
    candidates = discover_erc20_candidates(block_with_logs(logs=[erc20_transfer(address)]))
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.chain == "base"
    assert candidate.chain_id == 8453
    assert candidate.address == address.lower()
    assert candidate.asset_key == f"base:{address.lower()}"
    assert candidate.status == "UNVERIFIED_ERC20_CANDIDATE"
    assert candidate.transfer_log_count == 1
    assert candidate.evidence_providers == ("one:aaa", "two:bbb")


def test_same_address_on_robinhood_gets_different_asset_identity():
    address = "0xabcdef0123456789abcdef0123456789abcdef01"
    base = discover_erc20_candidates(block_with_logs(logs=[erc20_transfer(address)]))[0]
    robinhood = discover_erc20_candidates(
        block_with_logs(chain="robinhood", chain_id=4663, logs=[erc20_transfer(address)])
    )[0]
    assert base.asset_key == f"base:{address}"
    assert robinhood.asset_key == f"robinhood:{address}"
    assert base.asset_key != robinhood.asset_key


def test_multiple_transfer_logs_collapse_into_one_candidate():
    address = "0xabcdef0123456789abcdef0123456789abcdef01"
    logs = [erc20_transfer(address), erc20_transfer(address)]
    candidates = discover_erc20_candidates(block_with_logs(logs=logs))
    assert len(candidates) == 1
    assert candidates[0].transfer_log_count == 2


def test_erc721_shaped_transfer_is_not_promoted_to_erc20_candidate():
    address = "0xabcdef0123456789abcdef0123456789abcdef01"
    log = erc20_transfer(address)
    log["topics"].append("0x" + "00" * 31 + "01")
    log["data"] = "0x"
    assert discover_erc20_candidates(block_with_logs(logs=[log])) == ()


def test_wrong_block_hash_and_malformed_address_fail_closed():
    address = "0xabcdef0123456789abcdef0123456789abcdef01"
    wrong_hash = erc20_transfer(address, block_hash="0x" + "ff" * 32)
    malformed = erc20_transfer("0x1234")
    assert discover_erc20_candidates(block_with_logs(logs=[wrong_hash, malformed])) == ()


def test_less_than_two_provenance_sources_cannot_create_candidate():
    address = "0xabcdef0123456789abcdef0123456789abcdef01"
    block = block_with_logs(logs=[erc20_transfer(address)], providers=("one:aaa",))
    assert discover_erc20_candidates(block) == ()


def test_non_transfer_event_is_ignored():
    address = "0xabcdef0123456789abcdef0123456789abcdef01"
    log = erc20_transfer(address)
    log["topics"][0] = "0x" + "11" * 32
    assert discover_erc20_candidates(block_with_logs(logs=[log])) == ()
