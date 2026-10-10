import asyncio,json,hashlib
from types import SimpleNamespace
import pytest
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from stinky_core.transport import redis_accounting as adapter
from scripts.redis_production_adapters import ProductionAcknowledgements,DurableJournal,read_records,writer_id

OWNER={'pid':1,'creation_ticks':10,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64}
ROLE='redis-streams'
COMMANDS=[(('XADD','key','*','data',b'\x00\xff'),'1-0'),
          (('LPUSH','queue','SYNTHETIC_SECRET_PAYLOAD'),1),
          (('SET','dedupe','1','EX',172800),True),(('XGROUP CREATE','key','group','0','MKSTREAM'),True),
          (('XREADGROUP','GROUP','group','consumer','COUNT',20,'BLOCK',5000,'STREAMS','key','>'),[[b'key',[(b'1-0',{b'data':b'value'})]]]),
          (('XACK','key','group','1-0'),1),(('XAUTOCLAIM','key','group','consumer',0,'0-0','COUNT',20),[b'0-0',[(b'1-0',{b'data':b'value'})],[]]),
          (('XCLAIM','key','group','consumer',0,'1-0'),[(b'1-0',{b'data':b'value'})])]

@pytest.fixture
def harness(tmp_path,monkeypatch):
    owner=dict(OWNER);journal=DurableJournal(tmp_path/'journal.jsonl');ledger=ProductionAcknowledgements(journal,[writer_id(owner,ROLE)])
    runtime=adapter.Runtime(ledger,lambda:dict(owner),endpoint='original',server_epoch='c'*40,roles=[ROLE])
    factory=adapter.ClientFactory();factory.configure(runtime)
    client=factory.from_url('redis://127.0.0.1:16566/0',role=ROLE)
    client.connection=SimpleNamespace(accounting_bound=False)
    calls=[];behavior={'reply':'1-0','exception':None,'wait':None}
    async def execute(self,*args,**kwargs):
        if args[0]=='CLIENT ID':return 11
        if args[0]=='INFO':return {'run_id':'c'*40}
        calls.append(args)
        assert read_records(journal.path,expected_head=journal.previous)[-1]['stage']=='COMMAND_INTENT'
        if behavior['wait']:await behavior['wait'].wait()
        if behavior['exception']:raise behavior['exception']
        return behavior['reply']
    async def close(self,*a,**k):pass
    monkeypatch.setattr(Redis,'execute_command',execute);monkeypatch.setattr(Redis,'aclose',close)
    yield client,runtime,ledger,journal,calls,behavior,owner
    client.connection=None
    journal.close()

@pytest.mark.parametrize('args,reply',COMMANDS)
def test_real_command_api_records_durable_intent_and_typed_reply(harness,args,reply):
    c,r,l,j,calls,b,_=harness;b['reply']=reply
    assert asyncio.run(c.execute_command(*args))==reply
    assert len(calls)==1 and l.settled()==1
    rows=read_records(j.path,expected_head=j.previous);assert [x['stage'] for x in rows]==['CONNECTION_REGISTERED','COMMAND_INTENT','COMMAND_REPLY']
    assert rows[1]['connection_id']==11 and rows[1]['generation']==1
    assert 'SYNTHETIC_SECRET_PAYLOAD' not in j.path.read_text()  # Payloads stored only as fingerprints.

@pytest.mark.parametrize('exception',[TimeoutError(),ConnectionError(),ResponseError('WRONGTYPE')])
def test_lost_or_uncertified_reply_holds_writer_and_never_replays(harness,exception):
    c,r,l,j,calls,b,_=harness;b['exception']=exception
    with pytest.raises(adapter.AmbiguousMutation):asyncio.run(c.lpush('queue','value'))
    assert len(calls)==1 and r.held
    with pytest.raises(RuntimeError,match='Unresolved'):l.settled()
    with pytest.raises(adapter.AccountingError):asyncio.run(c.lpush('queue','value'))
    assert len(calls)==1

