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


def test_desktop_recovery_schema_probe_is_read_only_and_fail_closed(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from scripts import safe_genesis_start as recovery
    calls=[]
    def probe(args,**kwargs):
        calls.append((args,kwargs["input"]))
        return "BEGIN\nt\nROLLBACK\n"
    monkeypatch.setattr(recovery,"run",probe)
    recovery.verify_schema(SimpleNamespace(find_docker=lambda:"docker"))
    assert "ON_ERROR_STOP=1" in calls[0][0]
    assert "BEGIN READ ONLY" in calls[0][1]
    assert all(name in calls[0][1] for name in gate.REQUIRED_TABLES)
    assert "intelligence_execution_v2_results" in calls[0][1]
    assert "CREATE" not in calls[0][1] and "INSERT" not in calls[0][1]
    monkeypatch.setattr(recovery,"run",lambda *a,**k:"BEGIN\nf\nROLLBACK\n")
    with pytest.raises(RuntimeError):recovery.verify_schema(SimpleNamespace(find_docker=lambda:"docker"))


def test_gate_contains_no_solana_execution_capability():
    text = (ROOT / "scripts" / "strict_startup_schema_gate.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "solana rpc" in lowered  # explicit no-RPC authority statement
    assert "private_key" not in lowered
    assert "signed_transaction" not in lowered
    assert "sendtransaction" not in lowered
    assert "order_submission_allowed" not in lowered


def test_current_observation_persistence_tables_are_mandatory():
    assert set(gate.REQUIRED_OBSERVATION_TABLES) == {
        "filter_evaluations",
        "fee_observations",
        "market_snapshots",
        "market_observations",
        "depth_quote_observations",
    }
    assert set(gate.REQUIRED_OBSERVATION_TABLES).issubset(set(gate.REQUIRED_TABLES))


def test_launcher_fails_readiness_when_sentinel_does_not_stay_running(tmp_path):
    from argparse import Namespace
    from types import SimpleNamespace
    from scripts.safe_genesis_start import recover
    (tmp_path/".env").write_text("fixture")
    calls=[]
    def start(name,**kwargs):
        calls.append(name)
        if name=="sentinel":raise RuntimeError("sentinel failed ownership proof")
        return 1
    launcher=SimpleNamespace(ROOT=tmp_path,LOG_DIR=tmp_path/"logs",ensure_docker=lambda:None,apply_schema=lambda:None,start_detached=start,fail=lambda *a,**k:None)
    assert recover(launcher,Namespace(sync=False,restart=False))==1
    assert calls==["event-log","api","sentinel"]
