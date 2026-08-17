"""Unit tests for feature definitions and vector computation."""

from feature_engine.definitions import (
    FEATURE_DEF_VERSION,
    FEATURE_SET_HASH,
    compute_feature_vector,
)


def test_feature_set_identity():
    assert FEATURE_DEF_VERSION == "1.0.0"
    assert FEATURE_SET_HASH.startswith("fs-v1.0.0")


def test_empty_context():
    values = compute_feature_vector({})
    assert values["launch_count"] == 0
    assert values["bond_rate"] == 0.0
    assert values["rug_count"] == 0
    assert values["has_rug_history"] is False
    assert values["median_ath_multiple"] == 0.0


def test_launch_and_bond():
    ctx = {
        "launch_count": 10,
        "bonded_count": 8,
        "rug_count": 1,
        "median_ath_multiple": 12.5,
        "wallet_age_days": 400.0,
        "unique_funding_sources": 3,
        "repeat_buyer_ratio": 0.42,
    }
    values = compute_feature_vector(ctx)
    assert values["launch_count"] == 10
    assert values["bond_rate"] == 0.8
    assert values["has_rug_history"] is True
    assert values["median_ath_multiple"] == 12.5
    assert values["repeat_buyer_ratio"] == 0.42


def test_bond_rate_zero_launches():
    values = compute_feature_vector({"launch_count": 0, "bonded_count": 0})
    assert values["bond_rate"] == 0.0
