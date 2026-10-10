"""Isolated-only migration coordinator. No production backend or CLI.

Unknown replies block routing. Abort after source shutdown may use only a proven
current recovery point, never the retained original container's stale loader.
"""
from __future__ import annotations
import hashlib
import threading
import re
import sys
from pathlib import Path
from contextlib import contextmanager
from scripts.genesis_identity_journal import IdentityJournal
from scripts.genesis_process_diagnostics import compare_snapshots
from scripts.redis_stream_integrity import framed_hash, verify_semantic_recovery
from scripts.redis_snapshot_integrity import verify_aof_ready
from scripts.redis_rollback_safety import verify_rollback_recovery

IMAGE = 'sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99'


def failure_code(exc):
    message=str(exc).casefold()
    for phrase,code in (('volume already','ACTIVE_VOLUME_WRITER'),('unresolved','UNRESOLVED_REPLY'),
                        ('identity','IDENTITY_GATE'),('acknowledged','ACK_CONTINUITY'),
                        ('writer ownership','WRITER_COMPLETENESS'),('aof','PERSISTENCE_GATE'),
                        ('injected','INJECTED_FAILURE')):
        if phrase in message:return code
    return 'UNCLASSIFIED_GATE_FAILURE'  # Never persist untrusted free text.


def verify_isolated_scope(records):
    if not records:raise RuntimeError('Isolated fixture scope unavailable')
    active_volumes=set();ids=set()
    for r in records:
        ident=r.get('Id')
        if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{64}',ident) or ident in ids:raise RuntimeError('Fixture native container identity unavailable')
        ids.add(ident)
        state=r.get('State',{})
        if type(state.get('Running')) is not bool or state.get('Paused') is not False or state.get('Status') not in ('running','created','exited'):raise RuntimeError('Fixture activity state unavailable')
        name=r.get('Name','')
        if name.startswith('/genesis-redis-c61-'):
            certification='checkpoint61';volume_prefix='project-genesis_checkpoint61-';ports=('16470','16471','16472','16473')
        elif name.startswith('/genesis-redis-c66-'):
            certification='checkpoint66';volume_prefix='project-genesis_checkpoint66-';ports=('16566','16567','16568','16569')
        else:raise RuntimeError('Production or unverified container forbidden')
        if r.get('Image')!=IMAGE:raise RuntimeError('Fixture image unverified')
        labels=r.get('Config',{}).get('Labels',{})
        if labels.get('genesis.certification')!=certification or labels.get('com.docker.compose.project')!='project-genesis' or labels.get('com.docker.compose.service')!='redis':
            raise RuntimeError('Fixture ownership unavailable')
        if r['Config'].get('Cmd')!=['redis-server','/data/redis.conf']:
            raise RuntimeError('Fixture loader unverified')
        mounts=r.get('Mounts',[])
        if len(mounts)!=1 or mounts[0].get('Type')!='volume' or not mounts[0].get('Name','').startswith(volume_prefix) or mounts[0].get('Destination')!='/data' or mounts[0].get('RW') is not True:
            raise RuntimeError('Fixture storage ownership unavailable')
        volume=mounts[0]['Name']
        if state['Running']:
            if volume in active_volumes:raise RuntimeError('Competing active volume writers')
            active_volumes.add(volume)
        binding=r.get('HostConfig',{}).get('PortBindings',{}).get('6379/tcp')
        if not isinstance(binding,list) or len(binding)!=1 or binding[0].get('HostIp')!='127.0.0.1' or binding[0].get('HostPort') not in ports:
            raise RuntimeError('Production or nonisolated endpoint forbidden')


