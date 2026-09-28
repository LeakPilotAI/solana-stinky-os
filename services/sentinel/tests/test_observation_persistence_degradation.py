import pytest

from sentinel.volume import VolumeMonitor


class _BrokenSessionContext:
    async def __aenter__(self):
        raise RuntimeError("database unavailable")

    async def __aexit__(self, *_args):
        return False


def _broken_sessions():
    return _BrokenSessionContext()


def _monitor():
    monitor = object.__new__(VolumeMonitor)
    monitor._sessions = _broken_sessions
    monitor._observation_persistence_degraded = {}
    return monitor


@pytest.mark.asyncio
async def test_depth_persistence_failure_marks_observation_degraded():
    monitor = _monitor()
    obs = type("Obs", (), {"mint": "mint-a"})()

    await monitor._persist_depth_observation(obs)

    state = monitor.observation_persistence_degraded
    assert "depth_observation" in state
    assert "database unavailable" in state["depth_observation"]


@pytest.mark.asyncio
async def test_market_snapshot_failure_marks_observation_degraded():
    monitor = _monitor()
    snap = type(
        "Snap",
        (),
        {
            "price_usd": 1.0,
            "liquidity_usd": 10_000.0,
            "volume_m5_usd": 50_000.0,
            "pair_address": "pair-a",
            "dex_id": "pumpswap",
        },
    )()

    await monitor._persist_market_snapshot("mint-a", snap)

    state = monitor.observation_persistence_degraded
    assert "market_snapshot" in state
    assert "database unavailable" in state["market_snapshot"]


def test_persistence_degradation_property_returns_copy():
    monitor = _monitor()
    monitor._mark_observation_persistence_degraded("depth_observation", "failed")

    snapshot = monitor.observation_persistence_degraded
    snapshot["depth_observation"] = "mutated"

    assert monitor.observation_persistence_degraded["depth_observation"] == "failed"


class _HealthySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, *_args, **_kwargs):
        return None

    async def commit(self):
        return None


def _healthy_sessions():
    return _HealthySession()


@pytest.mark.asyncio
async def test_successful_depth_write_clears_current_degradation():
    monitor = _monitor()
    monitor._mark_observation_persistence_degraded("depth_observation", "database unavailable")
    monitor._sessions = _healthy_sessions
    obs = type(
        "Obs",
        (),
        {
            "mint": "mint-a",
            "observed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            "input_lamports": 10_000_000,
            "out_amount_atomic": None,
            "price_impact_pct": None,
            "route_found": False,
            "status": "UNKNOWN",
            "source": "test",
            "error": "HTTP_429",
            "quote_context_slot": None,
            "quote_time_taken_sec": None,
            "expected_pair_address": "pair-a",
            "expected_dex_id": "pumpswap",
            "route_amm_keys": (),
        },
    )()

    await monitor._persist_depth_observation(obs)

    assert "depth_observation" not in monitor.observation_persistence_degraded


def test_recovery_of_one_stream_does_not_clear_other_failures():
    monitor = _monitor()
    monitor._mark_observation_persistence_degraded("depth_observation", "depth failed")
    monitor._mark_observation_persistence_degraded("market_snapshot", "market failed")

    monitor._clear_observation_persistence_degraded("depth_observation")

    assert monitor.observation_persistence_degraded == {
        "market_snapshot": "market failed"
    }


@pytest.mark.asyncio
async def test_filter_evaluation_failure_marks_observation_degraded():
    monitor = _monitor()
    monitor._threshold = 33_000.0

    await monitor._record_filter_eval(
        mint="mint-a",
        accepted=False,
        reason="LOW_VOLUME",
        fees_sol=None,
        fees_verified=False,
    )

    state = monitor.observation_persistence_degraded
    assert "filter_evaluation" in state
    assert "database unavailable" in state["filter_evaluation"]


@pytest.mark.asyncio
async def test_successful_filter_evaluation_clears_only_its_degradation():
    monitor = _monitor()
    monitor._threshold = 33_000.0
    monitor._mark_observation_persistence_degraded("filter_evaluation", "audit failed")
    monitor._mark_observation_persistence_degraded("depth_observation", "depth failed")
    monitor._sessions = _healthy_sessions

    await monitor._record_filter_eval(
        mint="mint-a",
        accepted=True,
        reason=None,
        fees_sol=None,
        fees_verified=False,
    )

    assert monitor.observation_persistence_degraded == {
        "depth_observation": "depth failed"
    }


