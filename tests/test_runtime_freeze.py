"""Regression: health probe must not kill Redis; trade ticks must not fill events."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_redis_health_check_does_not_reset_client():
    t = read("packages/stinky-core/src/stinky_core/transport/redis_streams.py")
    start = t.find("async def health_check")
    assert start != -1
    nxt = t.find("\n    async def ", start + 10)
    chunk = t[start:nxt if nxt != -1 else start + 800]
    assert "self._reset" not in chunk
    assert "timeout=0.4" in chunk or "timeout = 0.4" in chunk


def test_collector_skips_http_ingest_for_high_freq_ticks():
    t = read("services/post-migration-collector/src/post_migration/publisher.py")
    assert "_SKIP_HTTP" in t
    assert "POST_MIGRATION_BUY" in t
    assert "POST_MIGRATION_SELL" in t
    assert "POST_MIGRATION_MARKET_SNAPSHOT" in t
    assert "event.event_type not in _SKIP_HTTP" in t
    assert "timeout=2.0" in t


def test_api_health_is_fast_and_cached():
    t = read("services/api/src/stinky_api/main.py")
    assert "_HEALTH_CACHE" in t
    assert "timeout=0.6" in t
    assert "timeout=1.0" in t


def test_command_center_runners_are_bounded():
    t = read("services/api/src/stinky_api/main.py")
    assert "ORDER BY occurred_at DESC" in t
    assert "LIMIT 200" in t
    assert "DISTINCT ON (payload->>'mint')" not in t


def test_gate1_still_150k():
    t = read("packages/stinky-core/src/stinky_core/admission.py")
    assert "GATE1_VOLUME_5M_USD = 150_000.0" in t
    assert "GATE1_VOLUME_CALIBRATION_MAX_USD = 200_000.0" in t
