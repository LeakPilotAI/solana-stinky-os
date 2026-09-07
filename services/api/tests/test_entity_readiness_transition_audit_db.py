from datetime import datetime, timezone

import pytest

import stinky_api.entity_readiness_transition_audit as mod


class FakeSession:
    def __init__(self):
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self):
        self.commit_count += 1

    async def rollback(self):
        self.rollback_count += 1


def _readiness():
    return {
        "status": "NOT_READY_FOR_DESCRIPTIVE_CALIBRATION",
        "ready": False,
        "blockers": ["DEVELOPER_HISTORY_NOT_STABLE"],
        "components": {},
        "temporal_integrity": {},
        "evidence_independence": {},
        "calibration_scope": "ENTITY_INTELLIGENCE_DESCRIPTIVE_ONLY",
    }


@pytest.mark.asyncio
async def test_persist_commits_after_success(monkeypatch):
    calls = []

    async def fake_insert(session, *, entity_id, digest, readiness_json, observed_at, ingested_at):
        calls.append((entity_id, digest, observed_at, ingested_at))

    monkeypatch.setattr(mod, "_insert_snapshot", fake_insert)
    session = FakeSession()
    capture_ts = datetime(2026, 9, 1, tzinfo=timezone.utc)
    digest = await mod.persist_entity_readiness_snapshot(
        session,
        "11111111-1111-1111-1111-111111111111",
        _readiness(),
        observed_at=capture_ts,
    )
    assert calls
    assert calls[0][2] == capture_ts
    assert calls[0][3] == capture_ts
    assert session.commit_count == 1
    assert session.rollback_count == 0
    assert digest == mod.entity_readiness_hash(_readiness())


@pytest.mark.asyncio
async def test_persist_recovers_once_from_aborted_transaction(monkeypatch):
    attempts = 0
    timestamps = []

    async def flaky_insert(session, *, entity_id, digest, readiness_json, observed_at, ingested_at):
        nonlocal attempts
        attempts += 1
        timestamps.append((observed_at, ingested_at))
        if attempts == 1:
            raise RuntimeError("transaction aborted")

    monkeypatch.setattr(mod, "_insert_snapshot", flaky_insert)
    session = FakeSession()
    await mod.persist_entity_readiness_snapshot(session, "11111111-1111-1111-1111-111111111111", _readiness())
    assert attempts == 2
    assert timestamps[0][0] == timestamps[0][1]
    assert timestamps[1] == timestamps[0]
    assert session.rollback_count == 1
    assert session.commit_count == 1


def test_insert_explicitly_writes_ingested_timestamp():
    import inspect

    source = inspect.getsource(mod._insert_snapshot)
    assert "observed_at, ingested_at" in source
    assert ":observed_at, :ingested_at" in source


@pytest.mark.asyncio
async def test_naive_explicit_capture_timestamp_is_normalized_to_utc(monkeypatch):
    captured = []

    async def fake_insert(session, *, entity_id, digest, readiness_json, observed_at, ingested_at):
        captured.append((observed_at, ingested_at))

    monkeypatch.setattr(mod, "_insert_snapshot", fake_insert)
    session = FakeSession()
    naive = datetime(2026, 9, 1, 12, 30, 0)
    await mod.persist_entity_readiness_snapshot(
        session,
        "11111111-1111-1111-1111-111111111111",
        _readiness(),
        observed_at=naive,
    )
    observed, ingested = captured[0]
    assert observed.tzinfo == timezone.utc
    assert ingested == observed
