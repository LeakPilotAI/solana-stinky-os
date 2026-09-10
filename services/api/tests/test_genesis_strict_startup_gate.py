from pathlib import Path

import scripts.strict_startup_schema_gate as gate


ROOT = Path(__file__).resolve().parents[3]


def test_psql_enables_postgres_fail_closed_mode(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, *, input_text=None, timeout=120):
        captured["args"] = args
        captured["input"] = input_text
        return Result()

    monkeypatch.setattr(gate, "run", fake_run)
    gate.psql("docker", "SELECT 1;", stop_on_error=True)
    assert "ON_ERROR_STOP=1" in captured["args"]
    assert captured["input"] == "SELECT 1;"


def test_current_executor_persistence_tables_are_mandatory():
    assert set(gate.REQUIRED_EXECUTOR_TABLES) == {
        "executor_submission_state",
        "executor_submission_transition_audit",
    }


def test_desktop_launcher_runs_strict_gate_before_start_genesis():
    text = (ROOT / "Start-Stinky-OS.cmd").read_text(encoding="utf-8")
    strict = text.index("strict_startup_schema_gate.py")
    app = text.index("start_genesis.py")
    assert strict < app
    between = text[strict:app]
    assert "if not \"%ERRORLEVEL%\"==\"0\"" in between
    assert "goto :done" in between


def test_gate_contains_no_solana_execution_capability():
    text = (ROOT / "scripts" / "strict_startup_schema_gate.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "solana rpc" in lowered  # explicit no-RPC authority statement
    assert "private_key" not in lowered
    assert "signed_transaction" not in lowered
    assert "sendtransaction" not in lowered
    assert "order_submission_allowed" not in lowered
