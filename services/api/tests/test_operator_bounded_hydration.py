from pathlib import Path


def test_operator_endpoint_uses_bounded_operational_hydration():
    root = Path(__file__).resolve().parents[1]
    main = (root / "src" / "stinky_api" / "main.py").read_text(encoding="utf-8")
    queries = (root / "src" / "stinky_api" / "queries.py").read_text(encoding="utf-8")

    start = main.index('@app.get("/v1/operator")')
    end = main.index('@app.get("/v1/operator/investigations/{mint}")', start)
    operator = main[start:end]
    assert "queries.load_operator_snapshot(session)" in operator
    assert "_book_memory(None, session)" not in operator
    assert "async def load_operator_snapshot" in queries
    assert '"investigations": await rows' in queries
    assert '"operator_events": await rows' in queries
    assert '"provider_probes": await rows' in queries
    assert "LIMIT 500" in queries
    assert "LIMIT 100" in queries
    assert "LIMIT 200" in queries


def test_full_book_hydration_remains_available_for_research_endpoints():
    root = Path(__file__).resolve().parents[1]
    queries = (root / "src" / "stinky_api" / "queries.py").read_text(encoding="utf-8")
    assert "async def load_memory_snapshot" in queries
    assert "MEMORY_SELECT_WALLET_OBS" in queries
