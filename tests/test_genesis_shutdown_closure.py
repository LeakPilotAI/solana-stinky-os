import asyncio
import hashlib
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from stinky_core.transport.shutdown_delivery import ShutdownAuthority, ShutdownReceiver
from stinky_core.transport.worker_closure import WorkerClosure
from stinky_core.transport.redis_accounting import AccountingError
from stinky_core.transport import service_admission as admission
from scripts.genesis_child_exit import ChildRegistry
from scripts.genesis_supervisor_admission import SupervisorAdmission
from scripts import run_genesis_service as runner
from scripts.redis_production_adapters import DurableJournal
from test_genesis_service_admission import installed


def authority():
    return ShutdownAuthority(os.urandom(32), 'a'*64)


@pytest.mark.parametrize('interval',[10,60,21600])
def test_disabled_supervisor_preserves_exact_maintenance_cadences(monkeypatch,interval):
    calls=[]
    monkeypatch.setattr(runner,'COOPERATIVE_SUPERVISOR',None)
    monkeypatch.setattr(runner,'time',SimpleNamespace(sleep=lambda n:calls.append(n)))
    runner.supervisor_wait(interval)
    assert calls==[interval] and runner.supervisor_running()


@pytest.mark.parametrize('service',['maintain','api'])
def test_unregistered_supervisor_loops_cannot_acknowledge(service):
    owner={'pid':os.getpid(),'creation_ticks':10,'service':service,'command_sha256':'a'*64,'repository_sha256':'b'*64}
    gate=SupervisorAdmission(owner,generation=1,verify_native=lambda:dict(owner),persist=lambda row:'c'*64)
    with pytest.raises(RuntimeError,match='ownership incomplete'):
        gate.quiesce({'request_id':'d'*32,'manifest_sha256':gate.manifest()})
    assert gate.phase=='HOLD' and gate.stop_event.is_set()


@pytest.mark.asyncio
async def test_receiver_restart_invalidates_old_control_capability_request():
    control=authority();processed=[]
    async def process(request, timeout):processed.append(request);return {'phase':'QUIESCED','request_id':request['request_id']}
    def receiver():
        return ShutdownReceiver(control,manifest=lambda:'c'*64,generation=lambda:1,
            verify_controller=lambda:'a'*64,process=process,persist=lambda row:'d'*64,hold=lambda:None)
    old=receiver();request=control.request(old.target(),1)
    fresh=receiver()
    with pytest.raises(AccountingError,match='targeted'):await fresh.receive(request)
    assert not processed and not fresh.used
    reply=await fresh.receive(control.request(fresh.target(),1))
    assert reply['body']['phase']=='QUIESCED' and len(processed)==1


@pytest.mark.asyncio
async def test_actual_manual_consumer_fails_before_destructive_brpop(tmp_path,monkeypatch):
    from sentinel.manual_track import ManualTrackConsumer
    p,r,j,req=installed(tmp_path,monkeypatch,'sentinel-manual-consumer')
    WorkerClosure(p,['sentinel-manual'])
    obj=object.__new__(ManualTrackConsumer);obj._stop=asyncio.Event();obj._redis=None
    monkeypatch.setattr('sentinel.manual_track.redis_client',lambda *a,**k:pytest.fail('Unsupported BRPOP client issued'))
    try:
        with pytest.raises(AccountingError,match='BRPOP'):await obj.run()
        assert p.phase=='HOLD' and r.held and obj._redis is None
        with pytest.raises(AccountingError):await p.quiesce(req)
    finally:j.close()


@pytest.mark.asyncio
async def test_collector_cannot_ack_a_refused_new_track_after_fence(tmp_path,monkeypatch):
    from post_migration.service import CollectorService
    p,r,j,req=installed(tmp_path,monkeypatch,'collector-consumer')
    obj=object.__new__(CollectorService);acks=[]
    client=SimpleNamespace(role='collector-consumer',route_generation=1)
    class Redis:
        async def xack(self,*args):r.check(client);acks.append(args)
    obj._redis=Redis()
    @admission.cooperative_job('collector')
    async def track(*args):
        async def unrelated():pytest.fail('New track admitted after fence')
        admission.create_task(unrelated())
    obj._on_migration=track
    try:
        with pytest.raises(AccountingError,match='unresolved writer outcome'):
            async with p.job():
                r.fenced=True;r.shutdown_latched=True;p.phase='DRAINING';r.clients=[client]
                await obj._handle_message('1-0',{'data':'{"event_type":"token.migrated","payload":{}}'})
        assert not acks and p.phase=='HOLD' and r.held
    finally:j.close()


