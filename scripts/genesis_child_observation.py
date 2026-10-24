"""Private, default-off child admission observations; never lifecycle authority.

Trusted bootstrap code supplies private pipes and independent native inspectors.
No environment/argv bootstrap, process creation, Redis writes or termination here.
The child must not dispatch application work before completing the handshake.
"""
import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime

from scripts.genesis_launch_provenance import authenticated, descriptor, encoded, signed
from scripts.genesis_background_ownership import SERVICES
from scripts.genesis_background_ownership import MODULES


def target(proof):
    return hashlib.sha256(encoded(proof)).hexdigest()


class ChildObservations:
    def __init__(self, launches, *, native, ancestry, now=time.time_ns):
        if not callable(native) or not callable(ancestry):
            raise ValueError('Independent child and ancestry inspectors required')
        self.launches = launches; self.native = native; self.ancestry = ancestry
        self.now = now; self.records = {}; self.lock = threading.RLock()

    def _check(self, service, record):
        launch = self.launches.checked(service)
        body = record['challenge']
        if 'lineage' in body:
            record['wrapper'].verify()
            if encoded(record['wrapper'].rows)!=encoded(body['lineage']):raise ValueError('Wrapper binding differs')
        if (encoded(launch['challenge']) != encoded(body['launch']) or
                descriptor(self.native(body['owner']['pid'])) != body['owner'] or
                datetime.fromisoformat(body['owner']['created'].replace('Z','+00:00')) <
                datetime.fromisoformat(body['launch']['owner']['created'].replace('Z','+00:00')) or
                ('lineage' not in body and self.ancestry(body['owner'], body['launch']['owner']) is not True)):
            raise ValueError('Child generation, native identity or ancestry differs')

    def prepare(self, service, owner, *, deadline_ns=None, wrapper=None, work=None):
        with self.lock:
            if service not in SERVICES or service in self.records:
                raise ValueError('Unknown or duplicate child; explicit retirement required')
            launch = self.launches.checked(service)
            owner = descriptor(owner)
            if owner['pid'] == launch['challenge']['owner']['pid']:
                raise ValueError('Supervisor cannot impersonate child')
            if any(r['challenge']['owner']['pid'] == owner['pid'] for r in self.records.values()):
                raise ValueError('Child already assigned to another service')
            if deadline_ns is not None and (type(deadline_ns) is not int or deadline_ns <= self.now()):
                raise ValueError('Child channel deadline expired')
            body = {'kind': 'genesis-private-child-v1', 'launch': launch['challenge'],
                    'service': service, 'generation': launch['challenge']['generation'],
                    'owner': owner, 'nonce': secrets.token_hex(32),
                    'expires_ns': min(self.now() + 30_000_000_000, deadline_ns) if deadline_ns is not None else self.now()+30_000_000_000}
            record = {'challenge': json.loads(encoded(body)), 'key': secrets.token_bytes(32), 'phase': 'PENDING'}
            if work is not None:
                if service!='maintain' or not isinstance(work,dict):raise ValueError('Unexpected job context')
                record['challenge']['work']=json.loads(encoded(work))
            if wrapper is not None:
                from scripts.genesis_wrapper_observation import WrapperObservation
                if not isinstance(wrapper,WrapperObservation):raise ValueError('Typed wrapper proof required')
                # _check below performs the fresh native lineage verification for
                # this preparation phase; do not repeat the same phase here.
                if wrapper.rows[-1]!=owner:raise ValueError('Wrapper leaf differs')
                record['wrapper']=wrapper;record['challenge']['lineage']=json.loads(encoded(wrapper.rows))
            self._check(service, record)
            self.records[service] = record
            return encoded({'challenge': record['challenge'], 'key': record['key'].hex()})

    def accept(self, service, proof):
        with self.lock:
            record = self.records.get(service)
            try:
                if record is None or record['phase'] != 'PENDING':
                    raise ValueError('Unknown, retired or replayed child proof')
                body = authenticated(record['key'], proof)
                if encoded(body) != encoded(record['challenge']) or self.now() >= body['expires_ns']:
                    raise ValueError('Child proof differs or expired')
                self._check(service, record)
                if self.now() >= body['expires_ns']:
                    raise ValueError('Native verification exceeded child deadline')
                record['phase'] = 'AWAITING_CHILD_COMPLETION'
                record['target'] = target(proof)
                return signed(record['key'], {'kind': 'genesis-child-processed-v1',
                    'target': target(proof), 'lifecycle_authorized': False, 'write_authorized': False})
            except Exception:
                if record is not None: record['phase'] = 'HOLD'
                raise ValueError('Child processing rejected; HOLD') from None

    def confirm(self, service, proof):
        """A proof processed by controller is not proof child installed its context."""
        with self.lock:
            record = self.records.get(service)
            try:
                if record is None or record['phase'] != 'AWAITING_CHILD_COMPLETION':
                    raise ValueError('Unexpected or duplicate child completion')
                expected = {'kind': 'genesis-child-installed-v1', 'target': record['target'],
                            'lifecycle_authorized': False, 'write_authorized': False}
                if encoded(authenticated(record['key'], proof)) != encoded(expected):
                    raise ValueError('Child completion differs')
                self._check(service, record)
                if self.now() >= record['challenge']['expires_ns']:
                    raise ValueError('Child completion expired')
                record['phase'] = 'ATTESTED'
                # This phase already ran _check and the post-check deadline.
                # Later checked() calls still require a new native phase.
                return {'service':service,'owner':dict(record['challenge']['owner']),
                        'generation':record['challenge']['launch']['generation'],
                        'lifecycle_authorized':False,'write_authorized':False}
            except Exception:
                if record is not None: record['phase'] = 'HOLD'
                raise ValueError('Child completion unverified; HOLD') from None

    def checked(self, service):
        with self.lock:
            record = self.records.get(service)
            try:
                if record is None or record['phase'] != 'ATTESTED':
                    raise ValueError('Child not attested')
                self._check(service, record)
                return {'service': service, 'owner': dict(record['challenge']['owner']),
                        'generation': record['challenge']['launch']['generation'],
                        'lifecycle_authorized': False, 'write_authorized': False}
            except Exception:
                if record is not None: record['phase'] = 'HOLD'
                raise ValueError('Child observation unavailable; HOLD') from None

    def client_launches(self):
        """Explicit private child-owned Redis view; never exposes supervisor keys."""
        controller = self
        class ChildLaunchView:
            def checked(self, service):
                with controller.lock:
                    controller.checked(service)
                    record = controller.records[service]
                    return {'challenge': json.loads(encoded(record['challenge'])), 'key': record['key']}
        return ChildLaunchView()

    def hold(self, service):
        with self.lock:
            if service in self.records: self.records[service]['phase']='HOLD'


