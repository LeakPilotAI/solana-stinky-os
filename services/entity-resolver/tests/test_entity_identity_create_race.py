from uuid import UUID

import pytest

from entity_resolver.store import EntityStore


class _Result:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class _Session:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        if self.results:
            return _Result(self.results.pop(0))
        return _Result()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_entity_returns_existing_wallet_owner_when_unique_insert_loses_race():
    discarded = UUID("00000000-0000-0000-0000-000000000001")
    canonical = UUID("00000000-0000-0000-0000-000000000002")
    session = _Session([
        (discarded,),  # INSERT entities ... RETURNING entity_id
        None,          # wallet INSERT lost ON CONFLICT race
        (canonical,),  # canonical wallet owner lookup
        None,          # orphan entity cleanup
    ])
    store = EntityStore.__new__(EntityStore)
    store._sessions = lambda: _SessionContext(session)

    result = await store.create_entity(primary_wallet="SameWallet", entity_type="deployer")

    assert result == canonical
    assert session.commits == 1
    assert session.rollbacks == 0
    sql = "\n".join(call[0] for call in session.calls)
    assert "ON CONFLICT (wallet) DO NOTHING" in sql
    assert "RETURNING entity_id" in sql
    assert "SELECT entity_id FROM entity_wallets WHERE wallet" in sql
    assert "DELETE FROM entities" in sql
    assert "INSERT INTO entity_link_events" not in sql


@pytest.mark.asyncio
async def test_create_entity_rolls_back_if_wallet_conflict_has_no_canonical_owner():
    discarded = UUID("00000000-0000-0000-0000-000000000003")
    session = _Session([
        (discarded,),
        None,
        None,
    ])
    store = EntityStore.__new__(EntityStore)
    store._sessions = lambda: _SessionContext(session)

    with pytest.raises(RuntimeError, match="wallet entity conflict could not be resolved"):
        await store.create_entity(primary_wallet="UnresolvedWallet", entity_type="deployer")

    assert session.rollbacks == 1
    assert session.commits == 0
