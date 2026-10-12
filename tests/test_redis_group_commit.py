import os,threading,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts.redis_production_adapters import DurableJournal,read_records
from scripts.redis_writer_broker import PinnedRedisScope
from stinky_core.transport.redis_accounting import AccountingError,reply_bytes
from test_redis_writer_broker import broker,register,request


def enable(b):
    b.credentials.scope_validator=PinnedRedisScope(container_id='3'*64,image='sha256:'+'4'*64,
        name='genesis-redis-c74-unit',volume='project-genesis_checkpoint74-unit',port=16589,certification='checkpoint74')
    b.credentials.check_scope=lambda:None


def test_group_flush_is_ordered_and_never_publishes_head_early(tmp_path,monkeypatch):
    j=DurableJournal(tmp_path/'ledger');flush=os.fsync;calls=[]
    def observe(fd):
        assert j.sequence==0 and j.previous=='0'*64
        calls.append(fd);flush(fd)
    monkeypatch.setattr(os,'fsync',observe)
    try:
        with j.group_commit():
            j.persist({'stage':'first'});j.persist_many([{'stage':'second'},{'stage':'third'}])
            assert not calls and j.sequence==0 and j.path.stat().st_size==0
        assert len(calls)==1 and j.sequence==3
        assert read_records(j.path,expected_head=j.previous)==[{'stage':s} for s in ('first','second','third')]
    finally:j.close()


@pytest.mark.parametrize('failure',['partial_write','fsync','capacity','too_many','body'])
def test_failed_group_is_poisoned_and_prior_head_is_never_replaced(tmp_path,monkeypatch,failure):
    j=DurableJournal(tmp_path/'ledger',max_bytes=1000);j.persist({'stage':'previous'});head=j.previous
    try:
        if failure=='fsync':monkeypatch.setattr(os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('fixture flush')))
        if failure=='partial_write':
            original=j.stream
            class Partial:
                def write(self,data):return original.write(data[:len(data)//2])
            j.stream=Partial()
        with pytest.raises((OSError,AccountingError,ValueError)):
            with j.group_commit():
                j.persist({'stage':'candidate','data':'x'*2000 if failure=='capacity' else 'x'})
                if failure=='too_many':j.persist_many([{}]*8)
                if failure=='body':raise ValueError('fixture rejection')
        assert j.failed and j.previous==head
        with pytest.raises(AccountingError):j.persist({'stage':'no_retry'})
        if failure in ('partial_write','fsync'):
            if failure=='partial_write':original.flush()
            with pytest.raises(AccountingError):read_records(j.path,expected_head=head)
        else:assert read_records(j.path,expected_head=head)==[{'stage':'previous'}]
    finally:
        if failure=='partial_write':j.stream=original
        j.close()


def test_broker_returns_only_after_complete_durable_group_and_holds_partial_failure(broker,monkeypatch):
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer);enable(b)
    first=request(b,'begin_command',writer,'XACK',[b'key',b'g',b'1-0'],11,1)
    second=request(b,'begin_command',writer,'XACK',[b'key',b'g',b'2-0'],11,1)
    flush=os.fsync;events=[]
    def verify(fd):
        with pytest.raises(AccountingError):ledger.settled()
        assert ledger.commands[first]['state']==ledger.commands[second]['state']=='ISSUED'
        assert first in ledger.pending_commands and second in ledger.pending_commands
        events.append('fsync');flush(fd)
    monkeypatch.setattr(os,'fsync',verify)
    sequence=b.sequences[1]
    replies=b.dispatch_group([(1,{'sequence':sequence+n,'method':'complete_reply','args':[token,1,'original']})
                              for n,token in enumerate((first,second),1)])
    assert len(replies)==2 and events==['fsync'] and ledger.settled()==2 and not b.held
    monkeypatch.setattr(os,'fsync',flush)
    third=request(b,'begin_command',writer,'XACK',[b'key',b'g',b'3-0'],11,1)
    head=ledger.journal.previous
    monkeypatch.setattr(os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('fixture failure')))
    with pytest.raises(OSError):
        b.dispatch_group([(1,{'sequence':b.sequences[1]+1,'method':'complete_reply','args':[third,1,'original']})])
    assert b.held and b.fenced and ledger.journal.previous==head
    assert ledger.commands[third]['state']=='ISSUED' and third in ledger.pending_commands
    with pytest.raises(AccountingError):ledger.settled()


