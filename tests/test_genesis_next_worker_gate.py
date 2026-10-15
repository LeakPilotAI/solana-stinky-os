import json
import pytest
from scripts.genesis_launch_provenance import LaunchObservations,answer_launch,signed
from scripts.genesis_child_observation import ChildObservations,target
from scripts.genesis_next_worker_gate import WorkerGate,WorkerPeer


def fixture():
    def owner(pid,parent):return {'pid':pid,'parent_pid':parent,'created':'2026-10-15T00:00:00+00:00','executable':'node.exe','command_sha256':'a'*64}
    rows={1:owner(1,0),2:owner(2,1),3:owner(3,2)}
    native=lambda pid:dict(rows[pid])
    launches=LaunchObservations(native,now=lambda:1)
    raw=launches.prepare('web',rows[1]);launches.accept('web',answer_launch(raw,rows[1],now=lambda:1))
    parents=ChildObservations(launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'],now=lambda:1)
    v=json.loads(parents.prepare('web',rows[2]));proof=signed(bytes.fromhex(v['key']),v['challenge'])
    parents.accept('web',proof);parents.confirm('web',signed(bytes.fromhex(v['key']),{'kind':'genesis-child-installed-v1','target':target(proof),'lifecycle_authorized':False,'write_authorized':False}))
    clock=[0.0];sockets=[True];closure=[False]
    gate=WorkerGate(parents=parents,native=native,socket_owned=lambda o,p:sockets[0] and p==12345,
        closed=lambda o,p:closure[0],executable='node.exe',command_sha256='a'*64,now=lambda:clock[0])
    raw=gate.prepare(rows[3],'c'*64);peer=WorkerPeer(raw,owner=rows[3],parent=parents.checked('web'),receiver_nonce='c'*64)
    return gate,peer,rows,parents,launches,clock,sockets,closure


def running():
    v=fixture();g,p,*_=v;p.install(g.install(p.proof()));g.ready(p.ready(12345));return v


def retire(g,p,closure):
    request=g.stop_request();p.stop(request,fence=lambda:True)
    for kind in ('drained','completed','descendants_closed'):
        g.acknowledge(p.acknowledge(kind,evidence=lambda:{'accepting':False,'inflight':0,'unresolved':0}))
    closure[0]=True
    return g.finish()


def test_normal_private_install_socket_join_and_retirement():
    g,p,rows,parents,launches,clock,sockets,closure=running()
    assert g.status()['phase']=='RUNNING'
    assert retire(g,p,closure)['phase']=='RETIRED'
    assert not g.status()['lifecycle_authorized'] and not g.status()['production_enabled']
    assert g.record['key'] is None
    rows[3]['created']='2026-10-15T00:01:00+00:00'
    raw=g.prepare(rows[3],'c'*64);assert json.loads(raw)['challenge']['generation']==2
    with pytest.raises(ValueError):g.install(p.proof())
    assert g.status()['phase']=='HOLD'


@pytest.mark.parametrize('fault',['wrong-key','timeout','pid-reuse','parent-replaced','replay','duplicate-worker','lost-ipc','missing-socket'])
def test_authentication_faults_hold(fault):
    g,p,rows,parents,launches,clock,sockets,closure=fixture()
    if fault=='wrong-key':proof=signed(b'x'*32,p.body)
    else:proof=p.proof()
    if fault=='timeout':clock[0]=30
    if fault=='pid-reuse':rows[3]['created']='2026-10-15T00:01:00+00:00'
    if fault=='parent-replaced':rows[2]['command_sha256']='b'*64
    if fault=='replay':g.install(proof)
    with pytest.raises(ValueError):
        if fault=='duplicate-worker':g.prepare(rows[3],'c'*64)
        elif fault=='lost-ipc':g.disconnected()
        elif fault=='missing-socket':
            p.install(g.install(proof));sockets[0]=False;g.ready(p.ready(12345))
        else:g.install(proof)
    assert g.status()['phase']=='HOLD'


@pytest.mark.parametrize('fault',['timeout','lost-ipc','crash','inflight','unresolved','out-of-order','native-closure','parent-exit','restart-race'])
def test_retirement_faults_never_prove_closure(fault):
    g,p,rows,parents,launches,clock,sockets,closure=running()
    request=g.stop_request();p.stop(request,fence=lambda:True)
    if fault=='timeout':clock[0]=30
    if fault=='crash':rows.pop(3)
    if fault=='parent-exit':rows.pop(2)
    with pytest.raises(ValueError):
        if fault=='lost-ipc':g.disconnected()
        elif fault=='restart-race':g.prepare(rows[3],'c'*64)
        elif fault=='native-closure':
            for kind in ('drained','completed','descendants_closed'):
                g.acknowledge(p.acknowledge(kind,evidence=lambda:{'accepting':False,'inflight':0,'unresolved':0}))
            g.finish()
        else:
            b={'kind':'completed' if fault=='out-of-order' else 'drained','session':p.body['session'],
               'generation':p.body['generation'],'request':p.request,'accepting':False,
               'inflight':1 if fault=='inflight' else 0,'unresolved':1 if fault=='unresolved' else 0}
            g.acknowledge(signed(p.key,b))
    assert g.status()['phase']=='HOLD'


def test_parent_key_does_not_authenticate_worker_and_no_secret_status():
    g,p,_,parents,*_=fixture()
    with pytest.raises(ValueError):g.install(signed(parents.records['web']['key'],p.body))
    assert 'key' not in json.dumps(g.status()) and 'nonce' not in json.dumps(g.status())


def test_peer_fences_before_drain_and_never_auto_completes():
    g,p,*_=running();request=g.stop_request()
    with pytest.raises(ValueError):p.stop(request,fence=lambda:False)
    assert p.phase=='HOLD'
    with pytest.raises(ValueError):p.ready(12345)
    assert g.status()['phase']=='STOP_REQUESTED'


def test_drain_requires_actual_completed_evidence_and_replay_rejected():
    g,p,*_=running();r=g.stop_request();p.stop(r,fence=lambda:True)
    with pytest.raises(ValueError):p.stop(r,fence=lambda:True)
    with pytest.raises(ValueError):p.acknowledge('drained',evidence=lambda:{'accepting':False,'inflight':1,'unresolved':0})
    assert p.phase=='HOLD'


def test_recovery_cannot_restore_retired_or_unresolved_key():
    g,p,rows,parents,_,clock,sockets,closure=running()
    old=p.proof();retire(g,p,closure)
    with pytest.raises(ValueError):g.install(old)
    # Failed replay latches HOLD; no implicit resumption or serialized state restore.
    assert g.status()['phase']=='HOLD'


def test_new_receiver_nonce_rejects_copied_bootstrap():
    g,p,rows,parents,*_=fixture()
    raw=json.dumps({'challenge':p.body,'key':p.key.hex()}).encode()
    with pytest.raises(ValueError):WorkerPeer(raw,owner=rows[3],parent=parents.checked('web'),receiver_nonce='d'*64)


@pytest.mark.skipif(__import__('os').name!='nt',reason='Independent Windows native worker/socket evidence required')
def test_native_private_pipe_listener_and_normal_exit(tmp_path):
    import os,sys,subprocess,queue,threading
    from pathlib import Path
    from scripts.genesis_private_child_entry import native
    from scripts.genesis_background_ownership import capture,listener_identity
    # This is a synthetic Python worker, NOT Next dev. No signal/kill fallback.
    script=tmp_path/'worker.py'
    script.write_text("""
import json,os,secrets,socket,sys
from scripts.genesis_next_worker_gate import WorkerPeer
from scripts.genesis_private_child_entry import native
from scripts.genesis_launch_provenance import authenticated
nonce=secrets.token_hex(32)
print(json.dumps({'pid':os.getpid(),'nonce':nonce}),flush=True)
v=json.loads(sys.stdin.readline());raw=bytes.fromhex(v['frame'])
b=json.loads(raw)['challenge'];owner=native(os.getpid())
parent=b['parent']
if native(parent['owner']['pid'])!=parent['owner']:raise ValueError('Parent replaced')
p=WorkerPeer(raw,owner=owner,parent=parent,receiver_nonce=nonce)
def emit(v):print(json.dumps(v),flush=True)
def read():return json.loads(sys.stdin.readline())
emit(p.proof());p.install(read())
s=socket.socket();s.bind(('127.0.0.1',0));s.listen(1)
emit(p.ready(s.getsockname()[1]))
accepting=[True]
def fence():accepting[0]=False;return True
p.stop(read(),fence=fence)
def evidence():return {'accepting':accepting[0],'inflight':0,'unresolved':0}
for kind in ('drained','completed'):
 emit(p.acknowledge(kind,evidence=evidence))
 if authenticated(p.key,read())!={'continue':kind,'session':p.body['session']}:raise ValueError('Wrong receipt')
s.close();emit(p.acknowledge('descendants_closed',evidence=evidence))
if authenticated(p.key,read())!={'exit':True,'session':p.body['session']}:raise ValueError('Wrong exit receipt')
""",encoding='utf-8')
    proc=subprocess.Popen([sys._base_executable,str(script)],cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])+os.pathsep+os.environ.get('PYTHONPATH','')})
    inbox=queue.Queue()
    def reader():
        for line in proc.stdout:inbox.put(line)
    threading.Thread(target=reader,daemon=True).start()
    def read():return json.loads(inbox.get(timeout=30))
    def send(v):proc.stdin.write(json.dumps(v)+'\n');proc.stdin.flush()
    try:
        ready=read();owner=native(proc.pid);parent_owner=native(os.getpid())
        # Parent protocol registration is fixture scaffolding. Worker identity,
        # ancestry and socket ownership are independently native, not mocked.
        g0,p0,rows,parents,*_=fixture()
        parent_record=parents.records['web'];parent_record['challenge']['owner']=parent_owner
        launch=parents.launches._records['web']['challenge'];launch['owner']=dict(parent_owner,pid=1)
        rows.clear();rows.update({1:launch['owner'],parent_owner['pid']:parent_owner})
        parent_record['challenge']['launch']=dict(launch)
        parents.ancestry=lambda c,p:True  # Only scaffolding; never production evidence.
        def socket_owned(o,port):
            data=capture((port,))
            return listener_identity(data,o['pid'],port) and any(s['pid']==o['pid'] and s['port']==port and s['address']=='127.0.0.1' for s in data['sockets'])
        gate=WorkerGate(parents=parents,native=native,socket_owned=socket_owned,
            closed=lambda o,port:proc.poll()==0 and not any(r['pid']==o['pid'] or r['parent_pid']==o['pid'] for r in capture((port,))['after']) and not any(s['port']==port and s['state']=='Listen' for s in capture((port,))['sockets']),
            executable=owner['executable'],command_sha256=owner['command_sha256'])
        raw=gate.prepare(owner,ready['nonce']);send({'frame':raw.hex()})
        send(gate.install(read()));gate.ready(read())
        send(gate.stop_request())
        for kind in ('drained','completed'):
            gate.acknowledge(read());send(signed(gate.record['key'],{'continue':kind,'session':gate.record['challenge']['session']}))
        gate.acknowledge(read());send(signed(gate.record['key'],{'exit':True,'session':gate.record['challenge']['session']}))
        proc.stdin.close();proc.wait(timeout=15)
        assert proc.returncode==0,proc.stderr.read()
        assert gate.finish()['phase']=='RETIRED'
    finally:
        # Preserve a failed fixture; never terminate it to make a test pass.
        if proc.poll() is None:
            (tmp_path/'HOLD-retained-worker.json').write_text(json.dumps({'pid':proc.pid,'scope':'isolated synthetic worker'}))



