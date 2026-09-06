from pathlib import Path


def test_market_pattern_schema_preserves_occurrence_provenance_and_idempotency():
    migration = Path(__file__).resolve().parents[1] / "migrations" / "009_market_path_patterns.sql"
    sql = migration.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS market_path_patterns" in sql
    assert "CREATE TABLE IF NOT EXISTS market_path_pattern_occurrences" in sql
    assert "pattern_hash" in sql
    assert "first_observed_at" in sql
    assert "last_observed_at" in sql
    assert "ingested_at" in sql
    assert "evidence_basis" in sql
    assert "UNIQUE (pattern_hash, mint, observed_at)" in sql
