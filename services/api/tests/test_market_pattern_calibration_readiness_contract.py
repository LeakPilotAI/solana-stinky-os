from stinky_api.investigation_entity_network import _unknown


def test_unknown_investigation_exposes_calibration_readiness_contract():
    result = _unknown(status="NEW-UNKNOWN", wallet_limit=10, relationship_limit=20)

    readiness = result["market_pattern_calibration_readiness"]
    assert readiness["status"] == "NEW-UNKNOWN"
    assert readiness["readiness_status"] == "INSUFFICIENT_EVIDENCE"
    assert readiness["stable_horizons"] == []
    assert readiness["unstable_horizons"] == []
    assert readiness["evidence_only"] is True
