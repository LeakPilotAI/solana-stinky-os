from stinky_api.developer_correlation_audit import describe_developer_correlation_change, developer_correlation_hash
from stinky_api.developer_correlation_repetition import analyze_correlation_repetition


def _authority_absent_of_scores(result):
    serialized = str(result).lower()
    for forbidden in ("expected_return", "probability", "risk_score", "quality_score", "ownership_probability", "coordination_probability"):
        assert forbidden not in serialized
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["ownership_inferred"] is False
    assert result["coordination_inferred"] is False


def test_single_vs_repeated_and_multi_launch_are_descriptive_states():
    result = analyze_correlation_repetition({
        "status": "OBSERVED",
        "shared_funders": [{
            "funder_wallet": "FUNDER", "other_entity_id": "E2", "observation_count": 3,
            "first_observed_at": "2026-09-01T00:00:00+00:00", "last_observed_at": "2026-09-03T00:00:00+00:00",
        }],
        "cross_entity_wallet_reuse": [{
            "wallet": "WALLET", "other_entity_id": "E3",
            "first_seen_at": "2026-09-02T00:00:00+00:00", "last_seen_at": "2026-09-02T00:00:00+00:00",
        }],
        "deployer_buyer_recurrence": [{
            "wallet": "DEPLOYER", "buyer_entity_id": "E1", "launch_count": 2,
            "first_observed_at": "2026-09-01T00:00:00+00:00", "last_observed_at": "2026-09-04T00:00:00+00:00",
        }],
        "shared_relationship_structures": [],
    })
    states = {row["kind"]: row["repetition_state"] for row in result["records"]}
    assert states["SHARED_FUNDER"] == "REPEATED_OBSERVATION"
    assert states["WALLET_REUSE"] == "SINGLE_OBSERVATION"
    assert states["DEPLOYER_BUYER_RECURRENCE"] == "MULTI_LAUNCH_REPETITION"
    assert result["repeated_relationship_count"] == 2
    assert result["multi_launch_relationship_count"] == 1
    assert result["max_temporal_spread_seconds"] == 259200
    assert result["repetition_is_not_strength_score"] is True
    _authority_absent_of_scores(result)


def test_missing_temporal_or_launch_evidence_stays_explicit_unknown():
    result = analyze_correlation_repetition({
        "status": "OBSERVED",
        "shared_relationship_structures": [{"relationship_kind": "FUNDED", "other_entity_id": "E2", "observation_count": 2}],
    })
    record = result["records"][0]
    assert record["repetition_state"] == "REPEATED_OBSERVATION"
    assert record["temporal_spread_seconds"] is None
    assert record["distinct_launch_count"] is None
    assert "some_temporal_spans" in result["missing"]
    assert "some_distinct_launch_counts" in result["missing"]


def test_repetition_change_changes_snapshot_hash_and_audit_kind():
    base = {
        "status": "OBSERVED", "entity_id": "11111111-1111-1111-1111-111111111111", "wallets": ["W"],
        "shared_funders": [{"funder_wallet": "F", "other_entity_id": "E2"}],
        "cross_entity_wallet_reuse": [], "deployer_buyer_recurrence": [], "shared_relationship_structures": [], "missing": [],
    }
    previous = {**base, "repetition_analysis": analyze_correlation_repetition({**base, "shared_funders": [{"funder_wallet": "F", "other_entity_id": "E2", "observation_count": 1}]})}
    current = {**base, "repetition_analysis": analyze_correlation_repetition({**base, "shared_funders": [{"funder_wallet": "F", "other_entity_id": "E2", "observation_count": 3}]})}
    assert developer_correlation_hash(previous) != developer_correlation_hash(current)
    change = describe_developer_correlation_change(previous, current)
    assert change["changed"] is True
    assert [item["kind"] for item in change["changes"]] == ["REPETITION_EVIDENCE_CHANGED"]
    _authority_absent_of_scores(change)


def test_no_relationships_remain_new_unknown_without_fabricated_repetition():
    result = analyze_correlation_repetition({"status": "NEW-UNKNOWN"})
    assert result["status"] == "NEW-UNKNOWN"
    assert result["relationship_count_observed"] == 0
    assert result["repeated_relationship_count"] == 0
    assert result["records"] == []
    assert result["total_independent_observation_count"] == 0
