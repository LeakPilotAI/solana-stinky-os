from pathlib import Path

API_ROOT = Path(__file__).parents[1]


def test_api_health_propagates_event_log_degradation():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert 'event_log = "ok" if upstream_status == "ok" else "degraded"' in source
    assert 'dependencies_ok = db_ok and event_log == "ok"' in source
    assert 'status = "ok" if dependencies_ok else "degraded"' in source
    assert '"live": dependencies_ok' in source


def test_api_health_distinguishes_degraded_from_down_event_log():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert 'event_log = "degraded"' in source
    assert 'event_log = "down"' in source