class Acknowledgements:
    """Durable intents/replies for managed fixture XADD writers; not fake telemetry."""
    def __init__(self,journal,writers):
        if not writers or any(not isinstance(w,str) or not w for w in writers):raise RuntimeError('Writer registration incomplete')
        self.journal=journal;self.writers=frozenset(writers);self.commands={};self.lock=threading.RLock()

    def begin(self,writer,key,fields):
        with self.lock:
            if writer not in self.writers:raise RuntimeError('Unknown writer')
            if len(self.commands)>=50000:raise RuntimeError('Acknowledgement ledger bound exceeded')
            if not fields or len(fields)%2 or any(not isinstance(x,bytes) for x in [key,*fields]):raise RuntimeError('Malformed command evidence')
            token=len(self.commands)+1
            row={'token':token,'writer':writer,'key_sha256':hashlib.sha256(key).hexdigest(),
                 'payload_sha256':framed_hash(fields),'field_count':len(fields)//2,'state':'ISSUED'}
            self.journal.persist({'stage':'COMMAND_INTENT',**row})
            self.commands[token]=row;return token

    def acknowledged(self,token,entry_id,endpoint):
        with self.lock:
            row=self.commands[token]
            if row['state']!='ISSUED' or not isinstance(entry_id,str) or not re.fullmatch(r'[0-9]+-[0-9]+',entry_id) or not isinstance(endpoint,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',endpoint):raise RuntimeError('Acknowledgement identity invalid')
            changed={**row,'state':'ACKNOWLEDGED','entry_id':entry_id,'endpoint_id':endpoint}
            self.journal.persist({'stage':'COMMAND_REPLY',**changed});self.commands[token]=changed

    def begin_metadata(self,writer,command,args):
        with self.lock:
            if writer not in self.writers or command not in ('XGROUP','XREADGROUP','XCLAIM','XACK'):
                raise RuntimeError('Unknown metadata writer/operation')
            if len(self.commands)>=50000 or not args or any(not isinstance(x,bytes) for x in args):raise RuntimeError('Metadata evidence incomplete')
            token=len(self.commands)+1
            row={'token':token,'writer':writer,'operation':command,'args_sha256':framed_hash(args),'state':'ISSUED'}
            self.journal.persist({'stage':'COMMAND_INTENT',**row});self.commands[token]=row;return token

    def acknowledged_metadata(self,token,reply_bytes,endpoint):
        with self.lock:
            row=self.commands[token]
            if row.get('operation') not in ('XGROUP','XREADGROUP','XCLAIM','XACK') or row['state']!='ISSUED' or not isinstance(reply_bytes,bytes) or not isinstance(endpoint,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',endpoint):raise RuntimeError('Metadata acknowledgement incomplete')
            changed={**row,'state':'ACKNOWLEDGED','reply_sha256':hashlib.sha256(reply_bytes).hexdigest(),'endpoint_id':endpoint}
            self.journal.persist({'stage':'COMMAND_REPLY',**changed});self.commands[token]=changed

    def settled(self):
        with self.lock:
            if any(r['state']!='ACKNOWLEDGED' for r in self.commands.values()):raise RuntimeError('Unresolved Redis reply; routing prohibited')
            return len(self.commands)

    def verify(self,proof):
        with self.lock:
            self.settled()
            # Complete structural validation, not just a lookup into malformed data.
            verify_semantic_recovery(proof,proof,mode='rdb')
            entries={(k['key_sha256'],e['id']):e for k in proof['keys'] if k['type']=='stream' for e in k['stable']['entries']}
            for row in self.commands.values():
                if 'operation' in row:continue  # Final group/PEL state is in the complete strict proof.
                entry=entries.get((row['key_sha256'],row['entry_id']))
                if entry is None or entry['payload_sha256']!=row['payload_sha256'] or entry['field_count']!=row['field_count']:
                    raise RuntimeError('Acknowledged stream write missing or altered')
            return {'acknowledged':len(self.commands),'unresolved':0}


class Coordinator:
    """Backend must independently implement fixture ownership, fence and storage IO.

    Every move uses a new fence/snapshot. No rollback to a remembered old boundary
    after new replies. Failed repair leaves HOLD, retaining all current storage.
    """
    def __init__(self,backend,journal,ledger):
        self.backend=backend;self.journal=journal;self.ledger=ledger;self.current=backend.original
        try:verify_isolated_scope(backend.scope())
        except Exception as exc:
            journal.persist({'stage':'SCOPE_REJECTED','failure_type':type(exc).__name__})
            raise
        self.last_identity=None;self.boundary=None;self.boundary_ack_count=None;self.state='ORIGINAL'

    def record(self,stage,**values):self.journal.persist({'stage':stage,'state':self.state,'last_certified_route':self.current,**values})

    def identity_gate(self,phase):
        observed=self.backend.capture_identity(phase)
        if self.last_identity is not None:
            difference=compare_snapshots(self.last_identity,observed)
            if difference['status']!='MATCH':self.journal.gate(phase,self.last_identity,observed)
            self.record('ARCHIVED_IDENTITY_COMPARE',before=self.last_identity,after=observed,difference=difference)
        # A long snapshot/restore does not make an old observation fresh. Only
        # this immediate pair is eligible for live freshness certification.
        confirmation=self.backend.capture_identity(phase)
        self.journal.gate(phase,observed,confirmation)
        self.last_identity=confirmation

    def check_writers(self):
        evidence=self.backend.writer_inventory()
        observed=evidence.get('observed_connection_ids');verified=evidence.get('verified_connection_ids')
        if not isinstance(observed,list) or not isinstance(verified,list) or any(type(i) is not int or i<=0 for i in observed+verified) or len(set(observed))!=len(observed) or len(set(verified))!=len(verified) or set(observed)!=set(verified):
            raise RuntimeError('Redis connection identities not independently reconciled')
        owners={n['pid']:n['creation_ticks'] for n in self.last_identity['nodes']}
        if evidence.get('owner_pid') not in owners or owners[evidence['owner_pid']]!=evidence.get('owner_creation_ticks'):
            raise RuntimeError('Native writer owner identity changed or unavailable')
        if set(evidence.get('registered',[]))!=set(self.ledger.writers) or evidence.get('unknown')!=[] or type(evidence.get('inflight')) is not int or evidence['inflight']!=0 or evidence.get('fenced') is not True:
            raise RuntimeError('Writer ownership/completeness or inflight accounting unavailable')
        if 'writer_owners' in evidence:
            identities=evidence['writer_owners']
            if not isinstance(identities,dict) or set(identities)!=set(self.ledger.writers):raise RuntimeError('Writer identity coverage incomplete')
            for ident in identities.values():
                if not isinstance(ident,dict) or type(ident.get('pid')) is not int or type(ident.get('creation_ticks')) is not int or ident['pid'] not in owners or owners[ident['pid']]!=ident['creation_ticks']:
                    raise RuntimeError('Registered writer native identity unavailable or reused')
                node=next(n for n in self.last_identity['nodes'] if n['pid']==ident['pid'])
                repo=hashlib.sha256(str(Path(__file__).resolve().parents[1]).encode()).hexdigest()
                if ident.get('command_sha256')!=node['command_sha256'] or ident.get('repository_sha256')!=repo:
                    raise RuntimeError('Registered writer command/repository evidence differs')
        self.record('WRITER_FENCE',evidence=evidence)
        return evidence

    def verify_endpoint(self,name,expected):
        info,fsync=self.backend.persistence(name)
        verify_aof_ready(info)
        if fsync!='always':raise RuntimeError('Endpoint fsync policy unavailable')
        recovered,window=self.backend.recovery_proof(name)
        self.record('ENDPOINT_OBSERVATION',endpoint=name,expected=expected,observed=recovered,recovery_window_ms=window)
        writer_evidence=self.check_writers()
        result=verify_rollback_recovery(expected,self.current_fenced_proof,recovered,
                writers_fenced=writer_evidence.get('fenced'),unresolved_commands=writer_evidence['inflight'],
                fsync_confirmed=self.backend.fsync_confirmed(name),persistence=info,appendfsync=fsync,
                mode='aof',recovery_window_ms=window)
        self.record('RECOVERY_PROOF',endpoint=name,proof=result,accounting=self.ledger.verify(recovered))

    def _abort(self,source,target,source_stopped):
        self.state='ABORTING';self.record('ABORT_BEGIN')
        try:
            self.check_writers();self.ledger.settled()
            if not source_stopped and self.backend.running(source):
                current=self.backend.census(source);self.ledger.verify(current)
                recovery_point=self.backend.snapshot(source)
                if recovery_point.get('checksum_verified') is not True:raise RuntimeError('Abort recovery point checksum unavailable')
                verify_semantic_recovery(current,recovery_point['proof'],mode='rdb')
                self.ledger.verify(recovery_point['proof'])
                self.record('ABORT_ORIGINAL_RECOVERY_POINT',boundary=recovery_point)
                chosen=source
            elif self.boundary is not None and self.ledger.settled()==self.boundary_ack_count:
                # Writers never resumed after the fresh boundary. New replies
                # forbid this path; post-cutover rollback must take a new snapshot.
                # A lost/unregistered reply can evade the managed ledger. Never
                # discard a candidate's newer state just because ledger counts
                # match. Unavailable or different candidate state requires HOLD.
                candidate,window=self.backend.recovery_proof(target)
                self.record('ABORT_CANDIDATE_OBSERVATION',expected=self.boundary['proof'],observed=candidate,recovery_window_ms=window)
                verify_semantic_recovery(self.boundary['proof'],candidate,mode='aof',recovery_window_ms=window)
                self.ledger.verify(candidate)
                self.record('ABORT_CANDIDATE_CONTINUITY',accounting=self.ledger.verify(candidate))
                chosen=self.backend.restore_abort(self.boundary)
                self.verify_endpoint(chosen,self.boundary['proof'])
            else:raise RuntimeError('Fresh abort boundary cannot cover current acknowledgements')
            self.backend.exclusive_route(chosen)
            self.backend.reconnect(chosen)
            self.ledger.verify(self.backend.census(chosen))
            self.current=chosen;self.state='ABORTED_VERIFIED';self.record('ABORT_VERIFIED')
        except Exception as exc:
            self.state='HOLD';self.backend.hold()
            self.record('ABORT_BLOCKED',failure_type=type(exc).__name__,failure_code=failure_code(exc))
            raise RuntimeError('Abort uncertified; retain current storage and hold managed writers') from None

    @contextmanager
    def registered_writer_fence(self):
        actor=self.backend.fence()
        try:actor.__enter__()
        except BaseException:
            self.state='HOLD';self.backend.hold();self.record('WRITER_FENCE_ENTER_FAILED')
            raise RuntimeError('Writer quiescence uncertified; current storage retained') from None
        try:
            yield
        except BaseException:
            error=sys.exc_info()
            try:suppressed=actor.__exit__(*error)
            except BaseException:
                self.state='HOLD';self.backend.hold();self.record('WRITER_FENCE_EXIT_FAILED')
                raise RuntimeError('Writer fence release failed; managed writers held') from None
            if suppressed:
                self.state='HOLD';self.backend.hold();self.record('WRITER_FENCE_SUPPRESSION_REJECTED')
                raise RuntimeError('Writer fence cannot suppress a failed integrity gate') from None
            raise
        else:
            try:actor.__exit__(None,None,None)
            except BaseException:
                self.state='HOLD';self.backend.hold();self.record('WRITER_FENCE_EXIT_FAILED')
                raise RuntimeError('Writer fence release failed; managed writers held') from None

    def move(self,target):
        if target not in ('replacement','rollback') or target==self.current:
            self.record('TARGET_REJECTED');raise RuntimeError('Retained original or unknown target forbidden')
        try:verify_isolated_scope(self.backend.scope())
        except Exception as exc:
            self.record('SCOPE_REJECTED',failure_type=type(exc).__name__);raise
        source=self.current;source_stopped=False
        self.boundary=None;self.boundary_ack_count=None;self.last_identity=None
        try:self.identity_gate('BEFORE')
        except Exception as exc:
            self.backend.hold();self.record('BEFORE_IDENTITY_FAILED',failure_type=type(exc).__name__);raise
        with self.registered_writer_fence():
            try:
                self.gate='WRITER_FENCE'
                self.identity_gate('DURING');self.check_writers();self.ledger.settled()
                self.gate='FRESH_SNAPSHOT'
                self.boundary=self.backend.snapshot(source)
                if self.boundary.get('checksum_verified') is not True:raise RuntimeError('Snapshot checksum unverified')
                self.boundary_ack_count=self.ledger.settled()
                self.current_fenced_proof=self.backend.census(source)
                self.record('SOURCE_OBSERVATION',expected=self.boundary['proof'],observed=self.current_fenced_proof)
                verify_semantic_recovery(self.boundary['proof'],self.current_fenced_proof,mode='rdb')
                self.ledger.verify(self.boundary['proof']);self.state='BOUNDARY';self.record('FRESH_BOUNDARY',boundary=self.boundary,accounting=self.ledger.verify(self.boundary['proof']))
                self.gate='PREPARE_TARGET';self.backend.prepare(target,self.boundary)
                self.gate='TARGET_RECOVERY'
                self.verify_endpoint(target,self.boundary['proof']);self.state='TARGET_VERIFIED'
                # Refresh identity within each bounded stage; preserve old evidence.
                self.identity_gate('DURING');self.check_writers()
                verify_semantic_recovery(self.boundary['proof'],self.backend.census(source),mode='rdb')
                self.ledger.verify(self.backend.census(source))
                # Set before the operation: a partial stop must not assume old
                # volatile memory is still available and restart a stale loader.
                self.gate='SOURCE_DEACTIVATE';source_stopped=True;self.backend.deactivate(source)
                self.gate='EXCLUSIVE_ROUTE';self.backend.exclusive_route(target)
                self.gate='CLIENT_RECONNECT';self.backend.reconnect(target)
                self.gate='ROUTED_RECOVERY'
                self.verify_endpoint(target,self.boundary['proof'])
                self.current=target;self.state='ROUTED';self.record('ROUTE_VERIFIED')
            except Exception as exc:
                self.record('GATE_FAILED',gate=self.gate,failure_type=type(exc).__name__,failure_code=failure_code(exc))
                self._abort(source,target,source_stopped)
                raise RuntimeError('Migration aborted after failed gate; see immutable evidence') from None
            finally:
                # Identity failure here must not claim a completed migration.
                try:self.identity_gate('AFTER')
                except Exception as exc:
                    self.state='HOLD';self.backend.hold();self.record('AFTER_IDENTITY_FAILED',failure_type=type(exc).__name__)
                    raise RuntimeError('After identity gate failed; managed writers held') from None
        return self.state

    def rollback(self,target):
        if self.state not in ('ROUTED','ABORTED_VERIFIED'):raise RuntimeError('No verified current route to roll back')
        return self.move(target)  # CURRENT point, including all post-cutover replies.
