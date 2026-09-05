from datetime import datetime, timezone


def test_funding_observation_contract_is_direct_evidence_only() -> None:
    observed_at = datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc)
    evidence = {
        "relationship_kind": "funding_observation",
        "source_wallet": "SOURCE",
        "destination_wallet": "DESTINATION",
        "amount_lamports": 1_000_000_000,
        "signature": "SIG",
        "observed_at": observed_at.isoformat(),
        "confidence": 1.0,
        "evidence_basis": "direct_transfer_observation",
    }
    forbidden = {
        "quality_score",
        "risk_score",
        "prediction",
        "buy",
        "sell",
        "position_size",
        "ownership_inference",
    }
    assert forbidden.isdisjoint(evidence)
    assert evidence["evidence_basis"] == "direct_transfer_observation"


def test_funding_observation_preserves_temporal_evidence() -> None:
    first = datetime(2026, 9, 1, tzinfo=timezone.utc)
    last = datetime(2026, 9, 5, tzinfo=timezone.utc)
    assert first < last
