from datetime import datetime, timezone

from stinky_core.depth import (
    DEPTH_OBSERVATIONS_DDL,
    DEPTH_OBSERVATIONS_INSERT,
    DepthQuoteObservation,
    depth_persist_params,
)


def test_depth_persistence_retains_verified_and_unknown_semantics():
    at = datetime(2026, 9, 27, 13, 10, tzinfo=timezone.utc)
    verified = DepthQuoteObservation("mint", at, 10_000_000, 123, 0.01, True, "VERIFIED")
    unknown = DepthQuoteObservation("mint", at, 10_000_000, None, None, False, "UNKNOWN", error="HTTP_429")
    vp = depth_persist_params(verified)
    up = depth_persist_params(unknown)
    assert vp["out_amount_atomic"] == 123
    assert vp["price_impact_pct"] == 0.01
    assert vp["status"] == "VERIFIED"
    assert up["out_amount_atomic"] is None
    assert up["price_impact_pct"] is None
    assert up["status"] == "UNKNOWN"
    assert up["error"] == "HTTP_429"
    assert "depth_quote_observations" in DEPTH_OBSERVATIONS_DDL
    assert ":price_impact_pct" in DEPTH_OBSERVATIONS_INSERT


def test_depth_table_is_append_only_contract():
    sql = DEPTH_OBSERVATIONS_INSERT.upper()
    assert "ON CONFLICT" not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
