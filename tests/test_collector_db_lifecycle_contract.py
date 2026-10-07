from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = (
    ROOT
    / "services"
    / "post-migration-collector"
    / "src"
    / "post_migration"
    / "store.py"
)


def source() -> str:
    return STORE.read_text(encoding="utf-8")


def test_tracker_failure_json_parameters_are_explicitly_typed():
    text = source()

    assert "'tracking_exception_type', CAST(:error_type AS text)" in text
    assert "'tracking_exception_message', CAST(:error_message AS text)" in text

    assert "'tracking_exception_type', :error_type" not in text
    assert "'tracking_exception_message', :error_message" not in text


def test_wallet_trade_read_explicitly_ends_implicit_transaction():
    text = source()

    start = text.index("async def load_trades_for_wallet")
    end = text.find("\n    async def ", start + 1)

    if end == -1:
        end = len(text)

    method = text[start:end]

    assert "FROM wallet_trades" in method
    assert ").mappings().all()" in method
    assert "await session.rollback()" in method

    assert method.index(").mappings().all()") < method.index(
        "await session.rollback()"
    )
