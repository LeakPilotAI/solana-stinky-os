from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "src" / "stinky_api" / "live_phase10_readiness.py"
SCRIPT = ROOT.parents[1] / "scripts" / "recover-phase10-research-bridge.py"


def test_live_readiness_exposes_preflight_but_never_auto_recovers():
    text = LIVE.read_text(encoding="utf-8")
    assert "historical_research_bridge_preflight" in text
    assert '"bridge_preflight"' in text
    assert '"missing": dataset.get("missing") or []' in text
    assert "recover_historical_research_bridge" not in text


def test_recovery_is_explicit_operator_command():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--dry-run" in text
    assert "recover_historical_research_bridge" in text
    assert "historical_research_bridge_preflight" in text


def test_runtime_supervisor_evidence_is_fail_closed():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/v1/system/runtime-supervisors")' in source
    assert '"status": "UNKNOWN"' in source
    assert 'if phase == "FAILED":' in source
    assert 'elif age_seconds is None or age_seconds > 180:' in source
    assert 'item["status"] = "UNKNOWN"' in source
    assert '"status": "FAILED" if failed else ("UNKNOWN" if unknown else "OBSERVED")' in source
    assert '"source": "runtime-state-per-service"' in source
