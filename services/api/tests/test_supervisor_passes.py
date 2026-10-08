from datetime import datetime,timedelta,timezone
from pathlib import Path
import asyncio
import pytest
from stinky_api import supervisor_passes as s
from genesis_pass_provenance import Recorder,observe_pass,read_observations

T=datetime(2026,10,8,tzinfo=timezone.utc)

def source(tmp_path, code=0, clocks=None):
    recorder=Recorder(tmp_path/'passes.jsonl')
    times=iter(clocks or [T,T+timedelta(seconds=2)])
    ticks=iter([1,3])
    observe_pass(lambda:code,recorder,clock=lambda:next(times),monotonic=lambda:next(ticks))
    data=read_observations(recorder.path)
    state={'service':'maintain','supervisor_pid':data['events'][0]['supervisor_pid'],'supervisor_started_at':T.isoformat()}
    return data,state

def test_genuine_pass_success_and_clock_ownership(tmp_path):
    data,state=source(tmp_path)
    out=s.summarize_passes(data,state,T+timedelta(seconds=3))
    assert out['last_successful_pass']['exit_code']==0 and out['passes'][0]['duration_sec']==2
    assert out['passes'][0]['started_at']==T.isoformat()
    assert out['passes'][0]['sleep_interval_sec'] is None
    assert out['clock_owner']=='HOST_UTC_SUPERVISOR' and out['experiment_evidence'] is False
    assert out['process_identity_verified'] is False and out['downtime']=='UNESTABLISHED'
    assert out['freshness']['status']=='RECENT'

@pytest.mark.parametrize('status', ['UNAVAILABLE','invalid','conflict'])
def test_bad_sources_expose_no_passes(tmp_path,status):
    data,state=source(tmp_path)
    if status=='UNAVAILABLE':data={'status':status}
    elif status=='invalid':data['invalid_lines']=1
    else:data['conflicting_event_ids']=1
    out=s.summarize_passes(data,state,T)
    assert out['status']=='UNAVAILABLE' and 'passes' not in out

def test_empty_and_missing_timestamps_are_not_zero(tmp_path):
    data,state=source(tmp_path,clocks=[None,None])
    out=s.summarize_passes(data,state,T)
    assert out['last_successful_pass'] is None and out['freshness']['age_sec'] is None
    data['events']=[]
    out=s.summarize_passes(data,None,T)
    assert out['status']=='OBSERVED' and out['passes']==[] and out['freshness']['status']=='UNAVAILABLE'

def test_stale_failed_and_partial_pairs(tmp_path):
    data,state=source(tmp_path,code=1)
    out=s.summarize_passes(data,state,T+timedelta(seconds=400))
    assert out['freshness']['status']=='STALE' and out['recent_failures']==1 and out['last_successful_pass'] is None
    data['events']=data['events'][:1]
    out=s.summarize_passes(data,state,T)
    assert out['partial_passes']==1 and out['passes'][0]['finished_at'] is None and out['passes'][0]['exit_code'] is None

def test_duplicates_remain_honest_and_clock_conflicts_rejected(tmp_path):
    data,state=source(tmp_path)
    data['duplicate_events']=2
    out=s.summarize_passes(data,state,T)
    assert out['scope']['duplicate_events']==2
    data['events'][-1]['wall_clock_order']='REGRESSION'
    with pytest.raises(ValueError):s.summarize_passes(data,state,T)

def test_missing_state_cannot_claim_current_success(tmp_path):
    data,state=source(tmp_path)
    assert s.summarize_passes(data,None,T)['last_successful_pass'] is None
    assert s.summarize_passes(data,None,T)['passes'][0]['matches_current_state'] is None

class Result:
    def mappings(self):return self
    def one(self):return {'latest':None,'as_of':T}
class Session:
    def __init__(self,fail=False):self.fail=fail;self.queries=[];self.rollback_called=False
    async def execute(self,query,params=None):
        self.queries.append(str(query))
        if self.fail:raise OSError('SECRET_DB_URI')
        return Result()
    async def rollback(self):self.rollback_called=True

def test_endpoint_bounded_readonly_collection_and_independent_outage(tmp_path,monkeypatch):
    data,state=source(tmp_path)
    monkeypatch.setattr(s,'read_local',lambda:s.summarize_passes(data,state,T+timedelta(seconds=3)))
    session=Session()
    out=asyncio.run(s.operator_passes(session))
    assert out['collection_freshness']['latest_at'] is None
    assert any('LIMIT 50' in q and 'LIMIT 1' in q for q in session.queries)
    assert all(q.startswith(('SELECT','WITH','SET')) for q in session.queries)
    disconnected=Session(True)
    out=asyncio.run(s.operator_passes(disconnected))
    assert out['status']=='OBSERVED' and out['collection_freshness']['status']=='UNAVAILABLE' and disconnected.rollback_called
    assert 'SECRET' not in str(out)

def test_pass_response_caps_and_intervals(tmp_path):
    path=tmp_path/'passes.jsonl';recorder=Recorder(path)
    for i in range(25):
        times=iter([T+timedelta(seconds=i*12),T+timedelta(seconds=i*12+2)])
        ticks=iter([1,3]);observe_pass(lambda:0,recorder,clock=lambda:next(times),monotonic=lambda:next(ticks))
    data=read_observations(path)
    state={'service':'maintain','supervisor_pid':data['events'][0]['supervisor_pid'],'supervisor_started_at':T.isoformat()}
    out=s.summarize_passes(data,state,T+timedelta(seconds=300))
    assert len(out['passes'])==20 and out['scope']['truncated']
    assert all(p['sleep_interval_sec']==10 for p in out['passes'])
