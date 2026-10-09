from pathlib import Path
import pytest
from scripts import redis_snapshot_integrity as snap

def rdb(tmp_path,name='snapshot.rdb',payload=b'evidence'):
    p=tmp_path/name;p.write_bytes(b'REDIS0012'+payload+b'123456789');return p

def test_separate_copy_verification_preserves_files(tmp_path):
    first=rdb(tmp_path);second=rdb(tmp_path,'protected.rdb')
    before=first.read_bytes()
    assert snap.verify_same_snapshot(first,second)['sha256']==snap.fingerprint(before)
    assert not snap.inspect_rdb(first)['checksum_verified']
    assert first.read_bytes()==second.read_bytes()==before

@pytest.mark.parametrize('payload',[b'',b'wrong-header-and-checksum'])
def test_invalid_snapshot_fails_closed(tmp_path,payload):
    p=tmp_path/'bad';p.write_bytes(payload)
    with pytest.raises(ValueError):snap.inspect_rdb(p)

def test_changed_copy_fails_closed(tmp_path):
    with pytest.raises(ValueError,match='differs'):
        snap.verify_same_snapshot(rdb(tmp_path),rdb(tmp_path,'copy',b'changed'))

def test_size_bound_does_not_claim_checksum(tmp_path,monkeypatch):
    p=rdb(tmp_path);monkeypatch.setattr(snap,'MAX_SNAPSHOT_BYTES',10)
    with pytest.raises(ValueError,match='bound'):snap.inspect_rdb(p)

def test_census_redacts_values_and_identifiers():
    class Client:
        def eval(self,script,nkeys,*limits):
            assert nkeys==0 and limits==(snap.MAX_KEYS,snap.MAX_KEY_BYTES)
            return [[b'secret-key',b'stream',b'secret-value',-1,3,
                [[b'name',b'secret-group',b'consumers',1,b'pending',2,
                  b'last-delivered-id',b'10-0',b'entries-read',3,b'lag',0]],[]]]
    report=snap.census(Client())
    assert 'secret-' not in str(report)
    assert report['keys'][0]['groups'][0]['pending']==2
    snap.verify_recovery(report,report)

@pytest.mark.parametrize('field',['serialized_sha256','expires_at_ms','stream_length','groups'])
def test_recovery_mismatch_is_not_waived(field):
    original={'keys':[{field:'original'}]};other={'keys':[{field:'different'}]}
    with pytest.raises(ValueError,match='not certified'):snap.verify_recovery(original,other)

@pytest.mark.parametrize('command',[
 ['redis-server','--appendonly','no','--save',''],
 ['redis-server','/data/redis.conf','--appendonly','no'],
 ['redis-server'],['redis-server','/other/redis.conf']])
def test_startup_overrides_fail_closed(command):
    with pytest.raises(ValueError,match='override'):snap.verify_config_file_startup(command)

def test_explicit_config_file_startup_is_distinct_from_runtime_setting():
    snap.verify_config_file_startup(['redis-server','/data/redis.conf'])

@pytest.mark.parametrize('changed',[
 {'aof_enabled':0},{'aof_rewrite_in_progress':1},{'aof_rewrite_scheduled':1},
 {'aof_last_bgrewrite_status':'err'},{'aof_last_write_status':'err'}])
def test_aof_health_failures_are_not_claimed_durable(changed):
    info={'aof_enabled':1,'aof_rewrite_in_progress':0,'aof_rewrite_scheduled':0,
          'aof_last_bgrewrite_status':'ok','aof_last_write_status':'ok'}
    info.update(changed)
    with pytest.raises(ValueError,match='unhealthy'):snap.verify_aof_ready(info)

def test_missing_aof_metrics_fail_closed():
    with pytest.raises(ValueError):snap.verify_aof_ready({})
