from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import stinky_api.historical_evidence_reconstruction as module


class BrokenSession:
    async def execute(self, *_args, **_kwargs):
        raise ConnectionRefusedError("offline")


@pytest.mark.asyncio
async def test_historical_reconstruction_audit_fails_closed_when_database_is_unavailable():
    result = await module.historical_reconstruction_audit(BrokenSession())

    assert result["status"] == "UNKNOWN"
    assert result["failure_stage"] == "table_preflight"
    assert result["error_type"] == "ConnectionRefusedError"
    assert result["historical_developer_snapshot_reconstruction_authorized"] is False
    assert result["historical_correlation_snapshot_reconstruction_authorized"] is False
    assert result["predictive_authority"] is False
    assert result["trade_signal"] is False
    assert result["evidence_only"] is True


class InitSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


@pytest.mark.asyncio
async def test_snapshot_memory_initialization_creates_schema_only(monkeypatch):
    session = InitSession()
    developer = AsyncMock()
    correlation = AsyncMock()
    monkeypatch.setattr(module, "ensure_developer_audit_table", developer)
    monkeypatch.setattr(module, "ensure_developer_correlation_audit_table", correlation)

    result = await module.initialize_phase10_snapshot_memory(session)

    developer.assert_awaited_once_with(session)
    correlation.assert_awaited_once_with(session)
    session.commit.assert_awaited_once()
    assert result["status"] == "INITIALIZED"
    assert result["historical_rows_inserted"] == 0
    assert result["historical_developer_snapshot_reconstruction_authorized"] is False
    assert result["historical_correlation_snapshot_reconstruction_authorized"] is False


@pytest.mark.asyncio
async def test_launch_recovery_stays_blocked_when_audit_is_not_observed(monkeypatch):
    session = InitSession()
    monkeypatch.setattr(
        module,
        "historical_reconstruction_audit",
        AsyncMock(return_value={"status": "BLOCKED", "reason": "missing"}),
    )

    result = await module.recover_direct_migration_launches(session, limit=500)

    assert result["status"] == "BLOCKED"
    assert result["inserted_count"] == 0
    assert result["historical_developer_snapshot_reconstruction_authorized"] is False
    assert result["historical_correlation_snapshot_reconstruction_authorized"] is False
