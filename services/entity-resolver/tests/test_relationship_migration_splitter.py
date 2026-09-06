from pathlib import Path

from entity_resolver.sql_migrations import split_postgres_statements


ROOT = Path(__file__).resolve().parents[3]


def test_real_wallet_relationship_migration_splits_without_comment_fragments() -> None:
    sql = (
        ROOT
        / "services"
        / "entity-resolver"
        / "migrations"
        / "005_wallet_relationships.sql"
    ).read_text(encoding="utf-8")

    statements = split_postgres_statements(sql)

    assert statements
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_relationships_identity_unique" in s for s in statements)
    assert not any(s.lstrip().startswith("this named index") for s in statements)
    assert not any(s.lstrip().startswith("this ") for s in statements)


def test_relationship_store_uses_postgres_aware_splitter() -> None:
    source = (
        ROOT
        / "services"
        / "entity-resolver"
        / "src"
        / "entity_resolver"
        / "relationships.py"
    ).read_text(encoding="utf-8")

    assert "from entity_resolver.sql_migrations import split_postgres_statements" in source
    assert "for statement in split_postgres_statements(sql):" in source
    assert 'sql.split(";")' not in source
