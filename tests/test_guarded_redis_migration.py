import pytest
from scripts import guarded_redis_migration as guarded

class Adapter:
 def __init__(self):self.events=[]
 def open(self,p):self.events.append(('open',p));return p
 def creation(self,p):return p*10
 def suspend(self,p):self.events.append(('suspend',p))
 def resume(self,p):self.events.append(('resume',p))
 def close(self,p):self.events.append(('close',p))

def test_all_processes_resume_after_boundary_failure():
 a=Adapter()
 with pytest.raises(ValueError):
  with guarded.pause_verified_processes([(1,10),(2,20)],lambda p:None,a):raise ValueError('snapshot mismatch')
 assert a.events[-4:]==[('resume',2),('resume',1),('close',1),('close',2)]

def test_pid_reuse_is_not_suspended_and_prior_process_resumes():
 a=Adapter()
 with pytest.raises(RuntimeError,match='identity'):
  with guarded.pause_verified_processes([(1,10),(2,999)],lambda p:None,a):pytest.fail()
 assert ('suspend',2) not in a.events and ('resume',1) in a.events

def test_unverified_process_is_not_opened():
 a=Adapter()
 def verify(p):raise RuntimeError('foreign process')
 with pytest.raises(RuntimeError):
  with guarded.pause_verified_processes([(1,10)],verify,a):pytest.fail()
 assert a.events==[]

def test_suspend_failure_resumes_prior_handles():
 a=Adapter()
 def suspend(p):
  if p==2:raise RuntimeError('access denied')
  a.events.append(('suspend',p))
 a.suspend=suspend
 with pytest.raises(RuntimeError):
  with guarded.pause_verified_processes([(1,10),(2,20)],lambda _:None,a):pytest.fail()
 assert ('resume',1) in a.events and ('resume',2) not in a.events

def candidate():
 return {'Id':'new','Image':'image','Config':{'Cmd':['redis-server','/data/redis.conf'],
  'Labels':{'com.docker.compose.project':'project-genesis','com.docker.compose.service':'redis'}},
  'Mounts':[{'Type':'volume','Name':guarded.DURABLE_VOLUME,'Destination':'/data','RW':True}],
  'HostConfig':{'PortBindings':{'6379/tcp':[{'HostIp':'127.0.0.1','HostPort':'6380'}]}}}

def test_candidate_is_separate_from_retained_original_volume():
 guarded.verify_candidate(candidate(),container_id='new',volume=guarded.DURABLE_VOLUME,port=6380,image='image')

@pytest.mark.parametrize('bad',['id','image','project','command','volume','port'])
def test_candidate_ambiguity_fails_closed(bad):
 r=candidate()
 if bad=='id':r['Id']='other'
 if bad=='image':r['Image']='other'
 if bad=='project':r['Config']['Labels']['com.docker.compose.project']='atlas'
 if bad=='command':r['Config']['Cmd']+=['--appendonly','no']
 if bad=='volume':r['Mounts'][0]['Name']=guarded.SOURCE_VOLUME
 if bad=='port':r['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort']='6379'
 with pytest.raises(RuntimeError):guarded.verify_candidate(r,container_id='new',volume=guarded.DURABLE_VOLUME,port=6380,image='image')

def test_active_volume_writer_blocks_another_instance():
 with pytest.raises(RuntimeError):guarded.verify_no_volume_writer([{'State':{'Running':True},'Mounts':[{'Name':'volume'}]}],'volume')
 guarded.verify_no_volume_writer([{'State':{'Running':False},'Mounts':[{'Name':'volume'}]}],'volume')

def test_candidate_cannot_add_original_or_unrelated_mounts():
 r=candidate();r['Mounts'].append({'Type':'bind','Source':'unrelated','Destination':'/other'})
 with pytest.raises(RuntimeError,match='additional'):guarded.verify_candidate(r,container_id='new',volume=guarded.DURABLE_VOLUME,port=6380,image='image')

def test_candidate_cannot_select_an_unapproved_volume():
 with pytest.raises(RuntimeError,match='scope'):guarded.verify_candidate(candidate(),container_id='new',volume='atlas-volume',port=6380,image='image')

@pytest.mark.parametrize('record',[{'State':{},'Mounts':[]},{'State':{'Running':False}}])
def test_missing_activity_or_mount_inventory_fails_closed(record):
 with pytest.raises(RuntimeError,match='unavailable'):guarded.verify_no_volume_writer([record],'volume')
