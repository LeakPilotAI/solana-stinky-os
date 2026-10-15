"""Explicit inactive bridge for the real runner; observation is not admission."""
import os
import threading
from contextlib import nullcontext

from scripts.genesis_launch_provenance import answer_launch, descriptor, encoded


class SupervisorObservation:
    def __init__(self, *, service, read_private, send_private, native, child, private_child=None, maintenance=None):
        if not all(callable(f) for f in (read_private, send_private, native, child)):
            raise ValueError('Explicit private/native observation callbacks required')
        self.service = service; self._read = read_private; self._send = send_private
        self._native = native; self._child = child; self._owner = None
        self._public = None; self.phase = 'PREPARED'; self._lock = threading.RLock()
        if private_child is not None:
            from scripts.genesis_private_child_channel import PrivatePythonChildChannel
            if not isinstance(private_child,PrivatePythonChildChannel) or private_child.service!=service:
                raise ValueError('Explicit service-bound private child channel required')
        self.private_child=private_child
        if maintenance is not None:
            from scripts.genesis_maintenance_observation import MaintenanceObservation
            if service!='maintain' or private_child is not None or not isinstance(maintenance,MaintenanceObservation):
                raise ValueError('Explicit separate maintenance observation required')
        self.maintenance=maintenance

    def loop(self,name):
        self.verify()
        return self.maintenance.loop(name) if self.maintenance is not None else nullcontext()

    def job(self,command):
        self.verify()
        return self.maintenance.job(command) if self.maintenance is not None else nullcontext()

    @property
    def private_pipe(self):
        return self.private_child is not None or self.maintenance is not None

    def child_command(self, command):
        self.verify()
        channel=self.maintenance.channel() if self.maintenance is not None else self.private_child
        return channel.command_for(command) if channel is not None else command

    def enter(self, service, pid):
        with self._lock:
            try:
                if (self.phase != 'PREPARED' or service != self.service or pid != os.getpid() or
                        os.environ.get('GENESIS_SUPERVISOR_LAUNCH_TOKEN')):
                    raise ValueError('Mixed, replayed or mismatched supervisor bootstrap')
                owner = descriptor(self._native(pid))
                proof = answer_launch(self._read(), owner)
                if (self.private_child is not None and
                        encoded(self.private_child.controller.launches.checked(service)['challenge']) !=
                        encoded(proof['body'])):
                    raise ValueError('Child channel belongs to another supervisor generation')
                if self.maintenance is not None and encoded(self.maintenance.launches.checked(service)['challenge'])!=encoded(proof['body']):
                    raise ValueError('Maintenance belongs to another supervisor generation')
                if descriptor(self._native(pid)) != owner:
                    raise ValueError('Supervisor changed during private processing')
                self._send(proof)
                self._owner = owner
                self._public = {'generation': proof['body']['generation'], 'service': service,
                                'pid': pid, 'scope': 'OBSERVATION_NOT_LIFECYCLE_AUTHORITY'}
                self.phase = 'OBSERVED'
            except Exception:
                self.phase = 'HOLD'
                raise ValueError('Supervisor observation bootstrap rejected; HOLD') from None

    def verify(self):
        try:
            if self.phase != 'OBSERVED' or descriptor(self._native(os.getpid())) != self._owner:
                raise ValueError('Native observation differs')
        except Exception:
            self.phase = 'HOLD'
            raise ValueError('Supervisor observation stale; HOLD') from None

    def heartbeat(self, payload):
        with self._lock:
            self.verify()
            if (not isinstance(payload, dict) or payload.get('service') != self.service or
                    payload.get('supervisor_pid') != self._owner['pid']):
                self.phase = 'HOLD'
                raise ValueError('Heartbeat observation target mismatch; HOLD')
            result = dict(payload)
            result.pop('supervisor_launch_token', None)
            result['launch_observation'] = dict(self._public)
            return result

    def child_started(self, process, command):
        with self._lock:
            try:
                self.verify()
                channel=self.maintenance.channel() if self.maintenance is not None else self.private_child
                if channel is not None:
                    def native_before_continue():
                        self.verify()
                        return self._child(process,tuple(command),dict(self._owner)) is True
                    channel.deliver(process,command,dict(self._owner),before_continue=native_before_continue)
                elif self._child(process, tuple(command), dict(self._owner)) is not True:
                    raise ValueError('Unverified child')
            except Exception:
                self.phase = 'HOLD'
                raise ValueError('Child/wrapper native observation unavailable; HOLD') from None