@pytest.mark.parametrize('kind',['installed-timeout','ready-timeout','bad-install','invalid-port','boolean-inflight','duplicate-ack'])
def test_receiver_failure_latches_hold(kind):
    g,p,rows,parents,*_=fixture()
    clock=[0.0]
    raw=json.dumps({'challenge':p.body,'key':p.key.hex()}).encode()
    p=WorkerPeer(raw,owner=rows[3],parent=parents.checked('web'),receiver_nonce='c'*64,now=lambda:clock[0])
    receipt=g.install(p.proof())
    with pytest.raises(ValueError):
        if kind=='installed-timeout':clock[0]=30;p.install(receipt)
        elif kind=='bad-install':p.install(signed(b'q'*32,{}))
        else:
            p.install(receipt)
            if kind=='ready-timeout':clock[0]=30;p.ready(12345)
            elif kind=='invalid-port':p.ready(True)
            else:
                g.ready(p.ready(12345));p.stop(g.stop_request(),fence=lambda:True)
                if kind=='boolean-inflight':p.acknowledge('drained',evidence=lambda:{'accepting':0,'inflight':False,'unresolved':0})
                else:
                    p.acknowledge('drained',evidence=lambda:{'accepting':False,'inflight':0,'unresolved':0})
                    p.acknowledge('drained',evidence=lambda:{'accepting':False,'inflight':0,'unresolved':0})
    assert p.phase=='HOLD'


def test_failed_socket_recheck_latches_hold_without_signal():
    g,p,*_=running()
    def broken(*args):raise RuntimeError('Lost socket evidence')
    g.socket_owned=broken
    with pytest.raises(ValueError):g.stop_request()
    assert g.status()['phase']=='HOLD'
