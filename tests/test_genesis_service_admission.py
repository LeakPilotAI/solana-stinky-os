import asyncio
import hashlib
import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.redis_production_adapters import DurableJournal,read_records
from scripts.genesis_supervisor_admission import SupervisorAdmission,CORE
from scripts import run_genesis_service as runner
from stinky_core.transport import service_admission as admission
from stinky_core.transport.cooperative_shutdown import CooperativeParticipant
from stinky_core.transport.redis_accounting import Runtime,ClientFactory,AccountingError


def installed(tmp_path,monkeypatch,role):
    monkeypatch.setattr(admission,'PARTICIPANT',None)
    owner={'pid':1,'creation_ticks':10,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64}
    ledger=SimpleNamespace(settled=lambda:0)
    runtime=Runtime(ledger,lambda:dict(owner),endpoint='isolated',server_epoch='c'*40,roles=[role])
    factory=ClientFactory();factory.configure(runtime)
    journal=DurableJournal(tmp_path/'phase.jsonl')
    def persist(row):journal.persist(row);return journal.previous
    p=CooperativeParticipant(runtime,persist=persist,stop_admission=lambda:True)
    admission.install(p,factory=factory)
    return p,runtime,journal,{'request_id':'d'*32,'manifest_sha256':p.manifest()}


@pytest.mark.asyncio
async def test_actual_api_request_finishes_but_next_request_is_refused(tmp_path,monkeypatch):
    from stinky_api import track
    p,r,j,req=installed(tmp_path,monkeypatch,'api-manual-queue')
    started=asyncio.Event();release=asyncio.Event();calls=[]
    class Redis:
        async def lpush(self,*args):calls.append('push');started.set();await release.wait();return 1
        async def llen(self,*args):return 1
        async def aclose(self):calls.append('close')
    monkeypatch.setattr(track,'redis_client',lambda *a,**k:Redis())
    body=track.TrackRequest(mint='a'*28+'pump')
    task=asyncio.create_task(track.enqueue_manual_track(body))
    try:
        await started.wait();shutdown=asyncio.create_task(p.quiesce(req,timeout=1));await asyncio.sleep(0)
        assert not shutdown.done() and p.phase=='DRAINING'
        release.set();assert (await task)['queued'];assert (await shutdown)['phase']=='QUIESCED'
        with pytest.raises(AccountingError):await track.enqueue_manual_track(body)
        assert calls==['push','close']
    finally:release.set();await task;j.close()


@pytest.mark.asyncio
async def test_actual_ingest_and_nested_transport_can_finish_after_fence(tmp_path,monkeypatch):
    from event_log.service import EventLogService
    from stinky_core.transport.redis_streams import RedisStreamsTransport
    from stinky_core.events.base import Event,EventType
    p,r,j,req=installed(tmp_path,monkeypatch,'redis-streams')
    started=asyncio.Event();release=asyncio.Event();calls=[]
    client=type('Client',(),{'role':'redis-streams','route_generation':1})()
    r.clients.add(client)
    class Redis:
        async def xadd(self,*a,**k):r.check(client);calls.append('redis');return b'1-0'
    transport=RedisStreamsTransport();transport._redis=Redis()
    service=object.__new__(EventLogService)
    service._transport=transport
    service._validator=SimpleNamespace(validate=lambda event:SimpleNamespace(is_valid=True,errors=[]))
    async def commit():started.set();await release.wait();calls.append('commit')
    service._repo=SimpleNamespace(insert_event_raw=AsyncMock(),commit=commit)
    event=Event(event_type=EventType.TOKEN_LAUNCH,payload={'mint':'fixture'})
    task=asyncio.create_task(service.ingest(event))
    try:
        await started.wait();shutdown=asyncio.create_task(p.quiesce(req,timeout=1));await asyncio.sleep(0)
        release.set();assert (await task)==(True,[]);assert (await shutdown)['phase']=='QUIESCED'
        assert calls==['commit','redis']
        with pytest.raises(AccountingError):await service.ingest(event)
        assert service._repo.insert_event_raw.await_count==1
    finally:release.set();await task;j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('service',['collector','entities','sentinel','discord'])
