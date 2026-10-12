"""Explicit checkpoint74 fixture boundary; never accepts production identities."""
import hashlib,json,os,socket,subprocess,time,uuid
from pathlib import Path
import redis
from scripts.redis_snapshot_integrity import verify_guarded_stop_snapshot
from scripts.redis_stream_integrity import semantic_census


def certify(config,broker,observer,admin,inspect_writer_ids):
    pins=config['pins'];root=Path(config['artifact_root']).resolve()
    assert root.is_relative_to((Path.cwd()/'logs').resolve()) and not root.is_symlink()
    assert pins['certification']=='checkpoint74' and pins['port']==16589
    pin=broker.credentials.scope_validator
    def call(*args):
        result=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=30)
        if result.returncode:raise RuntimeError('Isolated recovery action failed: '+args[0])
        return result.stdout.strip()
    def source():
        rows=json.loads(call('inspect',pins['container_id']));pin(rows);return rows[0]
    source();assert broker.fenced and not broker.held and broker.ledger.settled()>0
    before=semantic_census(observer);directory=root/'final-snapshot';directory.mkdir(exist_ok=False)
    filename=observer.config_get('dbfilename')['dbfilename'];assert filename=='dump.rdb'
    existing=subprocess.run(['docker','exec',pins['container_id'],'test','-f','/data/dump.rdb'],capture_output=True,timeout=10)
    assert existing.returncode in (0,1)
    if existing.returncode==0:
        prior=root/'previous-fixture.rdb';assert not prior.exists()
        call('cp',pins['container_id']+':/data/dump.rdb',str(prior))
        assert 9<prior.stat().st_size<=128*1024*1024
        with prior.open('r+b') as stream:stream.flush();os.fsync(stream.fileno())
        prior.chmod(0o444)
        (root/'previous-fixture-rdb-sha256.txt').write_text(hashlib.sha256(prior.read_bytes()).hexdigest())
    # This controller principal can only persist/read this isolated dataset. It
    # is disabled again before the fresh writer-exclusion proof is evaluated.
    client=admin()
    try:
        source();client.execute_command('ACL','SETUSER','persistence','on','+save')
        persistence=redis.Redis(host='127.0.0.1',port=16589,username='persistence',password=config['persistence_password'],socket_timeout=10)
        try:
            deadline=time.monotonic()+10
            while persistence.info('persistence')['rdb_bgsave_in_progress']:
                assert time.monotonic()<deadline;time.sleep(.05)
            assert persistence.save() is True
        finally:persistence.close()
    finally:
        client.execute_command('ACL','SETUSER','persistence','off','-save');client.close()
    source();snapshot=directory/'dump.rdb';call('cp',pins['container_id']+':/data/'+filename,str(snapshot))
    assert not snapshot.is_symlink() and 9<snapshot.stat().st_size<=128*1024*1024
    copy=root/'final-protected.rdb'
    with copy.open('xb') as stream:
        stream.write(snapshot.read_bytes());stream.flush();os.fsync(stream.fileno())
    checksum=hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert hashlib.sha256(copy.read_bytes()).hexdigest()==checksum
    for path in (snapshot,copy):path.chmod(0o444)
    name='genesis-rdb-c74-'+uuid.uuid4().hex[:8]
    with socket.socket() as check:assert check.connect_ex(('127.0.0.1',16590))!=0
    ident=call('create','--name',name,'--label','genesis.certification=checkpoint74-final-recovery',
        '--label','com.docker.compose.project=project-genesis','--label','com.docker.compose.service=redis',
        '--memory','128m','--cpus','0.25','--read-only','--user','redis:redis',
        '--mount','type=bind,source='+str(directory.resolve())+',target=/data,readonly',
        '-p','127.0.0.1:16590:6379',pins['image'],'redis-server','--appendonly','no','--save','','--dir','/data')
    (root/'final-restore-identity.json').write_text(json.dumps({'id':ident,'name':name,'snapshot_sha256':checksum}))
    def inspect():
        row=json.loads(call('inspect',ident))[0]
        assert row['Id']==ident and row['Name']=='/'+name and row['Image']==pins['image']
        assert row['Config']['Labels']['genesis.certification']=='checkpoint74-final-recovery'
        assert len(row['Mounts'])==1 and row['Mounts'][0]['Type']=='bind' and row['Mounts'][0]['RW'] is False
        actual=row['Mounts'][0]['Source'].replace('\\','/').casefold()
        expected=directory.resolve().as_posix().casefold()
        linux='/run/desktop/mnt/host/'+expected[0]+expected[2:]
        assert actual in (expected,linux)
        assert row['Mounts'][0]['Destination']=='/data' and row['HostConfig']['ReadonlyRootfs'] is True
        assert row['HostConfig']['PortBindings']['6379/tcp']==[{'HostIp':'127.0.0.1','HostPort':'16590'}]
        return row
    restored_client=redis.Redis(host='127.0.0.1',port=16590,socket_timeout=5)
    try:
        inspect();call('start',ident)
        for _ in range(100):
            try:restored_client.ping();break
            except redis.ConnectionError:time.sleep(.1)
        restored=semantic_census(restored_client);after=semantic_census(observer)
        checked=call('exec',ident,'redis-check-rdb','/data/dump.rdb');assert 'Checksum OK' in checked
        (root/'final-rdb-check.txt').write_text(checked)
        def connections():
            source()
            return {'server_epoch':observer.info('server')['run_id'],'writer_ids':inspect_writer_ids(),
                    'maxmemory_policy':observer.config_get('maxmemory-policy')['maxmemory-policy']}
        result=verify_guarded_stop_snapshot(broker=broker,observed_ids=inspect_writer_ids(),
            before=before,after=after,restored=restored,snapshot=snapshot,protected_copy=copy,
            check_snapshot=lambda path,manifest:manifest['sha256']==checksum and 'Checksum OK' in checked,
            inspect_connections=connections)
        (root/'final-source-proof.json').write_text(json.dumps(before))
        (root/'final-restored-proof.json').write_text(json.dumps(restored))
        (root/'final-boundary-results.json').write_text(json.dumps(result,indent=2))
        return result
    finally:
        restored_client.close()
        if inspect()['State']['Running']:call('stop','--time','10',ident)
