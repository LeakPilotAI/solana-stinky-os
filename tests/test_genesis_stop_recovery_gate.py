import copy
from types import SimpleNamespace
import pytest
from scripts.redis_snapshot_integrity import verify_guarded_stop_snapshot
from test_redis_writer_broker import broker,register
from test_redis_stream_integrity import proof


def inputs(tmp_path,fixture):
    b,ledger,owner,writer,credentials=fixture;register(b,owner,writer)
    assert b.quiesce([11])==0
    original=tmp_path/'final.rdb';original.write_bytes(b'REDIS0012'+b'synthetic-unit-fixture-only')
    protected=tmp_path/'protected.rdb';protected.write_bytes(original.read_bytes())
    expected=proof()
    return dict(broker=b,observed_ids=[11],before=expected,after=copy.deepcopy(expected),
        restored=copy.deepcopy(expected),snapshot=original,protected_copy=protected,
        check_snapshot=lambda path,manifest:True,
        inspect_connections=lambda:{'server_epoch':'c'*40,'writer_ids':[11],'maxmemory_policy':'noeviction'})


def test_full_stop_gate_requires_matching_independent_recovery_point(tmp_path,broker):
    result=verify_guarded_stop_snapshot(**inputs(tmp_path,broker))
    assert result['status']=='RECOVERY_POINT_VERIFIED' and result['snapshot']['checksum_verified']
    assert result['scope']=='INACTIVE_GATE_ONLY_NOT_LIFECYCLE_CERTIFICATION'


@pytest.mark.parametrize('failure',['held','unfenced','credential_fence','unknown_writer','duplicate_writer',
    'missing_participant','checksum','copy','same_copy','expiry','payload','pending_owner','delivery_count','source_changed',
    'server_epoch','eviction','connection_changed','reused_pid','fence_lost_during_check','retired_during_check'])
def test_stop_cannot_advance_without_complete_recovery_gate(tmp_path,broker,failure):
    args=inputs(tmp_path,broker);b=broker[0];restored=args['restored']['keys'][0]['stable']
    if failure=='held':b.held=True
    if failure=='unfenced':b.fenced=False
    if failure=='credential_fence':b.credentials.fenced=False
    if failure=='unknown_writer':args['observed_ids']=[11,90]
    if failure=='duplicate_writer':args['observed_ids']=[11,11]
    if failure=='missing_participant':b.sequences.clear()
    if failure=='checksum':args['check_snapshot']=lambda *a:False
    if failure=='copy':args['protected_copy'].write_bytes(b'REDIS0012'+b'corrupt')
    if failure=='same_copy':args['protected_copy']=args['snapshot']
    if failure=='expiry':
        for name in ('before','after','restored'):args[name]['keys'][0]['expires_at_ms']=900
    if failure=='payload':restored['entries'][0]['payload_sha256']='f'*64
    if failure=='pending_owner':restored['groups'][0]['pending'][0]['consumer_sha256']='f'*64
    if failure=='delivery_count':restored['groups'][0]['pending'][0]['delivery_count']+=1
    if failure=='source_changed':args['after']['keys'][0]['stable']['entries-added']+=1
    if failure in ('server_epoch','eviction','connection_changed'):
        evidence={'server_epoch':'c'*40,'writer_ids':[11],'maxmemory_policy':'noeviction'}
        evidence.update({'server_epoch':'d'*40} if failure=='server_epoch' else
                        {'maxmemory_policy':'allkeys-lru'} if failure=='eviction' else {'writer_ids':[90]})
        args['inspect_connections']=lambda:evidence
    if failure=='reused_pid':b.verify_native=lambda p:{**broker[2],'creation_ticks':11}
    if failure=='fence_lost_during_check':
        def mutate(*a):b.fenced=False;return True
        args['check_snapshot']=mutate
    if failure=='retired_during_check':
        def mutate(*a):
            for key,row in b.ledger.bindings.items():row['active']=False
            return True
        args['check_snapshot']=mutate
    with pytest.raises((ValueError,RuntimeError)):verify_guarded_stop_snapshot(**args)


def test_successful_bgsave_message_cannot_replace_restore_or_fencing(tmp_path,broker):
    args=inputs(tmp_path,broker);args['restored']={'bgsave_status':'ok'}
    with pytest.raises(ValueError):verify_guarded_stop_snapshot(**args)
