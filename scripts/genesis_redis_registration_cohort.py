"""Bounded inactive physical-client rendezvous; no pending-client exemptions.

All members are explicitly declared before connections are opened. No member
gets a matched processed receipt until the complete server/native audit passes.
Caller must run blocking exchanges outside an async event loop (e.g. to_thread).
"""
import math
import threading
import time

from scripts.genesis_redis_pool_observation import processed_receipt


class RegistrationCohort:
    def __init__(self, registry, launches, members, *, timeout=10):
        if (not isinstance(members, tuple) or not 1 <= len(members) <= 8 or
                any(not isinstance(m, tuple) or len(m) != 2 or
                    any(not isinstance(s, str) for s in m) for m in members) or
                len(set(members)) != len(members) or type(timeout) not in (int,float) or
                not math.isfinite(timeout) or not 0 < timeout <= 30):
            raise ValueError('Explicit bounded registration cohort required')
        self.registry = registry; self.launches = launches; self.members = frozenset(members)
        self.timeout = timeout; self.condition = threading.Condition()
        self.phase = 'PREPARED'; self.challenges = {}; self.proofs = {}; self.replies = {}
        self.failure_stage = None

    def prepare(self):
        with self.condition:
            try:
                if self.phase != 'PREPARED': raise ValueError('Cohort reused')
                for service, slot in sorted(self.members):
                    self.challenges[(service, slot)] = self.registry.prepare(service, slot)
                self.deadline = time.monotonic() + self.timeout
                self.phase = 'COLLECTING'
                return dict(self.challenges)
            except Exception:
                self._hold()
                raise ValueError('Registration preparation failed; HOLD') from None

    def _hold(self):
        self.phase = 'HOLD'; self.replies.clear()
        self.registry.hold(self.members)
        self.condition.notify_all()

    def exchange(self, service, slot, proof):
        member = (service, slot)
        with self.condition:
            stage = 'ADMISSION'
            try:
                if (self.phase != 'COLLECTING' or member not in self.members or
                        member in self.proofs or time.monotonic() >= self.deadline):
                    raise ValueError('Undeclared, duplicate, expired or closed registration')
                stage = 'PHYSICAL_PROOF'
                self.registry.stage(service, slot, proof)
                self.proofs[member] = proof
                if set(self.proofs) == self.members:
                    stage = 'COMPLETE_INVENTORY'
                    result = self.registry.audit()
                    if result['status'] != 'ISOLATED_OBSERVATIONS_MATCH':
                        raise ValueError('Complete inventory not independently verified')
                    for (s, connection), pending in self.proofs.items():
                        key = self.launches.checked(s)['key']
                        self.replies[(s, connection)] = processed_receipt(key, pending, result)
                    if time.monotonic() >= self.deadline:
                        raise ValueError('Registration exceeded deadline')
                    self.phase = 'OBSERVED'; self.condition.notify_all()
                while self.phase == 'COLLECTING':
                    stage = 'WAITING_FOR_MEMBERS'
                    remaining = self.deadline - time.monotonic()
                    if remaining <= 0: raise ValueError('Missing cohort member')
                    self.condition.wait(remaining)
                if self.phase != 'OBSERVED': raise ValueError('Cohort held')
                # A participant can change while another waiter wakes. Never use
                # cached success as proof of a presently complete native inventory.
                stage = 'DELIVERY_INVENTORY'
                if (self.registry.audit()['status'] != 'ISOLATED_OBSERVATIONS_MATCH' or
                        time.monotonic() >= self.deadline):
                    raise ValueError('Cohort changed before receipt delivery')
                return self.replies[member]
            except Exception:
                if self.failure_stage is None: self.failure_stage = stage
                self._hold()
                raise ValueError('Coordinated registration rejected; HOLD') from None