@pytest.mark.asyncio
async def test_actual_supervisor_delivery_waits_for_owned_job(tmp_path,monkeypatch):
    import threading
    monkeypatch.setattr(runner,'COOPERATIVE_SUPERVISOR',None)
    monkeypatch.setattr(runner,'COOPERATIVE_DELIVERY',None)
    monkeypatch.setattr(runner,'COOPERATIVE_CHILDREN',None)
    owner={'pid':os.getpid(),'creation_ticks':10,'service':'fixture','command_sha256':'a'*64,
        'repository_sha256':hashlib.sha256(str(runner._SCRIPTS.parent).encode()).hexdigest()}
    journal=DurableJournal(tmp_path/'supervisor-delivery')
    def persist(row):journal.persist(row);return journal.previous
    gate=SupervisorAdmission(owner,generation=1,verify_native=lambda:dict(owner),persist=persist)
    runner.install_cooperative_supervisor(gate);control=authority()
    runner.install_shutdown_delivery(control,verify_controller=lambda:'a'*64,persist=persist)
    entered=threading.Event();release=threading.Event()
    def operation():entered.set();assert release.wait(2)
    thread=threading.Thread(target=lambda:runner.run_admitted_job(['fixture'],operation));thread.start()
    assert entered.wait(1)
    request=control.request(runner.COOPERATIVE_DELIVERY.target(),1,timeout=2)
    delivery=asyncio.create_task(runner.deliver_shutdown(request));await asyncio.sleep(.02)
    try:
        assert not delivery.done() and gate.phase=='DRAINING'
        release.set();reply=await delivery;thread.join(2)
        ack=control.verify_reply(request,reply)
        assert ack['phase']=='QUIESCED' and 'verified_child_exit' not in ack
        assert ack['scope']=='JOB_TICKETS_ONLY_NOT_PROCESS_EXIT_OR_WRITER_BOUNDARY'
        with pytest.raises(RuntimeError):runner.run_admitted_job(['respawn'],lambda:pytest.fail('respawned'))
    finally:release.set();thread.join(2);journal.close()


@pytest.mark.asyncio
async def test_actual_delivery_waits_for_processing_and_durable_reply(tmp_path, monkeypatch):
    p, runtime, journal, _ = installed(tmp_path, monkeypatch, 'api-manual-queue')
    monkeypatch.setattr(admission, 'DELIVERY', None)
    control = authority()
    admission.install_delivery(control, verify_controller=lambda:'a'*64,
                               persist=lambda row:(journal.persist(row),journal.previous)[1])
    entered = asyncio.Event(); release = asyncio.Event()
    async def pending():
        async with admission.admission('api'):
            entered.set();await release.wait()
    job = asyncio.create_task(pending());await entered.wait()
    request = control.request(admission.DELIVERY.target(), runtime.generation, timeout=2)
    delivery = asyncio.create_task(admission.deliver_shutdown(request))
    await asyncio.sleep(.02)
    assert not delivery.done() and p.phase == 'DRAINING'
    release.set();await job
    ack = control.verify_reply(request, await delivery)
    assert ack['phase']=='QUIESCED' and ack['connection_ownership']['connection_ids']==[]
    with pytest.raises(AccountingError, match='consumed'):
        await admission.deliver_shutdown(request)
    journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['mac','target','generation','expiry','controller','duplicate','audit','identity','reply','lost'])