def test_group_exists_is_explicit_no_effect_receipt(harness):
    c,r,l,j,calls,b,_=harness;b['exception']=ResponseError('BUSYGROUP Consumer Group name already exists')
    with pytest.raises(ResponseError):asyncio.run(c.xgroup_create('key','group','0'))
    assert l.settled()==1 and not r.held

def test_blocking_nil_group_reply_is_known_not_unknown(harness):
    c,r,l,j,calls,b,_=harness;b['reply']=None
    assert asyncio.run(c.xreadgroup('group','consumer',{'key':'>'},block=5000)) is None and l.settled()==1

def test_destructive_list_pop_is_unsupported_before_any_dispatch(harness):
    c,r,l,j,calls,b,_=harness
    with pytest.raises(adapter.AccountingError,match='durable processing'):asyncio.run(c.brpop('queue',5))
    assert calls==[] and not l.commands

@pytest.mark.parametrize('args',[('FLUSHALL',),('EVAL','return 1',0),('BRPOP','queue',0),('SET','key','value'),('XGROUP DESTROY','key','group'),('XREADGROUP','GROUP','g','c','BLOCK',0,'STREAMS','key','>')])
def test_unsupported_or_unbounded_operations_rejected_before_mutation(harness,args):
    c,r,l,j,calls,b,_=harness
    with pytest.raises(adapter.AccountingError):asyncio.run(c.execute_command(*args))
    assert calls==[] and not l.commands

def test_pid_reuse_and_stale_route_generation_fenced(harness):
    c,r,l,j,calls,b,owner=harness;owner['creation_ticks']+=1
    with pytest.raises(adapter.AccountingError,match='ownership'):asyncio.run(c.xadd('key',{'data':'value'}))
    owner['creation_ticks']-=1;r.generation+=1
    with pytest.raises(adapter.AccountingError,match='generation'):asyncio.run(c.xadd('key',{'data':'value'}))
    assert calls==[]

def test_unknown_connection_fails_even_if_it_spoofs_a_registered_name(harness):
    c,r,l,j,calls,b,_=harness;asyncio.run(c.xadd('key',{'data':'value'}));r.fenced=True
    with pytest.raises(adapter.AccountingError,match='physical'):r.verify_connections([11,12])
    assert r.verify_connections([11])==[11]

def test_quiesce_drains_an_inflight_command_before_gate(harness):
    c,r,l,j,calls,b,_=harness
    async def run():
        event=asyncio.Event();b.update(wait=event,reply=1)
        task=asyncio.create_task(c.lpush('queue','value'))
        while not r.inflight:await asyncio.sleep(0)
        gate=asyncio.create_task(r.quiesce());await asyncio.sleep(.001)
        assert r.fenced and not gate.done()
        event.set();assert await task==1;assert await gate==1
        assert r.verify_connections([11])==[11]
        with pytest.raises(adapter.AccountingError):await c.lpush('queue','value')
    asyncio.run(run())

def test_drain_timeout_does_not_cancel_or_silently_settle_mutation(harness):
    c,r,l,j,calls,b,_=harness
    async def run():
        event=asyncio.Event();b.update(wait=event,reply=1);task=asyncio.create_task(c.lpush('queue','value'))
        while not r.inflight:await asyncio.sleep(0)
        with pytest.raises(adapter.AccountingError,match='drain'):await r.quiesce(timeout=.001)
        assert not task.done() and r.held
        with pytest.raises(RuntimeError,match='Unresolved'):l.settled()
        event.set();await task;assert l.settled()==1 and r.held
    asyncio.run(run())

def test_journal_reply_failure_preserves_unknown_and_blocks_replay(harness,monkeypatch):
    c,r,l,j,calls,b,_=harness;b['reply']=1;original=j.persist
    def persist(record):
        if record['stage']=='COMMAND_REPLY':raise OSError('synthetic disk error')
        return original(record)
    monkeypatch.setattr(j,'persist',persist)
    with pytest.raises(adapter.AmbiguousMutation):asyncio.run(c.lpush('queue','value'))
    assert len(calls)==1
    with pytest.raises(RuntimeError,match='Unresolved'):l.settled()

