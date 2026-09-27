from pathlib import Path

from stinky_core.depth import DEPTH_OBSERVATIONS_DDL, DEPTH_OBSERVATIONS_INDEXES


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "services" / "sentinel" / "migrations" / "012_depth_quote_observations.sql"


def test_depth_schema_is_owned_by_canonical_migration():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS depth_quote_observations" in sql
    assert "quote_context_slot BIGINT" in sql
    assert "quote_time_taken_sec DOUBLE PRECISION" in sql
    assert "idx_depth_quote_mint_time" in sql


def test_runtime_depth_contract_cannot_drift_from_migration_columns():
    sql = MIGRATION.read_text(encoding="utf-8")
    for column in (
        "mint", "observed_at", "input_lamports", "out_amount_atomic",
        "price_impact_pct", "route_found", "status", "source", "error",
        "quote_context_slot", "quote_time_taken_sec", "expected_pair_address",
        "expected_dex_id", "route_amm_keys",
    ):
        assert column in sql
        assert column in DEPTH_OBSERVATIONS_DDL
    for statement in DEPTH_OBSERVATIONS_INDEXES:
        assert "idx_depth_quote_mint_time" in statement
