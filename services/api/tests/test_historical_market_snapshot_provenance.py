from pathlib import Path

from stinky_api.historical_market_snapshot_provenance import (
    CLASS_AMBIGUOUS,
    CLASS_CAPTURE_TIME_ONLY,
    CLASS_DUAL_TIME_PROVEN,
    CLASS_EVENT_LATE,
    CLASS_NO_SNAPSHOT,
)

ROOT = Path(__file__).resolve().parents[1]


def test_provenance_classifications_are_explicit():
    assert CLASS_DUAL_TIME_PROVEN == "DUAL_TIME_PROVEN"
    assert CLASS_CAPTURE_TIME_ONLY == "CAPTURE_TIME_ONLY"
    assert CLASS_AMBIGUOUS == "AMBIGUOUS_PROVENANCE"
    assert CLASS_EVENT_LATE == "DURABLE_EVENT_AFTER_FEATURE_CUTOFF"
    assert CLASS_NO_SNAPSHOT == "NO_SNAPSHOT"


def test_audit_is_read_only_and_dual_time_fail_closed():
    source = (ROOT / "src" / "stinky_api" / "historical_market_snapshot_provenance.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "insert into" not in lowered
    assert "update " not in lowered
    assert "delete from" not in lowered
    assert '"captured_at_is_not_ingested_at": true' in source
    assert '"only_dual_time_proven_is_reconstructable": true' in source
    assert "event[\"ingested_at\"] <= feature_as_of" in source


def test_audit_matches_exact_snapshot_identity_and_is_bounded():
    source = (ROOT / "src" / "stinky_api" / "historical_market_snapshot_provenance.py").read_text(encoding="utf-8")
    assert "e.payload->>'mint' = s.mint" in source
    assert "e.occurred_at = s.captured_at" in source
    assert "e.payload->>'source'" in source
    assert "e.payload->>'pair_address'" in source
    assert "e.payload->>'dex_id'" in source
    assert '"query_count_max": 4' in source
    assert "limit = max(1, min(500" in source


def test_audit_has_no_prediction_or_trade_authority():
    source = (ROOT / "src" / "stinky_api" / "historical_market_snapshot_provenance.py").read_text(encoding="utf-8").lower()
    assert '"predictive_authority": false' in source
    assert '"trade_signal": false' in source
    assert '"risk_inferred": false' in source
    assert '"quality_inferred": false' in source
