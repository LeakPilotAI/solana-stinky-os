from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from entity_resolver.launch_history import LaunchHistoryStore


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return self._row or []


class _Session:
    def __init__(self, row):
        self.row = row
        self.committed = False
        self.rolled_back = False
        self.params = None
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        self.params = params
        self.calls.append((str(statement), params))
        return _Result(self.row)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class _Sessions:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


@pytest.mark.asyncio
async def test_record_outcome_updates_known_launch() -> None:
    session = _Session((123,))
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    observed = datetime(2026, 9, 4, 12, 34, 56, 123456, tzinfo=timezone.utc)
    result = await store.record_outcome(
        mint="MINT",
        status="completed",
        metadata={"peak_multiple": 3.2},
        observed_at=observed,
    )

    assert result is True
    assert session.committed is True
    assert session.rolled_back is False
    assert session.params["mint"] == "MINT"
    assert session.params["status"] == "completed"
    assert "2026-09-04T12:34:56.123456+00:00" in session.params["metadata"]


@pytest.mark.asyncio
async def test_record_outcome_does_not_create_unknown_history() -> None:
    session = _Session(None)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    result = await store.record_outcome(mint="UNKNOWN", status="completed")

    assert result is False
    assert session.committed is False
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_list_deployer_launches_returns_history_and_bounds_limit() -> None:
    rows = [
        {
            "id": 1,
            "mint": "MINT1",
            "outcome_status": "completed",
            "outcome_meta": {"peak_multiple": 2.0},
        }
    ]
    session = _Session(rows)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    result = await store.list_deployer_launches(
        deployer_wallet="DEPLOYER",
        limit=9999,
    )

    assert result == rows
    assert session.params == {"wallet": "DEPLOYER", "limit": 500}


@pytest.mark.asyncio
async def test_list_entity_launches_uses_entity_id_and_default_limit() -> None:
    rows = [{"id": 7, "mint": "MINT7", "outcome_status": None}]
    session = _Session(rows)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)
    entity_id = uuid4()

    result = await store.list_entity_launches(entity_id=entity_id)

    assert result == rows
    assert session.params == {"eid": entity_id, "limit": 100}


@pytest.mark.asyncio
async def test_deployer_history_summary_returns_evidence_counts() -> None:
    row = {
        "launch_count": 6,
        "outcomes_known": 4,
        "completed_count": 4,
        "outcomes_unknown": 2,
        "first_launch_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_launch_at": datetime(2026, 9, 4, tzinfo=timezone.utc),
    }
    session = _Session(row)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    result = await store.get_deployer_history_summary(deployer_wallet="DEPLOYER")

    assert result == {"deployer_wallet": "DEPLOYER", **row}
    assert session.params == {"wallet": "DEPLOYER"}


@pytest.mark.asyncio
async def test_measured_outcome_projects_existing_reputation_memberships_atomically() -> None:
    session = _Session((123,))
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)
    observed = datetime(2026, 9, 7, 13, 30, tzinfo=timezone.utc)

    result = await store.record_outcome(
        mint="MINT",
        status="RUNNER",
        metadata={"classification": {"label_version": "outcome-v1.1.0"}},
        observed_at=observed,
    )

    assert result is True
    sql = "\n".join(statement for statement, _ in session.calls)
    assert "INSERT INTO wallet_outcome_labels" in sql
    assert "FROM wallet_observations" in sql
    assert "INSERT INTO creator_outcome_labels" in sql
    assert "FROM creator_observations" in sql
    assert "INSERT INTO pattern_outcomes" in sql
    assert "FROM pattern_fingerprints" in sql
    projected = [params for statement, params in session.calls if "outcome_labels" in statement or "pattern_outcomes" in statement]
    assert len(projected) == 4
    assert any("INSERT INTO entity_launch_outcome_labels" in statement for statement, _ in session.calls)
    assert all(params["label"] == "RUNNER" for params in projected)
    projection_params = [params for statement, params in session.calls if "wallet_outcome_labels" in statement or "creator_outcome_labels" in statement or "pattern_outcomes" in statement]
    ledger_params = [params for statement, params in session.calls if "entity_launch_outcome_labels" in statement]
    assert all(params["labeled_at"] == observed for params in projection_params)
    assert all(params["observed_at"] == observed for params in ledger_params)
    assert all(params["label_version"] == "outcome-v1.1.0" for params in projected)
    assert session.committed is True


@pytest.mark.asyncio
async def test_generic_completion_does_not_project_performance_labels() -> None:
    session = _Session((123,))
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    result = await store.record_outcome(
        mint="MINT",
        status="completed",
        metadata={"performance_outcome": "UNKNOWN"},
    )

    assert result is True
    sql = "\n".join(statement for statement, _ in session.calls)
    assert "wallet_outcome_labels" not in sql
    assert "creator_outcome_labels" not in sql
    assert "pattern_outcomes" not in sql
    assert session.committed is True


@pytest.mark.asyncio
async def test_reputation_projection_schema_contract_accepts_complete_schema() -> None:
    required = [
        "wallet_observations",
        "wallet_outcome_labels",
        "creator_observations",
        "creator_outcome_labels",
        "pattern_fingerprints",
        "pattern_outcomes",
    ]
    session = _Session(required)
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    await store.ensure_reputation_projection_schema()

    assert sorted(session.params["required"]) == sorted(required)


@pytest.mark.asyncio
async def test_reputation_projection_schema_contract_fails_closed_when_missing() -> None:
    session = _Session(["wallet_observations", "wallet_outcome_labels"])
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = _Sessions(session)

    with pytest.raises(RuntimeError) as excinfo:
        await store.ensure_reputation_projection_schema()

    message = str(excinfo.value)
    assert "Sentinel intelligence-memory migration 006" in message
    assert "creator_observations" in message
    assert "pattern_outcomes" in message


def test_migration_reuses_existing_launch_identity_instead_of_second_launch():
    from pathlib import Path

    src = Path(__file__).parents[1] / "src" / "entity_resolver"
    service = (src / "service.py").read_text(encoding="utf-8")
    history = (src / "launch_history.py").read_text(encoding="utf-8")

    assert "get_launch_identity_for_mint" in history
    assert "existing_launch = (" in service
    assert 'entity_id = existing_launch["entity_id"]' in service
    assert "migration_creator_disagrees_with_launch" in service
    migration = service[service.index('elif et == "token.migrated"'):service.index('elif et == "post_migration.buy"')]
    assert migration.index("if existing_launch:") < migration.index("record_launch(")


def test_measured_outcomes_write_dual_time_immutable_ledger():
    source = (
        Path(__file__).parents[1] / "src" / "entity_resolver" / "launch_history.py"
    ).read_text(encoding="utf-8")
    migration = (
        Path(__file__).parents[1] / "migrations" / "011_entity_launch_outcome_labels.sql"
    ).read_text(encoding="utf-8")

    assert "INSERT INTO entity_launch_outcome_labels" in source
    assert 'if measured_status in {"RUNNER", "HELD", "FADE"}' in source
    assert "ON CONFLICT (mint, label_version) DO NOTHING" in source
    assert "observed_at TIMESTAMPTZ NOT NULL" in migration
    assert "ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()" in migration
    assert "UNIQUE (mint, label_version)" in migration
