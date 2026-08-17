"""Tests for migration log parsing."""

from sentinel.migration import (
    looks_like_migrate_attempt,
    parse_migrate_program_data,
    parse_migration_from_transaction,
    parse_migration_logs,
)


def test_skip_without_migrate_instruction():
    result = {"value": {"signature": "sig1", "logs": ["Program log: something"]}}
    assert parse_migration_logs(result) is None


def test_skip_already_migrated():
    result = {
        "value": {
            "signature": "sig2",
            "logs": [
                "Program log: Instruction: Migrate",
                "Program log: Bonding curve already migrated",
            ],
        }
    }
    assert parse_migration_logs(result) is None


def test_case_insensitive_migrate():
    result = {
        "value": {
            "signature": "sig3",
            "logs": [
                "Program log: Instruction: migrate",
                "Program data: not-valid",
            ],
        }
    }
    # looks like migrate but invalid data → None from parse, True from looks_like
    assert looks_like_migrate_attempt(result) is True
    assert parse_migration_logs(result) is None


def test_invalid_program_data_returns_none():
    assert parse_migrate_program_data("not-valid-base64!!!") is None


def test_parse_from_transaction_uses_log_messages():
    tx = {
        "meta": {
            "err": None,
            "logMessages": [
                "Program log: Instruction: Migrate",
                "Program log: Bonding curve already migrated",
            ],
        },
        "transaction": {"signatures": ["sigTx1"]},
    }
    assert parse_migration_from_transaction(tx, signature="sigTx1") is None


def test_looks_like_migrate_false_without_instruction():
    result = {"value": {"logs": ["Program log: Create"]}}
    assert looks_like_migrate_attempt(result) is False