def test_persistence_health_emits_only_state_transitions(capsys):
    monitor = _monitor()

    monitor._mark_observation_persistence_degraded("depth_observation", "first failure")
    monitor._mark_observation_persistence_degraded("depth_observation", "second failure")
    monitor._clear_observation_persistence_degraded("depth_observation")

    output = capsys.readouterr().out
    assert output.count("observation_persistence.degraded") == 1
    assert output.count("observation_persistence.recovered") == 1
    assert "depth_observation" in output


def _market_tick_snap():
    from datetime import datetime, timezone
    return type(
        "Snap",
        (),
        {
            "fetched_at": datetime.now(timezone.utc),
            "volume_m5_usd": 50_000.0,
            "price_usd": 1.0,
            "liquidity_usd": 10_000.0,
            "pair_address": "pair-a",
            "dex_id": "pumpswap",
            "market_cap_usd": 75_000.0,
            "txns_m5_buys": 10,
            "txns_m5_sells": 3,
        },
    )()


@pytest.mark.asyncio
async def test_market_observation_failure_marks_observation_degraded():
    monitor = _monitor()
    monitor._memory = None
    migration = type("Migration", (), {"mint": "mint-a"})()

    await monitor._record_market_snapshot(migration, _market_tick_snap())

    state = monitor.observation_persistence_degraded
    assert "market_observation" in state
    assert "database unavailable" in state["market_observation"]


@pytest.mark.asyncio
async def test_successful_market_observation_clears_only_its_degradation():
    monitor = _monitor()
    monitor._memory = None
    monitor._mark_observation_persistence_degraded("market_observation", "tick failed")
    monitor._mark_observation_persistence_degraded("depth_observation", "depth failed")
    monitor._sessions = _healthy_sessions
    migration = type("Migration", (), {"mint": "mint-a"})()

    await monitor._record_market_snapshot(migration, _market_tick_snap())

    assert monitor.observation_persistence_degraded == {
        "depth_observation": "depth failed"
    }


@pytest.mark.asyncio
async def test_investigation_memory_failure_marks_observation_degraded():
    from datetime import datetime, timezone
    monitor = _monitor()

    await monitor._persist_memory_decision(
        mint="mint-a",
        observed_at=datetime.now(timezone.utc),
        buyers=[],
        creator=None,
        fingerprint=None,
        investigation={"mint": "mint-a", "gate1_at": datetime.now(timezone.utc).isoformat()},
    )

    state = monitor.observation_persistence_degraded
    assert "investigation_memory" in state
    assert "database unavailable" in state["investigation_memory"]


@pytest.mark.asyncio
async def test_successful_investigation_memory_write_clears_only_its_degradation():
    from datetime import datetime, timezone
    monitor = _monitor()
    monitor._mark_observation_persistence_degraded("investigation_memory", "memory failed")
    monitor._mark_observation_persistence_degraded("market_observation", "market failed")
    monitor._sessions = _healthy_sessions

    await monitor._persist_memory_decision(
        mint="mint-a",
        observed_at=datetime.now(timezone.utc),
        buyers=[],
        creator=None,
        fingerprint=None,
        investigation=None,
    )

    assert monitor.observation_persistence_degraded == {
        "market_observation": "market failed"
    }


@pytest.mark.asyncio
async def test_investigation_memory_persists_canonical_market_identity():
    from datetime import datetime, timezone

    class CapturingSession(_HealthySession):
        def __init__(self):
            self.calls = []

        async def execute(self, statement, params=None, **_kwargs):
            self.calls.append((str(statement), params))
            return None

    session = CapturingSession()

    def sessions():
        class Context:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *_args):
                return False
        return Context()

    monitor = _monitor()
    monitor._sessions = sessions
    await monitor._persist_memory_decision(
        mint="mint-a",
        observed_at=datetime.now(timezone.utc),
        buyers=[],
        creator=None,
        fingerprint=None,
        pair_address="pair-canonical",
        dex_id="pumpswap",
        investigation=None,
    )

    market_params = next(
        params for sql, params in session.calls
        if params and "pair_address" in params and "dex_id" in params
    )
    assert market_params["pair_address"] == "pair-canonical"
    assert market_params["dex_id"] == "pumpswap"


@pytest.mark.asyncio
async def test_failed_memory_hydration_stays_retryable_and_degraded():
    from stinky_core.memory import IntelligenceMemory

    monitor = _monitor()
    monitor._memory = IntelligenceMemory()
    monitor._memory_hydrated = False

    await monitor._hydrate_memory()

    assert monitor._memory_hydrated is False
    assert "memory_hydration" in monitor.observation_persistence_degraded


