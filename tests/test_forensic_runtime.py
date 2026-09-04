"""Hour-1 freeze: Redis hourly RDB OOM + CC wait_for pool leak."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_redis_disables_hourly_rdb_and_caps_memory():
    t = read("docker-compose.yml")
    assert '--save ""' in t or "--save \"\"" in t or '--save ""' in t
    assert "--save" in t
    assert "--maxmemory 384mb" in t
    assert "--appendonly no" in t
    # never unbounded stream persistence
    assert "10_000_000" not in read("packages/stinky-core/src/stinky_core/transport/redis_streams.py")


def test_stream_maxlen_fits_512m_cap():
    t = read("packages/stinky-core/src/stinky_core/transport/redis_streams.py")
    assert "maxlen: int = 20_000" in t
    assert "maxlen=self._maxlen" in t


def test_health_check_still_non_destructive():
    t = read("packages/stinky-core/src/stinky_core/transport/redis_streams.py")
    start = t.find("async def health_check")
    nxt = t.find("\n    async def ", start + 10)
    chunk = t[start:nxt if nxt != -1 else start + 800]
    assert "self._reset" not in chunk


def test_cc_does_not_cancel_sessions():
    t = read("services/api/src/stinky_api/main.py")
    start = t.find("async def command_center")
    end = t.find("@app.get(\"/v1/coordination\")")
    chunk = t[start:end]
    assert "wait_for(coro_factory()" not in chunk
    assert "SET LOCAL statement_timeout" in chunk
    assert "_CC_LOCK" in chunk
    assert "_CC_CACHE" in chunk


def test_pool_timeout_is_short():
    t = read("services/api/src/stinky_api/db.py")
    assert "pool_timeout=5" in t
    assert "pool_size=10" in t


def test_ticks_skip_redis_stream():
    t = read("services/post-migration-collector/src/post_migration/publisher.py")
    assert "_SKIP_STREAM" in t
    assert "event.event_type not in _SKIP_STREAM" in t


def test_entity_reconnect_is_bounded():
    t = read("services/entity-resolver/src/entity_resolver/service.py")
    assert "socket_timeout=5" in t
    assert "backoff" in t
    assert "min(backoff * 2, 30.0)" in t


def test_gate1_untouched():
    t = read("packages/stinky-core/src/stinky_core/admission.py")
    assert "GATE1_VOLUME_5M_USD = 33_000.0" in t
    assert "GATE1_VOLUME_CALIBRATION_MAX_USD = 200_000.0" in t


def test_no_atlas_in_forensic_paths():
    for rel in (
        "docker-compose.yml",
        "packages/stinky-core/src/stinky_core/transport/redis_streams.py",
        "services/api/src/stinky_api/db.py",
    ):
        low = read(rel).lower()
        assert "robinhood" not in low
        assert "paper trade" not in low