def test_default_and_production_scopes_cannot_enable_group_dispatch(broker):
    b,*_=broker
    with pytest.raises(AccountingError):b.dispatch_group([(1,{})])
    assert not b.group_active


def test_identity_change_during_flush_cannot_release_group_reply(broker,monkeypatch):
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer);enable(b)
    token=request(b,'begin_command',writer,'XACK',[b'key',b'g',b'1-0'],11,1)
    flush=os.fsync
    def changed(fd):flush(fd);owner['creation_ticks']+=1
    monkeypatch.setattr(os,'fsync',changed)
    with pytest.raises(AccountingError):
        b.dispatch_group([(1,{'sequence':b.sequences[1]+1,'method':'complete_reply','args':[token,1,'original']})])
    assert b.held and b.fenced


def test_partial_semantic_group_failure_keeps_every_prior_receipt_unsettled(broker):
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer);enable(b)
    first=request(b,'begin_command',writer,'XACK',[b'key',b'g',b'1-0'],11,1)
    second=request(b,'begin_command',writer,'XACK',[b'key',b'g',b'2-0'],11,1)
    head=ledger.journal.previous;sequence=b.sequences[1]
    with pytest.raises(AccountingError):
        b.dispatch_group([(1,{'sequence':sequence+1,'method':'complete_reply','args':[first,1,'original']}),
                          (1,{'sequence':sequence+2,'method':'complete_reply','args':[second,-1,'original']})])
    assert b.held and ledger.journal.failed and ledger.journal.previous==head
    assert ledger.commands[first]['state']==ledger.commands[second]['state']=='ISSUED'
    assert set(ledger.pending_commands)=={first,second}


def test_single_flight_admission_does_not_wait_or_release_provisional_group_lock(broker):
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer);enable(b)
    ledger.custody=SimpleNamespace(single_flight_backpressure=True,
        conflicts=lambda row,name:row['command']=='XADD' and name=='XADD',before=lambda *args:None)
    first=request(b,'begin_command',writer,'XADD',[b'key',b'*',b'f',b'one'],11,1)
    wait=[];b.admission_changed.wait=lambda *args:wait.append(True)
    seq=b.sequences[1]
    result=b.dispatch_group([(1,{'sequence':seq+1,'method':'begin_command',
        'args':[writer,'XADD',[b'key',b'*',b'f',b'two'],11,1]})])
    assert result==[{'pre_dispatch_busy':True}] and wait==[]
    assert len(ledger.commands)==1 and first in ledger.pending_commands and not b.held


def test_profiled_recursive_lock_preserves_condition_release_and_restore():
    from custody_profile import ProfiledRLock
    log=[];lock=ProfiledRLock(lambda label,elapsed:log.append((label,elapsed)))
    condition=threading.Condition(lock);entered=threading.Event()
    def notify():
        with condition:entered.set();condition.notify()
    with condition:
        with lock:
            thread=threading.Thread(target=notify);thread.start()
            condition.wait(1)
            assert entered.is_set() and lock._is_owned()
        assert lock._is_owned()
    thread.join(1);assert not thread.is_alive()
    assert {'broker_lock_wait','broker_critical_section'}<=set(label for label,_ in log)
    assert all(elapsed>=0 for _,elapsed in log)


