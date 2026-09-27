import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from sentinel.volume import DexScreenerClient


MINT = "requested-solana-mint"


def pair(**overrides):
    value = {
        "chainId": "solana", "dexId": "pumpswap", "pairAddress": "observed-pool",
        "baseToken": {"address": MINT}, "priceUsd": "2",
        "liquidity": {"usd": 5}, "volume": {"m5": 900000},
    }
    value.update(overrides)
    return value


def fetch(pairs):
    client = object.__new__(DexScreenerClient)
    client._cooldown_until = 0
    client.last_probe = None
    client._http = Mock(get=AsyncMock(return_value=Mock(status_code=200, json=lambda: {"pairs": pairs})))
    return asyncio.run(client.fetch_volume(MINT))


@pytest.mark.parametrize("bad", [
    pair(chainId="base"), pair(chainId=None),
    pair(baseToken={"address": "unrelated-mint"}), pair(baseToken={}),
    pair(baseToken=None), pair(pairAddress=None), pair(pairAddress=" "),
    pair(pairAddress=123), pair(baseToken=[]),
    pair(baseToken={"address": "unrelated-mint"}, quoteToken={"address": MINT}),
])
def test_foreign_or_missing_pair_identity_cannot_be_attributed_to_requested_mint(bad):
    assert fetch([bad]) is None


def test_unrelated_high_liquidity_pair_cannot_replace_matching_research_pair():
    foreign = pair(baseToken={"address": "unrelated-mint"}, liquidity={"usd": 999999})
    result = fetch([None, foreign, pair()])
    assert result.mint == MINT
    assert result.pair_address == "observed-pool"
    assert result.price_usd == 2
    assert result.liquidity_usd == 5


@pytest.mark.parametrize("liquidity", [None, 0, 0.001, 5])
def test_low_and_unknown_liquidity_remain_valid_research_observations(liquidity):
    result = fetch([pair(liquidity={"usd": liquidity})])
    assert result is not None
    assert result.liquidity_usd == liquidity
    assert result.volume_m5_usd == 900000


def test_existing_selection_among_matching_pairs_remains_unchanged():
    result = fetch([pair(), pair(pairAddress="second-pool", liquidity={"usd": 20})])
    assert result.pair_address == "second-pool"
    assert result.liquidity_usd == 20