async def test_actual_handler_paths_reject_new_side_effects_after_quiescence(tmp_path,monkeypatch,service):
    roles={'collector':'collector-consumer','entities':'entity-consumer','sentinel':'redis-streams','discord':'discord-alerts'}
    p,r,j,req=installed(tmp_path,monkeypatch,roles[service]);calls=[]
    if service=='collector':
        from post_migration.service import CollectorService
        obj=object.__new__(CollectorService)
        obj._redis=SimpleNamespace(xack=AsyncMock(side_effect=lambda *args:calls.append('ack')))
        operation=lambda:obj._handle_batch([('1-0',{'data':json.dumps({'event_type':'wallet.performance_updated'})})])
    elif service=='entities':
        from entity_resolver.service import EntityService
        obj=object.__new__(EntityService)
        obj._resolver=SimpleNamespace(run_batch=AsyncMock(side_effect=lambda:calls.append('batch')))
        operation=obj._run_batch_guarded
    elif service=='sentinel':
        from sentinel.publisher import LaunchPublisher
        from stinky_core.events.base import Event,EventType
        obj=object.__new__(LaunchPublisher)
        obj._publish_event=AsyncMock(side_effect=lambda *a,**k:calls.append('publish') or True)
        operation=lambda:obj.publish_raw_event(Event(event_type=EventType.TOKEN_LAUNCH,payload={}),kind='fixture')
    else:
        from discord_bot.alerter import AlertDispatcher
        obj=object.__new__(AlertDispatcher)
        operation=lambda:obj._handle('1-0',{})
        # Empty records exercise actual parsing/ACK; no network client is used.
        obj._redis=SimpleNamespace(xack=AsyncMock(side_effect=lambda *args:calls.append('ack')))
    try:
        await operation();before=list(calls);await p.quiesce(req)
        with pytest.raises(AccountingError):await operation()
        assert calls==before
    finally:j.close()


@pytest.mark.asyncio
async def test_background_registration_is_atomic_and_failed_task_is_held(tmp_path,monkeypatch):
    p,r,j,req=installed(tmp_path,monkeypatch,'redis-streams');release=asyncio.Event()
    async def work():await release.wait();raise ValueError('fixture failure')
    task=admission.create_task(work())
    try:
        assert task in p.jobs
        shutdown=asyncio.create_task(p.quiesce(req,timeout=1));await asyncio.sleep(0)
        release.set()
        with pytest.raises(ValueError):await task
        with pytest.raises(AccountingError):await shutdown
        assert p.phase=='HOLD' and r.held
    finally:release.set();j.close()


@pytest.mark.asyncio
async def test_real_cleanup_paths_hold_before_cancellation(tmp_path,monkeypatch):
    from post_migration.service import CollectorService
    p,r,j,req=installed(tmp_path,monkeypatch,'collector-consumer')
    obj=object.__new__(CollectorService)
    try:
        with pytest.raises(AccountingError,match='Legacy task cancellation'):await obj.stop()
        assert r.held and p.phase=='HOLD'
    finally:j.close()


def test_installation_rejects_hot_patch_and_wrong_runtime(tmp_path,monkeypatch):
    p,r,j,req=installed(tmp_path,monkeypatch,'redis-streams')
    try:
        with pytest.raises(AccountingError):admission.install(p,factory=ClientFactory())
    finally:j.close()


@pytest.mark.asyncio
async def test_authenticated_role_mismatch_blocks_actual_api_before_client_creation(tmp_path,monkeypatch):
    from stinky_api import track
    p,r,j,req=installed(tmp_path,monkeypatch,'entity-consumer')
    monkeypatch.setattr(track,'redis_client',lambda *a,**k:pytest.fail('Wrong role reached Redis'))
    try:
        with pytest.raises(AccountingError,match='authenticated writer role'):
            await track.enqueue_manual_track(track.TrackRequest(mint='a'*28+'pump'))
        assert p.phase=='HOLD' and r.held
    finally:j.close()


@pytest.mark.asyncio
async def test_fenced_background_task_is_closed_without_admission(tmp_path,monkeypatch):
    import inspect
    p,r,j,req=installed(tmp_path,monkeypatch,'redis-streams')
    async def never():pytest.fail('New work executed after fence')
    try:
        await p.quiesce(req)
        coroutine=never()
        with pytest.raises(AccountingError):admission.create_task(coroutine,suboperation=True)
        assert inspect.getcoroutinestate(coroutine)==inspect.CORO_CLOSED and not p.jobs
    finally:j.close()


def test_new_installation_cannot_attach_to_already_issued_factory(tmp_path,monkeypatch):
    p,r,j,req=installed(tmp_path,monkeypatch,'redis-streams')
    monkeypatch.setattr(admission,'PARTICIPANT',None)
    factory=ClientFactory();factory.configure(r);factory.issued=True
    try:
        with pytest.raises(AccountingError):admission.install(p,factory=factory)
        assert admission.PARTICIPANT is None and p.phase=='RUNNING'
    finally:j.close()


def test_supervisor_installation_rejects_other_repository(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'COOPERATIVE_SUPERVISOR',None)
    owner={'pid':os.getpid(),'creation_ticks':10,'service':'api','command_sha256':'a'*64,'repository_sha256':'b'*64}
    gate=SupervisorAdmission(owner,generation=1,verify_native=lambda:dict(owner),persist=lambda row:'c'*64)
    with pytest.raises(RuntimeError):runner.install_cooperative_supervisor(gate)
    assert runner.COOPERATIVE_SUPERVISOR is None