@pytest.mark.parametrize('point',['before_commit','after_commit'])
def test_real_process_crash_preserves_only_the_trusted_durable_group_boundary(tmp_path,point):
    path=tmp_path/'journal';head=tmp_path/'trusted-head'
    code="""
import os,sys
from pathlib import Path
from scripts.redis_production_adapters import DurableJournal
j=DurableJournal(sys.argv[1]);j.persist({'stage':'prior'})
def anchor():
 with Path(sys.argv[2]).open('xb') as f:
  f.write(j.previous.encode());f.flush();os.fsync(f.fileno())
with j.group_commit():
 j.persist({'stage':'observed'});j.persist({'stage':'receipt'})
 if sys.argv[3]=='before_commit':anchor();os._exit(74)
anchor();os._exit(74)
"""
    result=subprocess.run([sys.executable,'-c',code,str(path),str(head),point],capture_output=True,timeout=10)
    assert result.returncode==74,result.stderr
    expected=[{'stage':'prior'}]
    if point=='after_commit':expected.extend([{'stage':'observed'},{'stage':'receipt'}])
    assert read_records(path,expected_head=head.read_text())==expected


def test_group_recovery_preserves_accepted_rejected_and_unresolved_commands(broker,tmp_path):
    from scripts.redis_broker_recovery import recover_held_boundary
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer);enable(b)
    first=request(b,'begin_command',writer,'XACK',[b'key',b'g',b'1-0'],11,1)
    reject=request(b,'begin_command',writer,'XGROUP CREATE',[b'key',b'g',b'0'],11,1)
    unknown=request(b,'begin_command',writer,'LPUSH',[b'q',b'unknown'],11,1)
    seq=b.sequences[1]
    b.dispatch_group([(1,{'sequence':seq+1,'method':'complete_reply','args':[first,1,'original']}),
                      (1,{'sequence':seq+2,'method':'reject_group_exists','args':[reject,'original']})])
    journal=DurableJournal(tmp_path/'held')
    try:
        recovered=recover_held_boundary(ledger.journal.path,expected_head=ledger.journal.previous,
            next_journal=journal,revoke=lambda principal:None,verify_revoked=lambda principal:True)
        assert recovered['held'] and recovered['ledger'].commands==ledger.commands
        assert recovered['ledger'].commands[reject]['outcome']=='REJECTED_NO_EFFECT'
        assert recovered['ledger'].commands[unknown]['state']=='ISSUED'
        with pytest.raises(RuntimeError):recovered['ledger'].settled()
    finally:journal.close()


def test_group_freezes_metadata_identity_at_each_persistence_call(tmp_path):
    journal=DurableJournal(tmp_path/'journal');record={'stage':'intent','owner':{'pid':1}}
    try:
        with journal.group_commit():
            journal.persist(record);record['owner']['pid']=2
        assert read_records(journal.path,expected_head=journal.previous)==[{'stage':'intent','owner':{'pid':1}}]
    finally:journal.close()


def test_stalled_dispatch_has_bounded_queue_and_no_early_success():
    import time
    from scripts.redis_writer_broker import IsolatedGroupDispatcher
    entered=threading.Event();release=threading.Event();processed=[]
    class Fixture:
        def verify_isolated_group_scope(self):pass
        def dispatch_group(self,rows):
            entered.set();assert release.wait(3)
            processed.extend(pid for pid,_ in rows);return [pid for pid,_ in rows]
        def hold(self):pass
    dispatcher=IsolatedGroupDispatcher(Fixture());results=[];threads=[]
    def submit(pid):results.append(dispatcher.submit(pid,{'method':'complete_reply'}))
    try:
        first=threading.Thread(target=submit,args=(1,));first.start();threads.append(first)
        assert entered.wait(1)
        for pid in range(2,10):
            thread=threading.Thread(target=submit,args=(pid,));thread.start();threads.append(thread)
        deadline=time.monotonic()+1
        while len(dispatcher.queue)<8 and time.monotonic()<deadline:time.sleep(.001)
        assert len(dispatcher.queue)==8 and results==[]
        with pytest.raises(AccountingError):dispatcher.submit(10,{'method':'complete_reply'})
        release.set()
        for thread in threads:thread.join(2);assert not thread.is_alive()
        assert sorted(results)==list(range(1,10)) and processed==list(range(1,10))
        assert dispatcher.stats['peak_queue']==8 and dispatcher.stats['max_group']<=4
    finally:release.set();dispatcher.close()


