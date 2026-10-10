import json
from types import SimpleNamespace

import pytest
from stinky_core.transport.redis_accounting import AccountingError,reply_bytes
from scripts.redis_production_adapters import DurableJournal,ProductionAcknowledgements,writer_id
from scripts.redis_writer_broker import WriterBroker,RetentionBoundary,pack,unpack,ProductionCredentials,PinnedRedisScope

OWNER={'pid':1,'creation_ticks':10,'service':'fixture','command_sha256':'a'*64,'repository_sha256':'b'*64}

@pytest.fixture
def broker(tmp_path):
    journal=DurableJournal(tmp_path/'broker.jsonl')
    owner=dict(OWNER);w=writer_id(owner,'redis-streams')
    ledger=ProductionAcknowledgements(journal,[w])
    credentials=SimpleNamespace(revocations=0,fenced=False)
    def revoke():credentials.revocations+=1;credentials.fenced=True
    credentials.revoke_all=revoke
    credentials.set_fenced=lambda v:setattr(credentials,'fenced',v)
    credentials.verify_principals=lambda:True
    credentials.is_bound=lambda *args:True
    credentials.issue=lambda *a:a
    credentials.seal=lambda *a:a
    b=WriterBroker(ledger,credentials,{1:dict(owner)},lambda pid:dict(owner),RetentionBoundary({'maxmemory-policy':'noeviction'},0),server_epoch='c'*40,endpoint='original')
    yield b,ledger,owner,w,credentials
    journal.close()

def request(b,method,*args):
    return b.dispatch(1,{'sequence':b.sequences.get(1,0)+1,'method':method,'args':list(args)})

def register(b,owner,w):request(b,'register_connection',w,owner,11,'c'*40,1)

def test_ipc_typed_roundtrip_preserves_payload_bytes_and_dict_key_types():
    value=[b'\x00\xff',{b'key':[(b'1-0',{b'data':b'payload'})]},None,False,12]
    assert unpack(json.loads(json.dumps(pack(value))))==value

def test_ipc_shape_and_nesting_fail_closed():
    with pytest.raises(AccountingError):unpack({'unexpected':'value'})
    value={'list':[None]}
    for _ in range(22):value={'list':[value]}
    with pytest.raises(AccountingError):unpack(value)

def test_registered_attempts_settle_before_boundary(broker):
    b,l,o,w,c=broker;register(b,o,w)
    token=request(b,'begin_command',w,'XADD',[b'key',b'*',b'data',b'payload'],11,1)
    request(b,'complete_command',token,b'1-0',reply_bytes(b'1-0'),'original')
    assert b.quiesce([11])==1 and b.fenced and c.fenced
    with pytest.raises(AccountingError):request(b,'begin_command',w,'XADD',[b'key',b'*',b'data',b'later'],11,1)
    assert len(l.commands)==1 and b.held

def test_lost_reply_prevents_quiescence_and_revokes_credentials(broker):
    b,l,o,w,c=broker;register(b,o,w)
    request(b,'begin_command',w,'LPUSH',[b'queue',b'item'],11,1)
    with pytest.raises(RuntimeError,match='Unresolved'):b.quiesce([11])
    assert b.held and c.revocations==1 and l.commands[1]['state']=='ISSUED'

@pytest.mark.parametrize('observed',[[],[11,12],[11,11]])
def test_disconnected_unknown_or_duplicate_connections_block_boundary(broker,observed):
    b,l,o,w,c=broker;register(b,o,w)
    with pytest.raises(AccountingError):b.quiesce(observed)
    assert b.held and c.revocations==1

def test_pid_reuse_blocks_new_dispatch(broker):
    b,l,o,w,c=broker;register(b,o,w);o['creation_ticks']+=1
    with pytest.raises(AccountingError):request(b,'begin_command',w,'LPUSH',[b'q',b'v'],11,1)
    assert b.held and not l.commands

def test_unregistered_native_peer_cannot_issue_credentials(broker):
    b,l,o,w,c=broker
    with pytest.raises(AccountingError):b.dispatch(2,{'sequence':1,'method':'issue','args':[o,'redis-streams',1,'c'*40]})
    assert b.held

def test_replayed_request_is_not_redis_replay(broker):
    b,l,o,w,c=broker;register(b,o,w)
    with pytest.raises(AccountingError):b.dispatch(1,{'sequence':1,'method':'settled','args':[]})
    assert b.held and not l.commands

def test_credential_seal_binds_verified_owner_in_original_argument_order(broker):
    b,l,o,w,c=broker;ticket={'username':'fixture'}
    assert request(b,'seal',o,ticket,'redis-streams',1,'c'*40,11)==(ticket,o,'redis-streams',1,'c'*40,11)

@pytest.mark.parametrize('method',['eval','flushall','__class__','resume','shutdown'])
def test_public_broker_method_allowlist(broker,method):
    b,l,o,w,c=broker
    with pytest.raises(AccountingError):request(b,method)
    assert b.held

@pytest.mark.parametrize('args',[[b'key',b'MAXLEN',b'~',b'20000',b'*',b'data',b'v'],[b'key',b'MINID',b'100',b'*',b'data',b'v']])
def test_retention_is_blocked_before_command_intent(broker,args):
    b,l,o,w,c=broker;register(b,o,w)
    with pytest.raises(AccountingError,match='retention'):request(b,'begin_command',w,'XADD',args,11,1)
    assert not l.commands and b.held

def test_expiry_is_not_fabricated_as_a_retention_receipt(broker):
    b,l,o,w,c=broker;register(b,o,w)
    with pytest.raises(AccountingError):request(b,'begin_command',w,'SET',[b'k',b'v',b'EX',b'60'],11,1)
    assert not l.commands

