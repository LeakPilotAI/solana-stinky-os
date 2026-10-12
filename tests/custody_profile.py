"""Test-only lock instrumentation preserving Condition/RLock behavior."""
import threading,time


class PrivateFixtureConfig(dict):
    def __repr__(self):return '<private isolated fixture configuration>'


class ProfiledRLock:
    def __init__(self,observe):
        self.native=threading.RLock();self.local=threading.local();self.observe=observe
    def acquire(self,*args,**kwargs):
        start=time.perf_counter();result=self.native.acquire(*args,**kwargs)
        if result:
            depth=getattr(self.local,'depth',0)
            if depth==0:
                self.observe('broker_lock_wait',time.perf_counter()-start);self.local.started=time.perf_counter()
            self.local.depth=depth+1
        return result
    def release(self):
        if self.local.depth==1:self.observe('broker_critical_section',time.perf_counter()-self.local.started)
        self.local.depth-=1;self.native.release()
    def __enter__(self):self.acquire();return self
    def __exit__(self,*args):self.release()
    def _is_owned(self):return self.native._is_owned()
    def _release_save(self):
        self.observe('broker_critical_section',time.perf_counter()-self.local.started)
        depth=self.local.depth;state=self.native._release_save();self.local.depth=0
        return state,depth
    def _acquire_restore(self,state):
        native,depth=state;start=time.perf_counter();self.native._acquire_restore(native)
        self.observe('broker_lock_wait',time.perf_counter()-start)
        self.local.depth=depth;self.local.started=time.perf_counter()