def test_fenced_admission_never_opens_group_or_creates_intent(broker):
    b,ledger,owner,writer,credentials=broker;register(b,owner,writer);enable(b)
    assert b.quiesce([11])==0
    head=ledger.journal.previous
    with pytest.raises(AccountingError,match='fenced'):
        b.dispatch_group([(1,{'sequence':b.sequences[1]+1,'method':'begin_command',
            'args':[writer,'LPUSH',[b'q',b'no'],11,1]})])
    assert b.held and b.fenced and not ledger.journal.failed
    assert ledger.journal.previous==head and not ledger.commands
    assert credentials.revocations==1


@pytest.mark.parametrize('failed',[False,True])
def test_revocation_is_verified_independently_of_journal_availability(tmp_path,failed):
    from scripts.redis_writer_broker import ProductionCredentials
    journal=DurableJournal(tmp_path/'revocation');journal.failed=failed
    authority=object.__new__(ProductionCredentials);authority.journal=journal
    authority.tickets={'native-one':{},'native-two':{}}
    calls=[]
    class Admin:
        def execute_command(self,*args):calls.append(args)
        def acl_getuser(self,user):
            assert ('ACL','SETUSER',user,'off','resetpass','-@all') in calls
            return {'flags':['off'],'passwords':[],'categories':['-@all'],'commands':[],'selectors':[]}
        def close(self):calls.append(('closed',))
    authority.checked_admin=lambda:Admin()
    try:
        status=authority.revoke_all()
        assert status=={'status':'HOLD' if failed else 'REVOKED','verified':True,'durable':not failed}
        assert authority.fenced and len(calls)==3
        if failed:
            assert journal.sequence==0 and journal.path.stat().st_size==0
            with pytest.raises(AccountingError):journal.persist({'stage':'forbidden'})
        else:assert read_records(journal.path,expected_head=journal.previous)==[{'stage':'BROKER_CREDENTIALS_REVOKED'}]
    finally:journal.close()


def test_revocation_flush_failure_reports_hold_and_keeps_credentials_disabled(tmp_path,monkeypatch):
    from scripts.redis_writer_broker import ProductionCredentials
    journal=DurableJournal(tmp_path/'revocation');authority=object.__new__(ProductionCredentials)
    authority.journal=journal;authority.tickets={'native':{}};disabled=[]
    class Admin:
        def execute_command(self,*args):disabled.append(args[2])
        def acl_getuser(self,user):return {'flags':['off'],'passwords':[],'categories':['-@all'],'commands':[],'selectors':[]}
        def close(self):pass
    authority.checked_admin=lambda:Admin()
    monkeypatch.setattr(os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('fixture flush failure')))
    try:
        with pytest.raises(OSError):authority.revoke_all()
        assert disabled==['native'] and journal.failed
        assert authority.revocation_status=={'status':'HOLD','verified':True,'durable':False}
        assert authority.revoke_all()==authority.revocation_status
    finally:journal.close()


def test_revocation_cannot_claim_success_when_redis_still_grants_authority(tmp_path):
    from scripts.redis_writer_broker import ProductionCredentials
    journal=DurableJournal(tmp_path/'revocation');journal.failed=True
    authority=object.__new__(ProductionCredentials);authority.journal=journal;authority.tickets={'native':{}}
    class Admin:
        def execute_command(self,*args):pass
        def acl_getuser(self,user):return {'flags':['on'],'passwords':['retained'],'categories':['-@all'],'commands':[],'selectors':[]}
        def close(self):pass
    authority.checked_admin=lambda:Admin()
    try:
        with pytest.raises(AccountingError,match='not verified'):authority.revoke_all()
        assert authority.fenced and journal.sequence==0
        assert authority.revocation_status=={'status':'HOLD','verified':False,'durable':False}
    finally:journal.close()
