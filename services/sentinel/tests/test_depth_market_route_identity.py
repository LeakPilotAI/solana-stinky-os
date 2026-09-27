from stinky_core.depth import parse_quote, depth_persist_params, WSOL_MINT


def _payload(pair: str):
    return {
        "inputMint": WSOL_MINT,
        "outputMint": "mint-a",
        "inAmount": "10000000",
        "outAmount": "2500000",
        "priceImpactPct": "0.012",
        "contextSlot": 123456,
        "timeTaken": 0.02,
        "routePlan": [{"swapInfo": {"ammKey": pair, "label": "Pump.fun Amm"}}],
    }


def test_expected_pair_must_be_present_in_jupiter_route():
    obs = parse_quote("mint-a", 10_000_000, _payload("other-pair"), expected_pair_address="canonical-pair", expected_dex_id="pumpswap")
    assert obs.status == "UNKNOWN"
    assert obs.error == "EXPECTED_PAIR_NOT_IN_ROUTE"
    assert obs.expected_pair_address == "canonical-pair"
    assert obs.route_amm_keys == ("other-pair",)


def test_matching_pair_preserves_route_provenance_for_persistence():
    obs = parse_quote("mint-a", 10_000_000, _payload("canonical-pair"), expected_pair_address="canonical-pair", expected_dex_id="pumpswap")
    assert obs.status == "VERIFIED"
    assert obs.usable
    assert obs.expected_pair_address == "canonical-pair"
    assert obs.expected_dex_id == "pumpswap"
    assert obs.route_amm_keys == ("canonical-pair",)
    params = depth_persist_params(obs)
    assert params["expected_pair_address"] == "canonical-pair"
    assert params["expected_dex_id"] == "pumpswap"
    assert params["route_amm_keys"] == "canonical-pair"


def test_missing_amm_keys_fails_closed_when_route_exists():
    payload = _payload("canonical-pair")
    payload["routePlan"] = [{"swapInfo": {}}]
    obs = parse_quote("mint-a", 10_000_000, payload, expected_pair_address="canonical-pair", expected_dex_id="pumpswap")
    assert obs.status == "UNKNOWN"
    assert obs.error == "MISSING_ROUTE_PROVENANCE"
