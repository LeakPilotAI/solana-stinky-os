from pathlib import Path

API_ROOT = Path(__file__).parents[1]


def test_command_center_exposes_section_failures_instead_of_false_live_empty_state():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert "section_failures: dict[str, str] = {}" in source
    assert 'section_failures[label] = error' in source
    assert 'out[key] = None' in source
    assert 'section_failures[f"counts.{key}"]' in source
    assert 'command_center_available = not degraded_sections' in source
    assert '"status": "live" if command_center_available else "degraded"' in source
    assert '"available": command_center_available' in source
    assert '"degraded_sections": degraded_sections' in source


def test_command_center_does_not_claim_empty_investigations_when_alerts_failed():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert '"available": "trending" not in section_failures' in source
    assert 'if "alerts" in section_failures or any(a.get("mint") for a in (alerts or []))' in source
    assert '"available": "alerts" not in section_failures' in source


def test_command_center_pipeline_and_precision_failures_degrade_overall_truth():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    assert 'section_failures[f"pipeline.{key}"]' in source
    assert '"available": not any(k.startswith("pipeline.") for k in section_failures)' in source
    assert 'section_failures["alert_precision"]' in source
    assert '"message": "alert outcomes unavailable"' in source


def test_trending_query_uses_latest_row_and_indexable_fee_lookup_shape():
    source = (API_ROOT / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    start = source.index("async def _trending_m5")
    end = source.index('@app.get("/v1/command-center")', start)
    block = source[start:end]
    assert "ROW_NUMBER() OVER" not in block
    assert "SELECT DISTINCT ON (ms.mint)" in block
    assert "LEFT JOIN LATERAL" in block
    assert "ORDER BY fe.evaluated_at DESC" in block
    assert "LIMIT 1" in block


def test_runtime_query_indexes_cover_latest_fee_and_market_reads():
    migration = (API_ROOT / "migrations" / "012_runtime_query_indexes.sql").read_text(encoding="utf-8")
    assert "filter_evaluations (mint, evaluated_at DESC)" in migration
    assert "market_snapshots (mint, captured_at DESC)" in migration
