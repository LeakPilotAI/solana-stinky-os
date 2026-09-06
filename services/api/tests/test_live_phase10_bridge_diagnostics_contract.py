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
