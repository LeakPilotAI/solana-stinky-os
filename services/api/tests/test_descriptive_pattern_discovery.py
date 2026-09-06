from stinky_api.descriptive_pattern_discovery import (
    discover_descriptive_patterns,
    extract_discrete_feature_tokens,
)


def _row(index, outcome, *, motif=True, repeated=True, lifecycle=True):
    correlation = {
        "status": "OBSERVED",
        "shared_funders": [{"funder_wallet": "F"}] if repeated else [],
        "repetition_analysis": {
            "status": "OBSERVED",
            "relationship_count_observed": 2 if repeated else 0,
            "repeated_relationship_count": 1 if repeated else 0,
            "multi_launch_relationship_count": 0,
        },
        "network_motifs": {"records": [{
            "motif_kind": "SHARED_FUNDER_CONSTELLATION",
            "motif_state": "MULTI_ENTITY_CONSTELLATION",
        }]} if motif else {"records": []},
    }
    features = {
        "developer_snapshot": {
            "history_state": "OBSERVED_HISTORY",
            "recurring_early_buyers": {"status": "OBSERVED"},
        },
        "correlation_snapshot": correlation,
        "market_lifecycle": {
            "observed_horizons": ["5m"] if lifecycle else [],
            "horizons": {"5m": {"metrics": {"survived": True, "liquidity_usd": 10000}}} if lifecycle else {},
        },
    }
    return {
        "mint": f"M{index}",
        "row_hash": f"row-{index}",
        "features": features,
        "label": {"outcome": outcome},
    }


def _dataset(rows, ready=True):
    return {
        "dataset_hash": "dataset-123",
        "feature_horizon": "5m",
        "formation_status": "READY_FOR_DESCRIPTIVE_DISCOVERY" if ready else "INSUFFICIENT_EVIDENCE",
        "rows": rows,
    }


def test_discovery_reports_support_and_outcomes_without_probability():
    rows = [_row(1, "RUNNER"), _row(2, "FADE"), _row(3, "RUNNER"), _row(4, "UNKNOWN"), _row(5, "HELD")]
    result = discover_descriptive_patterns(_dataset(rows), min_support=5, max_pattern_size=2)
    assert result["discovery_status"] == "DESCRIPTIVE_PATTERNS_OBSERVED"
    assert result["pattern_count"] >= 1
    pattern = result["patterns"][0]
    assert pattern["support_count"] == 5
    assert pattern["outcome_counts"] == {"RUNNER": 2, "HELD": 1, "FADE": 1, "UNKNOWN": 1}
    assert pattern["dataset_hash"] == "dataset-123"
    assert pattern["supporting_row_hashes"] == ["row-1", "row-2", "row-3", "row-4", "row-5"]
    assert pattern["association_is_not_prediction"] is True
    assert pattern["predictive_authority"] is False
    assert pattern["trade_signal"] is False
    assert "probability" not in pattern


def test_minimum_support_blocks_singletons_and_small_samples():
    rows = [_row(1, "RUNNER"), _row(2, "FADE")]
    result = discover_descriptive_patterns(_dataset(rows), min_support=3)
    assert result["patterns"] == []
    assert result["pattern_count"] == 0
    assert result["discovery_status"] == "INSUFFICIENT_EVIDENCE"


def test_unknown_outcomes_are_preserved_in_pattern_distribution():
    rows = [_row(1, "UNKNOWN"), _row(2, "UNKNOWN"), _row(3, "FADE")]
    result = discover_descriptive_patterns(_dataset(rows), min_support=3, max_pattern_size=1)
    assert result["patterns"]
    assert result["patterns"][0]["outcome_counts"]["UNKNOWN"] == 2
    assert result["patterns"][0]["known_outcome_count"] == 1


def test_same_support_set_suppresses_subset_spam_and_keeps_most_specific():
    rows = [_row(i, "FADE") for i in range(1, 6)]
    result = discover_descriptive_patterns(_dataset(rows), min_support=5, max_pattern_size=3, pattern_limit=100)
    support_sets = [tuple(p["supporting_row_hashes"]) for p in result["patterns"]]
    assert len(support_sets) == len(set(support_sets))
    assert result["patterns"][0]["feature_count"] == 3
    assert result["candidate_pattern_count_before_support_dedup"] > result["pattern_count"]


def test_feature_extraction_uses_categorical_facts_and_not_numeric_bucketing():
    row = _row(1, "RUNNER")
    tokens = extract_discrete_feature_tokens(row)
    assert "developer.history_state=OBSERVED_HISTORY" in tokens
    assert "correlation.shared_funders=OBSERVED" in tokens
    assert "correlation.repetition=REPEATED_OBSERVATION_PRESENT" in tokens
    assert "motif.kind=SHARED_FUNDER_CONSTELLATION" in tokens
    assert "lifecycle.horizon.5m=OBSERVED" in tokens
    assert "lifecycle.5m.metric.survived=True" in tokens
    assert not any("liquidity_usd" in token for token in tokens)


def test_dataset_not_ready_never_claims_discovery_ready_even_if_pattern_exists():
    rows = [_row(i, "RUNNER") for i in range(1, 6)]
    result = discover_descriptive_patterns(_dataset(rows, ready=False), min_support=5)
    assert result["patterns"]
    assert result["discovery_status"] == "INSUFFICIENT_EVIDENCE"
