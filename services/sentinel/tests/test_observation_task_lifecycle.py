import asyncio

import pytest

from sentinel.volume import VolumeMonitor


class _Closable:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _Disposable:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


@pytest.mark.asyncio
async def test_close_cancels_and_drains_owned_background_tasks():
    monitor = object.__new__(VolumeMonitor)
    monitor._background_tasks = set()
    monitor._client = _Closable()
    monitor._engine = _Disposable()

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = monitor._track_background_task(asyncio.create_task(blocked()))
    await asyncio.wait_for(started.wait(), timeout=0.2)

    await asyncio.wait_for(monitor.close(), timeout=0.2)

    assert task.done()
    assert task.cancelled()
    assert cancelled.is_set()
    assert monitor._background_tasks == set()
    assert monitor._client.closed
    assert monitor._engine.disposed


@pytest.mark.asyncio
async def test_completed_background_task_removes_itself_from_registry():
    monitor = object.__new__(VolumeMonitor)
    monitor._background_tasks = set()

    async def complete():
        return 1

    task = monitor._track_background_task(asyncio.create_task(complete()))
    assert task in monitor._background_tasks
    assert await task == 1
    await asyncio.sleep(0)
    assert task not in monitor._background_tasks