class PrivateChildReceiver:
    """One-use receiver installed explicitly before application dispatch.

    Service and expected launch come from trusted private bootstrap, never an
    untrusted frame alone. Installing this object grants no Redis/write authority.
    """
    def __init__(self, *, service, launch, native, ancestry, now=time.time_ns):
        if service not in SERVICES or launch['service'] != service or not callable(native) or not callable(ancestry):
            raise ValueError('Explicit service/native child bootstrap required')
        self.service = service; self.launch = json.loads(encoded(launch))
        self.native = native; self.ancestry = ancestry; self.now = now
        self.phase = 'PREPARED'; self.key = None; self.proof = None; self.completion = None
        self.lock = threading.RLock()

    def _current(self, body):
        from scripts.genesis_wrapper_observation import fresh
        ids=[os.getpid(),body['launch']['owner']['pid'],*[row['pid'] for row in body.get('lineage',[])]]
        observed=fresh(self.native,ids)
        owner = observed[os.getpid()]
        parent = observed[body['launch']['owner']['pid']]
        if 'lineage' in body:
            from scripts.genesis_wrapper_observation import verify_lineage
            verify_lineage(body['lineage'],parent,owner,observed.__getitem__)
        if (owner['pid'] != os.getpid() or owner != body['owner'] or parent != body['launch']['owner'] or
                datetime.fromisoformat(owner['created'].replace('Z','+00:00')) <
                datetime.fromisoformat(parent['created'].replace('Z','+00:00')) or
                ('lineage' not in body and self.ancestry(owner, parent) is not True)):
            raise ValueError('Private child native relationship unavailable')

    def receive(self, frame):
        with self.lock:
            try:
                if self.phase != 'PREPARED' or not isinstance(frame, bytes) or not 0 < len(frame) <= 16384:
                    raise ValueError('Child channel reused or outside bound')
                envelope = json.loads(frame)
                if set(envelope) != {'challenge', 'key'} or encoded(envelope) != frame:
                    raise ValueError('Noncanonical private frame')
                key = bytes.fromhex(envelope['key']); body = envelope['challenge']
                fields={'kind','launch','service','generation','owner','nonce','expires_ns'}
                if (len(key) != 32 or set(body) not in (fields,fields|{'lineage'},fields|{'work'},fields|{'lineage','work'}) or
                        body['kind'] != 'genesis-private-child-v1' or encoded(body['launch']) != encoded(self.launch) or
                        body['service'] != self.service or type(body['generation']) is not int or
                        body['generation'] != self.launch['generation'] or
                        type(body['expires_ns']) is not int or not 0 < body['expires_ns'] - self.now() <= 30_000_000_000):
                    raise ValueError('Private generation or deadline differs')
                self._current(body)
                self.key = key; self.proof = signed(key, body); self.phase = 'AWAITING_PROCESSED'
                return self.proof
            except Exception:
                self.phase = 'HOLD'; self.key = None
                raise ValueError('Private child bootstrap rejected; HOLD') from None

    def complete(self, reply, install):
        with self.lock:
            try:
                if self.phase != 'AWAITING_PROCESSED' or not callable(install):
                    raise ValueError('Processed child receipt unavailable')
                expected = {'kind': 'genesis-child-processed-v1', 'target': target(self.proof),
                            'lifecycle_authorized': False, 'write_authorized': False}
                if encoded(authenticated(self.key, reply)) != encoded(expected):
                    raise ValueError('Child receipt target differs')
                body = self.proof['body']; self._current(body)
                if self.now() >= body['expires_ns'] or install() is not True:
                    raise ValueError('Child installation failed or timed out')
                self._current(body)
                if self.now() >= body['expires_ns']:
                    raise ValueError('Child installation exceeded deadline')
                self.phase = 'OBSERVED'
                self.completion = signed(self.key, {'kind': 'genesis-child-installed-v1',
                    'target': target(self.proof), 'lifecycle_authorized': False, 'write_authorized': False})
                return {'service': self.service, 'generation': body['launch']['generation'],
                        'scope': 'CHILD_PROCESSING_NOT_LIFECYCLE_AUTHORITY',
                        'write_authorized': False, 'lifecycle_authorized': False}
            except Exception:
                self.phase = 'HOLD'
                raise ValueError('Private child completion rejected; HOLD') from None
            finally:
                self.key = None


def dispatch_python_service(receiver, frame, exchange, confirm):
    """Explicit isolated Python entry gate; not called by normal desktop startup.

    Web and maintenance require separate language/job bootstrap and HOLD here.
    A trusted owner supplies exchange over a private channel, never status output.
    """
    import runpy
    import sys
    if (not isinstance(receiver, PrivateChildReceiver) or receiver.service not in MODULES or
            not callable(exchange) or not callable(confirm)):
        raise ValueError('Certified Python service entry required; HOLD')
    proof = receiver.receive(frame)
    receiver.complete(exchange(proof), lambda: True)
    if confirm(receiver.completion) is not True:
        receiver.phase = 'HOLD'
        raise ValueError('Child installation not confirmed; HOLD')
    # Neither private frames nor service keys are forwarded into application argv.
    sys.argv = [MODULES[receiver.service]]
    return runpy.run_module(MODULES[receiver.service], run_name='__main__', alter_sys=True)
