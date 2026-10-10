from copy import deepcopy
from contextlib import contextmanager
from types import SimpleNamespace
import time,json
import pytest
from scripts.redis_migration_coordinator import Coordinator,Acknowledgements,verify_isolated_scope,IMAGE
from scripts.genesis_identity_journal import IdentityJournal
from test_redis_stream_integrity import proof
from test_genesis_process_diagnostics import snapshot

PAYLOAD=[b'field',b'value',b'field',b'\x00\xff']
HEALTH={'aof_enabled':1,'aof_rewrite_in_progress':0,'aof_rewrite_scheduled':0,'aof_last_write_status':'ok','aof_last_bgrewrite_status':'ok'}


def scope():
    return [{'Id':f'{i+1:064x}','State':{'Running':False,'Paused':False,'Status':'created'},'Name':'/genesis-redis-c61-'+name,'Image':IMAGE,
             'Config':{'Labels':{'genesis.certification':'checkpoint61','com.docker.compose.project':'project-genesis','com.docker.compose.service':'redis'},'Cmd':['redis-server','/data/redis.conf']},
             'Mounts':[{'Type':'volume','Name':'project-genesis_checkpoint61-'+name,'Destination':'/data','RW':True}],
             'HostConfig':{'PortBindings':{'6379/tcp':[{'HostIp':'127.0.0.1','HostPort':str(16470+i)}]}}}
            for i,name in enumerate(('original','replacement','rollback'))]


class Backend:
    original='original'
    def __init__(self,root,failure=None):
        self.identity=snapshot(root);self.data={self.original:proof()};self.live={self.original:True};self.events=[];self.failure=failure;self.held=False
    def scope(self):return scope()
    def inject(self,name):
        if self.failure==name:self.failure=None;raise RuntimeError('Injected '+name)
    def capture_identity(self,phase):
        data=deepcopy(self.identity);data['captured_at_monotonic_ns']=time.monotonic_ns()
        if self.failure=='identity' and phase=='DURING':data['nodes'][0]['creation_ticks']+=1
        return data
    @contextmanager
    def fence(self):
        self.events.append('FENCED')
        try:yield
        finally:self.events.append('UNFENCED')
    def writer_inventory(self):
        return {'registered':['writer'],'unknown':['foreign'] if self.failure=='writer' else [],'inflight':0,'fenced':True,'observed_connection_ids':[1],'verified_connection_ids':[1],'owner_pid':10,'owner_creation_ticks':1000}
    def census(self,name):return deepcopy(self.data[name])
    def snapshot(self,name):
        self.inject('snapshot');return {'proof':self.census(name),'checksum_verified':True}
    def prepare(self,name,boundary):
        self.inject('prepare');self.data[name]=deepcopy(boundary['proof'])
    def persistence(self,name):return deepcopy(HEALTH),'always'
    def fsync_confirmed(self,name):return True
    def recovery_proof(self,name):return self.census(name),(0,10000000000000)
    def deactivate(self,name):self.live[name]=False;self.inject('deactivate')
    def exclusive_route(self,name):
        self.inject('route');self.live={n:False for n in self.live};self.live[name]=True
    def reconnect(self,name):self.inject('reconnect');self.events.append('CONNECTED:'+name)
    def restore_abort(self,boundary):
        self.data['rollback']=deepcopy(boundary['proof']);return 'rollback'
    def running(self,name):return self.live.get(name,False)
    def hold(self):self.held=True


def setup(tmp_path,failure=None):
    journal=IdentityJournal(tmp_path/'journal');ledger=Acknowledgements(journal,['writer'])
    token=ledger.begin('writer',b'key',PAYLOAD)
    # proof() uses a fixed synthetic key hash: match it to the real key digest.
    backend=Backend(tmp_path,failure);backend.data['original']['keys'][0]['key_sha256']=__import__('hashlib').sha256(b'key').hexdigest()
    ledger.acknowledged(token,'1-0','original')
    return Coordinator(backend,journal,ledger),backend,ledger


def test_complete_route_and_current_rollback(tmp_path):
    c,b,l=setup(tmp_path)
    assert c.move('replacement')=='ROUTED'
    assert c.rollback('rollback')=='ROUTED' and c.current=='rollback'
    assert sum(b.live.values())==1 and not b.held


@pytest.mark.parametrize('stage',['snapshot','prepare','deactivate','route','reconnect'])
def test_abort_at_each_stage_preserves_acked_payload_and_single_route(tmp_path,stage):
    c,b,l=setup(tmp_path,stage)
    with pytest.raises(RuntimeError,match='aborted'):c.move('replacement')
    assert c.state=='ABORTED_VERIFIED'
    assert l.verify(b.census(c.current))['acknowledged']==1
    assert sum(b.live.values())==1
    records=[json.loads(p.read_text()) for p in c.journal.directory.glob('*.json')]
    assert any(r.get('stage')=='GATE_FAILED' for r in records)


