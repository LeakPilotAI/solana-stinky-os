import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_entity_readiness_cohort.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("live_entity_readiness_cohort_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_cli_has_no_stinky_api_or_third_party_imports():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert "stinky_api" not in roots
    assert "fastapi" not in roots
    assert "sqlalchemy" not in roots
    assert "asyncpg" not in roots


def test_cli_targets_running_genesis_api_and_clamps_bounds():
    module = _load_script()
    args = SimpleNamespace(
        entity_limit=999,
        snapshot_limit=1,
        as_of="2026-08-15T00:00:00Z",
        include_entities=True,
        api_url="http://127.0.0.1:8010/",
    )
    url = module._url(args)
    assert url.startswith("http://127.0.0.1:8010/v1/entity-graph/live-readiness-cohort?")
    assert "entity_limit=500" in url
    assert "snapshot_limit=2" in url
    assert "include_entities=true" in url
    assert "as_of=2026-08-15T00%3A00%3A00Z" in url


def test_cli_module_loads_without_api_dependencies():
    module = _load_script()
    assert module.DEFAULT_API_URL == "http://127.0.0.1:8010"
