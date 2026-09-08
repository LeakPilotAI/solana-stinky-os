from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from entity_resolver.durable_outcome_reconciliation import DurableOutcomeReconciler


def _row(*, outcome_status=None):
    return {
        "track_id": UUID("00000000-0000-0000-0000-000000000777"),
        "mint": "MintDurableOutcome",
        "migration_at": datetime(2026, 9, 7, 12, 30, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 9, 7, 13, 30, tzinfo=timezone.utc),
        "buyers_captured": 7,
        "trades_observed": 19,
        "snapshots_taken": 12,
        "entity_id": UUID("00000000-0000-0000-0000-000000000321"),
        "outcome_status": outcome_status,
    }


def _unknown_classification():
    return {"label": "UNKNOWN", "reason": "insufficient_measured_price_path", "evidence_only": True}


def test_completion_metadata_is_stable_durable_evidence():
    metadata = DurableOutcomeReconciler._completion_metadata(_row())
    assert metadata == {
        "evidence_basis": "durable_migration_track_completion",
        "track_id": "00000000-0000-0000-0000-000000000777",
        "completed_at": "2026-09-07T13:30:00+00:00",
        "buyers_captured": 7,
        "trades_observed": 19,
        "snapshots_taken": 12,
    }


@pytest.mark.asyncio
async def test_missing_stream_outcome_is_recovered_then_captured():
    reconciler = DurableOutcomeReconciler.__new__(DurableOutcomeReconciler)
    reconciler._launch_history = SimpleNamespace(record_outcome=AsyncMock(return_value=True))
    reconciler._capture = AsyncMock(return_value=True)
    reconciler._classified_outcome = AsyncMock(return_value=_unknown_classification())

    assert await reconciler._reconcile_candidate(_row()) is True

    reconciler._launch_history.record_outcome.assert_awaited_once()
    call = reconciler._launch_history.record_outcome.await_args.kwargs
    assert call["mint"] == "MintDurableOutcome"
    assert call["status"] == "completed"
    assert call["observed_at"] == datetime(2026, 9, 7, 13, 30, tzinfo=timezone.utc)
    assert call["metadata"]["evidence_basis"] == "durable_migration_track_completion"
    assert call["metadata"]["performance_outcome"] == "UNKNOWN"
    reconciler._capture.assert_awaited_once_with(
        "MintDurableOutcome", "00000000-0000-0000-0000-000000000321"
    )


@pytest.mark.asyncio
async def test_completed_track_is_promoted_to_measured_runner_before_capture():
    reconciler = DurableOutcomeReconciler.__new__(DurableOutcomeReconciler)
    reconciler._launch_history = SimpleNamespace(record_outcome=AsyncMock(return_value=True))
    reconciler._capture = AsyncMock(return_value=True)
    reconciler._classified_outcome = AsyncMock(
        return_value={
            "label": "RUNNER",
            "reason": "peak_multiple_met",
            "label_version": "outcome-v1.1.0",
            "peak_multiple": 2.4,
            "evidence_basis": "completed_market_snapshot_path",
            "evidence_only": True,
        }
    )

    assert await reconciler._reconcile_candidate(_row(outcome_status="completed")) is True

    reconciler._launch_history.record_outcome.assert_awaited_once()
    call = reconciler._launch_history.record_outcome.await_args.kwargs
    assert call["status"] == "RUNNER"
    assert call["observed_at"] == datetime(2026, 9, 7, 13, 30, tzinfo=timezone.utc)
    assert call["metadata"]["evidence_basis"] == "durable_completed_market_path_classification"
    assert call["metadata"]["classification"]["label"] == "RUNNER"
    reconciler._capture.assert_awaited_once()


@pytest.mark.asyncio
async def test_already_recorded_completion_with_unknown_path_retries_capture_without_rewriting():
    reconciler = DurableOutcomeReconciler.__new__(DurableOutcomeReconciler)
    reconciler._launch_history = SimpleNamespace(record_outcome=AsyncMock())
    reconciler._capture = AsyncMock(return_value=True)
    reconciler._classified_outcome = AsyncMock(return_value=_unknown_classification())

    assert await reconciler._reconcile_candidate(_row(outcome_status="completed")) is True

    reconciler._launch_history.record_outcome.assert_not_awaited()
    reconciler._capture.assert_awaited_once()


@pytest.mark.asyncio
async def test_richer_outcome_is_never_downgraded_or_reclassified():
    reconciler = DurableOutcomeReconciler.__new__(DurableOutcomeReconciler)
    reconciler._launch_history = SimpleNamespace(record_outcome=AsyncMock())
    reconciler._capture = AsyncMock()
    reconciler._classified_outcome = AsyncMock()

    assert await reconciler._reconcile_candidate(_row(outcome_status="RUNNER")) is False

    reconciler._classified_outcome.assert_not_awaited()
    reconciler._launch_history.record_outcome.assert_not_awaited()
    reconciler._capture.assert_not_awaited()
