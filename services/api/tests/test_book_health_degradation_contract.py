from pathlib import Path

API_ROOT = Path(__file__).parents[1]
REPO_ROOT = API_ROOT.parents[1]

def test_book_health_does_not_present_unavailable_hydration_as_empty_health():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert 'status = "UNKNOWN" if source == "unavailable"' in source
    assert '"PARTIAL" if source == "postgres_partial" else "COMPLETE"' in source
    assert 'hydration = _book_hydration_meta(source)' in source
    assert '"health": health if hydration_status == "COMPLETE" else None' in source
    assert '"desk": desk if hydration_status == "COMPLETE" else None' in source
    assert '"degradation_reason": (' in source
    assert '"book_memory_unavailable" if status == "UNKNOWN"' in source
    assert '"book_memory_partial_hydration" if status == "PARTIAL"' in source

def test_health_ui_suppresses_zero_stats_when_hydration_is_unavailable():
    source = (REPO_ROOT / "apps" / "web" / "src" / "app" / "health" / "page.tsx").read_text(encoding="utf-8")
    assert "Evidence hydration:" in source
    assert "zero counts are not being inferred" in source
    assert "!loading && !available" in source
    assert "!loading && available" in source


def test_memory_snapshot_reports_failed_layers_instead_of_silent_empty_success():
    source=(API_ROOT/"src"/"stinky_api"/"queries.py").read_text(encoding="utf-8")
    assert "failed_layers: list[str] = []" in source
    assert "failed_layers.append(layer)" in source
    assert '"_hydration_failed_layers": failed_layers' in source

def test_book_health_propagates_partial_hydration_as_degraded():
    source=(API_ROOT/"src"/"stinky_api"/"main.py").read_text(encoding="utf-8")
    assert '"postgres_partial"' in source
    assert '"PARTIAL" if source == "postgres_partial"' in source
    assert '"book_memory_partial_hydration"' in source
    assert 'loaded["_failed_layers"] = failed_layers' in source


def test_book_operator_views_do_not_present_degraded_hydration_as_valid_empty_state():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert "def _book_hydration_meta(source: str)" in source
    assert "def _degraded_book_response(source: str, loaded: dict[str, Any])" in source
    assert 'return {**degraded, "desk": None}' in source
    assert '"dips": None' in source
    assert '"count": None' in source
    assert '"empty_note": None' in source
    assert '"NO ACTIVE QUALITY DETERIORATION" if not cards else None' in source
