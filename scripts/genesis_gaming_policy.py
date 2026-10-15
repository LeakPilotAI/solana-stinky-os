"""Default-off isolated admission policy. No OS, service, GPU or lifecycle controls.

Not imported by production entrypoints. Targets are proposals, not measured limits.
Only trusted in-process fixtures can opt in; UI closure has no relationship to it.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import math
import secrets
import threading
import time

from scripts.genesis_launch_provenance import LaunchObservations

# These are isolated offline report roles, never prospective capture or live jobs.
REPORTS = frozenset({'offline-path-report', 'offline-latency-report'})
PRESERVED = frozenset({'event-log', 'api', 'sentinel', 'collector', 'entities',
                      'web', 'maintain', 'discord', 'persistence', 'ownership',
                      'v2-maintenance', 'research-maintenance', 'slow-maintenance'})


@dataclass(frozen=True)
class Budget:
    # Proposals for future measurement; admission alone cannot enforce OS budgets.
    cpu_percent: float = 5.0  # normalized whole-host share, not one-core utilization
    memory_mib: int = 256
    disk_mib_per_second: float = 1.0
    network_kib_per_second: int = 0
    gpu_jobs: int = 0
    latency_regression_percent: float = 5.0
    report_concurrency: int = 1
    report_interval_seconds: float = 60.0

    def __post_init__(self):
        for name, low, high in [('cpu_percent', .1, 10),
                                ('disk_mib_per_second', .01, 2),
                                ('latency_regression_percent', 0, 5),
                                ('report_interval_seconds', 1, 3600)]:
            v = getattr(self, name)
            if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
                raise ValueError('Invalid proposed budget')
        if (type(self.memory_mib) is not int or not 16 <= self.memory_mib <= 512 or
                type(self.report_concurrency) is not int or self.report_concurrency != 1 or
                type(self.gpu_jobs) is not int or self.gpu_jobs != 0 or
                type(self.network_kib_per_second) is not int or self.network_kib_per_second != 0):
            raise ValueError('Unsafe proposed budget')


class GamingPolicy:
    def __init__(self, *, isolated_opt_in=False, observations=None, budget=None, clock=time.monotonic):
        if type(isolated_opt_in) is not bool or not callable(clock):
            raise ValueError('Explicit fixture opt-in required')
        if isolated_opt_in and not isinstance(observations, LaunchObservations):
            raise ValueError('Authenticated observation controller required')
        if budget is not None and not isinstance(budget, Budget):
            raise ValueError('Typed budget required')
        self._enabled = isolated_opt_in
        self._observations = observations
        self._budget = budget or Budget()
        self._clock = clock
        self._lock = threading.RLock()
        self._mode = 'NORMAL'
        self._binding = None
        self._active = set()
        self._last = None
        self._time = None
        self._hold = False

    def _now(self):
        value = self._clock()
        if type(value) not in (int, float) or not math.isfinite(value) or (self._time is not None and value < self._time):
            self._hold = True
            raise ValueError('Clock unavailable or regressed; HOLD')
        self._time = value
        return value

    def _identity(self):
        try:
            r = self._observations.checked('maintain')['challenge']
            # Native identity checked on each admission; copied public status is insufficient.
            return (r['session'], r['generation'], tuple(sorted(r['owner'].items())))
        except Exception:
            self._hold = True
            raise ValueError('Ownership unavailable; HOLD') from None

    def select(self, mode):
        with self._lock:
            if mode not in ('NORMAL', 'GAMING') or not isinstance(mode, str):
                raise ValueError('Unknown mode')
            if mode == 'NORMAL':
                # Always release policy restrictions, never kill/cancel already-admitted work.
                self._mode = 'NORMAL'
                self._binding = None
                self._last = None
                return
            if not self._enabled or self._hold:
                raise ValueError('Gaming controls disabled or HOLD')
            identity = self._identity()
            if self._binding is not None and identity != self._binding:
                self._hold = True
                raise ValueError('Generation changed; HOLD')
            self._now()
            self._binding = identity
            self._mode = 'GAMING'

    @contextmanager
    def admission(self, workload):
        # This controls only fixture report admissions, never process scheduling.
        with self._lock:
            if not isinstance(workload, str) or workload not in REPORTS | PRESERVED:
                raise ValueError('Unclassified workload; HOLD')
            ticket = None
            admitted = True
            if workload in REPORTS:
                if len(self._active) >= 64:
                    raise ValueError('Bounded fixture admissions exhausted')
                if self._mode == 'GAMING':
                    if self._hold or self._identity() != self._binding:
                        self._hold = True
                        raise ValueError('Stale policy ownership; HOLD')
                    now = self._now()
                    admitted = (len(self._active) < self._budget.report_concurrency and
                                (self._last is None or now - self._last >= self._budget.report_interval_seconds))
                    if admitted:
                        self._last = now
                if admitted:
                    ticket = secrets.token_hex(16)
                    self._active.add(ticket)
        try:
            yield admitted
        finally:
            if ticket is not None:
                with self._lock:
                    self._active.remove(ticket)

    def status(self):
        with self._lock:
            return {'mode': self._mode, 'enabled': self._enabled, 'hold': self._hold,
                    'active_reports': len(self._active), 'scope': 'ISOLATED_ADMISSION_ONLY',
                    'budgets_measured': False, 'lifecycle_authorized': False,
                    'os_resource_controls': False, 'production_enabled': False}