def test_default_factory_remains_legacy_and_cannot_be_hot_reconfigured(harness):
    _,r,*_=harness;f=adapter.ClientFactory();calls=[]
    marker=object();assert f.from_url('fixture',role=ROLE,legacy_factory=lambda *a,**kw:(calls.append((a,kw)) or marker),socket_timeout=3) is marker
    assert calls==[(('fixture',),{'socket_timeout':3})]
    with pytest.raises(adapter.AccountingError,match='replacement'):f.configure(r)

def test_pipeline_and_child_client_cannot_bypass_accounting(harness):
    c,*_=harness
    with pytest.raises(adapter.AccountingError):c.pipeline()
    with pytest.raises(adapter.AccountingError):c.client()

def test_bound_connection_cannot_reconnect_to_new_generation():
    c=adapter.FencedConnection();c.accounting_bound=True
    with pytest.raises(adapter.AccountingError,match='reconnect'):asyncio.run(c.connect())

def test_partial_or_corrupted_journal_is_not_a_settled_reply(tmp_path):
    p=tmp_path/'journal';j=DurableJournal(p);j.persist({'stage':'COMMAND_INTENT'});j.close()
    original=p.read_bytes();head=j.previous;p.write_bytes(original[:-1])
    with pytest.raises(adapter.AccountingError,match='truncated'):read_records(p,expected_head=head)
    p.write_bytes(original.replace(b'COMMAND_INTENT',b'COMMAND_REPLY'))
    with pytest.raises(adapter.AccountingError,match='head'):read_records(p,expected_head=head)
    p.write_bytes(original+original)
    with pytest.raises(adapter.AccountingError,match='ordering'):read_records(p,expected_head=head)

def test_journal_intent_disk_failure_prevents_dispatch(harness,monkeypatch):
    c,r,l,j,calls,b,_=harness;original=j.persist
    def fail(row):
        if row['stage']=='COMMAND_INTENT':raise OSError('synthetic fsync failure')
        original(row)
    monkeypatch.setattr(j,'persist',fail)
    with pytest.raises(OSError):asyncio.run(c.lpush('queue','value'))
    assert calls==[] and not l.commands

@pytest.mark.parametrize('uri',['redis://127.0.0.1:16566/0?retry_on_timeout=True','rediss://127.0.0.1:16566/0'])
def test_url_cannot_override_retry_or_physical_fencing(harness,uri):
    _,r,*_=harness;f=adapter.ClientFactory();f.configure(r)
    with pytest.raises(adapter.AccountingError):f.from_url(uri,role=ROLE)


def test_known_generation_requires_close_and_drained_reauthorization(harness):
    c,r,l,j,calls,b,_=harness;asyncio.run(c.xadd('key',{'data':'value'}))
    with pytest.raises(adapter.AccountingError):asyncio.run(r.retire_and_reauthorize(endpoint='replacement',server_epoch='d'*40))
    async def run():
        await r.quiesce();await r.retire_and_reauthorize(endpoint='replacement',server_epoch='d'*40)
        assert c.retired and r.generation==2 and r.server_epoch=='d'*40
        with pytest.raises(adapter.AccountingError):await c.xadd('key',{'data':'value'})
    asyncio.run(run());assert len(calls)==1


def test_full_snapshot_gate_still_rejects_acknowledged_append_missing_from_retention(harness):
    from test_redis_stream_integrity import proof
    c,r,l,j,calls,b,_=harness;asyncio.run(c.xadd('key',{'data':'value'}))
    with pytest.raises(RuntimeError,match='missing or altered'):l.verify(proof())

