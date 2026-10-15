"""Inactive worker-private IPC protocol. No process creation, signals or Next patches.

Trusted integration supplies fresh native, socket and descendant-closure evidence.
Private frames must use a dedicated inherited pipe/IPC, never argv/env/status/logs.
An acknowledgement is not proof of exit. Production lifecycle authority stays false.
"""
from datetime import datetime
import json
import re
import math
from functools import wraps
import secrets
import threading
import time

from scripts.genesis_child_observation import ChildObservations
from scripts.genesis_launch_provenance import authenticated, descriptor, encoded, signed


def frame(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 16384:
        raise ValueError('Private IPC frame outside bound')
    return json.loads(raw)


class WorkerGate:
    def __init__(self, *, parents, native, socket_owned, closed, executable,
                 command_sha256, now=time.monotonic):
        if (not isinstance(parents, ChildObservations) or
                any(not callable(f) for f in (native, socket_owned, closed, now)) or
                not isinstance(executable, str) or not executable or
                not isinstance(command_sha256, str) or not re.fullmatch('[a-f0-9]{64}',command_sha256)):
            raise ValueError('Explicit trusted isolated worker configuration required')
        self.parents=parents;self.native=native;self.socket_owned=socket_owned
        self.closed=closed;self.executable=executable;self.command=command_sha256
        self.now=now;self.lock=threading.RLock();self.record=None;self.generation=0

    def _hold(self):
        if self.record is not None:self.record['phase']='HOLD'
        raise ValueError('Worker evidence incomplete; HOLD') from None

    def _current(self):
        r=self.record
        try:
            if r is None or r['phase'] in ('HOLD','RETIRED'):self._hold()
            if self.parents.checked('web') != r['parent']:self._hold()
            if descriptor(self.native(r['owner']['pid'])) != r['owner']:self._hold()
        except Exception:self._hold()

    def _deadline(self):
        r=self.record
        value=self.now()
        if type(value) not in (int,float) or not r['started'] <= value < r['deadline']:self._hold()

    def prepare(self, owner, receiver_nonce):
        with self.lock:
            if self.record is not None and self.record['phase']!='RETIRED':self._hold()
            if self.generation>=64:raise ValueError('Bounded trial exhausted')
            if not isinstance(receiver_nonce,str) or not re.fullmatch('[a-f0-9]{64}',receiver_nonce):
                raise ValueError('Fresh private receiver nonce required')
            parent=self.parents.checked('web');owner=descriptor(owner)
            if (owner['pid']==parent['owner']['pid'] or owner['parent_pid']!=parent['owner']['pid'] or
                    owner['executable']!=self.executable or owner['command_sha256']!=self.command or
                    datetime.fromisoformat(owner['created'])<datetime.fromisoformat(parent['owner']['created'])):
                raise ValueError('Worker identity not pinned')
            self.generation+=1;start=self.now()
            body={'kind':'genesis-next-worker-v1','session':secrets.token_hex(32),
                  'generation':self.generation,'parent':parent,'owner':owner,
                  'nonce':secrets.token_hex(32),'receiver_nonce':receiver_nonce,'lifecycle_authorized':False}
            r={'phase':'CHALLENGED','parent':parent,'owner':owner,'challenge':body,
               'key':secrets.token_bytes(32),'started':start,'deadline':start+30}
            self.record=r;self._current();self._deadline()
            return encoded({'challenge':body,'key':r['key'].hex()})

    def install(self, proof):
        with self.lock:
            try:
                self._current();self._deadline();r=self.record
                if r['phase']!='CHALLENGED' or encoded(authenticated(r['key'],proof))!=encoded(r['challenge']):self._hold()
                r['phase']='INSTALLED'
                return signed(r['key'],{'kind':'installed','session':r['challenge']['session'],
                                        'generation':self.generation})
            except Exception:self._hold()

    def ready(self, proof):
        with self.lock:
            try:
                self._current();self._deadline();r=self.record
                b=authenticated(r['key'],proof)
                if (r['phase']!='INSTALLED' or set(b)!={'kind','session','generation','port'} or
                    b['kind']!='ready' or b['session']!=r['challenge']['session'] or
                    type(b['generation']) is not int or b['generation']!=self.generation or type(b['port']) is not int or not 1<=b['port']<=65535 or
                    self.socket_owned(r['owner'],b['port']) is not True):self._hold()
                self._current();self._deadline();r['port']=b['port'];r['phase']='RUNNING'
                return self.status()
            except Exception:self._hold()

    def stop_request(self):
        with self.lock:
            try:
                self._current();r=self.record
                if r['phase']!='RUNNING':self._hold()
                if self.socket_owned(r['owner'],r['port']) is not True:self._hold()
                start=self.now()
                if type(start) not in (int,float) or not math.isfinite(start) or start<r['started']:self._hold()
                r['started']=start;r['deadline']=start+30
                r['request']=secrets.token_hex(32);r['phase']='STOP_REQUESTED'
                return signed(r['key'],{'kind':'stop','session':r['challenge']['session'],
                              'generation':self.generation,'request':r['request']})
            except Exception:self._hold()

    def acknowledge(self, proof):
        with self.lock:
            try:
                self._current();self._deadline();r=self.record
                kind={'STOP_REQUESTED':'drained','DRAINED':'completed','COMPLETED':'descendants_closed'}.get(r['phase'])
                expected={'kind':kind,'session':r['challenge']['session'],
                          'generation':self.generation,'request':r['request'],
                          'accepting':False,'inflight':0,'unresolved':0}
                if kind is None or encoded(authenticated(r['key'],proof))!=encoded(expected):self._hold()
                r['phase']={'drained':'DRAINED','completed':'COMPLETED','descendants_closed':'AWAITING_NATIVE_EXIT'}[kind]
                return self.status()
            except Exception:self._hold()

    def finish(self):
        with self.lock:
            # Worker may already have exited, so do not require its PID to remain live.
            try:
                r=self.record;self._deadline()
                if (r['phase']!='AWAITING_NATIVE_EXIT' or self.parents.checked('web')!=r['parent'] or
                    self.closed(r['owner'],r['port']) is not True):self._hold()
                self._deadline();r['phase']='RETIRED';r['key']=None
                return self.status()
            except Exception:self._hold()

    def disconnected(self):
        with self.lock:self._hold()

    def status(self):
        with self.lock:
            return {'phase':self.record['phase'] if self.record else 'UNREGISTERED',
                    'generation':self.generation,'scope':'ISOLATED_WORKER_OBSERVATION',
                    'production_enabled':False,'lifecycle_authorized':False}


def peer_failure(method):
    @wraps(method)
    def guarded(self,*args,**kwargs):
        try:return method(self,*args,**kwargs)
        except Exception:
            self.phase='HOLD'
            raise ValueError('Worker private protocol rejected; HOLD') from None
    return guarded


class WorkerPeer:
    """Synthetic receiver; callbacks must describe actual worker-owned work.

    No automatic job cancellation or listener/descendant termination. A future
    adapter must fence, drain, close and exit cooperatively, then prove it natively.
    """
    def __init__(self, raw, *, owner, parent, receiver_nonce, now=time.monotonic):
        v=frame(raw)
        if set(v)!={'challenge','key'}:raise ValueError('Private challenge required')
        b=v['challenge']
        if (set(b)!={'kind','session','generation','parent','owner','nonce','receiver_nonce','lifecycle_authorized'} or
                b['kind']!='genesis-next-worker-v1' or b['owner']!=descriptor(owner) or
                b['parent']!=parent or b['receiver_nonce']!=receiver_nonce or
                not isinstance(receiver_nonce,str) or not re.fullmatch('[a-f0-9]{64}',receiver_nonce) or
                type(b['generation']) is not int or b['generation']<1 or owner['parent_pid']!=parent['owner']['pid'] or
                b['lifecycle_authorized'] is not False or not isinstance(v['key'],str) or len(v['key'])!=64):
            raise ValueError('Private worker identity mismatch')
        self.body=b;self.key=bytes.fromhex(v['key']);self.phase='CHALLENGED';self.request=None
        self.now=now;self.started=now()
        if type(self.started) not in (int,float) or not math.isfinite(self.started):raise ValueError('Worker clock unavailable')

    def _fresh(self):
        value=self.now()
        if not self.started<=value<self.started+30:raise ValueError('Worker installation expired')

    def proof(self):return signed(self.key,self.body)

    @peer_failure
    def install(self, proof):
        self._fresh()
        expected={'kind':'installed','session':self.body['session'],'generation':self.body['generation']}
        if self.phase!='CHALLENGED' or encoded(authenticated(self.key,proof))!=encoded(expected):raise ValueError('Installation rejected')
        self.phase='INSTALLED'

    @peer_failure
    def ready(self, port):
        self._fresh()
        if type(port) is not int or not 1<=port<=65535:raise ValueError('Invalid worker socket')
        if self.phase!='INSTALLED':raise ValueError('Dispatch before private installation denied')
        self.phase='RUNNING'
        return signed(self.key,{'kind':'ready','session':self.body['session'],'generation':self.body['generation'],'port':port})

    @peer_failure
    def stop(self, proof, *, fence):
        b=authenticated(self.key,proof)
        if (self.phase!='RUNNING' or set(b)!={'kind','session','generation','request'} or
                type(b['generation']) is not int or not isinstance(b['request'],str) or not re.fullmatch('[a-f0-9]{64}',b['request']) or
                b['kind']!='stop' or b['session']!=self.body['session'] or b['generation']!=self.body['generation']):
            raise ValueError('Stop replay or wrong worker')
        # Latch before calling worker hook. A failed fence cannot be retried as RUNNING.
        self.phase='HOLD'
        if fence() is not True:raise ValueError('Work admission not fenced')
        self.request=b['request'];self.phase='STOP_REQUESTED'

    @peer_failure
    def acknowledge(self, kind, *, evidence):
        expected={'STOP_REQUESTED':'drained','DRAINED':'completed','COMPLETED':'descendants_closed'}.get(self.phase)
        if kind!=expected:raise ValueError('Out-of-order worker completion')
        self.phase='HOLD'
        if encoded(evidence())!=encoded({'accepting':False,'inflight':0,'unresolved':0}):raise ValueError('Worker unresolved')
        proof=signed(self.key,{'kind':kind,'session':self.body['session'],
            'generation':self.body['generation'],'request':self.request,
            'accepting':False,'inflight':0,'unresolved':0})
        self.phase={'drained':'DRAINED','completed':'COMPLETED','descendants_closed':'CLOSED'}[kind]
        return proof
