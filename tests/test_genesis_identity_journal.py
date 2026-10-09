import json
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
import pytest
from scripts import genesis_identity_journal as journal
from test_genesis_process_diagnostics import snapshot


@pytest.mark.parametrize('phase',['BEFORE','DURING','AFTER'])
def test_each_phase_has_immutable_exact_evidence(tmp_path,phase):
    data=snapshot(tmp_path);j=journal.IdentityJournal(tmp_path/'evidence')
    a=j.gate(phase,data,deepcopy(data));b=j.gate(phase,data,deepcopy(data))
    assert a!=b and a.exists() and b.exists()
    result=json.loads(a.read_text());assert result['before']==data and result['gate']=='PASSED'


@pytest.mark.parametrize('kind',['child','supervisor','reuse','unknown'])
def test_mismatch_is_persisted_before_rejection(tmp_path,kind):
    a=snapshot(tmp_path);b=deepcopy(a)
    if kind=='child':b['nodes'][1]['pid']=12
    if kind=='supervisor':b['nodes']=b['nodes'][1:]
    if kind=='reuse':b['nodes'][1]['creation_ticks']+=1
    if kind=='unknown':b['nodes'][1]['parent_pid']=90
    j=journal.IdentityJournal(tmp_path/'evidence')
    with pytest.raises(RuntimeError,match='persisted'):j.gate('DURING',a,b)
    record=json.loads(next(j.directory.glob('*.json')).read_text())
    assert record['before']==a and record['after']==b and record['gate']=='REJECTED'
    assert record['classification']=={'child':'VERIFIED_CHILD_CHURN','supervisor':'SUPERVISOR_CHANGE','reuse':'PID_REUSE','unknown':'OWNERSHIP_CHANGE'}[kind]


def test_invalid_capture_has_failure_record(tmp_path):
    j=journal.IdentityJournal(tmp_path/'evidence')
    with pytest.raises(RuntimeError):j.gate('BEFORE',{}, {})
    assert json.loads(next(j.directory.glob('*.json')).read_text())['classification']=='INVALID_SNAPSHOT'


def test_unknown_ownership_capture_is_persisted_without_secrets(tmp_path,monkeypatch):
    j=journal.IdentityJournal(tmp_path/'evidence')
    rows=[(10,0,'python.exe',f'python.exe "{tmp_path}/scripts/run_genesis_service.py" --name collector'),
          (11,10,'python.exe','python.exe -m atlas.api --token secret')]
    monkeypatch.setattr(journal.safe,'inventory',lambda _:rows)
    with pytest.raises(RuntimeError,match='failed closed'):j.capture('DURING',SimpleNamespace(ROOT=tmp_path),None)
    text=next(j.directory.glob('*.json')).read_text()
    assert 'secret' not in text and json.loads(text)['classification']=='UNKNOWN_OWNERSHIP'


def test_redacted_command_records_known_role_only(tmp_path):
    value=journal.command_evidence('python.exe',f'python.exe "{tmp_path}/scripts/run_genesis_service.py" --name collector --password secret')
    assert value['redacted_command_tokens'][-2:]==['--name','collector']
    assert 'secret' not in str(value)


def test_stale_snapshot_failure_is_persisted(tmp_path,monkeypatch):
    a=snapshot(tmp_path);b=deepcopy(a);j=journal.IdentityJournal(tmp_path/'evidence')
    monkeypatch.setattr(journal.diag.time,'monotonic_ns',lambda:a['captured_at_monotonic_ns']+journal.diag.MAX_SNAPSHOT_AGE_NS+1)
    with pytest.raises(RuntimeError):j.gate('DURING',a,b)
    assert json.loads(next(j.directory.glob('*.json')).read_text())['classification']=='STALE_OR_CLOCK_ORDER_FAILURE'


@pytest.mark.parametrize('phase',['BEFORE','DURING','AFTER'])
def test_full_capture_records_native_identity_command_and_ownership(tmp_path,monkeypatch,phase):
    rows=[(10,0,'python.exe',f'python.exe "{tmp_path}/scripts/run_genesis_service.py" --name collector --token secret'),
          (11,10,'python.exe','python.exe -m post_migration.cli')]
    monkeypatch.setattr(journal.safe,'inventory',lambda _:list(reversed(rows)))
    monkeypatch.setattr(journal.diag,'native_identity',lambda adapter,pid:(pid*100,'c:/python.exe'))
    j=journal.IdentityJournal(tmp_path/'evidence');data=j.capture(phase,SimpleNamespace(ROOT=tmp_path),None)
    record=json.loads(next(j.directory.glob('*.json')).read_text())
    assert [n['pid'] for n in data['nodes']]==[10,11]
    assert record['ownership_basis']=='EXACT_REPOSITORY_RUNNER_SERVICE_AND_VALIDATED_ANCESTRY'
    assert record['command_evidence'][1]['service']=='collector'
    assert record['command_evidence'][1]['redacted_command_tokens']==['python.exe','-m','post_migration.cli']
    assert record['command_evidence'][0]['command_sha256']==data['nodes'][0]['command_sha256']
    assert 'secret' not in json.dumps(record)


@pytest.mark.parametrize('failure',['none','churn','work'])
def test_sequenced_window_records_after_native_resumption_on_every_exit(tmp_path,failure):
    events=[];data=snapshot(tmp_path);j=journal.IdentityJournal(tmp_path/'evidence')
    def capture(phase):
        events.append(phase);value=deepcopy(data)
        if phase=='DURING' and failure=='churn':value['nodes'][1]['pid']=12
        return value
    @contextmanager
    def pause(before):
        events.append('PAUSED')
        try:yield
        finally:events.append('RESUMED')
    def run():
        with journal.recorded_identity_window(j,capture,pause):
            events.append('WORK')
            if failure=='work':raise ValueError('isolated boundary failed')
    if failure=='none':run()
    else:
        with pytest.raises((RuntimeError,ValueError)):run()
    assert events.index('RESUMED')<events.index('AFTER')
    assert events[:3]==['BEFORE','PAUSED','DURING']
    assert events[-2:]==['RESUMED','AFTER']
    records=[json.loads(p.read_text()) for p in j.directory.glob('*.json')]
    assert any(r['phase']=='AFTER' for r in records)
