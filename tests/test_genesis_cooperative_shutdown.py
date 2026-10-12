import asyncio
from types import SimpleNamespace

import pytest

from scripts.redis_production_adapters import DurableJournal, read_records
from stinky_core.transport.cooperative_shutdown import CooperativeParticipant
from stinky_core.transport.redis_accounting import AccountingError, Runtime, ClientFactory
from test_redis_writer_broker import broker, register
from test_redis_stream_integrity import proof


def fixture(tmp_path):
    owner={'pid':1,'creation_ticks':10,'service':'fixture',
           'command_sha256':'a'*64,'repository_sha256':'b'*64}
    ledger=SimpleNamespace(uncertain=False)
    def settled():
        if ledger.uncertain:raise AccountingError('Unresolved reply')
        return 3
    ledger.settled=settled
    runtime=Runtime(ledger,lambda:dict(owner),endpoint='isolated',server_epoch='c'*40,roles=['redis-streams'])
    journal=DurableJournal(tmp_path/'lifecycle.jsonl')
    def persist(row):journal.persist(row);return journal.previous
    producer={'accepting':True}
    def stop():producer['accepting']=False;return True
    participant=CooperativeParticipant(runtime,persist=persist,stop_admission=stop)
    request={'request_id':'d'*32,'manifest_sha256':participant.manifest()}
    return participant,runtime,ledger,journal,producer,owner,request


@pytest.mark.asyncio
async def test_concurrent_jobs_finish_before_durable_quiescence_and_cannot_resume(tmp_path):
    p,r,l,j,producer,owner,request=fixture(tmp_path)
    entered=[asyncio.Event(),asyncio.Event()];release=asyncio.Event()
    async def job(index):
        async with p.job():entered[index].set();await release.wait()
    tasks=[asyncio.create_task(job(i)) for i in range(2)]
    try:
        await asyncio.gather(*(e.wait() for e in entered))
        shutdown=asyncio.create_task(p.quiesce(request,timeout=1))
        await asyncio.sleep(0)
        assert r.fenced and not producer['accepting'] and not shutdown.done()
        with pytest.raises(AccountingError):
            async with p.job():pytest.fail('New work accepted')
        release.set();ack=await shutdown;await asyncio.gather(*tasks)
        assert ack['phase']=='QUIESCED' and ack['acknowledged']==3
        assert [v['phase'] for v in read_records(j.path,expected_head=ack['journal_head'])]==['FENCING','DRAINING','QUIESCED']
        with pytest.raises(AccountingError):r.resume_verified()
        with pytest.raises(AccountingError):await r.retire_and_reauthorize(endpoint='new',server_epoch='c'*40)
        with pytest.raises(AccountingError):await p.quiesce(request)
        assert p.phase=='HOLD' and r.held
    finally:release.set();await asyncio.gather(*tasks);j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['lost_reply','identity','epoch','generation','producer','audit','stale_request'])
async def test_failed_participant_cannot_claim_final_boundary(tmp_path,failure):
    p,r,l,j,producer,owner,request=fixture(tmp_path)
    if failure=='lost_reply':l.uncertain=True
    if failure=='identity':owner['creation_ticks']+=1
    if failure=='epoch':r.server_epoch='e'*40
    if failure=='generation':r.generation+=1
    if failure=='producer':p.stop_admission=lambda:False
    if failure=='audit':p.persist=lambda row:None
    if failure=='stale_request':request['manifest_sha256']='f'*64
    try:
        with pytest.raises(AccountingError):await p.quiesce(request,timeout=.05)
        assert r.held and r.fenced and p.phase=='HOLD'
        with pytest.raises(AccountingError):r.resume_verified()
    finally:j.close()


@pytest.mark.asyncio
async def test_timeout_does_not_cancel_or_kill_inflight_job(tmp_path):
    p,r,l,j,producer,owner,request=fixture(tmp_path);entered=asyncio.Event();release=asyncio.Event()
    async def job():
        async with p.job():entered.set();await release.wait()
    task=asyncio.create_task(job())
    try:
        await entered.wait()
        with pytest.raises(AccountingError,match='timed out'):await p.quiesce(request,timeout=.01)
        assert not task.done() and not task.cancelled() and r.held
        release.set();await task
        assert p.phase=='HOLD'
    finally:release.set();await task;j.close()


@pytest.mark.asyncio
async def test_pending_redis_operation_must_settle_before_phase_ack(tmp_path):
    p,r,l,j,producer,owner,request=fixture(tmp_path);r.inflight.add('issued')
    try:
        shutdown=asyncio.create_task(p.quiesce(request,timeout=1));await asyncio.sleep(0)
        assert not shutdown.done() and r.fenced
        r.inflight.remove('issued');ack=await shutdown
        assert ack['phase']=='QUIESCED'
    finally:j.close()