@pytest.mark.parametrize('failure',['identity','writer'])
def test_process_change_or_unknown_writer_fails_closed(tmp_path,failure):
    c,b,l=setup(tmp_path,failure)
    with pytest.raises(RuntimeError):c.move('replacement')
    assert b.live['original'] and not b.live.get('replacement',False)
    assert list(c.journal.directory.glob('*.json'))


def test_missing_acknowledged_payload_cannot_be_silently_restored(tmp_path):
    c,b,l=setup(tmp_path)
    b.data['original']['keys'][0]['stable']['entries'][0]['payload_sha256']='f'*64
    with pytest.raises(RuntimeError):c.move('replacement')
    assert c.state=='HOLD' and b.held and b.live['original']


def test_unknown_reply_prevents_cutover_and_stale_abort_claim(tmp_path):
    c,b,l=setup(tmp_path);l.begin('writer',b'key',PAYLOAD)
    with pytest.raises(RuntimeError):c.move('replacement')
    assert c.state=='HOLD' and b.held and b.live['original']


def test_postcutover_reply_missing_from_current_source_blocks_rollback(tmp_path):
    c,b,l=setup(tmp_path);c.move('replacement')
    t=l.begin('writer',b'key',PAYLOAD);l.acknowledged(t,'2-0','replacement')
    with pytest.raises(RuntimeError):c.rollback('rollback')
    assert c.state=='HOLD' and b.live['replacement']


def test_postcutover_acknowledgements_use_fresh_rollback_not_old_boundary(tmp_path):
    c,b,l=setup(tmp_path);c.move('replacement');old=deepcopy(c.boundary)
    value=b.data['replacement']['keys'][0]['stable']
    value['entries'].append({**value['entries'][0],'id':'2-0'})
    value['length']=value['entries-added']=2;value['last-generated-id']='2-0';value['groups'][0]['lag']=1
    t=l.begin('writer',b'key',PAYLOAD);l.acknowledged(t,'2-0','replacement')
    assert c.rollback('rollback')=='ROUTED'
    assert l.verify(b.census('rollback'))['acknowledged']==2
    assert c.boundary!=old and len(c.boundary['proof']['keys'][0]['stable']['entries'])==2


def test_lost_reply_or_failed_reply_journal_never_counts_as_acknowledged(tmp_path,monkeypatch):
    c,b,l=setup(tmp_path);t=l.begin('writer',b'key',PAYLOAD)
    def disk_failure(_):raise OSError('isolated disk failure')
    monkeypatch.setattr(l.journal,'persist',disk_failure)
    with pytest.raises(OSError):l.acknowledged(t,'2-0','replacement')
    with pytest.raises(RuntimeError,match='Unresolved'):l.settled()


def test_secret_endpoint_is_not_persisted(tmp_path):
    l=Acknowledgements(IdentityJournal(tmp_path),['writer']);t=l.begin('writer',b'key',PAYLOAD)
    with pytest.raises(RuntimeError):l.acknowledged(t,'1-0','redis://user:secret@host')
    assert all('secret' not in p.read_text() for p in tmp_path.glob('*.json'))


def test_original_volume_cannot_be_chosen_as_restore_target(tmp_path):
    c,b,l=setup(tmp_path)
    with pytest.raises(RuntimeError):c.move('original')
    assert b.live['original']


def test_metadata_replies_are_explicitly_settled(tmp_path):
    c,b,l=setup(tmp_path)
    token=l.begin_metadata('writer','XACK',[b'key',b'group',b'1-0'])
    with pytest.raises(RuntimeError,match='Unresolved'):l.settled()
    l.acknowledged_metadata(token,b'1','original')
    assert l.verify(b.census('original'))['acknowledged']==2


def test_unknown_metadata_operation_cannot_mutate_through_the_ledger(tmp_path):
    c,b,l=setup(tmp_path)
    with pytest.raises(RuntimeError):l.begin_metadata('writer','FLUSHALL',[b'key'])
    assert l.settled()==1


def test_spoofed_client_name_without_registered_connection_id_is_rejected(tmp_path,monkeypatch):
    c,b,l=setup(tmp_path)
    original=b.writer_inventory
    def unowned():
        data=original();data['observed_connection_ids']=[1,2];return data
    monkeypatch.setattr(b,'writer_inventory',unowned)
    with pytest.raises(RuntimeError):c.move('replacement')
    assert c.state=='HOLD' and b.live['original']


