from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "008_market_outcome_ingestion.sql"
)


def test_market_snapshot_ingestion_migration_exists_and_is_triggered():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION ingest_market_outcome_observation()" in sql
    assert "CREATE TRIGGER trg_market_snapshot_outcome_ingestion" in sql
    assert "AFTER INSERT ON market_snapshots" in sql
    assert "INSERT INTO market_outcome_observations" in sql


def test_ingestion_uses_only_supported_lifecycle_horizons():
    sql = MIGRATION.read_text(encoding="utf-8")
    for horizon, seconds in (("5m", 300), ("15m", 900), ("30m", 1800), ("1h", 3600), ("4h", 14400), ("24h", 86400)):
        assert f"('{horizon}', {seconds})" in sql
    assert "make_interval(secs => horizon_seconds)" in sql


def test_ingestion_preserves_anchor_observation_and_real_snapshot_time():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "SELECT mt.migration_at" in sql
    assert "MIN(ms.captured_at)" in sql
    assert "anchor_observed_at" in sql
    assert "observed_at" in sql
    assert "NEW.captured_at" in sql
    assert "market_snapshot_observation" in sql


def test_missing_horizons_are_not_fabricated():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "NEW.captured_at >= feature_cutoff" in sql
    assert "evidence_basis = 'market_snapshot_observation'" in sql
    assert "NOT EXISTS" in sql
    assert "ON CONFLICT DO NOTHING" in sql


def test_phase10_pre_cutoff_evidence_is_separate_and_bounded():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "phase10_pre_cutoff_market_snapshot" in sql
    assert "seconds_before_cutoff >= 0" in sql
    assert "seconds_before_cutoff <= 90" in sql
    assert "horizon_name IN ('5m', '15m', '30m')" in sql
    assert "phase10_prospective" in sql
