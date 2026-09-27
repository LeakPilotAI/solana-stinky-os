import httpx
import pytest

from stinky_core.depth import JupiterDepthClient, WSOL_MINT, parse_quote


MINT = "TokenMint111111111111111111111111111111111"
PAIR = "CanonicalPair111111111111111111111111111111"
DEX = "pumpswap"


def test_parse_failures_keep_expected_market_identity():
    obs = parse_quote(
        MINT,
        10_000_000,
        {"inputMint": WSOL_MINT, "outputMint": "wrong"},
        expected_pair_address=PAIR,
        expected_dex_id=DEX,
    )
    assert obs.status == "UNKNOWN"
    assert obs.error == "QUOTE_IDENTITY_MISMATCH"
    assert obs.expected_pair_address == PAIR
    assert obs.expected_dex_id == DEX


@pytest.mark.asyncio
async def test_http_failure_keeps_expected_market_identity():
    def handler(_request: httpx.Request):
        return httpx.Response(429)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    depth = JupiterDepthClient(client)
    obs = await depth.quote_buy(
        MINT, 10_000_000, expected_pair_address=PAIR, expected_dex_id=DEX
    )
    await client.aclose()

    assert obs.status == "UNKNOWN"
    assert obs.error == "HTTP_429"
    assert obs.expected_pair_address == PAIR
    assert obs.expected_dex_id == DEX


@pytest.mark.asyncio
async def test_transport_failure_keeps_expected_market_identity():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("offline", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    depth = JupiterDepthClient(client)
    obs = await depth.quote_buy(
        MINT, 10_000_000, expected_pair_address=PAIR, expected_dex_id=DEX
    )
    await client.aclose()

    assert obs.status == "UNKNOWN"
    assert obs.error == "ConnectError"
    assert obs.expected_pair_address == PAIR
    assert obs.expected_dex_id == DEX