def test_persistent_snapshot_failure_cannot_claim_recoverable_abort(tmp_path,monkeypatch):
    c,b,l=setup(tmp_path)
    def unavailable(_):raise OSError('isolated disk unavailable')
    monkeypatch.setattr(b,'snapshot',unavailable)
    with pytest.raises(RuntimeError):c.move('replacement')
    assert c.state=='HOLD' and b.live['original'] and b.held


def test_unregistered_postroute_write_cannot_be_discarded_by_old_boundary(tmp_path,monkeypatch):
    c,b,l=setup(tmp_path)
    def late_reply(name):
        data=b.data[name]['keys'][0]['stable']
        data['entries'].append({**data['entries'][0],'id':'2-0'})
        data['length']=data['entries-added']=2;data['last-generated-id']='2-0';data['groups'][0]['lag']=1
        raise RuntimeError('Injected lost reconnection response')
    monkeypatch.setattr(b,'reconnect',late_reply)
    with pytest.raises(RuntimeError):c.move('replacement')
    assert c.state=='HOLD' and b.live['replacement'] and b.held
    assert len(b.data['replacement']['keys'][0]['stable']['entries'])==2
    assert 'rollback' not in b.data


def test_missing_scope_activity_and_duplicate_volume_writers_fail_closed():
    records=scope();del records[0]['State']
    with pytest.raises(RuntimeError):verify_isolated_scope(records)
    records=scope()
    for r in records[:2]:r['State'].update(Running=True,Status='running')
    records[1]['Mounts']=deepcopy(records[0]['Mounts'])
    with pytest.raises(RuntimeError,match='Competing'):verify_isolated_scope(records)


def test_writer_owner_creation_discrepancy_cannot_authorize_route(tmp_path,monkeypatch):
    c,b,l=setup(tmp_path);original=b.writer_inventory
    def changed():
        result=original();result['owner_creation_ticks']+=1;return result
    monkeypatch.setattr(b,'writer_inventory',changed)
    with pytest.raises(RuntimeError):c.move('replacement')
    assert c.state=='HOLD' and b.live['original']


def test_unknown_writer_cannot_issue_intent(tmp_path):
    l=Acknowledgements(IdentityJournal(tmp_path),['writer'])
    with pytest.raises(RuntimeError):l.begin('foreign',b'key',PAYLOAD)
    assert not l.commands


@pytest.mark.parametrize('kind',['production_name','production_port','atlas_volume','image','label','command'])
def test_production_or_unowned_scope_never_reaches_coordinator_control(kind):
    records=scope();r=records[0]
    if kind=='production_name':r['Name']='/stinky-redis'
    if kind=='production_port':r['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort']='6380'
    if kind=='atlas_volume':r['Mounts'][0]['Name']='projectatlas_atlas_redis'
    if kind=='image':r['Image']='unknown'
    if kind=='label':r['Config']['Labels']={}
    if kind=='command':r['Config']['Cmd']+=['--appendonly','no']
    with pytest.raises(RuntimeError):verify_isolated_scope(records)

def test_writer_fence_entry_failure_holds_without_stopping_source(tmp_path,monkeypatch):
    c,b,l=setup(tmp_path)
    @contextmanager
    def failure():
        raise RuntimeError('Unresolved drain')
        yield
    monkeypatch.setattr(b,'fence',failure)
    with pytest.raises(RuntimeError,match='quiescence'):c.move('replacement')
    assert c.state=='HOLD' and b.held and b.live['original']
    assert 'replacement' not in b.data

def test_writer_fence_exit_failure_does_not_claim_routed_success(tmp_path,monkeypatch):
    c,b,l=setup(tmp_path)
    @contextmanager
    def failure():
        yield
        raise RuntimeError('Release failed')
    monkeypatch.setattr(b,'fence',failure)
    with pytest.raises(RuntimeError,match='release'):c.move('replacement')
    assert c.state=='HOLD' and b.held and b.live['replacement']
    assert l.verify(b.census('replacement'))['acknowledged']==1

def test_checkpoint66_namespace_requires_exact_label_volume_and_isolated_port():
    record=scope()[0];record['Name']='/genesis-redis-c66-proof'
    record['Config']['Labels']['genesis.certification']='checkpoint66'
    record['Mounts'][0]['Name']='project-genesis_checkpoint66-proof'
    record['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort']='16566'
    verify_isolated_scope([record])
    for field in ('label','volume','port','name'):
        bad=deepcopy(record)
        if field=='label':bad['Config']['Labels']['genesis.certification']='checkpoint61'
        elif field=='volume':bad['Mounts'][0]['Name']='project-genesis_redis-data'
        elif field=='port':bad['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort']='6380'
        else:bad['Name']='/stinky-redis'
        with pytest.raises(RuntimeError):verify_isolated_scope([bad])
