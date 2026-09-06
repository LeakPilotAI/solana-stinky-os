from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_live_window_audit_is_read_only_and_preserves_authority_boundaries():
    source = (ROOT / "scripts" / "audit-phase10-live-window.py").read_text(encoding="utf-8")
    lowered = source.lower()

    assert "audit_prospective_phase10_corpus" in source
    assert 'parser.add_argument("--since", required=True' in source
    assert '"migration_observed_at"' in source
    assert '"developer_dual_time_visible"' in source
    assert '"correlation_dual_time_visible"' in source
    assert '"lifecycle_dual_time_visible"' in source
    assert '"feature_complete"' in source
    assert '"writes": False' in source
    assert '"historical_backfill": False' in source
    assert '"predictive_authority": False' in source
    assert '"trade_signal": False' in source
    assert "insert into" not in lowered
    assert "update " not in lowered
    assert "delete from" not in lowered
