"""Explicit inactive supervisor pipe adapter. No default installer or process kill."""
import json
import threading
import time
import ntpath

from scripts.genesis_background_ownership import MODULES
from scripts.genesis_launch_provenance import encoded, signed, authenticated
from scripts.genesis_child_observation import ChildObservations, target


class PrivatePythonChildChannel:
    accepted_services=frozenset(MODULES)
    def __init__(self, *, service, controller, native, timeout=30, wrapper=None):
        if (service not in self.accepted_services or not isinstance(controller,ChildObservations) or
                not callable(native) or type(timeout) not in (int,float) or not 0 < timeout <= 30):
            raise ValueError('Explicit isolated Python child channel required')
        self.service=service; self.controller=controller; self.native=native
        self.timeout=timeout; self.phase='PREPARED'; self.command=None
        self.failure_stage=None
        self.work=None;self.process=None
        self.expected_executable=None
        self.claim=None
        if wrapper is not None:
            from scripts.genesis_wrapper_observation import WrapperObservation
            if not isinstance(wrapper,WrapperObservation):raise ValueError('Typed wrapper verifier required')
        self.wrapper=wrapper

    def command_for(self, command):
        if self.phase != 'PREPARED' or len(command)!=3 or tuple(command[1:])!=('-m',MODULES[self.service]):
            self.phase='HOLD'
            raise ValueError('Uncertified child command; HOLD')
        self.command=(command[0],'-m','scripts.genesis_private_child_entry',self.service)
        self.phase='SPAWNING'
        return list(self.command)

    def deliver(self, process, command, supervisor, *, before_continue=None):
        if self.phase!='SPAWNING' or tuple(command)!=self.command:
            self.phase='HOLD'; raise ValueError('Private child channel reused; HOLD')
        done=threading.Event(); errors=[];state_lock=threading.Lock()
        canceled=threading.Event(); deadline_ns=time.time_ns()+int(self.timeout*1e9)
        self.phase='DELIVERING'
        self.process=process
        def exchange():
            stage='CHANNEL'
            try:
                if process.poll() is not None or process.stdin is None or process.stdout is None:
                    raise ValueError('Private child pipe unavailable')
                def read():
                    raw=process.stdout.readline(16385)
                    if len(raw)>16384 or not raw.endswith('\n'): raise ValueError('Private reply outside bound')
                    return json.loads(raw)
                def write(body):
                    if canceled.is_set() or time.time_ns()>=deadline_ns:
                        raise ValueError('Private channel deadline expired')
                    process.stdin.write(encoded(body).decode()+'\n'); process.stdin.flush()
                stage='READY'; ready=read()
                if (not isinstance(ready,dict) or set(ready)!={'kind','pid'} or
                        ready['kind']!='genesis-private-child-ready-v1' or type(ready['pid']) is not int or
                        (self.wrapper is None and ready['pid']!=process.pid)):
                    raise ValueError('Uncertified Python wrapper; HOLD')
                stage='NATIVE_CHILD'; owner=self.native(ready['pid'])
                if self.claim is not None:self.claim(owner)
                if self.expected_executable is not None and ntpath.normcase(ntpath.normpath(owner['executable']))!=ntpath.normcase(ntpath.normpath(self.expected_executable)):
                    raise ValueError('Executable differs from configured Node image')
                if self.wrapper is not None:self.wrapper.bind(process.pid,ready['pid'],command,supervisor)
                if self.wrapper is None and owner['parent_pid']!=supervisor['pid']:
                    raise ValueError('Child parent differs')
                stage='PREPARE'; frame=self.controller.prepare(self.service,owner,deadline_ns=deadline_ns,wrapper=self.wrapper,work=self.work)
                launch=self.controller.launches.checked(self.service)['challenge']
                write({'launch':launch,'frame':frame.hex()})
                stage='PROOF'; proof=read(); write(self.controller.accept(self.service,proof))
                stage='COMPLETION'; completion=read(); self.controller.confirm(self.service,completion)
                key=bytes.fromhex(json.loads(frame)['key'])
                stage='FINAL_RECEIPT'; write(signed(key,{'kind':'genesis-child-confirmed-v1','target':target(completion)}))
                stage='DISPATCH_READY'
                if encoded(authenticated(key,read())) != encoded({'kind':'genesis-child-dispatch-ready-v1',
                                                                   'target':target(completion)}):
                    raise ValueError('Child final processing not acknowledged')
                if canceled.is_set() or time.time_ns()>=deadline_ns:
                    raise ValueError('Private channel completion expired')
                if self.wrapper is not None:self.wrapper.audit()
                stage='SUPERVISOR_NATIVE'
                if before_continue is not None and before_continue() is not True:
                    raise ValueError('Supervisor native callback rejected entry')
                if canceled.is_set() or time.time_ns()>=deadline_ns:raise ValueError('Wrapper audit exceeded deadline')
                # Keep short-lived workers at their authenticated entry until the
                # closed-tree audit finishes. Never infer ownership from exit code.
                stage='ENTRY_CONTINUATION'
                write(signed(key,{'kind':'genesis-child-observation-complete-v1','target':target(completion),
                                 'lifecycle_authorized':False,'write_authorized':False}))
                with state_lock:
                    if canceled.is_set() or time.time_ns()>=deadline_ns:raise ValueError('Entry continuation timed out')
                    self.phase='OBSERVED'
            except Exception:
                self.failure_stage=stage
                errors.append(True)
            finally: done.set()
        threading.Thread(target=exchange,daemon=True,name='genesis-private-child-observation').start()
        if not done.wait(self.timeout) or errors:
            with state_lock:
                canceled.set();self.phase='HOLD'
            # Preserve failed child and channel for diagnosis; never claim drain
            # or terminate a process as a consequence of an observation failure.
            self.controller.hold(self.service)
            raise ValueError('Private child delivery incomplete; HOLD') from None
        return True
