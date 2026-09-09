from stinky_api import db


def test_compact_sql_normalizes_whitespace_and_truncates():
    statement = "SELECT\n   *\tFROM   events  WHERE event_type = 'alert.candidate'"
    assert db._compact_sql(statement) == "SELECT * FROM events WHERE event_type = 'alert.candidate'"

    long_statement = "SELECT " + ("x" * 1000)
    compact = db._compact_sql(long_statement)
    assert len(compact) == db.SLOW_SQL_TEXT_LIMIT
    assert compact.startswith("SELECT ")


def test_slow_sql_threshold_is_conservative():
    assert db.SLOW_SQL_THRESHOLD_MS >= 250.0
