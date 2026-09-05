def test_behavioral_fingerprint_contract_is_descriptive_only() -> None:
    from entity_resolver.behavior import build_behavioral_fingerprint

    result = build_behavioral_fingerprint([])
    forbidden = {"quality_score", "risk_score", "prediction", "buy", "sell", "position_size"}

    assert forbidden.isdisjoint(result)
    assert result["evidence_basis"] == "entity_launches"
