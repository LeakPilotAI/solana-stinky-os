"""Inactive child identity/exit evidence. No termination or respawn operations."""
import hashlib
import json
import threading


class ChildRegistry:
    def __init__(self, gate, *, capture, inspect, persist):
        self.gate = gate
        self.capture = capture
        self.inspect = inspect
        self.persist = persist
        self.children = {}
        self.exit_heads = {}
        self.lock = threading.RLock()

    def register(self, proc, command):
        with self.lock:
            try:
                self.gate.verify()
                if self.gate.phase != 'RUNNING' or len(self.children) >= 64 or proc.pid in self.children:
                    raise RuntimeError('Child admission fenced, reused or outside bound')
                expected = hashlib.sha256(json.dumps(command, separators=(',', ':')).encode()).hexdigest()
                owner = self.capture(proc, command)
                if (not isinstance(owner, dict) or set(owner) != {'pid','parent_pid','creation_ticks','command_sha256','repository_sha256'} or
                    owner['pid'] != proc.pid or owner['parent_pid'] != self.gate.owner['pid'] or
                    type(owner['creation_ticks']) is not int or owner['creation_ticks'] <= 0 or
                    owner['command_sha256'] != expected or
                    owner['repository_sha256'] != self.gate.owner['repository_sha256']):
                    raise RuntimeError('Native child ownership mismatch')
                self.children[proc.pid] = {'process': proc, 'owner': dict(owner)}
            except BaseException:
                self.gate.phase = 'HOLD'
                raise

    def verify_exited(self, proc=None):
        with self.lock:
            try:
                self.gate.verify()
                rows = list(self.children.values()) if proc is None else [self.children[proc.pid]]
                if not rows:
                    raise RuntimeError('No native child inventory; process closure unavailable')
                for row in rows:
                    child = row['process']
                    # The trusted inspector must retain native creation/handle
                    # evidence and independently prove all descendants exited.
                    observed = self.inspect(child, row['owner'])
                    if (observed != {'owner':row['owner'], 'exited':True, 'descendants_exited':True,
                                     'exit_code':0} or child.poll() != 0):
                        raise RuntimeError('Child or descendants not verified cleanly exited; HOLD')
                    head = self.persist({'stage':'CHILD_EXIT_VERIFIED','owner':row['owner'],'exit_code':0})
                    if not isinstance(head,str) or len(head)!=64 or any(c not in '0123456789abcdef' for c in head):
                        raise RuntimeError('Durable native child exit evidence unavailable')
                    self.exit_heads[child.pid] = head
                return [row['owner'] for row in rows]
            except BaseException:
                self.gate.phase = 'HOLD'
                raise
