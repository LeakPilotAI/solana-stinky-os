import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.genesis_gaming_policy import Budget, GamingPolicy, PRESERVED
from scripts.genesis_launch_provenance import LaunchObservations, answer_launch


def fixture():
    owner = {'pid': 77, 'parent_pid': 7, 'created': '2026-10-15T01:00:00+00:00',
             'executable': 'C:/Genesis/python.exe', 'command_sha256': 'a' * 64}
    current = dict(owner)
    obs = LaunchObservations(lambda pid: dict(current), now=lambda: 1)
    frame = obs.prepare('maintain', owner)
    obs.accept('maintain', answer_launch(frame, owner, now=lambda: 1))
    clock = [0.0]
    p = GamingPolicy(isolated_opt_in=True, observations=obs, clock=lambda: clock[0])
    return p, obs, current, owner, clock


def test_default_off_and_no_environment_activation(monkeypatch):
    monkeypatch.setenv('GENESIS_GAMING_MODE', '1')
    p = GamingPolicy()
    assert p.status()['mode'] == 'NORMAL'
    with pytest.raises(ValueError): p.select('GAMING')
    with p.admission('offline-path-report') as allowed: assert allowed
    assert not p.status()['production_enabled']


def test_normal_preserves_concurrency_and_gaming_is_reversible():
    p, _, _, _, clock = fixture()
    with p.admission('offline-path-report') as a:
        with p.admission('offline-latency-report') as b: assert a and b
    p.select('GAMING')
    with p.admission('offline-path-report') as a:
        with p.admission('offline-latency-report') as b: assert a and not b
    with p.admission('offline-path-report') as allowed: assert not allowed
    clock[0] = 60
    with p.admission('offline-path-report') as allowed: assert allowed
    p.select('NORMAL')
    with p.admission('offline-path-report') as a:
        with p.admission('offline-latency-report') as b: assert a and b
    assert p.status()['active_reports'] == 0


@pytest.mark.parametrize('workload', sorted(PRESERVED))
def test_critical_and_unapproved_maintenance_never_throttled(workload):
    p, _, current, _, _ = fixture(); p.select('GAMING')
    # Stale optional report ownership cannot stop collection/alerts/persistence.
    current['created'] = '2026-10-15T02:00:00+00:00'
    with p.admission(workload) as allowed: assert allowed


@pytest.mark.parametrize('field,value', [('cpu_percent',float('nan')), ('cpu_percent',True),
    ('cpu_percent',100), ('memory_mib',0), ('gpu_jobs',1), ('report_concurrency',2),
    ('network_kib_per_second',1), ('report_interval_seconds',0),
    ('disk_mib_per_second',float('inf')), ('latency_regression_percent',10)])
def test_invalid_configuration_rejected(field,value):
    with pytest.raises(ValueError): Budget(**{field:value})


@pytest.mark.parametrize('change', ['pid','created','executable','command_sha256','generation','retired'])
def test_stale_or_replaced_ownership_cannot_control(change):
    p, obs, current, owner, _ = fixture(); p.select('GAMING')
    if change == 'generation':
        obs.retire('maintain'); frame=obs.prepare('maintain',owner)
        obs.accept('maintain',answer_launch(frame,owner,now=lambda:1))
    elif change == 'retired': obs.retire('maintain')
    elif change == 'pid': current['pid'] += 1
    elif change == 'command_sha256': current[change] = 'b' * 64
    else: current[change] += '-replaced'
    with pytest.raises(ValueError):
        with p.admission('offline-path-report'): pytest.fail('Stale admitted')
    assert p.status()['hold']
    p.select('NORMAL')
    assert p.status()['hold']  # Normal cannot resurrect gaming authority.
    with pytest.raises(ValueError): p.select('GAMING')


def test_concurrent_reports_bounded_and_no_queue_growth():
    p, _, _, _, _ = fixture(); p.select('GAMING')
    barrier=threading.Barrier(8)
    def worker(_):
        barrier.wait(timeout=5)
        with p.admission('offline-path-report') as allowed: return allowed
    with ThreadPoolExecutor(max_workers=8) as pool: result=list(pool.map(worker,range(8)))
    assert sum(result)==1 and p.status()['active_reports']==0


def test_inflight_not_cancelled_and_exception_releases_slot():
    p, _, _, _, clock = fixture(); p.select('GAMING')
    with pytest.raises(RuntimeError):
        with p.admission('offline-path-report') as allowed:
            assert allowed
            p.select('NORMAL')
            assert p.status()['active_reports']==1
            raise RuntimeError('fixture failed')
    assert p.status()['active_reports']==0
    p.select('GAMING');clock[0]=60
    with p.admission('offline-path-report') as allowed: assert allowed


@pytest.mark.parametrize('workload', ['atlas','Atlas/collector','unknown','cuda-training','',None])
def test_foreign_or_unclassified_workload_rejected(workload):
    p, _, _, _, _ = fixture();p.select('GAMING')
    with pytest.raises(ValueError):
        with p.admission(workload): pytest.fail('Foreign admitted')


def test_clock_regression_and_restart_defaults():
    p, obs, _, _, clock=fixture();p.select('GAMING')
    with p.admission('offline-path-report') as allowed:assert allowed
    clock[0]=-1
    with pytest.raises(ValueError):
        with p.admission('offline-path-report'):pass
    assert p.status()['hold']
    restarted=GamingPolicy(isolated_opt_in=True,observations=obs)
    assert restarted.status()['mode']=='NORMAL' and not restarted.status()['production_enabled']
    assert GamingPolicy().status()['mode']=='NORMAL'


def test_copied_public_status_not_authority_and_no_secret_output():
    p, obs, _, _, _=fixture()
    with pytest.raises(ValueError): GamingPolicy(isolated_opt_in=True,observations=obs.status('maintain'))
    assert set(p.status())=={'mode','enabled','hold','active_reports','scope','budgets_measured',
                            'lifecycle_authorized','os_resource_controls','production_enabled'}
    assert 'key' not in json.dumps(p.status())
    with pytest.raises(ValueError):p.select('AUTO')