def test_disabled_phase_reporting_does_not_fabricate_zero_jobs(monkeypatch):
    monkeypatch.setattr(admission,'PARTICIPANT',None)
    monkeypatch.setattr(runner,'COOPERATIVE_SUPERVISOR',None)
    for view in (admission.status(),runner.cooperative_status()):
        assert view['phase']=='DISABLED' and view['jobs'] is None and view['identity_verified'] is None


@pytest.mark.asyncio
async def test_service_phase_reporting_fails_closed_on_route_replacement(tmp_path,monkeypatch):
    p,r,j,req=installed(tmp_path,monkeypatch,'redis-streams')
    try:
        assert admission.status()['identity_verified']
        r.generation+=1
        view=admission.status()
        assert view['phase']=='HOLD' and view['jobs'] is None and view['identity_verified'] is False
        assert r.held and r.fenced
    finally:j.close()


@pytest.mark.asyncio
async def test_actual_service_cannot_hide_a_held_writer_by_catching_its_error(tmp_path,monkeypatch):
    from entity_resolver.service import EntityService
    p,r,j,req=installed(tmp_path,monkeypatch,'entity-consumer')
    obj=object.__new__(EntityService)
    async def failed():r.held=True;raise ConnectionError('Isolated ambiguous transport outcome')
    obj._resolver=SimpleNamespace(run_batch=failed)
    try:
        with pytest.raises(AccountingError,match='unresolved writer outcome'):await obj._run_batch_guarded()
        assert admission.status()['phase']=='HOLD' and p.phase=='HOLD'
    finally:j.close()


@pytest.mark.parametrize('service',sorted(CORE))
def test_actual_supervisor_job_path_drains_all_core_roles_and_cannot_respawn(tmp_path,monkeypatch,service):
    monkeypatch.setattr(runner,'COOPERATIVE_SUPERVISOR',None)
    owner={'pid':os.getpid(),'creation_ticks':10,'service':service,'command_sha256':'a'*64,'repository_sha256':hashlib.sha256(str(runner._SCRIPTS.parent).encode()).hexdigest()}
    journal=DurableJournal(tmp_path/'supervisor.jsonl')
    def persist(row):journal.persist(row);return journal.previous
    gate=SupervisorAdmission(owner,generation=1,verify_native=lambda:dict(owner),persist=persist)
    runner.install_cooperative_supervisor(gate)
    entered=threading.Event();release=threading.Event();results=[]
    def work():entered.set();assert release.wait(2);return 0
    child=threading.Thread(target=lambda:runner.run_admitted_job(['owned-fixture'],work));child.start()
    request={'request_id':'e'*32,'manifest_sha256':gate.manifest()}
    control=threading.Thread(target=lambda:results.append(gate.quiesce(request,timeout=1)))
    try:
        assert entered.wait(1);control.start()
        with gate.changed:
            assert gate.phase in ('FENCING','DRAINING') and gate.jobs
        release.set();child.join(2);control.join(2)
        assert not child.is_alive() and not control.is_alive()
        assert results[0]['phase']=='QUIESCED'
        assert [row['phase'] for row in read_records(journal.path,expected_head=results[0]['journal_head'])]==['FENCING','DRAINING','QUIESCED']
        with pytest.raises(RuntimeError):runner.run_admitted_job(['no-respawn'],lambda:pytest.fail('spawned'))
        with pytest.raises(RuntimeError):gate.quiesce(request)
    finally:release.set();child.join(2);control.join(2);journal.close()


@pytest.mark.parametrize('failure',['identity','timeout','audit','stale','crash'])
def test_supervisor_failure_never_claims_process_exit(tmp_path,monkeypatch,failure):
    monkeypatch.setattr(runner,'COOPERATIVE_SUPERVISOR',None)
    owner={'pid':os.getpid(),'creation_ticks':10,'service':'maintain','command_sha256':'a'*64,'repository_sha256':hashlib.sha256(str(runner._SCRIPTS.parent).encode()).hexdigest()}
    journal=DurableJournal(tmp_path/'supervisor.jsonl')
    def persist(row):journal.persist(row);return journal.previous
    gate=SupervisorAdmission(owner,generation=1,verify_native=lambda:dict(owner),persist=persist)
    runner.install_cooperative_supervisor(gate)
    req={'request_id':'e'*32,'manifest_sha256':gate.manifest()}
    if failure=='identity':owner['creation_ticks']+=1
    if failure=='audit':journal.failed=True
    if failure=='stale':req['manifest_sha256']='f'*64
    if failure=='crash':
        with pytest.raises(ValueError):runner.run_admitted_job(['failed-child'],lambda:(_ for _ in ()).throw(ValueError('fixture')))
    if failure=='timeout':gate.jobs['unsettled']='a'*64
    try:
        with pytest.raises(RuntimeError):gate.quiesce(req,timeout=.01)
        assert gate.phase=='HOLD'
    finally:journal.close()
