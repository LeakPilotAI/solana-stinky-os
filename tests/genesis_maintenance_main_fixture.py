"""Isolated actual-main driver. Synthetic business jobs; no DB/Redis/market access.

Private parent provisioning plus real native child entry/socket/kernel witnesses.
Not a production installer, cross-process drain coordinator or real-job proof.
"""
import hashlib
import json
import ntpath
import os
from pathlib import Path
import sys
import threading
import time

from scripts import run_genesis_service as runner
from scripts.genesis_launch_provenance import answer_launch,authenticated,encoded
from scripts.genesis_child_observation import target
from scripts.genesis_private_child_entry import native
from scripts.genesis_background_ownership import capture,listener_identity
from scripts.genesis_supervisor_observation import SupervisorObservation
from scripts.genesis_supervisor_admission import SupervisorAdmission
from scripts.genesis_maintenance_observation import MaintenanceObservation,LOOPS
from scripts.genesis_maintenance_binding import MaintenanceBinding
from scripts.genesis_child_exit import ChildRegistry
from scripts.genesis_native_descendants import OwnedDescendantJob
from test_genesis_maintenance_binding import ticks

ROOT=Path(__file__).resolve().parents[1]


def main():
    root=Path(sys.argv[1]).resolve()
    if not (root/'docker-compose.yml').is_file() or root==ROOT:
        raise RuntimeError('Exact separate fixture root required')
    print('PRIVATE-MAIN-READY',flush=True)
    frame=bytes.fromhex(json.loads(sys.stdin.readline())['frame'])
    private=json.loads(frame);owner=native(os.getpid())
    proof=answer_launch(frame,owner)
    print(json.dumps(proof),flush=True)
    acknowledgement=authenticated(bytes.fromhex(private['key']),json.loads(sys.stdin.readline()))
    if acknowledgement!={'kind':'fixture-main-processed','target':target(proof)}:
        raise RuntimeError('Parent did not process exact launch generation')

    class LaunchView:
        def checked(self,service):
            if service!='maintain' or native(os.getpid())!=private['challenge']['owner']:
                raise RuntimeError('Fixture launch identity replaced')
            return {'challenge':private['challenge'],'key':bytes.fromhex(private['key'])}
    launches=LaunchView()
    repohash=hashlib.sha256(str(ROOT).encode()).hexdigest()
    gowner={'pid':os.getpid(),'creation_ticks':ticks(os.getpid()),'service':'maintain',
            'command_sha256':owner['command_sha256'],'repository_sha256':repohash}
    def gate_native():
        row=native(os.getpid())
        return {**gowner,'pid':row['pid'],'creation_ticks':ticks(os.getpid()),'command_sha256':row['command_sha256']}
    audit=root/'audit.jsonl';audit_lock=threading.Lock()
    def persist(row):
        raw=encoded(row)
        with audit_lock:
            with audit.open('ab') as f:f.write(raw+b'\n');f.flush();os.fsync(f.fileno())
        return hashlib.sha256(raw).hexdigest()
    gate=SupervisorAdmission(gowner,generation=private['challenge']['generation'],verify_native=gate_native,persist=persist)
    py=sys.executable;scripts=root/'scripts';boundary='2026-10-05T12:46:27.418241+00:00'
    commands={
        'slow-maintenance':[((py,'-m','post_migration.cli',n),root/'post_migration/cli.py') for n in ['learn-success','recompute-performance']],
        'research-maintenance':[((py,str(scripts/n),'--boundary',b,'--limit','500'),scripts/n) for n,b in [
            ('run_intelligence_shadow_scorer.py',boundary),('run_intelligence_paper_decisions.py',boundary),
            ('run_intelligence_paper_execution_plans.py','2026-10-07T07:09:02.404079+00:00')]],
        'v2-maintenance':[((py,str(scripts/'run_intelligence_execution_v2.py')),scripts/'run_intelligence_execution_v2.py')]}
    jobs={};initial={};channels={};job_lock=threading.RLock();socket_proofs=[];faults=[]
    def register(proc,command):
        snap=capture();first=next(r for r in snap['before'] if r['pid']==proc.pid);last=next(r for r in snap['after'] if r['pid']==proc.pid)
        from scripts.genesis_launch_provenance import descriptor
        if (descriptor(first)!=descriptor(last) or last['parent_pid']!=os.getpid() or last['argv']!=list(command)
                or ntpath.normcase(last['executable'])!=ntpath.normcase(command[0])):
            raise RuntimeError('Exact native child command or ancestry missing')
        observed={**native(proc.pid),'creation_ticks':ticks(proc.pid)}
        if {k:v for k,v in observed.items() if k!='creation_ticks'}!=descriptor(last):
            raise RuntimeError('Child identity changed after command census')
        def inspect_native(pid):return {**native(pid),'creation_ticks':ticks(pid)}
        witness=OwnedDescendantJob(proc,observed,inspect_native)
        with job_lock:
            jobs[proc.pid]=(proc,witness);initial[proc.pid]=observed
            # Capture on the admitted service-loop thread. The final private
            # callback runs on the channel exchange thread, not this thread-local.
            channels[proc.pid]=manager.channel()
        return {'pid':proc.pid,'parent_pid':os.getpid(),'creation_ticks':observed['creation_ticks'],
                'command_sha256':hashlib.sha256(json.dumps(command,separators=(',',':')).encode()).hexdigest(),
                'repository_sha256':repohash}
    def inspected(proc,registered):
        with job_lock:witness=jobs[proc.pid][1]
        witness.verified_exit()
        return {'owner':registered,'exited':True,'descendants_exited':True,'exit_code':0}
    def retired(proc,work):
        with job_lock:proof=jobs[proc.pid][1].verified_exit()
        return {'root_pid':proc.pid,'root_exit_code':proof['root_exit_code'],'active_descendants':proof['active_processes'],
                'identity_verified':True,'job_id':work['job_id'],'source_sha256':work['sha256']}
    manager=MaintenanceObservation(launches=launches,native=native,ancestry=lambda c,p:c['parent_pid']==p['pid'],
        manifest=commands,retirement=retired)
    def child(proc,command,supervisor):
        observed=native(proc.pid)
        with job_lock:before=initial[proc.pid]
        if {**observed,'creation_ticks':ticks(proc.pid)}!=before or observed['parent_pid']!=supervisor['pid']:
            return False
        with job_lock:channel=channels[proc.pid]
        return channel.controller.checked('maintain')['owner']==observed
    def send(processed):
        if encoded(processed)!=encoded(proof):raise RuntimeError('Main substituted launch generation')
    observer=SupervisorObservation(service='maintain',read_private=lambda:frame,send_private=send,native=native,child=child,maintenance=manager)
    def idle():
        with job_lock:
            for proc,witness in jobs.values():witness.verified_exit()
        return {'active_descendants':0,'unresolved_writers':0,'identity_verified':True}
    binding=MaintenanceBinding(observer,gate,repository=ROOT,idle=idle,isolated=True)
    runner.LAUNCH_OBSERVATION=observer
    runner.install_cooperative_supervisor(gate)
    runner.install_child_registry(ChildRegistry(gate,capture=register,inspect=inspected,persist=persist))
    runner.install_maintenance_binding(binding)
    # Test-only root/clocks/dependency surfaces. Actual main/loops/dispatch/readers
    # remain unmodified. Synthetic jobs have no database or market implementation.
    runner.__file__=str(scripts/'run_genesis_service.py')
    runner.restore_search_path=lambda:None
    runner.CORE_HEALTH=()
    runner.API_HEALTH_POLL_SECONDS=.02
    watchdog=[]
    def safe_watchdog(r,d,run):
        if r!=root or not gate.jobs:raise RuntimeError('Fixture watchdog admission missing')
        watchdog.append('read-only-fixture-no-container-operations')
    runner.recover_watch_dependencies=safe_watchdog
    waits=set();wait_lock=threading.Lock()
    def wait(seconds):
        with wait_lock:waits.add(seconds)
        gate.stop_event.wait(120)
    runner.supervisor_wait=wait
    def controller():
        stage='START'
        active_pid=None
        try:
            deadline=time.monotonic()+150;processed=set()
            while time.monotonic()<deadline:
                if gate.phase=='HOLD' or gate.stop_event.is_set():
                    raise RuntimeError('Fixture controller observed HOLD before closure')
                with job_lock:rows=list(jobs.items())
                for pid,(proc,witness) in rows:
                    active_pid=pid
                    stage='JOB_MARKER'
                    marker=root/f'job-{pid}.json'
                    if pid in processed or not marker.is_file():continue
                    row=json.loads(marker.read_text());port=row['port']
                    if row['pid']!=pid or type(port) is not int or not 0<port<65536:
                        raise RuntimeError('Malformed socket provenance')
                    stage='NATIVE_IDENTITY'
                    observed=native(pid)
                    stage='SOCKET_OWNERSHIP'
                    if {**observed,'creation_ticks':ticks(pid)}!=initial[pid] or not listener_identity(capture((port,)),pid,port):
                        raise RuntimeError('Native admitted child socket missing')
                    socket_proofs.append({'pid':pid,'port':port,'generation':gate.generation,'verified':True})
                    stage='COOPERATIVE_COMPLETION'
                    (root/f'finish-{pid}').write_text('cooperative fixture work completion')
                    processed.add(pid)
                with wait_lock:complete=waits=={10,60,21600}
                if complete and len(processed)==6:
                    stage='QUIESCE'
                    gate.quiesce({'request_id':'d'*32,'manifest_sha256':gate.manifest()},timeout=10)
                    return
                time.sleep(.02)
            raise RuntimeError('Fixture admission/drain deadline; HOLD')
        except BaseException as e:
            import traceback
            frames=traceback.extract_tb(e.__traceback__)
            diagnostic={
                'exception_type':type(e).__name__,
                'stage':stage,
                'active_pid':active_pid,
                'traceback_locations':[
                    {'function':f.name,'line':f.lineno}
                    for f in frames[-6:]
                ],
            }
            (root/'controller-failure.json').write_text(
                json.dumps(diagnostic,indent=2)
            )
            faults.append(type(e).__name__);gate.phase='HOLD';gate.stop_event.set()
    control=threading.Thread(target=controller,name='fixture-controller');control.start()
    sys.argv=['isolated-maintenance-main','--name','maintain']
    try:
        result=runner.main();control.join(15)
        if faults or control.is_alive() or result!=0 or gate.phase!='QUIESCED':
            raise RuntimeError('Actual main fixture closure unresolved; HOLD')
        proof_rows=[]
        with job_lock:
            for proc,witness in jobs.values():proof_rows.append(witness.verified_exit())
        result={'scope':'ACTUAL_MAIN_NATIVE_CHILDREN_SYNTHETIC_BUSINESS_JOBS_NOT_SQL_REDIS_OR_PRODUCTION',
                'phase':gate.phase,'children':proof_rows,'sockets':socket_proofs,'cadences':sorted(waits),
                'watchdog':watchdog,'bounded_boundary':binding.verify_drained(),
                'loop_threads_retired':all(r['done'] for r in gate.loops.values()),
                'controller_retired':not control.is_alive(),'lifecycle_authorized':False}
        (root/'native-main-proof.json').write_text(json.dumps(result,indent=2))
    finally:
        gate.stop_event.set();control.join(15)
        with job_lock:
            (root/'channel-phases.json').write_text(json.dumps({str(pid):{'phase':c.phase,'stage':c.failure_stage} for pid,c in channels.items()}))
            for proc,witness in jobs.values():
                # Close only the private pipe this fixture created; this is
                # cooperative EOF rejection, never a process signal or kill.
                if proc.stdin and not proc.stdin.closed:proc.stdin.close()
                if proc.poll() is None:(root/f'HOLD-{proc.pid}.json').write_text(json.dumps({'pid':proc.pid,'reason':'No forced cleanup authorized'}))
                witness.close()


if __name__=='__main__':main()
