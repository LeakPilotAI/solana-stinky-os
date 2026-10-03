from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from post_migration.models import TrackStatus
from post_migration.tracker import MintTracker, _is_transient_database_disconnect


def _tracker(store):
    return MintTracker(
        store=store,
        publisher=AsyncMock(),
        chain=AsyncMock(),
        mint="DisconnectMint111111111111111111111111111111",
        pool="Pool111111111111111111111111111111111111",
        creator=None,
        destination=None,
        migration_signature="sig",
        migration_slot=1,
        migration_at=datetime.now(timezone.utc),
        payload={},
    )


def test_windows_connection_reset_is_transient_but_logic_errors_are_not():
    reset = ConnectionResetError(64, "The specified network name is no longer available")
    assert _is_transient_database_disconnect(reset) is True
    assert _is_transient_database_disconnect(ValueError("bad evidence")) is False


@pytest.mark.asyncio
async def test_transient_database_disconnect_leaves_track_active_for_bounded_backfill():
    store = AsyncMock()
    store.start_track.return_value = uuid4()
    store.get_track_status.return_value = TrackStatus.ACTIVE
    store.load_early_buyer_event_keys.side_effect = ConnectionResetError(
        64, "The specified network name is no longer available"
    )

    await _tracker(store).run()

    store.complete_track.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_database_failure_still_fails_track_closed():
    store = AsyncMock()
    store.start_track.return_value = uuid4()
    store.get_track_status.return_value = TrackStatus.ACTIVE
    store.load_early_buyer_event_keys.side_effect = ValueError("bad evidence")

    await _tracker(store).run()

    store.complete_track.assert_awaited_once_with(
        "DisconnectMint111111111111111111111111111111",
        status=TrackStatus.FAILED,
    )
