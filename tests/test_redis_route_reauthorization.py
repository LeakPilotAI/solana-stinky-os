from types import SimpleNamespace

import pytest

from test_redis_broker_recovery import source, OWNER
from scripts.redis_broker_recovery import recover_held_boundary, reauthorize_held_route
from scripts.redis_production_adapters import DurableJournal
from scripts.redis_writer_broker import RetentionBoundary
from stinky_core.transport.redis_accounting import AccountingError


@pytest.fixture
def restart(tmp_path):
    old,_,_=source(tmp_path);head=old.previous;old.close()
    audit=DurableJournal(tmp_path/'held.jsonl')
    recovered=recover_held_boundary(old.path,expected_head=head,next_journal=audit,
                                    revoke=lambda p:None,verify_revoked=lambda p:True)
    journal=DurableJournal(tmp_path/'new.jsonl')
    credentials=SimpleNamespace(tickets={},check_scope=lambda:None,verify_principals=lambda:True,
                                revoke_all=lambda:None,fenced=False,is_bound=lambda *a:True)
    args=dict(journal=journal,credentials=credentials,manifest={1:dict(OWNER)},
              verify_native=lambda pid:dict(OWNER),retention=RetentionBoundary({'maxmemory-policy':'noeviction'},0),
              server_epoch='c'*40,endpoint='original',authorize=lambda request:True,
              grant_path=tmp_path/('reauthorize-'+head+'.grant'))
    yield recovered,args,tmp_path
    journal.close();audit.close()


def test_fresh_authorization_preserves_parent_receipts_and_requires_new_binding(restart):
    recovered,args,_=restart
    broker=reauthorize_held_route(recovered,**args)
    assert broker.generation==2 and broker.ledger.commands==recovered['ledger'].commands
    assert not broker.ledger.bindings and args['grant_path'].is_file()
    with pytest.raises(AccountingError):
        broker.ledger.begin_command('1-10-redis-streams','LPUSH',[b'q',b'v'],11,1)


def test_denied_fresh_authorization_cannot_issue_route(restart):
    recovered,args,_=restart;args['authorize']=lambda request:False
    with pytest.raises(AccountingError):reauthorize_held_route(recovered,**args)
    assert not args['grant_path'].exists() and args['journal'].sequence==0


def test_immutable_source_grant_cannot_be_reused(restart):
    recovered,args,_=restart;reauthorize_held_route(recovered,**args)
    with pytest.raises(FileExistsError):reauthorize_held_route(recovered,**args)


def test_restarted_writer_requires_explicit_verified_role_mapping(restart):
    recovered,args,_=restart;owner={**OWNER,'pid':2,'creation_ticks':20}
    args['manifest']={2:owner};args['verify_native']=lambda pid:dict(owner)
    args['writer_roles']={2:['redis-streams']}
    broker=reauthorize_held_route(recovered,**args)
    assert broker.ledger.writers==frozenset({'2-20-redis-streams'})
    broker.ledger.register_connection('2-20-redis-streams',owner,12,'c'*40,2)
    assert broker.ledger.begin_command('2-20-redis-streams','LPUSH',[b'q',b'v'],12,2)==2
    with pytest.raises(AccountingError):
        broker.dispatch(2,{'sequence':1,'method':'begin_command','args':['2-20-redis-streams','LPUSH',[b'q',b'v'],12,1]})


def test_native_pid_reuse_or_manifest_change_blocks_reauthorization(restart):
    recovered,args,_=restart;args['verify_native']=lambda pid:{**OWNER,'creation_ticks':11}
    with pytest.raises(AccountingError):reauthorize_held_route(recovered,**args)
    assert not args['grant_path'].exists()


def test_inherited_credentials_cannot_be_unfenced(restart):
    recovered,args,_=restart;args['credentials'].tickets={'old':'credential'}
    with pytest.raises(AccountingError):reauthorize_held_route(recovered,**args)
    assert not args['grant_path'].exists()


def test_new_generation_restart_requires_anchored_parent_and_preserves_history(restart):
    recovered,args,path=restart;broker=reauthorize_held_route(recovered,**args)
    broker.ledger.register_connection('1-10-redis-streams',OWNER,12,'c'*40,2)
    head=args['journal'].previous
    audit=DurableJournal(path/'second-held.jsonl')
    try:
        again=recover_held_boundary(args['journal'].path,expected_head=head,next_journal=audit,
            revoke=lambda p:None,verify_revoked=lambda p:True,parent_loader=lambda h:recovered)
        assert again['next_generation']==3 and again['ledger'].commands==recovered['ledger'].commands
    finally:audit.close()


def test_missing_parent_cannot_abandon_acknowledged_writes(restart):
    recovered,args,path=restart;reauthorize_held_route(recovered,**args)
    audit=DurableJournal(path/'missing-parent.jsonl')
    try:
        with pytest.raises(AccountingError):
            recover_held_boundary(args['journal'].path,expected_head=args['journal'].previous,next_journal=audit,
                revoke=lambda p:None,verify_revoked=lambda p:True)
    finally:audit.close()
