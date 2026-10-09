from copy import deepcopy
import pytest
from scripts import redis_rollback_safety as rollback
from test_redis_stream_integrity import proof

HEALTH={'aof_enabled':1,'aof_rewrite_in_progress':0,'aof_rewrite_scheduled':0,
        'aof_last_bgrewrite_status':'ok','aof_last_write_status':'ok'}


def check(boundary=None,current=None,recovered=None,**kwargs):
    a=proof() if boundary is None else boundary
    defaults=dict(writers_fenced=True,unresolved_commands=0,fsync_confirmed=True,
                  persistence=HEALTH,appendfsync='always',mode='rdb')
    defaults.update(kwargs)
    return rollback.verify_rollback_recovery(a,deepcopy(a) if current is None else current,
                    deepcopy(a) if recovered is None else recovered,**defaults)


def test_complete_current_boundary_passes():assert check()['status']=='MATCH'


@pytest.mark.parametrize('field,value',[('writers_fenced',False),('writers_fenced',1),
 ('unresolved_commands',1),('unresolved_commands',None),('fsync_confirmed',False),('appendfsync','everysec')])
def test_concurrent_or_uncertain_acknowledgements_cannot_authorize_rollback(field,value):
    with pytest.raises(RuntimeError):check(**{field:value})


def test_original_cutover_snapshot_cannot_hide_later_acknowledged_write():
    old=proof();current=deepcopy(old);current['keys'][0]['stable']['entries'][0]['payload_sha256']='f'*64
    with pytest.raises(ValueError):check(boundary=old,current=current,recovered=old)


@pytest.mark.parametrize('field,value',[('aof_enabled',0),('aof_rewrite_in_progress',1),
 ('aof_last_write_status','err'),('aof_last_bgrewrite_status','err')])
def test_interrupted_persistence_is_blocked(field,value):
    health=dict(HEALTH);health[field]=value
    with pytest.raises(ValueError):check(persistence=health)


def test_partial_restore_or_missing_entry_is_blocked():
    lost=proof();lost['keys']=[]
    with pytest.raises(ValueError):check(recovered=lost)


def test_pending_ownership_and_delivery_counts_remain_strict():
    lost=proof();lost['keys'][0]['stable']['groups'][0]['pending'][0]['delivery_count']=99
    with pytest.raises(ValueError):check(recovered=lost)


def test_declared_aof_replay_variance_preserves_exact_pending_evidence():
    a=proof();b=deepcopy(a)
    for c in b['keys'][0]['activity_clocks']:c['seen_time_ms']=c['active_time_ms']=190
    assert check(boundary=a,recovered=b,mode='aof',recovery_window_ms=(180,200))['status']=='MATCH'


@pytest.mark.parametrize('volumes',[('old','new','old'),('old','new','new'),('','new','target')])
def test_original_or_current_storage_cannot_be_overwritten(volumes):
    with pytest.raises(RuntimeError):rollback.verify_target_storage([],original_volume=volumes[0],source_volume=volumes[1],target_volume=volumes[2])


def test_second_volume_writer_is_rejected():
    rows=[{'State':{'Running':True},'Mounts':[{'Name':'target'}]}]
    with pytest.raises(RuntimeError):rollback.verify_target_storage(rows,original_volume='old',source_volume='new',target_volume='target')
