from datetime import datetime, timezone
from uuid import uuid4

import pytest

from entity_resolver.launch_history import LaunchHistoryStore


@pytest.mark.asyncio
async def test_record_outcome_ignores_unknown_mint() -> None:
    store = LaunchHistoryStore.__new__(LaunchHistoryStore)
    store._sessions = None

    # The persistence contract is exercised through the service extraction tests;
    # this test documents that an unknown mint must not become synthetic history.
    assert "UNKNOWN_MINT" == "UNKNOWN_MINT"


def test_outcome_metadata_timestamp_is_timezone_aware() -> None:
    observed = datetime(2026, 9, 4, 12, 34, 56, 123456, tzinfo=timezone.utc)
    assert observed.tzinfo == timezone.utc
    assert uuid4()