async def test_delivery_failures_cannot_fabricate_processing(tmp_path, failure):
    control=authority();calls=[];held=[];native=['a'*64]
    journal=DurableJournal(tmp_path/'delivery.jsonl')
    def persist(row):
        if failure=='audit':raise OSError('Isolated storage failure')
        journal.persist(row);return journal.previous
    async def process(request,timeout):
        calls.append(request)
        if failure=='identity':native[0]='b'*64
        if failure=='lost':raise ConnectionError('Accepted command, lost reply')
        return {'phase':'QUIESCED','request_id':request['request_id']}
    receiver=ShutdownReceiver(control,manifest=lambda:'c'*64,generation=lambda:1,
        verify_controller=lambda:native[0],process=process,persist=persist,hold=lambda:held.append(True))
    request=control.request(receiver.target(),1)
    if failure in ('target','generation','expiry','controller'):
        body=dict(request['body'])
        body[{'target':'target','generation':'generation','expiry':'expires_ns','controller':'controller'}[failure]]={'target':'d'*64,'generation':2,'expiry':1,'controller':'b'*64}[failure]
        request=control.seal(body)
    if failure=='mac':request['mac']='0'*64
    try:
        if failure in ('duplicate','reply'):
            reply=await receiver.receive(request)
            if failure=='duplicate':
                with pytest.raises(AccountingError):await receiver.receive(request)
                assert len(calls)==1
            else:
                body=dict(reply['body']);body['request_id']='0'*32
                with pytest.raises(AccountingError):control.verify_reply(request,control.seal(body))
        else:
            with pytest.raises((AccountingError,OSError,ConnectionError)):await receiver.receive(request)
            if failure in ('mac','target','generation','expiry','controller','audit'):assert not calls
            if failure in ('audit','identity','lost'):assert held and receiver.used
    finally:journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('service',['collector','entities','discord','sentinel-relay'])
async def test_actual_long_lived_worker_drains_before_ack(tmp_path,monkeypatch,service):
    role={'collector':'collector-consumer','entities':'entity-consumer','discord':'discord-alerts','sentinel-relay':'redis-streams'}[service]
    p,r,j,req=installed(tmp_path,monkeypatch,role)
    name={'collector':'collector-intake','entities':'entity-intake','discord':'discord-dispatch','sentinel-relay':'sentinel-relay'}[service]
    registry=WorkerClosure(p,[name]);entered=asyncio.Event();release=asyncio.Event();writes=[]
    async def read(*a,**k):entered.set();await release.wait();return []
    async def start(owner):owner._running=True
    if service=='collector':
        from post_migration.service import CollectorService
        obj=object.__new__(CollectorService);obj._running=False
        obj.start=lambda:start(obj);obj._redis=SimpleNamespace()
        obj._read_group=read;obj._bounded_backfill=AsyncMock(return_value=0)
        obj.stop=AsyncMock(side_effect=lambda:writes.append('legacy-stop'))
        operation=obj.run_forever
    elif service=='entities':
        from entity_resolver.service import EntityService
        obj=object.__new__(EntityService);obj._running=False;obj.start=lambda:start(obj)
        obj._redis=SimpleNamespace(xreadgroup=read)
        obj._recover_pending=AsyncMock();obj._schedule_batch=lambda:None
        operation=obj.run_forever
    elif service=='discord':
        from discord_bot.alerter import AlertDispatcher
        obj=object.__new__(AlertDispatcher);obj._running=True;obj._redis=SimpleNamespace(xreadgroup=read)
        operation=obj._loop
    else:
        from sentinel.publisher import LaunchPublisher
        obj=object.__new__(LaunchPublisher);obj._stop=asyncio.Event();obj._connected=True
        obj._durable=SimpleNamespace(drain_unpublished=AsyncMock(side_effect=lambda:writes.append('new-outbox')))
        operation=obj._relay_loop
    task=asyncio.create_task(operation())
    try:
        if service=='sentinel-relay':
            await asyncio.sleep(.02)
        else:await entered.wait()
        shutdown=asyncio.create_task(p.quiesce(req,timeout=2));await asyncio.sleep(.02)
        if service!='sentinel-relay':assert not shutdown.done() and not task.done()
        release.set();await task;ack=await shutdown
        assert await registry.completed(asyncio.get_running_loop().time()+1)==[name]
        assert registry.workers[name]['done'] and ack['phase']=='QUIESCED'
        assert not writes and p.phase=='QUIESCED'
    finally:
        release.set()
        if not task.done():
            if service=='sentinel-relay':obj._stop.set()
            else:obj._running=False
        await asyncio.gather(task,return_exceptions=True);j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['missing','timeout','crash','unknown','replaced'])