@pytest.mark.asyncio
async def test_successful_memory_hydration_clears_only_hydration_degradation():
    from stinky_core.memory import IntelligenceMemory

    class EmptyMappings:
        def all(self):
            return []

    class EmptyResult:
        def mappings(self):
            return EmptyMappings()

    class HydrationSession:
        async def execute(self, *_args, **_kwargs):
            return EmptyResult()

    def sessions():
        class Context:
            async def __aenter__(self):
                return HydrationSession()
            async def __aexit__(self, *_args):
                return False
        return Context()

    monitor = _monitor()
    monitor._memory = IntelligenceMemory()
    monitor._memory_hydrated = False
    monitor._mark_observation_persistence_degraded("memory_hydration", "read failed")
    monitor._mark_observation_persistence_degraded("market_observation", "write failed")
    monitor._sessions = sessions

    await monitor._hydrate_memory()

    assert monitor._memory_hydrated is True
    assert monitor.observation_persistence_degraded == {
        "market_observation": "write failed"
    }


def test_restart_critical_hydration_reads_are_not_silently_downgraded():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index("async def _hydrate_memory")
    end = source.index("async def _persist_memory_decision", start)
    block = source[start:end]

    for selector in (
        "MEMORY_SELECT_DECISION",
        "MEMORY_SELECT_MARKET_OBS",
        "MEMORY_SELECT_INVESTIGATION",
    ):
        read = f"session.execute(text({selector}))"
        assert read in block
        prefix = block[: block.index(read)]
        assert "except Exception:\n                    " + selector.lower() not in prefix[-250:]


@pytest.mark.asyncio
async def test_watch_state_failure_marks_observation_degraded():
    monitor = _monitor()
    monitor._memory = None

    await monitor._upsert_watch(
        mint="mint-a",
        started_at="2026-01-01T00:00:00+00:00",
        status="FAILED",
        stop_reason="RUNTIME_ERROR:RuntimeError",
    )

    state = monitor.observation_persistence_degraded
    assert "watch_state" in state
    assert "database unavailable" in state["watch_state"]


@pytest.mark.asyncio
async def test_successful_watch_state_write_clears_only_its_degradation():
    monitor = _monitor()
    monitor._memory = None
    monitor._mark_observation_persistence_degraded("watch_state", "watch failed")
    monitor._mark_observation_persistence_degraded("market_observation", "market failed")
    monitor._sessions = _healthy_sessions

    await monitor._upsert_watch(
        mint="mint-a",
        started_at="2026-01-01T00:00:00+00:00",
        status="WATCHING",
    )

    assert monitor.observation_persistence_degraded == {
        "market_observation": "market failed"
    }


@pytest.mark.asyncio
async def test_provider_probe_failure_marks_observation_degraded():
    monitor = _monitor()
    monitor._memory = None

    await monitor._record_probe({
        "provider": "dexscreener",
        "at": "2026-01-01T00:00:00+00:00",
        "status": "FAILED",
        "ok": False,
        "error": "upstream unavailable",
    })

    state = monitor.observation_persistence_degraded
    assert "provider_probe" in state
    assert "database unavailable" in state["provider_probe"]


@pytest.mark.asyncio
async def test_successful_provider_probe_write_clears_only_its_degradation():
    monitor = _monitor()
    monitor._memory = None
    monitor._mark_observation_persistence_degraded("provider_probe", "probe failed")
    monitor._mark_observation_persistence_degraded("market_observation", "market failed")
    monitor._sessions = _healthy_sessions

    await monitor._record_probe({
        "provider": "dexscreener",
        "at": "2026-01-01T00:00:00+00:00",
        "status": "OK",
        "ok": True,
    })

    assert monitor.observation_persistence_degraded == {
        "market_observation": "market failed"
    }


@pytest.mark.asyncio
async def test_intelligence_decision_failure_marks_observation_degraded():
    monitor = _monitor()
    monitor._memory = None
    inv = type("Investigation", (), {
        "mint": "mint-a", "pipeline_status": "WATCH", "has_intelligence": True,
        "promote": False, "score": None, "synthetic": None, "rug": None,
        "model_version": "test",
    })()

    await monitor._persist_intelligence_decision(
        inv, _market_tick_snap(), alert_ok=False, alert_reason="TEST"
    )

    state = monitor.observation_persistence_degraded
    assert "intelligence_decision" in state
    assert "database unavailable" in state["intelligence_decision"]


