from pathlib import Path
P=Path(__file__).parents[1]/"scripts"/"run_intelligence_shadow_scorer.py"
M=Path(__file__).parents[1]/"services"/"post-migration-collector"/"migrations"/"004_intelligence_shadow_scores.sql"
def test_shadow_query_is_asof_and_outcome_blind():
    s=P.read_text(encoding="utf-8")
    assert "HORIZON_SEC=60" in s
    assert "ms.captured_at <= mt.migration_at +" in s
    assert "mb.bought_at <= mt.migration_at +" in s
    assert "canonical_measured_outcome" not in s
    assert "outcome_label" not in s
def test_shadow_authority_and_idempotency_contract():
    s=P.read_text(encoding="utf-8"); m=M.read_text(encoding="utf-8")
    assert 'SHADOW_VERSION="prospective-shadow-v1"' in s
    assert 'score["trade_signal"]' in s and 'score["predictive_authority"]' in s
    assert "'evidence_only',false,false" in s
    assert "ON CONFLICT(track_id,score_version,horizon_sec) DO NOTHING" in s
    assert "UNIQUE(track_id, score_version, horizon_sec)" in m
def test_shadow_persists_provenance():
    m=M.read_text(encoding="utf-8")
    for x in ("calibration_version","calibration_sha256","migration_at","cutoff_at","scored_at","market_observed_at","feature_payload","score_payload"):
        assert x in m

def test_shadow_db_connect_is_bounded_and_single_event_loop():
    s=P.read_text(encoding="utf-8")
    assert "async def connect_db(attempts:int=3)" in s
    assert "timeout=10,command_timeout=30" in s
    assert "except (OSError,ConnectionError,asyncio.TimeoutError)" in s
    assert "items,inserted=asyncio.run(cycle())" in s
    assert "asyncio.run(build_scores" not in s
    assert "asyncio.run(persist" not in s

def test_shadow_db_cleanup_is_bounded_and_transport_safe():
    s=P.read_text(encoding="utf-8")
    assert "async def close_db(conn)" in s
    assert "asyncio.wait_for(conn.close(timeout=2), timeout=3)" in s
    assert "except (OSError, ConnectionError, asyncio.TimeoutError)" in s
    assert "conn.terminate()" in s
    assert s.count("finally: await close_db(conn)") == 2
    assert "finally: await conn.close()" not in s
