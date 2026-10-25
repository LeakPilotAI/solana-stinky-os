"""Explicit real Next.js fixture on an isolated loopback port and directory."""
import hashlib
import json
import os
import queue
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest

from scripts.guarded_redis_migration import NativePause
from scripts.genesis_process_diagnostics import native_identity
from scripts.genesis_native_descendants import OwnedDescendantJob
import start_genesis as launcher
from stinky_core.transport.shutdown_delivery import ShutdownAuthority,canonical


@pytest.mark.parametrize("mode,active_hmr",[("development",False),("development",True),("production",False)])
def test_real_next_private_delivery_http_drain_and_native_exit(tmp_path,mode,active_hmr):
    if os.environ.get('GENESIS_NEXT_NATIVE_CERTIFICATION')!='isolated-checkpoint77':
        pytest.skip('Explicit real Next isolated fixture required')
    root=Path(__file__).resolve().parents[1]
    fixture_id='native-next-'+__import__('uuid').uuid4().hex
    directory=root/'tests'/'.genesis-native-next-fixtures'/fixture_id/'next-app'
    journal_dir=root/'logs'/'genesis-native-next-fixtures'/fixture_id
    assert not directory.parent.exists() and not journal_dir.exists()
    (directory/'pages'/'api').mkdir(parents=True)
    journal_dir.mkdir(parents=True)
    (directory/'package.json').write_text('{"name":"genesis-isolated-next-fixture","private":true}')
    (directory/'pages'/'api'/'probe.js').write_text("export default function probe(req,res){const delay=Number(req.query.delay||0);if(delay===400){process.stdout.write(JSON.stringify({fixture_request_admitted:true})+'\\n');setTimeout(()=>res.status(200).json({fixture:true,live_execution:false}),delay);}else res.status(200).json({fixture:true,live_execution:false})}")
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    assert port not in (3000,8000,8010,6380,16589)
    env=dict(os.environ);env['NODE_PATH']=str(root/'apps'/'web'/'node_modules')
    if mode=='production':
        env['NEXT_TELEMETRY_DISABLED']='1';env['NODE_ENV']='production'
        (directory/'next.config.js').write_text("module.exports={outputFileTracingRoot:__dirname,experimental:{cpus:1}}")
        cli=root/'apps/web/node_modules/next/dist/bin/next'
        built=subprocess.run(['node',str(cli),'build',str(directory)],env=env,
            cwd=directory,capture_output=True,text=True,timeout=180,creationflags=0x08000000 if os.name=='nt' else 0)
        (tmp_path/'production-build.txt').write_text(built.stdout+built.stderr)
        assert built.returncode==0,'Isolated production build failed; see preserved log'
    proc=subprocess.Popen(['node',str(root/'scripts'/'genesis_web_lifecycle.cjs')],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
        env=env,creationflags=0x08000000 if os.name=='nt' else 0)
    adapter=NativePause();handle=adapter.open(proc.pid);ticks,image=native_identity(adapter,proc.pid)
    row=next(r for r in launcher.list_win_processes() if r[0]==proc.pid)
    assert row[1]==os.getpid()
    owner={'pid':proc.pid,'creation_ticks':ticks,'service':'web','command_sha256':hashlib.sha256(row[3].encode()).hexdigest(),
           'repository_sha256':hashlib.sha256(str(root).encode()).hexdigest()}
    channel=ShutdownAuthority(os.urandom(32),'b'*64)
    def verify(pid):
        assert native_identity(adapter,pid)==(ticks,image)
        native=next(r for r in launcher.list_win_processes() if r[0]==pid)
        assert native[1]==os.getpid() and hashlib.sha256(native[3].encode()).hexdigest()==owner['command_sha256']
        return dict(owner)
    membership=OwnedDescendantJob(proc,owner,verify)
    inbox=queue.Queue();errors=[];hmr=None;active_request=None;request_results=[]
    stdout_events=[]
    def output():
        try:
            for line in proc.stdout:
                try:
                    value=json.loads(line)
                except ValueError:
                    if len(stdout_events)<100:
                        stdout_events.append('NON_JSON_LINE')
                    continue
                if len(stdout_events)<100:
                    if isinstance(value,dict):
                        stdout_events.append('JSON_KEYS:'+','.join(sorted(value.keys())))
                    else:
                        stdout_events.append('JSON_NON_OBJECT')
                inbox.put(value)
        except Exception as exc:
            stdout_events.append('READER_EXCEPTION:'+type(exc).__name__)
    def stderr():
        for line in proc.stderr:errors.append(line)
    reader=threading.Thread(target=output,daemon=True);reader.start()
    error_reader=threading.Thread(target=stderr,daemon=True);error_reader.start()
    bootstrap={'controller':channel.controller,'generation':1,'key_hex':channel._key.hex(),
        'owner_json':canonical(owner).decode(),'port':port,'root':str(root),'directory':str(directory),
        'journal':str(journal_dir/'web-control.jsonl'),'mode':mode}
    proc.stdin.write(json.dumps(bootstrap)+'\n');proc.stdin.flush()
    try:
        deadline=time.monotonic()+90
        ready=None
        while time.monotonic()<deadline:
            exit_code=proc.poll()
            if exit_code is not None:
                pytest.fail(
                    f'Native Next startup HOLD: child exited before READY; '
                    f'exit_code={exit_code}',
                    pytrace=False,
                )
            try:
                candidate=inbox.get(timeout=min(0.5,max(0.01,deadline-time.monotonic())))
            except queue.Empty:
                continue
            if not isinstance(candidate,dict) or candidate.get('phase')!='READY':
                pytest.fail('Native Next startup HOLD: unexpected control message',pytrace=False)
            ready=candidate
            break
        if ready is None:
            pytest.fail('Native Next startup HOLD: READY timeout after 90 seconds',pytrace=False)
        response=httpx.get(f'http://127.0.0.1:{port}/api/probe',timeout=60)
        assert response.status_code==200 and response.json()['fixture'] is True
        assert native_identity(adapter,proc.pid)==(ticks,image)
        if active_hmr:
            from websockets.sync.client import connect
            hmr=connect(f'ws://127.0.0.1:{port}/_next/webpack-hmr',open_timeout=15,close_timeout=5)
            # The framework's initial sync frame independently proves real HMR,
            # not merely TCP or HTTP upgrade acceptance.
            sync=json.loads(hmr.recv(timeout=15))
            assert sync.get('action')=='sync',sync
            (tmp_path/'active-hmr-evidence.json').write_text(json.dumps({
                'native_owner':owner,'upgrade_completed':True,'framework_action':sync['action'],
                'client_state':hmr.state.name,'port':port,'job_before_shutdown':membership.snapshot()}))
        if mode=='production':
            def request_in_flight():
                result=httpx.get(f'http://127.0.0.1:{port}/api/probe?delay=400',timeout=10)
                request_results.append((result.status_code,result.json(),time.monotonic()))
            active_request=threading.Thread(target=request_in_flight);active_request.start()
            assert inbox.get(timeout=10)=={'fixture_request_admitted':True}
        request=channel.request(ready['target'],1,timeout=30)
        proc.stdin.write(json.dumps({'body_json':canonical(request['body']).decode(),'mac':request['mac']})+'\n');proc.stdin.flush()
        # A completed journal is not proof that the signed reply reached stdout.
        # Use the same bounded acknowledgment window for every native mode.
        reply_deadline=time.monotonic()+35
        reply=None
        while time.monotonic()<reply_deadline:
            try:
                reply=inbox.get(timeout=min(0.5,max(0.01,reply_deadline-time.monotonic())))
                break
            except queue.Empty:
                if proc.poll() is not None:
                    pytest.fail(
                        f'Native acknowledgment HOLD: child exited before reply; '
                        f'exit_code={proc.returncode}',
                        pytrace=False,
                    )
        if reply is None:
            pytest.fail(
                'Native acknowledgment HOLD: no stdout reply within 35 seconds; '
                'journal completion alone is insufficient',
                pytrace=False,
            )
        raw=reply['body_json'];body=json.loads(raw);assert canonical(body).decode()==raw
        ack=channel.verify_reply(request,{'body':body,'mac':reply['mac']})
        if active_request is not None:
            active_request.join(5)
            assert not active_request.is_alive() and request_results[0][0]==200
            assert request_results[0][1]['fixture'] is True
        assert json.loads(ack['owner_json'])==owner and ack['completed_workers']==['web-http']
        proc.stdin.close();proc.wait(timeout=30);assert proc.returncode==0
        assert adapter.creation(handle)==ticks
        from ctypes import wintypes
        import ctypes
        code=wintypes.DWORD();method=adapter.kernel.GetExitCodeProcess
        method.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        assert method(handle,ctypes.byref(code)) and code.value==0
        proof=membership.verified_exit()
        (tmp_path/'native-descendant-proof.json').write_text(json.dumps(proof))
    finally:
        if active_request is not None:active_request.join(10)
        if hmr is not None:
            # Client cleanup is not server-shutdown certification.
            hmr.close(code=1000,reason='Isolated client cleanup')
        # Never force-kill a native fixture to manufacture graceful closure.
        if proc.poll() is None:
            (tmp_path/'native-next-hold.json').write_text(json.dumps({'pid':proc.pid,'creation_ticks':ticks,
                'status':'HOLD_FIXTURE_RETAINED','reason':'Native closure not proven'}))
        adapter.close(handle)
        membership.close()
        if errors:(tmp_path/'stderr.txt').write_text(''.join(errors))
        (tmp_path/'stdout-events.json').write_text(json.dumps(stdout_events))
