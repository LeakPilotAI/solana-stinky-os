"""Explicit isolated maintenance bridge. No installer, IPC, spawn or authority UI.

One supervisor/generation only. Separate processes and unenrolled registries HOLD.
Native callbacks are trusted witnesses, never inferred from a heartbeat.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
import threading

from scripts.genesis_launch_provenance import encoded, signed, authenticated
from scripts.genesis_supervisor_admission import SupervisorAdmission, FencedAdmission
from scripts.genesis_supervisor_observation import SupervisorObservation
from scripts.genesis_maintenance_observation import LOOPS


class MaintenanceBinding:
    def __init__(self, observer, gate, *, repository, idle, isolated=False):
        if (isolated is not True or not isinstance(observer,SupervisorObservation) or
                not isinstance(gate,SupervisorAdmission) or observer.service!='maintain' or
                observer.maintenance is None or observer.maintenance.retirement is None or
                not callable(idle) or gate.expected_loops!=LOOPS):
            raise ValueError('Explicit isolated authenticated maintenance binding required')
        self.observer=observer;self.gate=gate;self.manager=observer.maintenance
        self.idle=idle;self.local=threading.local();self.phase='BOUND'
        self.repository=hashlib.sha256(str(repository).encode()).hexdigest()
        record=self.manager.launches.checked('maintain')
        self.challenge=encoded(record['challenge'])
        self.body={'kind':'maintenance-supervisor-binding-v1','launch':record['challenge'],
                   'supervisor_manifest':gate.manifest()}
        self.proof=signed(record['key'],self.body)
        self.verify()
        with self.manager.lock:
            if (self.manager.active or self.manager.owners or self.manager.boundary.authority is not None or
                    any(m is not self.manager for m in self.manager.boundary.managers)):
                raise ValueError('Clean single enrolled manager required; other registries remain HOLD')
            self.manager.boundary.authority=self

    def hold(self):
        self.phase='HOLD'
        with self.gate.changed:
            self.gate.phase='HOLD';self.gate.changed.notify_all()
        raise ValueError('Maintenance binding incomplete; HOLD') from None

    def verify(self):
        try:
            self.gate.verify()
            record=self.manager.launches.checked('maintain');c=record['challenge'];o=c['owner'];g=self.gate.owner
            created=datetime.fromisoformat(o['created'].replace('Z','+00:00')).astimezone(timezone.utc)
            epoch=datetime(1970,1,1,tzinfo=timezone.utc);delta=created-epoch
            micros=(delta.days*86400+delta.seconds)*1000000+delta.microseconds
            if (self.phase=='HOLD' or encoded(c)!=self.challenge or self.observer.maintenance is not self.manager or
                    g['service']!='maintain' or g['pid']!=o['pid'] or g['pid']!=os.getpid() or
                    g['command_sha256']!=o['command_sha256'] or g['repository_sha256']!=self.repository or
                    (g['creation_ticks']-116444736000000000)//10!=micros or
                    self.gate.generation!=c['generation'] or self.gate.manifest()!=self.body['supervisor_manifest'] or
                    encoded(authenticated(record['key'],self.proof))!=encoded(self.body)):
                self.hold()
        except Exception:self.hold()

    def matches(self, observer, gate):
        if observer is not self.observer or gate is not self.gate:self.hold()
        self.verify()

    def admission(self, manager, *, job=False):
        self.verify()
        if manager is not self.manager:self.hold()
        if job:
            self.ticket()  # A direct caller cannot bypass the root admission ticket.
        elif self.gate.phase!='RUNNING':
            raise FencedAdmission('Maintenance loop admission fenced')

    @contextmanager
    def work(self, command):
        self.verify()
        ticket=getattr(self.local,'ticket',None)
        if ticket is not None:
            with self.gate.changed:
                if ticket not in self.gate.jobs:self.hold()
            yield ticket
            self.verify()
            return
        with self.gate.job(command) as ticket:
            self.local.ticket=ticket
            try:yield ticket
            finally:self.local.ticket=None

    def ticket(self):
        ticket=getattr(self.local,'ticket',None)
        with self.gate.changed:
            if ticket is None or ticket not in self.gate.jobs:self.hold()
        return ticket

    @contextmanager
    def writer(self, ticket):
        """Runner-created log reader, charged to its still-live parent job ticket."""
        self.verify()
        if getattr(self.local,'ticket',None) is not None:self.hold()
        with self.gate.changed:
            if ticket not in self.gate.jobs:self.hold()
        self.local.ticket=ticket
        try:yield
        except BaseException:self.hold()
        finally:self.local.ticket=None

    def verify_drained(self):
        self.verify()
        with self.gate.changed:
            if (self.gate.phase!='QUIESCED' or self.gate.jobs or set(self.gate.loops)!=LOOPS or
                    any(not r['done'] or r['failed'] for r in self.gate.loops.values())):
                self.hold()
        # No gate->manager lock nesting: admission uses manager->gate ordering.
        with self.manager.lock:
            if self.manager.active or self.manager.owners:self.hold()
        try:
            if encoded(self.idle())!=encoded({'active_descendants':0,'unresolved_writers':0,'identity_verified':True}):self.hold()
        except Exception:self.hold()
        self.verify()
        if self.gate.phase!='QUIESCED':self.hold()
        return {'scope':'BOUND_MAINTENANCE_ONLY_NOT_GLOBAL_WRITES_OR_PROCESS_EXIT','lifecycle_authorized':False}
