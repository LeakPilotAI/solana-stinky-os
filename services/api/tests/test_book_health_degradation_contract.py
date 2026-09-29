from pathlib import Path

API_ROOT = Path(__file__).parents[1]
REPO_ROOT = API_ROOT.parents[1]

def test_book_health_does_not_present_unavailable_hydration_as_empty_health():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert 'hydration_status = "UNKNOWN" if source == "unavailable" else "COMPLETE"' in source
    assert '"health": health if hydration_status == "COMPLETE" else None' in source
    assert '"desk": desk if hydration_status == "COMPLETE" else None' in source
    assert '"degradation_reason": "book_memory_unavailable"' in source

def test_health_ui_suppresses_zero_stats_when_hydration_is_unavailable():
    source = (REPO_ROOT / "apps" / "web" / "src" / "app" / "health" / "page.tsx").read_text(encoding="utf-8")
    assert "Evidence hydration:" in source
    assert "zero counts are not being inferred" in source
    assert "!loading && !available" in source
    assert "!loading && available" in source
