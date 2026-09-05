from entity_resolver.resolver import co_buy_confidence


def test_co_buy_confidence_is_deterministic_and_descriptive() -> None:
    assert co_buy_confidence(2) == (0.0, "insufficient_overlap")
    assert co_buy_confidence(3) == (0.55, "co_early_buy")
    assert co_buy_confidence(5) == (0.70, "co_early_buy")
    assert co_buy_confidence(8) == (0.85, "strong_co_early_buy")


def test_relationship_contract_contains_evidence_only() -> None:
    forbidden = {"quality_score", "risk_score", "prediction", "buy", "sell", "position_size"}
    relationship = {
        "relationship_kind": "co_early_buy",
        "wallet_a": "A",
        "wallet_b": "B",
        "shared_mints": 5,
        "confidence": 0.70,
        "evidence_basis": "migration_buyers",
    }
    assert forbidden.isdisjoint(relationship)
    assert relationship["evidence_basis"] == "migration_buyers"
    assert relationship["wallet_a"] < relationship["wallet_b"]


def test_deployer_buyer_association_is_factual_and_not_a_prediction() -> None:
    relationship = {
        "relationship_kind": "deployer_buyer_association",
        "wallet_a": "DEPLOYER",
        "wallet_b": "BUYER",
        "observed_mints": 3,
        "confidence": 1.0,
        "evidence_basis": "entity_launches+migration_buyers",
        "confidence_basis": "direct_observed_role_association",
        "first_seen_at": "2026-01-01T00:00:00+00:00",
        "last_seen_at": "2026-01-03T00:00:00+00:00",
    }
    forbidden = {"quality_score", "risk_score", "prediction", "buy", "sell", "position_size"}
    assert forbidden.isdisjoint(relationship)
    assert relationship["evidence_basis"] == "entity_launches+migration_buyers"
    assert relationship["first_seen_at"] < relationship["last_seen_at"]
