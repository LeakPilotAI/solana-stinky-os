from stinky_api.developer_correlation_audit import describe_developer_correlation_change, developer_correlation_hash
from stinky_api.developer_correlation_motifs import analyze_network_motifs
from stinky_api.developer_correlation_repetition import analyze_correlation_repetition


def _with_repetition(correlation):
    correlation = dict(correlation)
    correlation["repetition_analysis"] = analyze_correlation_repetition(correlation)
    return correlation


def _assert_descriptive(result):
    assert result["ownership_inferred"] is False
    assert result["coordination_inferred"] is False
    assert result["risk_inferred"] is False
    assert result["quality_inferred"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    serialized = str(result).lower()
    for forbidden in ("ownership_probability", "coordination_probability", "risk_score", "quality_score", "expected_return"):
        assert forbidden not in serialized


def test_multi_component_related_entity_becomes_constellation_without_ownership_inference():
    correlation = _with_repetition({
        "status": "OBSERVED",
        "shared_funders": [{"funder_wallet": "F1", "other_entity_id": "E2", "observation_count": 1,
                            "first_observed_at": "2026-09-01T00:00:00+00:00", "last_observed_at": "2026-09-01T00:00:00+00:00"}],
        "cross_entity_wallet_reuse": [{"wallet": "W1", "other_entity_id": "E2",
                                       "first_seen_at": "2026-09-02T00:00:00+00:00", "last_seen_at": "2026-09-02T00:00:00+00:00"}],
        "deployer_buyer_recurrence": [], "shared_relationship_structures": [],
    })
    result = analyze_network_motifs(correlation)
    assert result["motif_count"] == 1
    motif = result["records"][0]
    assert motif["motif_kind"] == "CROSS_ENTITY_RELATIONSHIP_MOTIF"
    assert motif["other_entity_ids"] == ["E2"]
    assert motif["component_kinds"] == ["SHARED_FUNDER", "WALLET_REUSE"]
    assert motif["motif_state"] == "MULTI_COMPONENT_CONSTELLATION"
    _assert_descriptive(result)


def test_same_funder_across_multiple_entities_forms_multi_entity_constellation():
    correlation = _with_repetition({
        "status": "OBSERVED",
        "shared_funders": [
            {"funder_wallet": "F1", "other_entity_id": "E2", "observation_count": 2,
             "first_observed_at": "2026-09-01T00:00:00+00:00", "last_observed_at": "2026-09-03T00:00:00+00:00"},
            {"funder_wallet": "F1", "other_entity_id": "E3", "observation_count": 1,
             "first_observed_at": "2026-09-02T00:00:00+00:00", "last_observed_at": "2026-09-02T00:00:00+00:00"},
        ],
        "cross_entity_wallet_reuse": [], "deployer_buyer_recurrence": [], "shared_relationship_structures": [],
    })
    result = analyze_network_motifs(correlation)
    constellations = [r for r in result["records"] if r["motif_kind"] == "SHARED_FUNDER_CONSTELLATION"]
    assert len(constellations) == 1
    motif = constellations[0]
    assert motif["other_entity_ids"] == ["E2", "E3"]
    assert motif["motif_state"] == "MULTI_ENTITY_FUNDER_CONSTELLATION"
    assert motif["repeated_component_count"] == 1
    assert result["multi_entity_constellation_count"] == 1
    _assert_descriptive(result)


def test_multi_launch_component_marks_historical_network_motif():
    correlation = _with_repetition({
        "status": "OBSERVED",
        "shared_funders": [], "cross_entity_wallet_reuse": [],
        "deployer_buyer_recurrence": [{"wallet": "D1", "buyer_entity_id": "E2", "launch_count": 3,
                                        "first_observed_at": "2026-08-01T00:00:00+00:00", "last_observed_at": "2026-09-01T00:00:00+00:00"}],
        "shared_relationship_structures": [],
    })
    result = analyze_network_motifs(correlation)
    assert result["motif_count"] == 1
    assert result["multi_launch_motif_count"] == 1
    assert result["records"][0]["motif_state"] == "MULTI_LAUNCH_MOTIF"


def test_single_one_off_component_does_not_fabricate_a_motif():
    correlation = _with_repetition({
        "status": "OBSERVED",
        "shared_funders": [{"funder_wallet": "F1", "other_entity_id": "E2", "observation_count": 1}],
        "cross_entity_wallet_reuse": [], "deployer_buyer_recurrence": [], "shared_relationship_structures": [],
    })
    result = analyze_network_motifs(correlation)
    assert result["motif_count"] == 0
    assert result["records"] == []


def test_motif_change_is_part_of_immutable_correlation_audit():
    base = {
        "status": "OBSERVED", "entity_id": "11111111-1111-1111-1111-111111111111", "wallets": ["W"],
        "shared_funders": [], "cross_entity_wallet_reuse": [], "deployer_buyer_recurrence": [],
        "shared_relationship_structures": [], "missing": [],
    }
    previous = _with_repetition(base)
    previous["network_motifs"] = analyze_network_motifs(previous)
    current = _with_repetition({**base, "deployer_buyer_recurrence": [{
        "wallet": "D1", "buyer_entity_id": "E2", "launch_count": 2,
        "first_observed_at": "2026-08-01T00:00:00+00:00", "last_observed_at": "2026-09-01T00:00:00+00:00",
    }]})
    current["network_motifs"] = analyze_network_motifs(current)
    assert developer_correlation_hash(previous) != developer_correlation_hash(current)
    change = describe_developer_correlation_change(previous, current)
    kinds = [item["kind"] for item in change["changes"]]
    assert "DEPLOYER_BUYER_RECURRENCE_ADDED" in kinds
    assert "REPETITION_EVIDENCE_CHANGED" in kinds
    assert "NETWORK_MOTIF_EVIDENCE_CHANGED" in kinds
    _assert_descriptive(change)
