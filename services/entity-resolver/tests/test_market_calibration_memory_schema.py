from pathlib import Path


def test_calibration_memory_migration_contract():
    migration = Path(__file__).resolve().parents[1] / "migrations" / "010_market_pattern_calibration_memory.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS market_pattern_calibration_snapshots" in sql
    assert "evidence_through_observed_at TIMESTAMPTZ NOT NULL" in sql
    assert "computed_at TIMESTAMPTZ NOT NULL" in sql
    assert "ingested_at TIMESTAMPTZ NOT NULL" in sql
    assert "trend_status TEXT NOT NULL" in sql
    assert "criteria_hash TEXT NOT NULL" in sql
    assert "snapshot JSONB NOT NULL" in sql
    assert "UNIQUE (pattern_hash, evidence_through_observed_at, criteria_hash)" in sql


def test_market_outcome_schema_startup_includes_calibration_memory_migration():
    module = Path(__file__).resolve().parents[1] / "src" / "entity_resolver" / "market_outcomes.py"
    source = module.read_text(encoding="utf-8")

    assert 'migration_010 = migration_dir / "010_market_pattern_calibration_memory.sql"' in source
    assert "market calibration memory migration missing" in source
    assert "sql_010" in source
