from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from post_migration.tracker import _completion_coverage_evidence


ROOT = Path(__file__).resolve().parents[3]


def test_completion_coverage_accepts_full_measured_hour():
    migration = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    result = _completion_coverage_evidence(
        migration_at=migration,
        coverage={
            "valid_price_snapshot_count": 58,
            "first_snapshot_at": migration + timedelta(seconds=30),
            "final_snapshot_at": migration + timedelta(seconds=3545),
        },
        required_window_sec=3600.0,
    )
    assert result["complete"] is True
    assert result["required_final_snapshot_coverage_sec"] == 3480.0


def test_completion_coverage_rejects_wall_clock_completion_with_short_path():
    migration = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    result = _completion_coverage_evidence(
        migration_at=migration,
        coverage={
            "valid_price_snapshot_count": 23,
            "first_snapshot_at": migration + timedelta(seconds=30.435314),
            "final_snapshot_at": migration + timedelta(seconds=260.525977),
        },
        required_window_sec=3600.0,
    )
    assert result["complete"] is False
    assert result["final_snapshot_coverage_sec"] == 260.525977


def test_completion_coverage_rejects_late_first_snapshot_and_too_few_points():
    migration = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    late = _completion_coverage_evidence(
        migration_at=migration,
        coverage={
            "valid_price_snapshot_count": 60,
            "first_snapshot_at": migration + timedelta(seconds=121),
            "final_snapshot_at": migration + timedelta(seconds=3590),
        },
        required_window_sec=3600.0,
    )
    sparse = _completion_coverage_evidence(
        migration_at=migration,
        coverage={
            "valid_price_snapshot_count": 1,
            "first_snapshot_at": migration + timedelta(seconds=30),
            "final_snapshot_at": migration + timedelta(seconds=3590),
        },
        required_window_sec=3600.0,
    )
    assert late["complete"] is False
    assert sparse["complete"] is False


def test_tracker_checks_persisted_coverage_before_completed_status():
    source = (
        ROOT
        / "services/post-migration-collector/src/post_migration/tracker.py"
    ).read_text(encoding="utf-8")
    coverage_call = source.index("market_snapshot_coverage(")
    failed_call = source.index("fail_track_for_incomplete_market_path(", coverage_call)
    completed_call = source.index(
        "complete_track(self.mint, status=TrackStatus.COMPLETED)", coverage_call
    )
    assert coverage_call < failed_call < completed_call
    assert 'metrics.inc("tracks_failed_incomplete_market_path")' in source


def test_store_failure_reason_is_explicit_and_completion_not_manufactured():
    source = (
        ROOT
        / "services/post-migration-collector/src/post_migration/store.py"
    ).read_text(encoding="utf-8")
    start = source.index("async def fail_track_for_incomplete_market_path")
    end = source.index("async def complete_track", start)
    block = source[start:end]
    assert "incomplete_measured_market_path" in block
    assert "completed_at = NULL" in block
    assert "status = 'failed'" in block
