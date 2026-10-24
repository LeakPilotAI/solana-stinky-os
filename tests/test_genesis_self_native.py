import os
import time

import pytest

from scripts import genesis_self_native as self_native
from scripts import genesis_private_child_entry as entry


@pytest.mark.parametrize('field',['pid','parent_pid','creation_ticks','created','executable','command_sha256'])
def test_self_identity_rejects_any_changed_bracket(monkeypatch,field):
    first={'pid':1,'parent_pid':2,'creation_ticks':123,'created':'2026-10-15T00:00:00Z',
           'executable':'fixture','command_sha256':'a'*64}
    second=dict(first);second[field]=first[field]+1 if isinstance(first[field],int) else str(first[field])+'changed'
    samples=iter([first,second]);monkeypatch.setattr(self_native,'_sample',lambda:next(samples))
    with pytest.raises(ValueError,match='unstable'):self_native.current()


def test_native_failure_never_falls_back_to_stale_identity(monkeypatch):
    def unavailable():raise OSError('Native evidence unavailable')
    monkeypatch.setattr(self_native,'_sample',unavailable)
    with pytest.raises(OSError):self_native.current()


def test_foreign_pid_still_requires_independent_remote_native_reader(monkeypatch):
    other=os.getpid()+1;calls=[]
    monkeypatch.setattr(entry,'native_many',lambda ids:calls.append(ids) or {other:'remote-evidence'})
    monkeypatch.setattr(self_native,'current',lambda:pytest.fail('Self evidence cannot attribute another process'))
    assert entry.native(other)=='remote-evidence' and calls==[(other,)]


@pytest.mark.skipif(os.name!='nt',reason='Independent Windows CIM comparison required')
def test_fresh_self_kernel_identity_matches_independent_cim(tmp_path):
    import json
    samples=[]
    for _ in range(3):
        before=entry.native_many((os.getpid(),))[os.getpid()]
        start=time.monotonic();observed=self_native.current();elapsed=time.monotonic()-start
        after=entry.native_many((os.getpid(),))[os.getpid()]
        assert before==observed==after
        samples.append(elapsed)
    (tmp_path/'native-equality.json').write_text(json.dumps({'independent_comparisons':3,'seconds':samples,
        'scope':'CURRENT_PROCESS_ONLY_NOT_LIFECYCLE_AUTHORITY'}))
