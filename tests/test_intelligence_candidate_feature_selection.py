from pathlib import Path

def test_candidate_feature_selector_is_conservative():
    t=(Path(__file__).parents[1]/"scripts"/"select_intelligence_candidate_features.py").read_text(encoding="utf-8")
    assert '"candidate-feature-ledger-v1"' in t
    assert 'coverage < .50' in t
    assert 'stable>=2' in t and 'stable>=1' in t
    assert '"INSUFFICIENT"' in t and '"WATCH"' in t and '"INCLUDE"' in t
    assert '"creator_prior_history"' in t
    assert '"collection_path_bias_0pct_runner_t60"' in t
    assert '"price_market_cap"' in t
    assert '"do_not_double_weight"' in t
    assert '"UNKNOWN_not_negative"' in t
