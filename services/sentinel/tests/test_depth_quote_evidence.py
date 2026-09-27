from datetime import datetime, timezone

import httpx
import pytest

from stinky_core.depth import JupiterDepthClient, WSOL_MINT, parse_quote


MINT = "TokenMint111111111111111111111111111111111"


def _payload(**overrides):
    row = {
        "inputMint": WSOL_MINT,
        "outputMint": MINT,
        "inAmount": "10000000",
        "outAmount": "250000000",
        "priceImpactPct": "0.0125",
        "routePlan": [{"swapInfo": {"label": "Pump.fun Amm"}}],
        "contextSlot": 350000001,
        "timeTaken": 0.012,
    }
    row.update(overrides)
    return row


def test_valid_quote_is_verified_observation_only():
    at = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
    obs = parse_quote(MINT, 10_000_000, _payload(), observed_at=at)
    assert obs.usable
    assert obs.status == "VERIFIED"
    assert obs.input_lamports == 10_000_000
    assert obs.out_amount_atomic == 250_000_000
    assert obs.price_impact_pct == pytest.approx(0.0125)
    assert obs.quote_context_slot == 350000001
    assert obs.quote_time_taken_sec == pytest.approx(0.012)


@pytest.mark.parametrize("payload,error", [
    (_payload(outputMint="wrong"), "QUOTE_IDENTITY_MISMATCH"),
    (_payload(inAmount="999"), "MALFORMED_QUOTE"),
    (_payload(priceImpactPct="nan"), "MALFORMED_QUOTE"),
    (_payload(priceImpactPct="-1"), "MALFORMED_QUOTE"),
    (_payload(routePlan=[]), "NO_ROUTE"),
    ({k: v for k, v in _payload().items() if k != "contextSlot"}, "MISSING_QUOTE_PROVENANCE"),
    (_payload(contextSlot="bad"), "MISSING_QUOTE_PROVENANCE"),
    (_payload(timeTaken="nan"), "MALFORMED_QUOTE_PROVENANCE"),
])
def test_bad_or_mismatched_quote_fails_closed(payload, error):
    obs = parse_quote(MINT, 10_000_000, payload)
    assert not obs.usable
    assert obs.status == "UNKNOWN"
    assert obs.error == error


@pytest.mark.asyncio
async def test_client_only_gets_quote_and_http_failure_is_unknown():
    def handler(request: httpx.Request):
        assert request.method == "GET"
        assert request.url.path.endswith("/quote")
        return httpx.Response(429)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    depth = JupiterDepthClient(client)
    obs = await depth.quote_buy(MINT, 10_000_000)
    assert obs.status == "UNKNOWN"
    assert obs.error == "HTTP_429"
