"""Default-off actual worker ownership and completion; no forceful cancellation."""
import asyncio
from contextlib import asynccontextmanager
import re
from functools import wraps

from stinky_core.transport.redis_accounting import AccountingError


class WorkerClosure:
    def __init__(self, participant, expected):
        if (not expected or len(expected) > 32 or len(set(expected)) != len(expected) or
            any(not re.fullmatch('[a-z][a-z-]{1,60}', name) for name in expected) or
            participant.phase != 'RUNNING' or participant.jobs or
            (participant.owner['service']!='fixture' and participant.runtime.clients) or
            getattr(participant, 'worker_closure', None) is not None):
            raise AccountingError('Explicit complete worker manifest required before jobs')
        self.participant = participant
        self.expected = frozenset(expected)
        self.workers = {}
        self.fenced = False
        original = participant.stop_admission
        def fence():
            self.participant.verify()
            self.fenced = True
            if self.expected != self.workers.keys() or original() is not True:
                raise AccountingError('Missing or unknown worker; HOLD')
            for row in self.workers.values():
                if row['done'] or row['failed']:
                    raise AccountingError('Worker exited before shutdown; HOLD')
                if row['stop']() is not True:
                    raise AccountingError('Worker producer fence unavailable')
            return True
        participant.stop_admission = fence
        participant.worker_closure = self

    @asynccontextmanager
    async def run(self, name, owner, stop):
        p = self.participant
        p.verify()
        if self.fenced or name not in self.expected or name in self.workers or not callable(stop):
            p.phase = 'HOLD'; p.runtime.held = p.runtime.fenced = True
            raise AccountingError('Unregistered or replaced worker')
        task = asyncio.current_task()
        self.workers[name] = {'owner': owner, 'task': task, 'stop': stop, 'done': False, 'failed': False}
        row = self.workers[name]
        try:
            # Workers are completion obligations, not command admission leases.
            # Each bounded iteration must separately acquire its actual job lease.
            yield
            p.verify()
            if not self.fenced or p.runtime.held:
                raise AccountingError('Unexpected worker exit before shutdown')
        except BaseException:
            row['failed'] = True
            p.phase = 'HOLD'; p.runtime.held = p.runtime.fenced = True
            raise
        finally:
            row['done'] = True

    async def completed(self, deadline):
        p = self.participant
        while any(not row['done'] for row in self.workers.values()):
            if asyncio.get_running_loop().time() >= deadline:
                raise AccountingError('Worker completion timed out; no cancellation')
            await asyncio.sleep(.01)
        if not self.fenced or self.expected != self.workers.keys() or any(row['failed'] for row in self.workers.values()):
            raise AccountingError('Worker completion evidence unavailable')
        return sorted(self.workers)


@asynccontextmanager
async def worker(name, owner, stop):
    from stinky_core.transport import service_admission
    p = service_admission.PARTICIPANT
    if p is None:
        yield
        return
    registry = getattr(p, 'worker_closure', None)
    if registry is None:
        p.phase = 'HOLD'; p.runtime.held = p.runtime.fenced = True
        raise AccountingError('Actual worker lacks explicit shutdown manifest')
    async with registry.run(name, owner, stop):
        yield


def active():
    from stinky_core.transport import service_admission
    return service_admission.PARTICIPANT is not None


def running_flag(owner):
    owner._running = False
    return True


def stop_event(owner):
    owner._stop.set()
    return True


def worker_loop(name, stop):
    def decorate(function):
        @wraps(function)
        async def run(owner, *args, **kwargs):
            async with worker(name, owner, lambda: stop(owner)):
                return await function(owner, *args, **kwargs)
        return run
    return decorate