@pytest.mark.parametrize('policy',['allkeys-lru','volatile-lru','allkeys-random','unknown',None])
def test_eviction_configuration_blocks_preservation_epoch(policy):
    with pytest.raises(AccountingError):RetentionBoundary({'maxmemory-policy':policy},0)

@pytest.mark.parametrize('expires',[1,None,-1,True])
def test_missing_or_nonzero_expiration_evidence_fails_closed(expires):
    with pytest.raises(AccountingError):RetentionBoundary({'maxmemory-policy':'noeviction'},expires)

def test_brpop_is_rejected_before_intent_and_revokes_actor(broker):
    b,l,o,w,c=broker;register(b,o,w)
    with pytest.raises(AccountingError,match='durable processing'):request(b,'begin_command',w,'BRPOP',[b'queue',b'5'],11,1)
    assert not l.commands and b.held

def test_malformed_manifest_is_not_native_registration(tmp_path):
    with pytest.raises(AccountingError):WriterBroker(None,None,{2:OWNER},lambda p:OWNER,None,server_epoch='c'*40,endpoint='original')

def test_unknown_key_globs_are_not_least_privilege_credentials():
    pin=PinnedRedisScope(container_id='a'*64,image='sha256:'+'b'*64,name='genesis-redis-c67-fixture',volume='project-genesis_checkpoint67-fixture',port=16570,certification='checkpoint67')
    with pytest.raises(AccountingError,match='Exact key scopes'):
        ProductionCredentials(None,None,None,None,scope_validator=pin,port=16570,keys={'redis-streams':['*']})

@pytest.mark.parametrize('generation',[0,2,True])
def test_stale_or_invalid_broker_generation_never_dispatches(broker,generation):
    b,l,o,w,c=broker;register(b,o,w)
    with pytest.raises(AccountingError):request(b,'begin_command',w,'LPUSH',[b'q',b'v'],11,generation)
    assert b.held and not l.commands

def test_acknowledgement_cannot_name_a_different_route(broker):
    b,l,o,w,c=broker;register(b,o,w)
    token=request(b,'begin_command',w,'LPUSH',[b'q',b'v'],11,1)
    with pytest.raises(AccountingError):request(b,'complete_command',token,1,reply_bytes(1),'other')
    assert l.commands[token]['state']=='ISSUED' and b.held

def test_registered_ledger_connection_without_sealed_credentials_cannot_mutate(broker):
    b,l,o,w,c=broker;register(b,o,w);c.is_bound=lambda *args:False
    with pytest.raises(AccountingError,match='sealed'):
        request(b,'begin_command',w,'LPUSH',[b'q',b'v'],11,1)
    assert not l.commands and b.held

def test_reply_digest_cannot_represent_different_reply_bytes(broker):
    b,l,o,w,c=broker;register(b,o,w)
    token=request(b,'begin_command',w,'LPUSH',[b'q',b'v'],11,1)
    with pytest.raises(AccountingError,match='serialization'):
        request(b,'complete_command',token,1,reply_bytes(2),'original')
    assert l.commands[token]['state']=='ISSUED' and b.held

def test_fixture_identity_cannot_be_reused_for_production_authority():
    authority=ProductionCredentials.__new__(ProductionCredentials)
    authority.scope_validator=SimpleNamespace(certification=None)
    with pytest.raises(AccountingError,match='Fixture identities'):
        authority.issue(OWNER,'redis-streams',1,'c'*40)

@pytest.mark.parametrize('corruption',['nopass','no_password_hash','no_client_password','broad_commands','selector','disabled'])
def test_broker_admin_cannot_have_passwordless_or_unaudited_authority(corruption):
    policy={'categories':['-@all'],'selectors':[],'commands':['+acl|getuser','+acl|setuser'],'flags':['on'],'passwords':['a'*64]}
    config={'host':'127.0.0.1','port':16570,'db':0,'username':'broker','password':'SYNTHETIC_NOT_SECRET'}
    if corruption=='nopass':policy['flags'].append('nopass')
    elif corruption=='no_password_hash':policy['passwords']=[]
    elif corruption=='no_client_password':config.pop('password')
    elif corruption=='broad_commands':policy['commands'].append('+lpush')
    elif corruption=='selector':policy['selectors']=[{'commands':'+@all'}]
    else:policy['flags']=['off']
    client=SimpleNamespace(connection_pool=SimpleNamespace(connection_kwargs=config),acl_getuser=lambda u:policy,close=lambda:None)
    authority=ProductionCredentials.__new__(ProductionCredentials);authority.check_scope=lambda:None;authority.admin=lambda:client;authority.port=16570
    with pytest.raises(AccountingError,match='privileges'):authority.checked_admin()

def test_observed_incremental_recovery_metadata_loss_is_not_a_clock_exception():
    from test_redis_stream_integrity import full,proof
    from scripts.redis_stream_integrity import verify_semantic_recovery
    import copy
    stream=full();group=stream[stream.index(b'groups')+1][0]
    consumers=group[group.index(b'consumers')+1]
    consumers.append([b'name',b'empty-consumer',b'seen-time',100,b'active-time',-1,b'pel-count',0,b'pending',[]])
    before=proof(stream)
    after_stream=copy.deepcopy(stream)
    recovered_group=after_stream[after_stream.index(b'groups')+1][0]
    recovered_group[recovered_group.index(b'consumers')+1].pop()
    recovered_group[recovered_group.index(b'entries-read')+1]=None
    after=proof(after_stream)
    with pytest.raises(ValueError,match='stream evidence'):
        verify_semantic_recovery(before,after,mode='aof',recovery_window_ms=(180,200))
