import asyncio
from unittest.mock import Mock

import pytest

from post_migration import service as module


def collector():
    instance = object.__new__(module.CollectorService)
    instance._active_tracks = set()
    instance._tasks = set()
    instance._store = Mock()
    instance._publisher = Mock()
    instance._chain = Mock()
    return instance


def test_batch_reserves_capacity_and_rejects_duplicates_before_tasks_start(monkeypatch):
    instance = collector()
    monkeypatch.setattr(module.settings, "max_concurrent_tracks", 1)

    async def scenario():
        release = asyncio.Event()
        monkeypatch.setattr(module, "MintTracker", Mock(return_value=Mock(run=release.wait)))
        accepted = [await instance.track_mint("mint-a"), await instance.track_mint("mint-a"), await instance.track_mint("mint-b")]
        tasks = list(instance._tasks)
        release.set()
        await asyncio.gather(*tasks)
        assert accepted == [True, False, False]
        assert not instance._active_tracks
        assert not instance._tasks
        assert await instance.track_mint("mint-b") is True
        await asyncio.gather(*instance._tasks)

    asyncio.run(scenario())


@pytest.mark.parametrize("finish", ["cancel_before_start", "cancel_running", "error", "success"])
def test_tracking_slot_released_on_every_task_exit(monkeypatch, finish):
    instance = collector()
    monkeypatch.setattr(module.settings, "max_concurrent_tracks", 1)

    async def scenario():
        release = asyncio.Event()

        async def run():
            if finish == "error":
                raise RuntimeError("synthetic tracker failure")
            if finish == "success":
                return
            await release.wait()

        monkeypatch.setattr(module, "MintTracker", Mock(return_value=Mock(run=run)))
        assert await instance.track_mint("mint-a")
        assert instance._active_tracks == {"mint-a"}
        task = next(iter(instance._tasks))
        if finish == "cancel_running":
            await asyncio.sleep(0)
        if finish.startswith("cancel"):
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert instance._active_tracks == set()
        assert instance._tasks == set()

    asyncio.run(scenario())


def test_task_creation_failure_releases_reservation(monkeypatch):
    instance = collector()

    async def run():
        pass

    coroutine = run()
    monkeypatch.setattr(module, "MintTracker", Mock(return_value=Mock(run=lambda: coroutine)))
    monkeypatch.setattr(module.asyncio, "create_task", Mock(side_effect=RuntimeError("synthetic scheduling failure")))
    with pytest.raises(RuntimeError, match="synthetic scheduling failure"):
        asyncio.run(instance.track_mint("mint-a"))
    assert not instance._active_tracks
    assert not instance._tasks
    assert coroutine.cr_frame is None
