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

    async def fake_insert(session, *, entity_id, digest, readiness_json, observed_at):
        calls.append((entity_id, digest, observed_at))

    monkeypatch.setattr(mod, "_insert_snapshot", fake_insert)
    session = FakeSession()
    digest = await mod.persist_entity_readiness_snapshot(
        session,
        "11111111-1111-1111-1111-111111111111",
        _readiness(),
        observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    assert calls
    assert session.commit_count == 1
    assert session.rollback_count == 0
    assert digest == mod.entity_readiness_hash(_readiness())


@pytest.mark.asyncio
async def test_persist_recovers_once_from_aborted_transaction(monkeypatch):
    attempts = 0

    async def flaky_insert(session, *, entity_id, digest, readiness_json, observed_at):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transaction aborted")

    monkeypatch.setattr(mod, "_insert_snapshot", flaky_insert)
    session = FakeSession()
    await mod.persist_entity_readiness_snapshot(session, "11111111-1111-1111-1111-111111111111", _readiness())
    assert attempts == 2
    assert session.rollback_count == 1
    assert session.commit_count == 1
