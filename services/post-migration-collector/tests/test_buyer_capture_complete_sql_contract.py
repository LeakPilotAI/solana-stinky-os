"""Regression contract for asyncpg buyer-capture JSONB persistence."""

from pathlib import Path


def test_buyer_capture_complete_parameter_is_explicitly_boolean_typed() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "post_migration"
        / "store.py"
    ).read_text(encoding="utf-8")

    assert (
        "jsonb_build_object('buyer_capture_complete', CAST(:complete AS boolean))"
        in source
    )
    assert "jsonb_build_object('buyer_capture_complete', :complete)" not in source
