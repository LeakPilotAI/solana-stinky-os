from datetime import datetime, timedelta, timezone

import pytest

from stinky_api.evm_reference_observation_trigger import (
    ReferenceDexObservationSchedule,
    reference_observation_is_due,
)


def test_reference_observation_schedule_due_boundary():
    now = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
    schedule = ReferenceDexObservationSchedule(interval_seconds=300)
    assert reference_observation_is_due(schedule, now=now, last_completed_at=None)
    assert not reference_observation_is_due(
        schedule, now=now, last_completed_at=now - timedelta(seconds=299)
    )
    assert reference_observation_is_due(
        schedule, now=now, last_completed_at=now - timedelta(seconds=300)
    )


def test_reference_observation_schedule_validation_and_disable():
    with pytest.raises(ValueError):
        ReferenceDexObservationSchedule(interval_seconds=59)
    now = datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc)
    schedule = ReferenceDexObservationSchedule(interval_seconds=60, enabled=False)
    assert not reference_observation_is_due(schedule, now=now, last_completed_at=None)
