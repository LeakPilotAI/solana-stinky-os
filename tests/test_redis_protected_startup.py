import copy
import pytest
from scripts.redis_protected_startup import install_grant,sign
from stinky_core.transport import redis_accounting as accounting
from stinky_core.transport.redis_accounting import AccountingError,ClientFactory

OWNER={'pid':1,'creation_ticks':10,'service':'collector','command_sha256':'a'*64,'repository_sha256':'b'*64}

def grant():
    body={'schema':'genesis-protected-startup-v1','owner':OWNER,'broker_identity':[2,20],
          'pipe':'\\\\.\\pipe\\genesis-unit','authkey':'d'*64,'server_epoch':'c'*40,
          'endpoint':'protected','generation':2,'roles':['redis-streams','collector-consumer'],
          'pins':{'container_id':'e'*64,'image':'sha256:'+'f'*64,'name':'stinky-redis',
                  'volume':'project-genesis_redis-data','port':6380},'expires_at':110,
          'admission':{'capacity':'GREEN','custody':'GREEN','recovery':'GREEN','retention':'GREEN',
                       'manifest_sha256':'a'*64,'brpop':'REJECTED'}}
    return {**body,'signature':sign(body)}

def test_fresh_verified_grant_initializes_before_client_or_write_authority():
    factory=ClientFactory();scopes=[]
    runtime=install_grant(factory,grant(),verify_owner=lambda:dict(OWNER),verify_scope=scopes.append,now=100)
    assert runtime is factory.runtime and not factory.issued and runtime.generation==2
    assert runtime.owner==OWNER and not runtime.clients and scopes[0].name=='stinky-redis'
    # The broker still must issue read-only credentials, register the native CID,
    # seal that connection and authorize each intent. This is not live activation.
    assert runtime.ledger.writers==frozenset({'1-10-redis-streams','1-10-collector-consumer'})

@pytest.mark.parametrize('field,value', [('expires_at',100),('expires_at',300),
    ('roles',['sentinel-manual-consumer']),('generation',0),('server_epoch','wrong'),
    ('pipe','\\\\other-host\\pipe\\genesis-unit'),('broker_identity',[2,0])])
def test_stale_invalid_or_unsupported_grants_fail_before_factory_configuration(field,value):
    body=grant();body.pop('signature');body[field]=value;body['signature']=sign({k:v for k,v in body.items() if k!='signature'})
    factory=ClientFactory()
    with pytest.raises(AccountingError):install_grant(factory,body,verify_owner=lambda:OWNER,verify_scope=lambda p:None,now=100)
    assert factory.runtime is None and not factory.issued

@pytest.mark.parametrize('gate',['capacity','custody','recovery','retention','brpop'])
def test_any_failed_admission_gate_refuses_initialization(gate):
    body=grant();body.pop('signature');body['admission'][gate]='BLOCKED';body['signature']=sign(body.copy())
    factory=ClientFactory()
    with pytest.raises(AccountingError):install_grant(factory,body,verify_owner=lambda:OWNER,verify_scope=lambda p:None,now=100)
    assert factory.runtime is None

def test_pid_reuse_and_unsigned_changes_cannot_regain_authority():
    body=grant();body['owner']={**OWNER,'creation_ticks':11}
    with pytest.raises(AccountingError):install_grant(ClientFactory(),body,verify_owner=lambda:OWNER,verify_scope=lambda p:None,now=100)
    body=grant()
    with pytest.raises(AccountingError):install_grant(ClientFactory(),body,verify_owner=lambda:{**OWNER,'creation_ticks':11},verify_scope=lambda p:None,now=100)

def test_existing_legacy_factory_cannot_be_hot_patched():
    factory=ClientFactory();factory.from_url('redis://fixture',role='redis-streams',legacy_factory=lambda *a,**k:object())
    with pytest.raises(AccountingError,match='replacement'):
        install_grant(factory,grant(),verify_owner=lambda:OWNER,verify_scope=lambda p:None,now=100)

def test_disabled_mode_preserves_existing_factory_options(monkeypatch):
    monkeypatch.delenv('GENESIS_PROTECTED_REDIS_GRANT',raising=False)
    factory=ClientFactory();monkeypatch.setattr(accounting,'FACTORY',factory);calls=[]
    def legacy(*args,**kwargs):calls.append((args,kwargs));return 'legacy'
    assert accounting.redis_client('redis://fixture',role='redis-streams',legacy_factory=legacy,
                                   decode_responses=True,socket_timeout=10)=='legacy'
    assert calls==[(('redis://fixture',),{'decode_responses':True,'socket_timeout':10})]

def test_protected_missing_grant_cannot_fall_back_to_anonymous_clients(monkeypatch):
    monkeypatch.setenv('GENESIS_PROTECTED_REDIS_GRANT','C:/outside/grant.dpapi')
    factory=ClientFactory();monkeypatch.setattr(accounting,'FACTORY',factory);calls=[]
    with pytest.raises(AccountingError):accounting.redis_client('redis://fixture',role='redis-streams',legacy_factory=lambda *a,**k:calls.append(1))
    assert not calls and factory.runtime is None and not factory.issued


def test_explicit_empty_protected_grant_is_not_treated_as_disabled(monkeypatch):
    monkeypatch.setenv('GENESIS_PROTECTED_REDIS_GRANT','')
    calls=[]
    with pytest.raises(AccountingError,match='empty'):
        accounting.redis_client('redis://fixture',role='redis-streams',legacy_factory=lambda *a,**k:calls.append(1))
    assert not calls
