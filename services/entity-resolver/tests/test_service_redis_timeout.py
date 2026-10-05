from pathlib import Path


def test_redis_socket_timeout_exceeds_blocking_read_window() -> None:
    source = (Path(__file__).parents[1] / "src" / "entity_resolver" / "service.py").read_text(encoding="utf-8")
    assert "socket_timeout=10" in source
    assert "block=5000" in source