@pytest.mark.asyncio
async def test_successful_intelligence_decision_clears_only_its_degradation():
    monitor = _monitor()
    monitor._memory = None
    monitor._mark_observation_persistence_degraded("intelligence_decision", "decision failed")
    monitor._mark_observation_persistence_degraded("provider_probe", "probe failed")
    monitor._sessions = _healthy_sessions
    inv = type("Investigation", (), {
        "mint": "mint-a", "pipeline_status": "WATCH", "has_intelligence": True,
        "promote": False, "score": None, "synthetic": None, "rug": None,
        "model_version": "test",
    })()

    await monitor._persist_intelligence_decision(
        inv, _market_tick_snap(), alert_ok=False, alert_reason="TEST"
    )

    assert monitor.observation_persistence_degraded == {
        "provider_probe": "probe failed"
    }


@pytest.mark.asyncio
async def test_market_inspection_failure_marks_observation_degraded():
    monitor = _monitor()

    await monitor._persist_inspection({"mint": "mint-a"})

    state = monitor.observation_persistence_degraded
    assert "market_inspection" in state
    assert "database unavailable" in state["market_inspection"]


@pytest.mark.asyncio
async def test_successful_market_inspection_clears_only_its_degradation():
    monitor = _monitor()
    monitor._mark_observation_persistence_degraded("market_inspection", "inspection failed")
    monitor._mark_observation_persistence_degraded("intelligence_decision", "decision failed")
    monitor._sessions = _healthy_sessions

    await monitor._persist_inspection({"mint": "mint-a"})

    assert monitor.observation_persistence_degraded == {
        "intelligence_decision": "decision failed"
    }


def test_watch_completion_is_blocked_by_market_observation_degradation():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index('logger.info(\n                "volume.watch_timeout"')
    end = source.index("        except Exception as exc:", start)
    block = source[start:end]

    assert 'completion_blockers' in block
    assert '"market_observation"' in block
    assert 'blocker = next(' in block
    assert 'status="FAILED"' in block
    assert 'stop_reason=f"PERSISTENCE_ERROR:{blocker}"' in block
    assert block.index('completion_blockers') < block.index('status="COMPLETED"')


def test_watch_completion_keeps_completed_path_when_market_observation_is_healthy():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index('logger.info(\n                "volume.watch_timeout"')
    end = source.index("        except Exception as exc:", start)
    block = source[start:end]

    assert "else:" in block
    assert 'status="COMPLETED"' in block
    assert 'kind="watch_complete"' in block


@pytest.mark.asyncio
async def test_failed_market_observation_is_not_published_to_memory():
    from stinky_core.memory import IntelligenceMemory

    monitor = _monitor()
    monitor._memory = IntelligenceMemory()
    migration = type("Migration", (), {"mint": "mint-a"})()

    await monitor._record_market_snapshot(migration, _market_tick_snap())

    assert [tick for tick in monitor._memory.market_ticks if tick.mint == "mint-a"] == []
    assert "market_observation" in monitor.observation_persistence_degraded


@pytest.mark.asyncio
async def test_successful_market_observation_is_published_after_commit():
    from stinky_core.memory import IntelligenceMemory

    monitor = _monitor()
    monitor._memory = IntelligenceMemory()
    monitor._sessions = _healthy_sessions
    migration = type("Migration", (), {"mint": "mint-a"})()

    await monitor._record_market_snapshot(migration, _market_tick_snap())

    ticks = [tick for tick in monitor._memory.market_ticks if tick.mint == "mint-a"]
    assert len(ticks) == 1
    assert ticks[0].pair_address == "pair-a"


@pytest.mark.asyncio
async def test_failed_intelligence_decision_is_not_published_to_memory():
    from stinky_core.memory import IntelligenceMemory

    monitor = _monitor()
    monitor._memory = IntelligenceMemory()
    inv = type("Investigation", (), {
        "mint": "mint-a", "pipeline_status": "WATCH", "has_intelligence": True,
        "promote": False, "score": None, "synthetic": None, "rug": None,
        "model_version": "test",
    })()

    await monitor._persist_intelligence_decision(
        inv, _market_tick_snap(), alert_ok=False, alert_reason="TEST"
    )

    assert monitor._memory.decisions == []
    assert "intelligence_decision" in monitor.observation_persistence_degraded