@pytest.mark.parametrize('rules',['+@all','-@all +xadd','-@all +@write','-@all +client|id +eval'])
def test_anonymous_or_unregistered_principal_cannot_be_called_fenced(rules):
    from scripts.redis_production_adapters import verify_default_write_fence
    with pytest.raises(adapter.AccountingError):verify_default_write_fence(rules)


def test_read_only_server_principal_fence_is_explicit():
    from scripts.redis_production_adapters import verify_default_write_fence
    assert verify_default_write_fence({'categories':['-@all'],'commands':['+ping','+info','+client|id','+client|list'],'selectors':[],'flags':['on','nopass']})

def test_complete_acl_policy_rejects_categories_and_selectors():
    from scripts.redis_production_adapters import verify_default_write_fence
    policy={'categories':['-@all'],'commands':['+ping'],'selectors':[],'flags':['on','nopass']}
    for patch in ({'categories':['+@all']},{'selectors':[['commands','+@all']]},{'commands':['+ping','+set']},{'flags':[]}):
        with pytest.raises(adapter.AccountingError):verify_default_write_fence(policy|patch)

@pytest.mark.parametrize('reply',[None,'1',True,-1])
def test_partial_or_malformed_list_acknowledgement_is_unresolved(harness,reply):
    c,r,l,j,calls,b,_=harness;b['reply']=reply
    with pytest.raises(adapter.AmbiguousMutation):asyncio.run(c.lpush('queue','value'))
    assert len(calls)==1 and r.held
    with pytest.raises(RuntimeError,match='Unresolved'):l.settled()

def test_scope_verified_credentials_cannot_target_production_port(harness,monkeypatch):
    from scripts.redis_production_adapters import SealedCredentials
    from test_redis_migration_coordinator import scope
    records=scope();records[0]['Name']='/genesis-redis-c66-test';records[0]['Config']['Labels']['genesis.certification']='checkpoint66';records[0]['Mounts'][0]['Name']='project-genesis_checkpoint66-test';records[0]['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort']='16566';records[0]['State']['Running']=True;records[0]['State']['Status']='running'
    records=records[:1];calls=[]
    admin=SimpleNamespace(connection_pool=SimpleNamespace(connection_kwargs={'host':'127.0.0.1','port':6380,'db':0}),close=lambda:calls.append('closed'))
    c,r,l,j,*_=harness;manager=SealedCredentials(lambda:admin,lambda:records,lambda:OWNER,j)
    with pytest.raises(adapter.AccountingError,match='endpoint'):manager.checked_admin()
    assert calls==['closed']

def test_native_writer_provider_uses_ancestry_and_rechecks_creation(tmp_path,monkeypatch):
    from scripts import genesis_process_diagnostics as diagnostics
    from scripts.redis_production_adapters import native_writer_verifier
    import os
    pid=os.getpid();path=r'c:\fixture\python.exe';ticks=[42]
    snapshot={'nodes':[{'pid':pid,'parent_pid':9,'creation_ticks':42,'image_path':path,'role':'owned-descendant','command_sha256':'a'*64},{'pid':9,'parent_pid':0,'creation_ticks':40,'image_path':path,'role':'supervisor:collector','command_sha256':'b'*64}]}
    monkeypatch.setattr(diagnostics,'capture_native',lambda *a:snapshot)
    monkeypatch.setattr(diagnostics,'native_identity',lambda *a:(ticks[0],path))
    verifier=native_writer_verifier(SimpleNamespace(ROOT=tmp_path),object());assert verifier()['service']=='collector'
    ticks[0]+=1
    with pytest.raises(adapter.AccountingError,match='PID reuse'):verifier()

def test_service_role_cannot_be_registered_under_another_native_owner(harness):
    c,r,l,j,*_=harness;owner=OWNER|{'service':'api'}
    with pytest.raises(adapter.AccountingError,match='role contradicts'):
        adapter.Runtime(l,lambda:owner,endpoint='original',server_epoch='c'*40,roles=['entity-consumer'],credentials=object())
