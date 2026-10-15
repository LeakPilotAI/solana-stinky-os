"""Inactive maintenance-loop/job authentication; no schedule or research changes."""
from contextlib import contextmanager
import hashlib
import importlib.util
from pathlib import Path
import secrets
import threading

from scripts.genesis_child_observation import ChildObservations
from scripts.genesis_launch_provenance import encoded
from scripts.genesis_private_child_channel import PrivatePythonChildChannel

LOOPS=frozenset({'slow-maintenance','v2-maintenance','research-maintenance'})


def source_digest(path):
    with Path(path).open('rb') as source:
        data=source.read(4*1024*1024+1)
    if len(data)>4*1024*1024:raise ValueError('Job source outside bound')
    return hashlib.sha256(data).hexdigest()


def verify_job(work, arguments):
    fields={'loop','job_id','command','source','sha256'}
    if (not isinstance(work,dict) or set(work)!=fields or work['loop'] not in LOOPS or
            not isinstance(work['command'],list) or len(work['command'])<2):
        raise ValueError('Authenticated maintenance job context required')
    command=work['command'];mode='module' if command[1]=='-m' else 'script'
    target=command[2] if mode=='module' else command[1]
    args=command[3:] if mode=='module' else command[2:]
    if list(arguments)!=[mode,target,*args]:raise ValueError('Maintenance target changed')
    source=Path(work['source'])
    if not source.is_absolute() or source_digest(source)!=work['sha256']:
        raise ValueError('Maintenance source changed')
    if mode=='script' and Path(target).resolve()!=source.resolve():raise ValueError('Job source differs')
    if mode=='module':
        spec=importlib.util.find_spec(target)
        if spec is None or Path(spec.origin).resolve()!=source.resolve():raise ValueError('Module source differs')
    return mode,target,args


class PrivateMaintenanceChannel(PrivatePythonChildChannel):
    accepted_services=frozenset({'maintain'})
    def __init__(self, *, work, **kwargs):
        super().__init__(service='maintain',**kwargs);self.work=work

    def command_for(self, command):
        if self.phase!='PREPARED' or list(command)!=self.work['command']:
            self.phase='HOLD';raise ValueError('Job command changed; HOLD')
        module=command[1]=='-m';target=command[2] if module else command[1]
        args=command[3:] if module else command[2:]
        self.command=(command[0],'-m','scripts.genesis_private_child_entry','maintain','--job',
                      'module' if module else 'script',target,*args)
        self.phase='SPAWNING';return list(self.command)


class MaintenanceObservation:
    """Trusted exact command/source manifest, three isolated thread-local loops."""
    def __init__(self, *, launches, native, ancestry, manifest, wrapper_factory=None, retirement=None):
        if (not callable(native) or not callable(ancestry) or set(manifest)!=LOOPS or
                any(not entries for entries in manifest.values())):
            raise ValueError('Complete trusted maintenance manifest required')
        if retirement is not None and not callable(retirement):raise ValueError('Explicit retirement verifier required')
        self.retirement=retirement
        self.launches=launches;self.native=native;self.ancestry=ancestry
        self.manifest={};self.local=threading.local();self.lock=threading.RLock()
        self.active=set();self.count=0;self.wrapper_factory=wrapper_factory;self.phase='READY';self.owners={}
        for loop,entries in manifest.items():
            self.manifest[loop]={}
            for command,source in entries:
                command=tuple(command);source=Path(source).resolve()
                if (not 2<=len(command)<=32 or any(not isinstance(s,str) for s in command) or
                        not Path(command[0]).is_absolute() or command in self.manifest[loop]):raise ValueError('Ambiguous maintenance command')
                self.manifest[loop][command]=(str(source),source_digest(source))

    @contextmanager
    def loop(self,name):
        with self.lock:
            if self.phase!='READY' or name not in LOOPS or name in self.active or getattr(self.local,'loop',None):
                self.phase='HOLD';raise ValueError('Duplicate/unknown maintenance loop; HOLD')
            self.launches.checked('maintain');self.active.add(name);self.local.loop=name
        try:yield
        finally:
            with self.lock:self.active.remove(name);self.local.loop=None

    @contextmanager
    def job(self,command):
        loop=getattr(self.local,'loop',None)
        with self.lock:
            if self.phase!='READY' or loop not in self.manifest or tuple(command) not in self.manifest[loop] or getattr(self.local,'channel',None) is not None or self.count>=64:
                self.phase='HOLD'
                raise ValueError('Unknown, overlapping or exhausted maintenance admission; HOLD')
            admitted_launch=encoded(self.launches.checked('maintain')['challenge'])
            source,digest=self.manifest[loop][tuple(command)]
            if source_digest(source)!=digest:self.phase='HOLD';raise ValueError('Job source changed; HOLD')
            self.count+=1
            work={'loop':loop,'job_id':secrets.token_hex(16),'command':list(command),'source':source,'sha256':digest}
            controller=ChildObservations(self.launches,native=self.native,ancestry=self.ancestry)
            wrapper=self.wrapper_factory() if self.wrapper_factory is not None else None
            channel=PrivateMaintenanceChannel(work=work,controller=controller,native=self.native,wrapper=wrapper)
            def claim(owner):
                with self.lock:
                    if self.phase!='READY' or owner['pid'] in self.owners:
                        self.phase='HOLD';raise ValueError('Duplicate/replaced maintenance writer claim; HOLD')
                    self.owners[owner['pid']]=(owner['created'],work['job_id'])
            channel.claim=claim
            self.local.channel=channel
        try:
            yield channel
            if encoded(self.launches.checked('maintain')['challenge'])!=admitted_launch:
                raise ValueError('Maintenance generation replaced; HOLD')
            if channel.phase!='OBSERVED' or channel.process is None or channel.process.poll()!=0:
                raise ValueError('Maintenance job completion unresolved; HOLD')
            if self.retirement is not None:
                proof=self.retirement(channel.process,work)
                expected={'root_pid':channel.process.pid,'root_exit_code':0,'active_descendants':0,'identity_verified':True,
                          'job_id':work['job_id'],'source_sha256':work['sha256']}
                if encoded(proof)!=encoded(expected):raise ValueError('Native job retirement unverified; HOLD')
                if encoded(self.launches.checked('maintain')['challenge'])!=admitted_launch:
                    raise ValueError('Maintenance generation changed during retirement; HOLD')
            with self.lock:
                for pid,ticket in list(self.owners.items()):
                    if ticket[1]==work['job_id']:del self.owners[pid]
            # Root exit is not proof of descendant exit or drained Redis writes.
        except BaseException:
            with self.lock:self.phase='HOLD';channel.phase='HOLD';channel.controller.hold('maintain')
            raise
        finally:self.local.channel=None

    def channel(self):
        channel=getattr(self.local,'channel',None)
        if channel is None:raise ValueError('No admitted maintenance child; HOLD')
        return channel
