"""A fresh phase is mandatory; duplicate reads within one phase are not receipts."""
import os

import pytest

from test_genesis_child_observation import setup
from scripts.genesis_wrapper_observation import WrapperObservation


def test_confirm_verifies_once_and_later_access_verifies_again(monkeypatch):
    rows,launches,controller,receiver,frame=setup()
    receiver.complete(controller.accept('api',receiver.receive(frame)),lambda:True)
    calls=[];original=controller._check
    def checked(service,record):calls.append(service);return original(service,record)
    monkeypatch.setattr(controller,'_check',checked)
    result=controller.confirm('api',receiver.completion)
    assert calls==['api'] and not result['lifecycle_authorized'] and not result['write_authorized']
    assert controller.checked('api')==result and calls==['api','api']
    rows[os.getpid()]['created']='2026-10-15T00:01:00Z'
    with pytest.raises(ValueError,match='HOLD'):controller.checked('api')
    assert controller.records['api']['phase']=='HOLD'


@pytest.mark.parametrize('changed',['parent','child','command','executable','late-check'])
def test_confirmation_still_rejects_changed_or_expired_native_phase(monkeypatch,changed):
    rows,launches,c,r,frame=setup()
    r.complete(c.accept('api',r.receive(frame)),lambda:True)
    if changed=='parent':rows[123]['created']='2026-10-15T00:01:00Z'
    elif changed=='child':rows[os.getpid()]['parent_pid']=999
    elif changed=='command':rows[os.getpid()]['command_sha256']='b'*64
    elif changed=='executable':rows[os.getpid()]['executable']='foreign'
    else:
        original=c._check
        def expire(service,record):
            original(service,record)
            c.now=lambda:record['challenge']['expires_ns']
        monkeypatch.setattr(c,'_check',expire)
    with pytest.raises(ValueError,match='HOLD'):c.confirm('api',r.completion)
    assert c.records['api']['phase']=='HOLD'
    with pytest.raises(ValueError):c.confirm('api',r.completion)


@pytest.mark.parametrize('changed',[None,'native-creation','native-image','foreign-descendant','changed-argv'])
def test_bind_retains_independent_native_and_closed_tree_checks(changed):
    command=[r'C:\venv\python.exe','-m','fixture']
    parent={'pid':1,'parent_pid':0,'created':'2026-10-15T00:00:00Z','executable':'parent','command_sha256':'a'*64}
    child={**parent,'pid':2,'parent_pid':1,'executable':command[0],'argv':command}
    census_rows={1:dict(parent),2:dict(child)};native_rows={p:dict(v) for p,v in census_rows.items()};phases=[]
    def native(pid):return dict(native_rows[pid])
    def batch(ids):phases.append(tuple(ids));return {pid:native(pid) for pid in ids}
    native.batch=batch
    def census():return {'before':[dict(v) for v in census_rows.values()],'after':[dict(v) for v in census_rows.values()]}
    if changed=='native-creation':native_rows[2]['created']='2026-10-15T00:01:00Z'
    if changed=='native-image':native_rows[2]['executable']=r'C:\foreign\python.exe'
    if changed=='foreign-descendant':census_rows[3]={**child,'pid':3,'parent_pid':2}
    if changed=='changed-argv':census_rows[2]['argv']=[command[0],'-m','foreign']
    policy=WrapperObservation(native=native,census=census,executables=(command[0],))
    if changed:
        with pytest.raises(ValueError):policy.bind(2,2,command,parent)
    else:
        policy.bind(2,2,command,parent)
        assert phases==[(1,2)]  # Native bracket plus both census phases, not cached ownership.
        native_rows[2]['created']='2026-10-15T00:01:00Z'
        with pytest.raises(ValueError):policy.audit()
