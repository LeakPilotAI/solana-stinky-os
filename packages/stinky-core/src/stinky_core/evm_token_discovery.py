"""Fail-closed ERC-20 candidate discovery from consensus-validated EVM logs.

A Transfer-shaped log is evidence that a contract may behave like an ERC-20; it
is not proof of safety, legitimacy, sellability, or even complete ERC-20
compliance. Genesis therefore emits only UNVERIFIED candidates for later
contract/risk analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .evm_ingestion import EvmIngestedBlock
from .multichain_identity import asset_key, canonical_chain_address


ERC20_TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)


@dataclass(frozen=True, slots=True)
class Erc20Candidate:
    chain: str
    chain_id: int
    address: str
    asset_key: str
    first_seen_block: int
    block_hash: str
    transfer_log_count: int
    status: str
    evidence_providers: tuple[str, ...]


def _is_topic(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True


def _is_uint256_data(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True


def _looks_like_erc20_transfer(log: dict[str, Any], *, block_hash: str) -> bool:
    """Conservatively identify the canonical ERC-20 Transfer event shape.

    ERC-721 uses the same event signature but normally indexes tokenId as a
    fourth topic. Requiring exactly three topics plus a 32-byte data word keeps
    NFT transfers out of this discovery path. This still creates a candidate,
    never a verified token classification.
    """
    if str(log.get("blockHash") or "").lower() != block_hash.lower():
        return False
    topics = log.get("topics")
    if not isinstance(topics, list) or len(topics) != 3:
        return False
    if not all(_is_topic(topic) for topic in topics):
        return False
    if str(topics[0]).lower() != ERC20_TRANSFER_TOPIC:
        return False
    return _is_uint256_data(log.get("data"))


def discover_erc20_candidates(block: EvmIngestedBlock) -> tuple[Erc20Candidate, ...]:
    """Return chain-scoped, unverified ERC-20 candidates from accepted logs.

    Only logs already accepted by the redundant block/log quorum are consumed.
    Malformed addresses or event shapes are ignored rather than promoted.
    Multiple Transfer logs from the same contract collapse into one candidate.
    """
    providers = tuple(sorted({source.provider for source in block.log_sources}))
    if len(providers) < 2:
        return ()

    counts: dict[str, int] = {}
    for log in block.logs:
        if not isinstance(log, dict) or not _looks_like_erc20_transfer(log, block_hash=block.block_hash):
            continue
        address = canonical_chain_address(block.chain, log.get("address"))
        if address is None:
            continue
        key = asset_key(block.chain, address)
        if key is None:
            continue
        counts[address] = counts.get(address, 0) + 1

    candidates = [
        Erc20Candidate(
            chain=block.chain,
            chain_id=block.chain_id,
            address=address,
            asset_key=asset_key(block.chain, address) or "",
            first_seen_block=block.block_number,
            block_hash=block.block_hash,
            transfer_log_count=count,
            status="UNVERIFIED_ERC20_CANDIDATE",
            evidence_providers=providers,
        )
        for address, count in counts.items()
    ]
    return tuple(sorted(candidates, key=lambda item: item.asset_key))
