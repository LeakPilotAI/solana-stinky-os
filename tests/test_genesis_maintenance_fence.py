"""Process-local manager fence; no production or global write authority."""
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

import pytest

from test_genesis_concurrent_maintenance import controller
from scripts.genesis_maintenance_observation import MaintenanceObservation, LOOPS
from scripts.genesis_maintenance_supervision import MaintenanceDrain


def alternate(m, cmd):
    return MaintenanceObservation(launches=m.launches, native=m.native, ancestry=m.ancestry,
        manifest={n:[(cmd,m.manifest[n][cmd][0])] for n in LOOPS}, retirement=m.retirement)


def test_direct_manager_and_replacement_are_fenced(tmp_path):
    d,m,cmd,*_=controller(tmp_path)
    other=alternate(m,cmd)
    proof=d.request_drain()
    for manager in (m,other,alternate(m,cmd)):
        with pytest.raises(ValueError,match='fenced'):
            with manager.loop('v2-maintenance'):pytest.fail('bypass')
        with pytest.raises(ValueError):MaintenanceDrain(manager,isolated=True,idle=lambda:{})
    assert d.drain(proof)['phase']=='QUIESCED_OBSERVATION'
    with pytest.raises(ValueError):
        with alternate(m,cmd).loop('research-maintenance'):pass


def test_admitted_loop_cannot_admit_new_job_after_fence(tmp_path):
    d,m,cmd,*_=controller(tmp_path)
    with m.loop('slow-maintenance'):
        proof=d.request_drain()
        with pytest.raises(ValueError,match='fenced'):
            with m.job(cmd):pytest.fail('post-boundary admission')
    assert m.phase=='READY'
    assert d.drain(proof)['phase']=='QUIESCED_OBSERVATION'


def test_direct_alternate_job_is_drained_with_native_completion(tmp_path):
    d,m,cmd,*_=controller(tmp_path);other=alternate(m,cmd)
    entered=threading.Event();release=threading.Event();draining=threading.Event()
    def job():
        with other.loop('slow-maintenance'):
            with other.job(cmd) as ch:
                ch.phase='OBSERVED';ch.process=SimpleNamespace(pid=9,poll=lambda:0)
                entered.set();assert release.wait(5)
    def drain(proof):
        draining.set();return d.drain(proof,timeout=5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        work=pool.submit(job);assert entered.wait(5)
        proof=d.request_drain();result=pool.submit(drain,proof);assert draining.wait(5)
        assert not result.done()
        release.set();work.result();assert result.result()['phase']=='QUIESCED_OBSERVATION'


@pytest.mark.parametrize('iteration',range(20))
def test_atomic_admission_drain_race(tmp_path,iteration):
    d,m,cmd,*_=controller(tmp_path);barrier=threading.Barrier(2);release=threading.Event()
    def attempt():
        barrier.wait(timeout=5)
        try:
            with m.loop('slow-maintenance'):assert release.wait(5)
            return 'admitted-before-fence'
        except ValueError:return 'fenced'
    with ThreadPoolExecutor(max_workers=1) as pool:
        f=pool.submit(attempt);barrier.wait(timeout=5);proof=d.request_drain()
        release.set();assert f.result() in ('admitted-before-fence','fenced')
    assert d.drain(proof)['phase']=='QUIESCED_OBSERVATION'
    with pytest.raises(ValueError):
        with m.loop('slow-maintenance'):pass


def test_failed_direct_job_prevents_quiescence_and_generation_reopen(tmp_path):
    d,m,cmd,launch,owner,_=controller(tmp_path)
    with pytest.raises(RuntimeError):
        with m.loop('slow-maintenance'):
            with m.job(cmd):raise RuntimeError('unresolved reply')
    with pytest.raises(ValueError):d.request_drain()
    assert m.boundary.phase=='HOLD'


def test_no_retirement_witness_cannot_join_protected_registry(tmp_path):
    d,m,cmd,*_=controller(tmp_path)
    with pytest.raises(ValueError,match='retirement'):
        MaintenanceObservation(launches=m.launches,native=m.native,ancestry=m.ancestry,
            manifest={n:[(cmd,m.manifest[n][cmd][0])] for n in LOOPS})


def test_unknown_job_on_alternate_manager_permanently_holds_boundary(tmp_path):
    d,m,cmd,*_=controller(tmp_path);other=alternate(m,cmd)
    with other.loop('slow-maintenance'):
        with pytest.raises(ValueError):
            with other.job((*cmd,'unknown')):pass
    assert m.boundary.phase=='HOLD'
    with pytest.raises(ValueError):d.request_drain()
    with pytest.raises(ValueError):
        with m.loop('v2-maintenance'):pass


def test_disabled_controller_cannot_reopen_closed_boundary(tmp_path):
    d,m,cmd,*_=controller(tmp_path)
    # The default-disabled controller must not claim a generation or open admission.
    disabled=MaintenanceDrain(m,idle=lambda:{})
    assert disabled.status()['production_enabled'] is False
    proof=d.request_drain();d.drain(proof)
    with pytest.raises(ValueError):
        with m.job(cmd):pass
    assert m.boundary.phase=='CLOSED'


def test_alternate_manager_cannot_duplicate_same_active_loop(tmp_path):
    d,m,cmd,*_=controller(tmp_path);other=alternate(m,cmd)
    with m.loop('slow-maintenance'):
        with pytest.raises(ValueError,match='already active'):
            with other.loop('slow-maintenance'):pass
    assert m.boundary.phase=='HOLD'
    with pytest.raises(ValueError):d.request_drain()


def test_duplicate_native_owner_across_managers_is_rejected(tmp_path):
    d,m,cmd,*_=controller(tmp_path);other=alternate(m,cmd)
    with pytest.raises(ValueError):
        with m.loop('slow-maintenance'), m.job(cmd) as first:
            first.claim({'pid':9,'created':'fixture'})
            with other.loop('v2-maintenance'), other.job(cmd) as second:
                with pytest.raises(ValueError,match='Duplicate'):
                    second.claim({'pid':9,'created':'fixture'})
                assert other.boundary.phase=='HOLD'
                raise ValueError('No completion may be inferred')
    assert m.owners and m.boundary.phase=='HOLD'
