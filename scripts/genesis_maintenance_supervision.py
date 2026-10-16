"""Inactive concurrent maintenance admission/drain. No spawn, signal or executor.

Caller owns isolated scheduling; production runner is not imported or modified.
Drain is observation of registered work, not proof of supervisor process exit.
"""
from contextlib import contextmanager
import math
import re
import secrets
import threading
import time
import weakref

from scripts.genesis_launch_provenance import encoded, signed, authenticated
from scripts.genesis_maintenance_observation import MaintenanceObservation, LOOPS

PERIODS={'v2-maintenance':10,'research-maintenance':60,'slow-maintenance':21600}
_CLAIMS=weakref.WeakKeyDictionary()
_CLAIMS_LOCK=threading.RLock()


class MaintenanceDrain:
    def __init__(self, manager, *, isolated=False, idle, clock=time.monotonic):
        if (not isinstance(manager,MaintenanceObservation) or manager.retirement is None or
                type(isolated) is not bool or not callable(idle) or not callable(clock)):
            raise ValueError('Explicit manager, retirement and idle witnesses required')
        self.manager=manager;self.enabled=isolated;self.idle=idle;self.clock=clock
        self.condition=manager.boundary.condition;self.phase='RUNNING' if isolated else 'DISABLED'
        self.binding=encoded(manager.launches.checked('maintain')['challenge'])
        self.active=set();self.completed=0;self.started=0;self.next_due={n:float('-inf') for n in LOOPS}
        self.request=None;self.last_time=None
        if isolated:
            with self.condition, _CLAIMS_LOCK:
                claims=_CLAIMS.setdefault(manager.launches,set())
                if self.binding in claims or len(claims)>=64:raise ValueError('Generation already claimed or trial exhausted')
                boundary=manager.boundary
                if boundary.binding is not None and (boundary.phase!='CLOSED' or not boundary.idle()):
                    raise ValueError('Previous maintenance boundary unresolved; HOLD')
                if any(m.retirement is None for m in boundary.managers):
                    raise ValueError('Every manager requires independent retirement evidence; HOLD')
                claims.add(self.binding)
                boundary.binding=self.binding;boundary.phase='OPEN'

    def _hold(self):
        if self.enabled and self.manager.boundary.binding==self.binding:
            self.manager.boundary.phase='HOLD'
        self.phase='HOLD';self.condition.notify_all()
        raise ValueError('Maintenance boundary incomplete; HOLD') from None

    def _verify(self):
        try:
            if self.enabled and (self.manager.boundary.binding!=self.binding or self.manager.boundary.phase=='HOLD'):self._hold()
            if self.manager.phase!='READY' or encoded(self.manager.launches.checked('maintain')['challenge'])!=self.binding:self._hold()
        except Exception:self._hold()

    def _time(self):
        value=self.clock()
        if type(value) not in (int,float) or not math.isfinite(value) or (self.last_time is not None and value<self.last_time):self._hold()
        self.last_time=value;return value

    @contextmanager
    def cycle(self,loop):
        admitted=False
        with self.condition:
            if not self.enabled or self.phase!='RUNNING':raise ValueError('Admission disabled or fenced')
            self._verify()
            if not isinstance(loop,str) or loop not in LOOPS or loop in self.active:self._hold()
            if self._time()>=self.next_due[loop]:
                self.active.add(loop);self.started+=1;admitted=True
        if not admitted:
            yield False;return
        try:
            with self.manager.loop(loop):yield True
            with self.condition:
                self._verify()
                if self.phase not in ('RUNNING','DRAINING'):self._hold()
                self.completed+=1;self.next_due[loop]=self._time()+PERIODS[loop]
        except BaseException:
            with self.condition:self.phase='HOLD';self.condition.notify_all()
            raise
        finally:
            with self.condition:self.active.remove(loop);self.condition.notify_all()

    def request_drain(self):
        with self.condition:
            self._verify()
            if not self.enabled or self.phase!='RUNNING':self._hold()
            record=self.manager.launches.checked('maintain')
            self.request={'kind':'maintenance-drain-v1','generation':record['challenge']['generation'],
                          'session':record['challenge']['session'],'nonce':secrets.token_hex(32)}
            self.manager.boundary.phase='DRAINING'
            self.phase='DRAINING'
            return signed(record['key'],self.request)

    def drain(self,proof,*,timeout=30):
        with self.condition:
            try:
                if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:self._hold()
                self._verify();record=self.manager.launches.checked('maintain')
                if self.phase!='DRAINING' or encoded(authenticated(record['key'],proof))!=encoded(self.request):self._hold()
                deadline=time.monotonic()+timeout
                while self.active or not self.manager.boundary.idle():
                    self._verify()
                    remaining=deadline-time.monotonic()
                    if remaining<=0:self._hold()
                    self.condition.wait(remaining)
                    if self.phase!='DRAINING':self._hold()
                self._verify()
                if (self.manager.owners or self.manager.active or
                        encoded(self.idle())!=encoded({'active_children':0,'unresolved_jobs':0,'admission_closed':True})):self._hold()
                if time.monotonic()>=deadline:self._hold()
                self._verify();self.manager.boundary.phase='CLOSED';self.phase='QUIESCED_OBSERVATION'
                return self.status()
            except Exception:self._hold()

    def status(self):
        with self.condition:
            return {'phase':self.phase,'active_loops':sorted(self.active),'started':self.started,
                    'completed':self.completed,'production_enabled':False,'lifecycle_authorized':False,
                    'scope':'PROCESS_LOCAL_TRUSTED_REGISTRY_MANAGERS_NOT_GLOBAL_WRITES'}


def classify_transaction(*,operation_id,operation_sha256,marker,rollback_confirmed,writer_closed):
    """One declared atomic transaction only. Never grants automatic job replay.

    Marker must be read independently AFTER commit; absence alone is ambiguous.
    Caller supplies actual cooperative rollback/connection closure evidence.
    """
    if (not isinstance(operation_id,str) or not 1<=len(operation_id)<=128 or not isinstance(operation_sha256,str) or
            not re.fullmatch('[a-f0-9]{64}',operation_sha256) or type(rollback_confirmed) is not bool or type(writer_closed) is not bool):
        raise ValueError('Typed transaction evidence required')
    expected={'operation_id':operation_id,'operation_sha256':operation_sha256}
    if marker is not None and not rollback_confirmed and encoded(marker)==encoded(expected):status='COMMITTED'
    elif marker is None and rollback_confirmed and writer_closed:status='ROLLED_BACK'
    else:status='AMBIGUOUS'
    return {'status':status,'automatic_replay':False,'scope':'ONE_DECLARED_TRANSACTION_NOT_JOB_COMPLETION'}
