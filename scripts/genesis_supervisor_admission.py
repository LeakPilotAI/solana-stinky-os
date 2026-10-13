"""Default-off cooperative supervisor job tickets; never kills or controls Docker.

Trusted startup/controller code must provide independent native identity evidence.
An acknowledgement certifies tickets only, not child-process exit or Redis closure.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import re
import threading
import time
import uuid


CORE={'event-log','api','sentinel','collector','entities','web','maintain'}


class FencedAdmission(RuntimeError):
    pass


class SupervisorAdmission:
    def __init__(self,owner,*,generation,verify_native,persist):
        if (not isinstance(owner,dict) or set(owner)!={'pid','creation_ticks','service','command_sha256','repository_sha256'} or
            owner['service'] not in CORE|{'fixture'} or
            any(type(owner[k]) is not int or owner[k]<=0 for k in ('pid','creation_ticks')) or
            any(not re.fullmatch('[0-9a-f]{64}',owner[k]) for k in ('command_sha256','repository_sha256')) or
            type(generation) is not int or generation<=0 or not callable(verify_native) or not callable(persist)):
            raise RuntimeError('Complete native supervisor ownership required')
        self.owner=dict(owner);self.generation=generation;self.verify_native=verify_native;self.persist=persist
        self.phase='RUNNING';self.jobs={};self.changed=threading.Condition(threading.RLock());self.head=None
        self.stop_event = threading.Event()
        self.loops = {}
        self.expected_loops = (frozenset({'slow-maintenance','v2-maintenance','research-maintenance'})
                               if owner['service']=='maintain' else
                               frozenset() if owner['service']=='fixture' else
                               frozenset({'supervised-child-loop'}))
        self.verify()

    def verify(self):
        if self.verify_native()!=self.owner:raise RuntimeError('Supervisor identity changed or unavailable')

    def manifest(self):
        return hashlib.sha256(json.dumps({'owner':self.owner,'generation':self.generation,
            'expected_loops':sorted(self.expected_loops)},sort_keys=True,separators=(',',':')).encode()).hexdigest()

    @contextmanager
    def loop(self, name):
        with self.changed:
            self.verify()
            if self.phase!='RUNNING' or name not in self.expected_loops or name in self.loops:
                self.phase='HOLD'
                raise RuntimeError('Supervisor loop missing, replaced or unregistered')
            row={'thread':threading.current_thread(),'done':False,'failed':False}
            self.loops[name]=row
        try:
            yield
            self.verify()
            if not self.stop_event.is_set():raise RuntimeError('Supervisor loop exited unexpectedly')
        except BaseException:
            with self.changed:
                row['failed']=True;self.phase='HOLD';self.changed.notify_all()
            raise
        finally:
            with self.changed:
                row['done']=True;self.changed.notify_all()

    def record(self,phase,request_id):
        head=self.persist({'stage':'SUPERVISOR_PHASE','phase':phase,'request_id':request_id,'manifest_sha256':self.manifest()})
        if not isinstance(head,str) or not re.fullmatch('[0-9a-f]{64}',head):raise RuntimeError('Durable supervisor audit unavailable')
        self.head=head

    @contextmanager
    def job(self,command):
        with self.changed:
            try:
                self.verify()
                if len(self.jobs)>=64:raise RuntimeError('Supervisor job admission full')
                if self.phase!='RUNNING':
                    # Refusal of new work is expected after a verified fence.
                    # It cannot reopen or poison a completed generation.
                    raise FencedAdmission('Supervisor job admission fenced')
                token=uuid.uuid4().hex
                # Raw commands can contain secrets. Keep only the bounded digest.
                encoded=json.dumps(command,separators=(',',':')).encode()
                if len(encoded)>16384:raise RuntimeError('Supervisor command outside bound')
                self.jobs[token]=hashlib.sha256(encoded).hexdigest()
            except FencedAdmission:raise
            except BaseException:
                self.phase='HOLD';self.changed.notify_all();raise
        try:
            yield token
            self.verify()
        except BaseException:
            with self.changed:self.phase='HOLD';self.changed.notify_all()
            raise
        finally:
            with self.changed:self.jobs.pop(token,None);self.changed.notify_all()

    def quiesce(self,request,*,timeout=10):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=60:
            raise RuntimeError('Bounded supervisor drain deadline required')
        with self.changed:
            try:
                deadline=time.monotonic()+timeout;self.verify()
                if (not isinstance(request,dict) or set(request)!={'request_id','manifest_sha256'} or
                    not isinstance(request['request_id'],str) or not re.fullmatch('[0-9a-f]{32}',request['request_id']) or
                    request['manifest_sha256']!=self.manifest() or self.phase!='RUNNING'):
                    raise RuntimeError('Stale supervisor request or generation')
                self.phase='FENCING';self.record(self.phase,request['request_id'])
                self.stop_event.set()
                if set(self.loops)!=self.expected_loops or any(row['done'] for row in self.loops.values()):
                    raise RuntimeError('Supervisor loop ownership incomplete; HOLD')
                if any(row['thread'] is threading.current_thread() for row in self.loops.values()):
                    raise RuntimeError('Supervisor cannot join its own active loop')
                self.phase='DRAINING';self.record(self.phase,request['request_id'])
                while self.jobs or any(not row['done'] for row in self.loops.values()):
                    self.verify()
                    remaining=deadline-time.monotonic()
                    if self.phase=='HOLD' or remaining<=0:raise RuntimeError('Supervisor drain unresolved; HOLD')
                    self.changed.wait(remaining)
                self.verify()
                if self.phase=='HOLD' or any(row['failed'] for row in self.loops.values()) or time.monotonic()>=deadline:raise RuntimeError('Supervisor drain deadline exceeded')
                self.phase='QUIESCED';self.record(self.phase,request['request_id']);self.verify()
                if time.monotonic()>=deadline:raise RuntimeError('Supervisor audit deadline exceeded')
                return {'phase':self.phase,'owner':dict(self.owner),'generation':self.generation,
                        'request_id':request['request_id'],'journal_head':self.head,
                        'scope':'JOB_TICKETS_ONLY_NOT_PROCESS_EXIT_OR_WRITER_BOUNDARY'}
            except BaseException:
                self.phase='HOLD';self.changed.notify_all();raise