@pytest.mark.asyncio
async def test_job_crash_keeps_shutdown_held(tmp_path):
    p,r,l,j,producer,owner,request=fixture(tmp_path)
    try:
        with pytest.raises(ValueError):
            async with p.job():raise ValueError('Fixture job failed')
        with pytest.raises(AccountingError):await p.quiesce(request)
        assert r.held and r.fenced
    finally:j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('timeout',[0,-1,True,float('nan'),float('inf'),61,None])
async def test_invalid_deadline_does_not_change_running_authority(tmp_path,timeout):
    p,r,l,j,producer,owner,request=fixture(tmp_path)
    try:
        with pytest.raises(AccountingError):await p.quiesce(request,timeout=timeout)
        assert p.phase=='RUNNING' and not r.fenced and producer['accepting']
    finally:j.close()


def test_unregistered_native_owner_cannot_construct_participant(tmp_path):
    p,r,l,j,producer,owner,request=fixture(tmp_path)
    try:
        owner['creation_ticks']+=1
        with pytest.raises(AccountingError):CooperativeParticipant(r,persist=p.persist,stop_admission=lambda:True)
    finally:j.close()


@pytest.mark.asyncio
async def test_identity_change_during_final_audit_cannot_release_phase_ack(tmp_path):
    p,r,l,j,producer,owner,request=fixture(tmp_path);persist=p.persist
    def altered(row):
        head=persist(row)
        if row['phase']=='QUIESCED':owner['creation_ticks']+=1
        return head
    p.persist=altered
    try:
        with pytest.raises(AccountingError):await p.quiesce(request)
        assert p.phase=='HOLD' and r.held
    finally:j.close()


@pytest.mark.asyncio
async def test_shutdown_latch_rejects_new_pools_before_credential_issuance(tmp_path):
    p,r,l,j,producer,owner,request=fixture(tmp_path)
    factory=ClientFactory();factory.configure(r)
    try:
        await p.quiesce(request)
        with pytest.raises(AccountingError,match='new client credentials'):
            factory.from_url('redis://127.0.0.1:16589/0',role='redis-streams')
        with pytest.raises(AccountingError,match='new client registration'):
            r.check(SimpleNamespace(role='redis-streams',route_generation=1),read_only=True)
    finally:j.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[None,'unknown_writer','duplicate_ack','stale_request',
                                   'wrong_phase','journal_corruption','connection',
                                   'uncertain','identity','source_change','audit'])
async def test_controller_requires_every_native_durable_participant_and_stable_source(tmp_path,broker,failure):
    import copy
    from scripts.genesis_cooperative_boundary import certify_participants
    b,l,owner,writer,credentials=broker;register(b,owner,writer)
    r=Runtime(l,lambda:dict(owner),endpoint='original',server_epoch='c'*40,
              roles=['redis-streams'],credentials=credentials)
    phases=DurableJournal(tmp_path/'phases');audit=DurableJournal(tmp_path/'boundary')
    def persist(row):phases.persist(row);return phases.previous
    participant=CooperativeParticipant(r,persist=persist,stop_admission=lambda:True)
    req={'request_id':'e'*32,'manifest_sha256':participant.manifest()}
    ack=await participant.quiesce(req)
    args=dict(request_id='e'*32,acknowledgements=[ack],journals={1:phases.path},
              inspect_connections=lambda:[11],census=proof,audit=audit,timeout=.1)
    def revoke():
        credentials.fenced=True;credentials.revocations+=1
        return {'status':'REVOKED','verified':True,'durable':True}
    credentials.revoke_all=revoke
    if failure=='unknown_writer':ack['owner']['pid']=2
    if failure=='duplicate_ack':args['acknowledgements']=[ack,copy.deepcopy(ack)]
    if failure=='stale_request':args['request_id']='f'*32
    if failure=='wrong_phase':ack['phase']='DRAINING'
    if failure=='journal_corruption':phases.path.write_bytes(b'corrupted')
    if failure=='connection':args['inspect_connections']=lambda:[11,90]
    if failure=='uncertain':l.uncertain.add(99)
    if failure=='identity':owner['creation_ticks']+=1
    if failure=='source_change':
        first=proof();second=copy.deepcopy(first);second['keys'][0]['stable']['entries'][0]['payload_sha256']='f'*64
        values=iter([first,second]);args['census']=lambda:next(values)
    if failure=='audit':audit.failed=True
    try:
        if failure:
            with pytest.raises((AccountingError,KeyError,ValueError)):certify_participants(b,**args)
            assert b.held and b.fenced
        else:
            boundary=certify_participants(b,**args)
            assert boundary['phase']=='WRITERS_FENCED_DRAINED' and b.fenced and not b.held
            assert read_records(audit.path,expected_head=boundary['journal_head'])[0]['stage']=='COOPERATIVE_WRITER_BOUNDARY'
    finally:phases.close();audit.close()