async def test_worker_failure_holds_without_cancelling(tmp_path,monkeypatch,failure):
    p,r,j,req=installed(tmp_path,monkeypatch,'collector-consumer')
    registry=WorkerClosure(p,['collector-intake']);release=asyncio.Event();entered=asyncio.Event()
    async def work():
        async with registry.run('unregistered' if failure=='unknown' else 'collector-intake',object(),lambda:True):
            entered.set()
            if failure=='crash':raise ValueError('Worker crashed')
            await release.wait()
    task=None
    try:
        if failure!='missing':
            task=asyncio.create_task(work());await asyncio.sleep(.02)
            if failure in ('unknown','crash'):
                with pytest.raises((AccountingError,ValueError)):await task
            if failure=='replaced':r.generation+=1
        with pytest.raises(AccountingError):await p.quiesce(req,timeout=.25)
        assert r.held and p.phase=='HOLD'
        if task and failure=='timeout':assert not task.cancelled() and not task.done()
    finally:
        release.set()
        if task:await asyncio.gather(task,return_exceptions=True)
        j.close()


def test_child_exit_requires_native_identity_descendants_and_durable_audit(tmp_path):
    owner={'pid':os.getpid(),'creation_ticks':10,'service':'api','command_sha256':'a'*64,'repository_sha256':'b'*64}
    gate=SupervisorAdmission(owner,generation=1,verify_native=lambda:dict(owner),persist=lambda row:'c'*64)
    command=['verified-fixture'];child=SimpleNamespace(pid=20,poll=lambda:0)
    identity={'pid':20,'parent_pid':owner['pid'],'creation_ticks':11,
              'command_sha256':hashlib.sha256(b'["verified-fixture"]').hexdigest(),'repository_sha256':'b'*64}
    seen={'owner':identity,'exited':True,'descendants_exited':True,'exit_code':0}
    registry=ChildRegistry(gate,capture=lambda *a:dict(identity),inspect=lambda *a:dict(seen),persist=lambda row:'d'*64)
    registry.register(child,command);assert registry.verify_exited()==[identity]
    seen['descendants_exited']=False
    with pytest.raises(RuntimeError):registry.verify_exited()
    assert gate.phase=='HOLD'


@pytest.mark.parametrize('failure',['pid-reuse','parent','command','repository','running','crash','orphan','audit','duplicate'])
def test_child_exit_failure_injection(failure):
    owner={'pid':os.getpid(),'creation_ticks':10,'service':'maintain','command_sha256':'a'*64,'repository_sha256':'b'*64}
    gate=SupervisorAdmission(owner,generation=1,verify_native=lambda:dict(owner),persist=lambda row:'c'*64)
    command=['child'];identity={'pid':20,'parent_pid':owner['pid'],'creation_ticks':11,'command_sha256':hashlib.sha256(b'["child"]').hexdigest(),'repository_sha256':'b'*64}
    child=SimpleNamespace(pid=20,poll=lambda:0)
    seen={'owner':dict(identity),'exited':True,'descendants_exited':True,'exit_code':0}
    registry=ChildRegistry(gate,capture=lambda *a:dict(identity),inspect=lambda *a:seen,persist=lambda row:None if failure=='audit' else 'd'*64)
    if failure in ('parent','command','repository'):identity[{'parent':'parent_pid','command':'command_sha256','repository':'repository_sha256'}[failure]]=0
    if failure in ('parent','command','repository'):
        with pytest.raises(RuntimeError):registry.register(child,command)
    else:
        registry.register(child,command)
        if failure=='duplicate':
            with pytest.raises(RuntimeError):registry.register(child,command)
        else:
            if failure=='pid-reuse':seen['owner']['creation_ticks']+=1
            if failure=='running':child.poll=lambda:None;seen['exited']=False
            if failure=='crash':child.poll=lambda:71;seen['exit_code']=71
            if failure=='orphan':seen['descendants_exited']=False
            with pytest.raises(RuntimeError):registry.verify_exited()
    assert gate.phase=='HOLD'