@pytest.mark.asyncio
async def test_successful_intelligence_decision_is_published_after_commit():
    from stinky_core.memory import IntelligenceMemory

    monitor = _monitor()
    monitor._memory = IntelligenceMemory()
    monitor._sessions = _healthy_sessions
    inv = type("Investigation", (), {
        "mint": "mint-a", "pipeline_status": "WATCH", "has_intelligence": True,
        "promote": False, "score": None, "synthetic": None, "rug": None,
        "model_version": "test",
    })()

    await monitor._persist_intelligence_decision(
        inv, _market_tick_snap(), alert_ok=False, alert_reason="TEST"
    )

    assert len(monitor._memory.decisions) == 1
    assert monitor._memory.decisions[0]["mint"] == "mint-a"


def test_watch_completion_is_blocked_by_investigation_memory_degradation():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index('logger.info(\n                "volume.watch_timeout"')
    end = source.index("        except Exception as exc:", start)
    block = source[start:end]

    assert '"investigation_memory"' in block
    assert 'completion_blockers' in block
    assert 'status="FAILED"' in block
    assert 'stop_reason=f"PERSISTENCE_ERROR:{blocker}"' in block
    assert block.index('completion_blockers') < block.index('status="COMPLETED"')


def test_watch_completion_blockers_cover_both_restart_critical_market_paths():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index('logger.info(\n                "volume.watch_timeout"')
    end = source.index("        except Exception as exc:", start)
    block = source[start:end]

    assert '"market_observation"' in block
    assert '"investigation_memory"' in block


def test_investigation_memory_is_published_only_after_durable_commit():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def _persist_memory_decision(")
    end = source.index("    async def _persist_depth_observation(", start)
    block = source[start:end]

    commit = block.index("await session.commit()")
    publish_decision = block.index("mem.ingest_decision(")
    publish_investigation = block.index("mem.record_investigation(")
    publish_market = block.index("mem.record_market_tick(")

    assert commit < publish_decision
    assert commit < publish_investigation
    assert commit < publish_market


def test_investigation_path_does_not_publish_memory_before_persist_helper():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def _investigate_and_maybe_alert(")
    block = source[start:]

    persist = block.index("await self._persist_memory_decision(")
    before_persist = block[:persist]
    assert "mem.ingest_decision(" not in before_persist
    assert "mem.record_investigation(" not in before_persist
    assert "mem.record_market_tick(" not in before_persist


def test_restart_hydrates_watch_states_and_skips_terminal_watches():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")

    hydrate_start = source.index("    async def _hydrate_memory(")
    hydrate_end = source.index("    async def _persist_memory_decision(", hydrate_start)
    hydrate = source[hydrate_start:hydrate_end]
    assert "MEMORY_SELECT_WATCH_STATE" in hydrate
    assert '"watch_states": [dict(r) for r in watches]' in hydrate

    resume_start = source.index("    async def _resume_open_watches(")
    resume_end = source.index("    def _track_background_task(", resume_start)
    resume = source[resume_start:resume_end]
    assert 'terminal_statuses = {"COMPLETED", "FAILED"}' in resume
    assert "if watch_state is None:" in resume
    assert 'if str(watch_state.get("status") or "").upper() in terminal_statuses:' in resume


def test_restart_fails_nonterminal_watch_when_investigation_evidence_is_missing():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def _resume_open_watches(")
    end = source.index("    def _track_background_task(", start)
    block = source[start:end]

    assert 'status not in {"DETECTED", "WATCHING"}' in block
    assert 'status="FAILED"' in block
    assert 'stop_reason="PERSISTENCE_ERROR:restart_investigation_missing"' in block
    assert "mint in investigation_mints" in block


def test_watch_state_is_published_only_after_durable_commit():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def _upsert_watch(")
    end = source.index("    async def _record_probe(", start)
    block = source[start:end]

    session_start = block.index("async with self._sessions() as session:")
    commit = block.index("await session.commit()", session_start)
    success_publish = block.index("mem.record_watch_state(rec)", commit)
    assert commit < success_publish


def test_watch_state_no_session_is_explicitly_degraded():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index("    async def _upsert_watch(")
    end = source.index("    async def _record_probe(", start)
    block = source[start:end]

    no_session = block.index("if not self._sessions:")
    degraded = block.index('_mark_observation_persistence_degraded("watch_state", "NO_SESSION")', no_session)
    assert no_session < degraded


def test_watch_completion_is_blocked_by_watch_state_degradation():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "src" / "sentinel" / "volume.py"
    ).read_text(encoding="utf-8")
    start = source.index("            completion_blockers = (")
    end = source.index("        except Exception as exc:", start)
    block = source[start:end]

    assert '"watch_state"' in block
    assert 'stop_reason=f"PERSISTENCE_ERROR:{blocker}"' in block
    assert block.index('"watch_state"') < block.index('status="COMPLETED"')
