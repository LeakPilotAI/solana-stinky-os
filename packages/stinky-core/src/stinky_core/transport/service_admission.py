"""Explicitly installed cooperative admission hooks; normal services are unchanged.

Installation is a trusted startup operation on an already authenticated Runtime,
not an environment switch, shutdown endpoint or permission to activate production.
"""
from contextlib import asynccontextmanager
from functools import wraps
import asyncio
import threading

from stinky_core.transport.redis_accounting import AccountingError, FACTORY


PARTICIPANT = None
_INSTALL_LOCK = threading.RLock()
DELIVERY = None
ROLES = {'event-log':{'redis-streams'}, 'api':{'api-manual-queue'},
         'collector':{'redis-streams','collector-consumer'}, 'entities':{'entity-consumer'},
         'sentinel':{'redis-streams','sentinel-manual-consumer'}, 'discord':{'discord-alerts'},
         'redis-streams':{'redis-streams'}}


def install(participant, *, factory=FACTORY):
    global PARTICIPANT
    from stinky_core.transport.cooperative_shutdown import CooperativeParticipant
    with _INSTALL_LOCK:
        if (PARTICIPANT is not None or not isinstance(participant, CooperativeParticipant) or
            factory.runtime is not participant.runtime or factory.issued or
            (participant.owner['service']!='fixture' and factory is not FACTORY) or
            participant.phase != 'RUNNING' or participant.runtime.clients):
            raise AccountingError('Cooperative admission requires authenticated clean startup')
        participant.verify()
        PARTICIPANT = participant


@asynccontextmanager
async def admission(service):
    participant = PARTICIPANT
    if participant is None:
        yield
        return
    participant.verify()
    if (service not in ROLES or not participant.runtime.roles.intersection(ROLES[service]) or
        (service!='redis-streams' and participant.owner['service'] not in (service,'fixture'))):
        participant.phase='HOLD';participant.runtime.held=participant.runtime.fenced=True
        raise AccountingError('Service admission contradicts authenticated writer role')
    task = asyncio.current_task()
    if task in participant.jobs:
        # Nested transport calls belong to this exact pre-admitted task. They
        # cannot create a new lease or remove the outer task's registration.
        if participant.runtime.held or participant.phase not in ('RUNNING','FENCING','DRAINING'):
            raise AccountingError('Existing application job held')
        try:
            yield
        except BaseException:
            participant.phase='HOLD';participant.runtime.held=participant.runtime.fenced=True
            raise
    else:
        async with participant.job():
            yield


def cooperative_job(service):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            async with admission(service):
                return await function(*args, **kwargs)
        return wrapped
    return decorate


def guard_legacy_cleanup():
    if PARTICIPANT is not None:
        PARTICIPANT.phase='HOLD'
        PARTICIPANT.runtime.held=PARTICIPANT.runtime.fenced=True
        raise AccountingError('Legacy task cancellation/client close is not cooperative shutdown')


def install_delivery(authority, *, verify_controller, persist):
    global DELIVERY
    from stinky_core.transport.shutdown_delivery import ShutdownReceiver
    p = PARTICIPANT
    with _INSTALL_LOCK:
        if p is None or DELIVERY is not None or p.phase != 'RUNNING':
            raise AccountingError('Authenticated participant startup required for delivery')
        p.verify()
        async def process(request, timeout):
            ack = await p.quiesce({'request_id':request['request_id'], 'manifest_sha256':p.manifest()}, timeout=timeout)
            p.verify()
            workers = getattr(p, 'worker_closure', None)
            ack['completed_workers'] = (await workers.completed(asyncio.get_running_loop().time()+.001)
                                        if workers is not None else None)
            ids = [c.connection_id for c in p.runtime.clients
                   if c.connection_id is not None and not c.retired]
            ack['connection_ownership'] = {'owner': dict(p.owner),
                'generation': p.runtime.generation, 'server_epoch': p.runtime.server_epoch,
                'connection_ids': p.runtime.verify_connections(ids),
                'scope': 'AUTHENTICATED_NATIVE_REPORT_REQUIRES_INDEPENDENT_SERVER_JOIN'}
            return ack
        def hold():
            p.phase = 'HOLD'; p.runtime.held = p.runtime.fenced = True
        DELIVERY = ShutdownReceiver(authority, manifest=delivery_manifest,
            generation=lambda: p.runtime.generation, verify_controller=verify_controller,
            process=process, persist=persist, hold=hold)


def delivery_manifest():
    import hashlib
    import json
    p = PARTICIPANT
    if p is None:
        raise AccountingError('Delivery manifest unavailable')
    p.verify()
    workers = getattr(p, 'worker_closure', None)
    if workers is None:
        return p.manifest()
    return hashlib.sha256(json.dumps({'participant':p.manifest(), 'workers':sorted(workers.expected)},
        sort_keys=True,separators=(',', ':')).encode()).hexdigest()


async def deliver_shutdown(envelope):
    if DELIVERY is None:
        raise AccountingError('Shutdown delivery disabled')
    return await DELIVERY.receive(envelope)


def status():
    participant=PARTICIPANT
    if participant is None:
        return {'phase':'DISABLED','jobs':None,'identity_verified':None,
                'scope':'NO_INSTALLED_COOPERATIVE_PARTICIPANT'}
    try:participant.verify();verified=True
    except Exception:
        participant.phase='HOLD';participant.runtime.held=participant.runtime.fenced=True;verified=False
    if participant.runtime.held:participant.phase='HOLD'
    return {'phase':participant.phase,'jobs':len(participant.jobs) if verified else None,
            'identity_verified':verified,'scope':'PROCESS_LOCAL_NOT_COMPLETE_RUNTIME'}


def create_task(coroutine, *, name=None, suboperation=False):
    participant = PARTICIPANT
    if participant is None:
        return asyncio.create_task(coroutine, name=name)
    try:
        participant.verify()
        inherited=(suboperation is True and asyncio.current_task() in participant.jobs and
                   participant.phase in ('FENCING','DRAINING'))
        if (participant.phase != 'RUNNING' or participant.runtime.fenced or participant.runtime.held) and not inherited:
            raise AccountingError('Background task admission fenced')
        if participant.runtime.held:raise AccountingError('Existing suboperation held')
        if len(participant.jobs)>=128:
            raise AccountingError('Background job registration bound exceeded')
    except BaseException:
        coroutine.close()
        raise
    async def run():
        task=asyncio.current_task()
        try:
            return await coroutine
        except BaseException:
            participant.phase='HOLD'
            participant.runtime.held=participant.runtime.fenced=True
            raise
        finally:
            participant.jobs.remove(task)
            participant.job_events.pop(task).set()
    task=asyncio.create_task(run(),name=name)
    # Register before returning control; a queued task must not cross a fence
    # unregistered just because its coroutine has not started executing yet.
    participant.jobs.add(task)
    participant.job_events[task]=asyncio.Event()
    def complete(done):
        if done in participant.jobs:
            # A task cancelled before its first instruction has no wrapper finally.
            # Close the unused coroutine but retain an explicit unresolved HOLD.
            coroutine.close();participant.jobs.remove(done)
            participant.job_events.pop(done).set()
            participant.phase='HOLD'
            participant.runtime.held=participant.runtime.fenced=True
    task.add_done_callback(complete)
    return task
