"""Inactive, process-local cooperative boundary for explicitly managed writers.

No signal delivery, process termination, Redis configuration or implicit activation.
Call only through a trusted controller channel. This acknowledgement is a participant
boundary, never proof of complete production coverage or snapshot recoverability.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from contextlib import asynccontextmanager

from stinky_core.transport.redis_accounting import AccountingError, identity


class CooperativeParticipant:
    def __init__(self, runtime, *, persist, stop_admission):
        if not callable(persist) or not callable(stop_admission):
            raise AccountingError('Explicit durable audit and producer fence required')
        self.runtime = runtime
        self.persist = persist
        self.stop_admission = stop_admission
        self.owner = identity(runtime.verify_identity())
        if self.owner != runtime.owner:
            raise AccountingError('Participant owner differs from registered runtime')
        self.generation = runtime.generation
        self.server_epoch = runtime.server_epoch
        self.jobs = set()
        self.job_events = {}
        if getattr(runtime,'shutdown_participant',None) is not None:
            raise AccountingError('Runtime already has a cooperative participant')
        runtime.shutdown_participant = self
        self.phase = 'RUNNING'
        self.request_id = None
        self.last_head = None

    def manifest(self):
        body = {'owner': self.owner, 'generation': self.generation,
                'server_epoch': self.server_epoch, 'roles': sorted(self.runtime.roles)}
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def verify(self):
        if (identity(self.runtime.verify_identity()) != self.owner or
            self.runtime.generation != self.generation or
            self.runtime.server_epoch != self.server_epoch):
            raise AccountingError('Participant identity or route changed')

    def record(self, phase):
        head = self.persist({'stage': 'COOPERATIVE_PHASE', 'phase': phase,
                             'request_id': self.request_id, 'manifest_sha256': self.manifest()})
        if not isinstance(head, str) or not re.fullmatch('[0-9a-f]{64}', head):
            raise AccountingError('Durable participant audit head unavailable')
        self.last_head = head

    @asynccontextmanager
    async def job(self):
        self.verify()
        if self.phase != 'RUNNING' or self.runtime.fenced or self.runtime.held:
            raise AccountingError('Application work admission fenced')
        task = asyncio.current_task()
        if task is None or task in self.jobs:
            raise AccountingError('Duplicate or unavailable job identity')
        self.jobs.add(task)
        self.job_events[task]=asyncio.Event()
        try:
            yield
            self.verify()
            if self.runtime.held:
                raise AccountingError('Application job has an unresolved writer outcome')
        except BaseException:
            self.phase = 'HOLD'
            self.runtime.held = self.runtime.fenced = True
            raise
        finally:
            self.jobs.remove(task)
            self.job_events.pop(task).set()

    async def quiesce(self, request, *, timeout=10):
        if (type(timeout) not in (int, float) or not math.isfinite(timeout) or
            not 0 < timeout <= 60):
            raise AccountingError('Bounded shutdown deadline required')
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            self.verify()
            if (not isinstance(request, dict) or set(request) != {'request_id', 'manifest_sha256'} or
                not isinstance(request['request_id'], str) or
                not re.fullmatch('[0-9a-f]{32}', request['request_id']) or
                request['manifest_sha256'] != self.manifest() or self.phase != 'RUNNING'):
                raise AccountingError('Stale, repeated or unregistered shutdown request')
            self.request_id = request['request_id']
            self.phase = 'FENCING'
            # Permanent for this runtime. A future Start needs a new reviewed grant
            # and runtime; resume_verified cannot reopen this shutdown generation.
            self.runtime.shutdown_latched = True
            self.runtime.fenced = True
            self.record(self.phase)
            if self.stop_admission() is not True:
                raise AccountingError('Producer/background job fencing unverified')
            self.verify()
            if loop.time() >= deadline:
                raise AccountingError('Shutdown fencing exceeded deadline')
            self.phase = 'DRAINING'
            self.record(self.phase)
            tasks = set(self.jobs)
            if asyncio.current_task() in tasks:
                raise AccountingError('Shutdown cannot drain its own active job')
            if tasks:
                if not tasks <= self.job_events.keys():
                    raise AccountingError('Unregistered job completion evidence')
                waiters=[asyncio.create_task(self.job_events[task].wait()) for task in tasks]
                try:
                    _, pending = await asyncio.wait(waiters, timeout=max(0, deadline - loop.time()))
                    if pending:
                        raise AccountingError('Shutdown jobs timed out; no cancellation or force kill')
                finally:
                    # Only private completion waiters are cancelled. Application
                    # jobs are never cancelled, killed or declared complete here.
                    for waiter in waiters:
                        if not waiter.done():waiter.cancel()
                    await asyncio.gather(*waiters,return_exceptions=True)
            if self.jobs or self.phase == 'HOLD':
                raise AccountingError('Application work unresolved')
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AccountingError('Shutdown deadline exceeded')
            acknowledged = await self.runtime.quiesce(timeout=remaining)
            self.verify()
            if self.runtime.held or not self.runtime.fenced or loop.time() >= deadline:
                raise AccountingError('Writer boundary unverified')
            self.phase = 'QUIESCED'
            self.record(self.phase)
            self.verify()
            if loop.time() >= deadline or self.runtime.held or not self.runtime.fenced:
                raise AccountingError('Shutdown audit boundary changed or exceeded deadline')
            return {'phase': self.phase, 'owner': dict(self.owner),
                    'request_id': self.request_id, 'manifest_sha256': self.manifest(),
                    'journal_head': self.last_head, 'acknowledged': acknowledged,
                    'scope': 'PARTICIPANT_ONLY_NOT_FINAL_RECOVERY_BOUNDARY'}
        except BaseException:
            self.phase = 'HOLD'
            self.runtime.held = self.runtime.fenced = True
            self.runtime.shutdown_latched = True
            try:
                self.record('HOLD')
            except BaseException:
                pass  # Never report an audit head or completed stop after failure.
            raise
