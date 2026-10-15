"""Explicit inactive bridge for the real runner; observation is not admission."""
import os
import threading

from scripts.genesis_launch_provenance import answer_launch, descriptor


class SupervisorObservation:
    def __init__(self, *, service, read_private, send_private, native, child):
        if not all(callable(f) for f in (read_private, send_private, native, child)):
            raise ValueError('Explicit private/native observation callbacks required')
        self.service = service; self._read = read_private; self._send = send_private
        self._native = native; self._child = child; self._owner = None
        self._public = None; self.phase = 'PREPARED'; self._lock = threading.RLock()

    def enter(self, service, pid):
        with self._lock:
            try:
                if (self.phase != 'PREPARED' or service != self.service or pid != os.getpid() or
                        os.environ.get('GENESIS_SUPERVISOR_LAUNCH_TOKEN')):
                    raise ValueError('Mixed, replayed or mismatched supervisor bootstrap')
                owner = descriptor(self._native(pid))
                proof = answer_launch(self._read(), owner)
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
                if self._child(process, tuple(command), dict(self._owner)) is not True:
                    raise ValueError('Unverified child')
            except Exception:
                self.phase = 'HOLD'
                raise ValueError('Child/wrapper native observation unavailable; HOLD') from None
