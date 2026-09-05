from uuid import uuid4

import pytest

from entity_resolver.behavior import BehaviorFingerprintStore


class _Result:
    def first(self):
        return None

    def mappings(self):
        return self

    def all(self):
        return []


class _Session:
    def __init__(self):
        self.calls = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        self.calls.append(params)
        if len(self.calls) == 1:
            return _Result()
        return _Result()

    async def commit(self):
        self.committed = True


class _Sessions:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


@pytest.mark.asyncio
async def test_refresh_entity_persists_fingerprint() -> None:
    session = _Session()
    store = BehaviorFingerprintStore.__new__(BehaviorFingerprintStore)
    store._sessions = _Sessions(session)

    async def fake_launches(_entity_id):
        return [
            {"observed_at": "2026-09-01T00:00:00+00:00", "outcome_status": "completed"},
            {"observed_at": "2026-09-01T01:00:00+00:00", "outcome_status": None},
        ]

    store._launches_for_entity = fake_launches
    entity_id = uuid4()

    result = await store.refresh_entity(entity_id)

    assert result["launch_count"] == 2
    assert result["outcomes_unknown"] == 1
    assert result["cadence_bucket"] == "high_frequency"
    assert session.committed is True
    persisted = session.calls[-1]
    assert persisted["eid"] == entity_id
    assert persisted["launch_count"] == 2
    assert persisted["outcomes_known"] == 1
    assert persisted["completed_count"] == 1
    assert persisted["outcomes_unknown"] == 1
    assert '"evidence_basis":"entity_launches+entity_wallets+early_buyer_observations"' in persisted["fingerprint"]
