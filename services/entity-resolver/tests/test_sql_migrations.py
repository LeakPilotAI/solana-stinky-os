from pathlib import Path

from entity_resolver.sql_migrations import split_postgres_statements


ROOT = Path(__file__).resolve().parents[3]


def test_splitter_preserves_plpgsql_function_body_and_splits_top_level_commands() -> None:
    sql = (
        ROOT
        / "services"
        / "entity-resolver"
        / "migrations"
        / "008_market_outcome_ingestion.sql"
    ).read_text(encoding="utf-8")

    statements = split_postgres_statements(sql)

    assert len(statements) == 3
    assert statements[0].lstrip().startswith("-- Turn measured market_snapshot inserts")
    assert "CREATE OR REPLACE FUNCTION ingest_market_outcome_observation()" in statements[0]
    assert "RETURN NEW;\nEND;\n$$" in statements[0]
    assert statements[1].startswith("DROP TRIGGER IF EXISTS trg_market_snapshot_outcome_ingestion")
    assert statements[2].startswith("CREATE TRIGGER trg_market_snapshot_outcome_ingestion")


def test_splitter_ignores_semicolons_inside_quotes_comments_and_dollar_tags() -> None:
    sql = """
    SELECT ';' AS value;
    SELECT "semi;colon" FROM example;
    /* block ; comment */
    DO $tag$
    BEGIN
        PERFORM 'inside;body';
    END;
    $tag$;
    -- line ; comment
    SELECT 3;
    """

    statements = split_postgres_statements(sql)

    assert len(statements) == 4
    assert "SELECT ';' AS value" in statements[0]
    assert 'SELECT "semi;colon" FROM example' in statements[1]
    assert "PERFORM 'inside;body';" in statements[2]
    assert statements[3].endswith("SELECT 3")
