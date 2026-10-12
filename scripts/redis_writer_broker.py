"""Inactive local broker. No CLI, environment activation or production bootstrap.

The named-pipe transport uses bounded JSON, HMAC authentication and the OS peer
PID. A trusted controller must supply the independently verified native manifest.
Missing actors, uncertain IPC and unsupported retention leave the boundary HOLD.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import re
import struct
import threading
from multiprocessing.connection import Client, Listener

from stinky_core.transport.redis_accounting import AccountingError, DispatchBusy, identity,reply_bytes
from scripts.redis_production_adapters import SealedCredentials, validate_command,verify_default_write_fence


class PinnedRedisScope:
    def __init__(self, *, container_id, image, name, volume, port, certification=None):
        if not isinstance(container_id,str) or not re.fullmatch('[0-9a-f]{64}',container_id) or not isinstance(image,str) or not re.fullmatch('sha256:[0-9a-f]{64}',image):
            raise AccountingError('Native container/image pins unavailable')
        self.container_id=container_id;self.image=image;self.name=name
        self.volume=volume;self.port=port;self.certification=certification
        if name=='stinky-redis':
            if port!=6380 or volume not in ('project-genesis_redis-data','project-genesis_redis-durable58-data') or certification is not None:
                raise AccountingError('Production ownership scope unavailable')
        elif not ((name.startswith('genesis-redis-c67-') and volume.startswith('project-genesis_checkpoint67-') and port in (16570,16571,16572,16573) and certification=='checkpoint67') or
                  (name.startswith('genesis-redis-c68-') and volume.startswith('project-genesis_checkpoint68-') and port in (16574,16575,16576,16577) and certification=='checkpoint68') or
                  (name.startswith('genesis-redis-c69-') and volume.startswith('project-genesis_checkpoint69-') and port in (16578,16579,16580,16581) and certification=='checkpoint69') or
                  (name.startswith('genesis-redis-c71-') and volume.startswith('project-genesis_checkpoint71-') and port in (16582,16583,16584,16585) and certification=='checkpoint71') or
                  (name.startswith('genesis-redis-c72-') and volume.startswith('project-genesis_checkpoint72-') and port == 16586 and certification=='checkpoint72')):
            raise AccountingError('Unrecognized Redis authority scope')

    def __call__(self, records):
        if len(records)!=1:raise AccountingError('Single pinned authority endpoint required')
        r=records[0];labels=r.get('Config',{}).get('Labels') or {}
        mounts=r.get('Mounts',[])
        if r.get('Id')!=self.container_id or r.get('Image')!=self.image or r.get('Name')!='/'+self.name:
            raise AccountingError('Redis native ownership differs from reviewed pins')
        if labels.get('com.docker.compose.project')!='project-genesis' or labels.get('com.docker.compose.service')!='redis' or (self.certification is not None and labels.get('genesis.certification')!=self.certification):
            raise AccountingError('Redis project ownership unavailable')
        if len(mounts)!=1 or mounts[0].get('Type')!='volume' or mounts[0].get('Name')!=self.volume or mounts[0].get('Destination')!='/data' or mounts[0].get('RW') is not True:
            raise AccountingError('Redis writable storage ownership differs')
        if r.get('HostConfig',{}).get('PortBindings',{}).get('6379/tcp')!=[{'HostIp':'127.0.0.1','HostPort':str(self.port)}] or r.get('State',{}).get('Running') is not True or r.get('State',{}).get('Paused') is not False:
            raise AccountingError('Redis endpoint or runtime scope differs')


def pack(value):
    if isinstance(value, bytes):return {'bytes': base64.b64encode(value).decode('ascii')}
    if isinstance(value, dict):return {'map': [[pack(k), pack(v)] for k, v in value.items()]}
    if isinstance(value, tuple):return {'tuple': [pack(v) for v in value]}
    if isinstance(value, list):return {'list': [pack(v) for v in value]}
    if value is None or type(value) in (str, int, bool):return value
    raise AccountingError('IPC value type unavailable')


def unpack(value, depth=0):
    if depth > 20:raise AccountingError('IPC nesting bound exceeded')
    if isinstance(value, dict):
        if set(value) == {'bytes'}:return base64.b64decode(value['bytes'], validate=True)
        if set(value) == {'list'}:return [unpack(v, depth+1) for v in value['list']]
        if set(value) == {'tuple'}:return tuple(unpack(v, depth+1) for v in value['tuple'])
        if set(value) == {'map'}:return {unpack(k, depth+1): unpack(v, depth+1) for k, v in value['map']}
        raise AccountingError('IPC shape unavailable')
    if value is None or type(value) in (str, int, bool):return value
    raise AccountingError('IPC scalar unavailable')


def native_pipe_pid(connection, *, server=False):
    if os.name != 'nt':raise AccountingError('Verified Windows pipe required')
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32', use_last_error=True)
    query=kernel.GetNamedPipeServerProcessId if server else kernel.GetNamedPipeClientProcessId
    query.argtypes=[wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    query.restype=wintypes.BOOL
    pid=wintypes.ULONG()
    if not query(connection.fileno(), ctypes.byref(pid)) or not pid.value:
        raise AccountingError('Native pipe peer unavailable')
    return pid.value


def native_creation(pid):
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:raise AccountingError('Broker native identity unavailable')
    try:
        times=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):
            raise AccountingError('Broker creation identity unavailable')
        return (times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
    finally:kernel.CloseHandle(handle)


def receive(connection,maximum):
    if not connection.poll(5):raise AccountingError('Broker IPC deadline exceeded')
    return connection.recv_bytes(maximum)


def signature(key,kind,challenge,nonce):
    return hmac.new(key,kind+challenge+nonce,hashlib.sha256).digest()


class RetentionBoundary:
    """Preservation-first epoch: no implicit trimming, expiry or eviction waiver.

    Production's MAXLEN and allkeys-lru cannot meet this contract unchanged.
    This gate deliberately blocks activation until a separately certified archival
    epoch protocol exists; it does not alter existing live retention semantics.
    """
    def __init__(self, configuration, expiring_keys):
        if configuration.get('maxmemory-policy') != 'noeviction':
            raise AccountingError('Eviction can destroy unaccounted evidence')
        if type(expiring_keys) is not int or expiring_keys != 0:
            raise AccountingError('Expiry evidence cannot cross preservation epoch')
        self.held=False

    def before(self, name, args):
        validate_command(name, args)
        if self.held:raise AccountingError('Retention epoch held')
        if name == 'SET' or (name == 'XADD' and args[1].upper() in (b'MAXLEN', b'MINID')):
            raise AccountingError('Destructive retention requires independently certified archive')

    def verify(self, ledger, proof):
        try:return ledger.verify(proof)
        except BaseException:
            self.held=True
            raise


class ProductionCredentials(SealedCredentials):
    """Explicitly injected authority; never instantiated by application startup.

    scope_validator verifies pinned native Docker/container/volume/port ownership.
    Production requires this reviewed controller capability, not relabeled fixture
    records. Existing isolated coordinator scope checks remain unchanged.
    """
    def __init__(self, admin, scope, verify_owner, journal, *, scope_validator, port, keys, readers=None):
        super().__init__(admin, scope, verify_owner, journal)
        if not isinstance(scope_validator,PinnedRedisScope):raise AccountingError('Reviewed native Redis pins required')
        if type(port) is not int or not 1 <= port <= 65535 or not isinstance(keys,dict) or not keys or len(keys)>8:
            raise AccountingError('Credential authority scope missing')
        if any(role not in self.ROLE_COMMANDS or not isinstance(names,(list,tuple)) or not 1<=len(names)<=128 for role,names in keys.items()):
            raise AccountingError('Explicit bounded role key scopes required')
        if any(not isinstance(k, str) or not k or any(c in k for c in '*?[]\\\r\n ') for names in keys.values() for k in names):
            raise AccountingError('Exact key scopes required')
        self.scope_validator=scope_validator;self.port=port;self.keys=keys;self.readers=readers or {}
        self.check_scope()

    def check_scope(self):self.scope_validator(self.scope())

    def checked_admin(self):
        self.check_scope();c=self.admin();cfg=c.connection_pool.connection_kwargs
        if cfg.get('host') not in ('localhost', '127.0.0.1') or int(cfg.get('port', 0)) != self.port or cfg.get('db', 0) != 0:
            c.close();raise AccountingError('Credential authority endpoint differs')
        user=cfg.get('username')
        if not user or user=='default':
            c.close();raise AccountingError('Separate restricted broker principal required')
        policy=c.acl_getuser(user)
        allowed={'+acl|getuser','+acl|setuser','+acl|users','+client|list','+info','+ping'}
        if not policy or policy.get('categories')!=['-@all'] or policy.get('selectors')!=[] or set(policy.get('commands',[]))-allowed or 'on' not in policy.get('flags',[]) or 'nopass' in policy.get('flags',[]) or not policy.get('passwords') or not cfg.get('password'):
            c.close();raise AccountingError('Broker has unaudited Redis privileges')
        return c

    def issue(self, owner, role, generation, epoch):
        if self.scope_validator.certification is None and owner.get('service')=='fixture':
            raise AccountingError('Fixture identities cannot authorize production credentials')
        self.verify_principals()
        if self.fenced or role not in self.keys:raise AccountingError('Credential issuance fenced or unscoped')
        ticket=super().issue(owner, role, generation, epoch)
        c=self.checked_admin()
        try:c.execute_command('ACL', 'SETUSER', ticket['username'], 'resetkeys', *['~'+k for k in self.keys[role]])
        except BaseException:
            self.fenced=True
            c.execute_command('ACL', 'SETUSER', ticket['username'], 'off', 'resetpass', '-@all')
            raise
        finally:c.close()
        return ticket

    def verify_principals(self):
        c=self.checked_admin()
        read_commands={'+ping','+info','+client|list','+config|get','+waitaof','+eval_ro','+keys','+scan','+type','+dump','+pttl','+pexpiretime','+dbsize','+memory|usage','+time','+get','+llen','+lrange','+xlen','+xrange','+xrevrange','+xpending','+xinfo'}
        try:
            users=c.acl_users()
            if len(users)>4096:raise AccountingError('ACL principal inventory outside bound')
            verify_default_write_fence(c.acl_getuser('default'))
            admin=c.connection_pool.connection_kwargs['username']
            for user in users:
                if user in ('default',admin):continue
                policy=c.acl_getuser(user)
                if policy is None:raise AccountingError('Principal disappeared during inventory')
                if 'off' in policy.get('flags',[]):continue
                if policy.get('categories')!=['-@all'] or policy.get('selectors')!=[]:
                    raise AccountingError('Unregistered ACL category or selector authority')
                if user in self.tickets:
                    allowed=set(self.READ_RULES+self.ROLE_COMMANDS[self.tickets[user]['role']])
                elif user in self.readers:
                    allowed=set(self.readers[user])
                    if allowed-read_commands:raise AccountingError('Reader capability can mutate data')
                else:raise AccountingError('Unregistered enabled Redis principal')
                if set(policy.get('commands',[]))-allowed:raise AccountingError('Unexpected principal mutation permission')
            return True
        finally:c.close()

    def revoke_all(self):
        self.fenced=True;c=self.checked_admin()
        try:
            for user in self.tickets:c.execute_command('ACL', 'SETUSER', user, 'off', 'resetpass', '-@all')
            self.journal.persist({'stage':'BROKER_CREDENTIALS_REVOKED'})
        finally:c.close()

    def is_bound(self,owner,role,generation,epoch,cid):
        return any(r=={'owner':owner,'role':role,'generation':generation,'epoch':epoch,'cid':cid} for r in self.tickets.values())


class WriterBroker:
    def __init__(self, ledger, credentials, manifest, verify_native, retention, *, server_epoch, endpoint, generation=1, parent_head=None):
        if not manifest or len(manifest)>128:raise AccountingError('Writer manifest unavailable')
        self.manifest={pid:identity(owner) for pid,owner in manifest.items()}
        if any(pid != owner['pid'] for pid,owner in self.manifest.items()):raise AccountingError('Manifest PID differs')
        self.ledger=ledger;self.credentials=credentials;self.verify_native=verify_native
        self.retention=retention;self.fenced=False;self.held=False;self.lock=threading.RLock()
        self.admission_changed=threading.Condition(self.lock)
        self.sequences={};self.current_owner=None
        if not isinstance(server_epoch,str) or not re.fullmatch('[0-9a-f]{40}',server_epoch) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',endpoint):
            raise AccountingError('Reviewed broker route required')
        if type(generation) is not int or generation<1 or (parent_head is not None and not re.fullmatch('[0-9a-f]{64}',parent_head)):
            raise AccountingError('Broker generation/recovery parent unavailable')
        self.server_epoch=server_epoch;self.endpoint=endpoint;self.generation=generation
        route={'stage':'BROKER_ROUTE','server_epoch':server_epoch,
            'endpoint':endpoint,'generation':self.generation,
            'manifest':[self.manifest[pid] for pid in sorted(self.manifest)],'writers':sorted(ledger.writers)}
        if parent_head is not None:route['parent_head']=parent_head
        self.ledger.journal.persist(route)

    def owner(self, pid):
        owner=self.manifest.get(pid)
        if owner is None or identity(self.verify_native(pid)) != owner:
            raise AccountingError('Unregistered or stale native writer')
        return owner

    def hold(self):
        # Publish the deny state before waiting for an in-progress journal/ACL
        # decision. Queued legitimate requests cannot race ahead of a known
        # authentication/identity failure to obtain a fresh intent or credential.
        self.held=True;self.fenced=True
        with self.lock:
            self.admission_changed.notify_all()
            self.credentials.revoke_all()

    def dispatch(self, pid, request):
        with self.lock:
            try:
                if not isinstance(request,dict) or set(request)!={'sequence','method','args'}:
                    raise AccountingError('Broker request shape unavailable')
                owner=self.owner(pid);sequence=request['sequence']
                if type(sequence) is not int or sequence != self.sequences.get(pid,0)+1:
                    raise AccountingError('Replayed or out-of-order broker request')
                self.sequences[pid]=sequence;self.current_owner=owner
                method=request['method'];args=request['args']
                if not isinstance(args,list):raise AccountingError('Broker arguments unavailable')
                if self.held:raise AccountingError('Broker held')
                if method in ('issue','seal'):
                    if self.fenced:raise AccountingError('Broker registration fenced')
                    if not args or args[0] != owner:raise AccountingError('Credential owner spoofed')
                    role=args[1] if method=='issue' else args[2]
                    generation=args[2] if method=='issue' else args[3]
                    epoch=args[3] if method=='issue' else args[4]
                    if type(generation) is not int or generation!=self.generation or epoch!=self.server_epoch:
                        raise AccountingError('Stale broker credential route')
                    roles={'event-log':{'redis-streams'},'api':{'api-manual-queue'},'sentinel':{'redis-streams'},'collector':{'redis-streams','collector-consumer'},'entities':{'entity-consumer'},'discord':{'discord-alerts'}}
                    if owner['service']!='fixture' and role not in roles.get(owner['service'],set()):
                        raise AccountingError('Credential role contradicts native service')
                    if method=='seal':args=[args[1],args[0],*args[2:]]
                    result=getattr(self.credentials,method)(*args)
                    if self.held:raise AccountingError('Hold arrived during credential admission')
                    return result
                if method == 'register_connection':
                    if self.fenced or args[1] != owner:raise AccountingError('Connection registration fenced')
                    if args[3]!=self.server_epoch or type(args[4]) is not int or args[4]!=self.generation:
                        raise AccountingError('Stale broker connection route')
                if method == 'begin_command':
                    if self.fenced:raise AccountingError('Broker dispatch fenced')
                    if type(args[4]) is not int or args[4]!=self.generation:raise AccountingError('Stale broker mutation generation')
                    prefix=f"{pid}-{owner['creation_ticks']}-"
                    role=args[0][len(prefix):] if isinstance(args[0],str) and args[0].startswith(prefix) else None
                    if not self.credentials.is_bound(owner,role,args[4],self.server_epoch,args[3]):
                        raise AccountingError('Mutation lacks sealed native credential binding')
                    if getattr(self.ledger,'custody',None) is not self.retention:self.retention.before(args[1],args[2])
                allowed={'register_connection','retire_connection','begin_command','complete_command','complete_reply','reject_group_exists','mark_uncertain','settled'}
                if method not in allowed:raise AccountingError('Broker method not allowlisted')
                if method in ('register_connection','retire_connection','begin_command'):
                    if not str(args[0]).startswith(f"{pid}-{owner['creation_ticks']}-"):
                        raise AccountingError('Writer identity spoofed')
                if method in ('complete_command','complete_reply','reject_group_exists','mark_uncertain'):
                    writer=self.ledger.commands[args[0]]['writer']
                    if not writer.startswith(f"{pid}-{owner['creation_ticks']}-"):
                        raise AccountingError('Acknowledgement owner differs')
                    if args[-1]!=self.endpoint or self.ledger.commands[args[0]]['generation']!=self.generation:
                        raise AccountingError('Acknowledgement route differs')
                    if method=='complete_command' and args[2]!=reply_bytes(args[1]):
                        raise AccountingError('Acknowledgement serialization differs')
                if method=='complete_reply':
                    if len(args)!=3:raise AccountingError('Compact completion shape differs')
                    # Identical canonical receipt bytes, without transporting a
                    # second full representation of a500-entry group response.
                    result=self.ledger.complete_command(args[0],args[1],reply_bytes(args[1]),args[2])
                    self.admission_changed.notify_all()
                    return result
                if method=='mark_uncertain':
                    self.ledger.mark_uncertain(*args);self.hold();return {'held':True}
                if method=='begin_command':
                    # Only a proven pre-intent conflict may release the broker
                    # lock. Give the existing physical attempt's completion a
                    # chance to acquire it rather than repeatedly polling IPC.
                    for attempt in range(9):
                        try:
                            result=self.ledger.begin_command(*args);break
                        except DispatchBusy:
                            if attempt==8:raise
                            self.admission_changed.wait(.025)
                            owner=self.owner(pid);self.current_owner=owner
                            if (self.held or self.fenced or self.sequences.get(pid)!=sequence or
                                args[4]!=self.generation or
                                not self.credentials.is_bound(owner,role,args[4],self.server_epoch,args[3])):
                                raise AccountingError('Admission changed while awaiting settlement')
                else:result=getattr(self.ledger,method)(*args)
                if method in ('complete_command','reject_group_exists','retire_connection'):
                    self.admission_changed.notify_all()
                if self.held and method in ('register_connection','begin_command'):
                    raise AccountingError('Hold arrived during admission; no permission returned')
                return result
            except DispatchBusy:
                # Only the ledger's verified pre-intent admission refusal can
                # reach this branch. Authentication/ownership errors still HOLD.
                if method != 'begin_command':
                    self.hold();raise
                return {'pre_dispatch_busy': True}
            except BaseException:
                self.hold();raise

    def quiesce(self, observed_ids):
        with self.lock:
            self.fenced=True;self.credentials.set_fenced(True)
            self.admission_changed.notify_all()
            try:
                self.credentials.verify_principals()
                for pid in self.manifest:self.owner(pid)
                if set(self.sequences) != set(self.manifest):raise AccountingError('Writer participant missing')
                expected={r['client_id'] for r in self.ledger.bindings.values() if r['active']}
                if len(observed_ids)!=len(set(observed_ids)) or set(observed_ids)!=expected:
                    raise AccountingError('Unregistered or disconnected writer connection')
                return self.ledger.settled()
            except BaseException:
                self.hold();raise


def session_limit(value):
    if type(value) is not int or not 1 <= value <= 256:
        raise AccountingError('Broker session bound unavailable')
    return value


def session_frame(key, kind, session, payload):
    return signature(key, kind, session, payload) + payload


def read_session_frame(connection, key, kind, session):
    # A session may be idle while a bounded Redis group read is blocked. An
    # unexpected disconnect/timeout still HOLDs; no automatic replay/reconnect.
    if not connection.poll(30):raise AccountingError('Broker session deadline exceeded')
    frame=connection.recv_bytes(1024*1024+32)
    if len(frame)<32 or not hmac.compare_digest(frame[:32],signature(key,kind,session,frame[32:])):
        raise AccountingError('Broker session frame authentication failed')
    return frame[32:]


class PipeServer:
    """One serialized bounded RPC; use recv_bytes, never unpickle client objects."""
    def __init__(self,address,authkey,broker,*,max_workers=1,max_requests=1):
        if os.name!='nt' or not address.startswith('\\\\.\\pipe\\genesis-') or len(authkey)!=32:
            raise AccountingError('Authenticated Genesis named pipe required')
        if type(max_workers) is not int or not 1<=max_workers<=8:
            raise AccountingError('Broker connection worker bound unavailable')
        self.listener=Listener(address,family='AF_PIPE',authkey=None);self.broker=broker;self.authkey=authkey
        self.max_requests=session_limit(max_requests)
        self.max_workers=max_workers;self.slots=threading.BoundedSemaphore(max_workers)
        self.workers=set();self.worker_lock=threading.Lock()

    def serve_one(self):
        if self.max_workers==1:
            return self._serve_connection(self.listener.accept())
        # Accept/authenticate a bounded number of independent native peers. The
        # broker lock still serializes every identity/generation/ledger decision.
        self.slots.acquire()
        try:connection=self.listener.accept()
        except BaseException:
            self.slots.release();raise
        def work():
            try:self._serve_connection(connection)
            finally:
                with self.worker_lock:self.workers.discard(threading.current_thread())
                self.slots.release()
        worker=threading.Thread(target=work,daemon=True)
        with self.worker_lock:self.workers.add(worker)
        try:worker.start()
        except BaseException:
            with self.worker_lock:self.workers.discard(worker)
            connection.close();self.slots.release();self.broker.hold();raise

    def _serve_connection(self,connection):
        try:
            pid=native_pipe_pid(connection)
            self.broker.owner(pid)
            challenge=os.urandom(32);connection.send_bytes(challenge)
            answer=receive(connection,64)
            if len(answer)!=64 or not hmac.compare_digest(answer[32:],signature(self.authkey,b'client',challenge,answer[:32])):
                raise AccountingError('Broker client authentication failed')
            connection.send_bytes(signature(self.authkey,b'server',challenge,answer[:32]))
            limit=struct.unpack('>I',answer[28:32])[0] if self.max_requests>1 else 1
            if not 1<=limit<=self.max_requests:raise AccountingError('Broker session limit differs')
            session=challenge+answer[:32]
            for ordinal in range(limit):
                frame_session=session+struct.pack('>I',ordinal)
                if native_pipe_pid(connection)!=pid:raise AccountingError('Broker session peer changed')
                raw=(read_session_frame(connection,self.authkey,b'request',frame_session)
                     if limit>1 else receive(connection,1024*1024))
                if limit>1 and not raw:
                    self.broker.owner(pid)
                    connection.send_bytes(session_frame(self.authkey,b'response',frame_session,b''))
                    return  # Authenticated normal close, never a lost reply.
                request=unpack(json.loads(raw))
                response=self.broker.dispatch(pid,request)
                encoded=json.dumps(pack({'ok':True,'value':response}),separators=(',',':')).encode()
                if len(encoded)>1024*1024:raise AccountingError('Broker response outside bound')
                connection.send_bytes(session_frame(self.authkey,b'response',frame_session,encoded) if limit>1 else encoded)
        except BaseException:
            self.broker.hold()
            try:connection.send_bytes(json.dumps(pack({'ok':False})).encode())
            except (OSError,EOFError):pass
        finally:connection.close()

    def close(self):
        self.listener.close()
        with self.worker_lock:workers=tuple(self.workers)
        for worker in workers:worker.join(6)
        if any(worker.is_alive() for worker in workers):
            self.broker.hold()
            raise AccountingError('Broker connection drain not verified')


class PipeProxy:
    def __init__(self,address,authkey,writers,*,server_identity,max_requests=1):
        if not isinstance(server_identity,tuple) or len(server_identity)!=2 or any(type(v) is not int or v<=0 for v in server_identity) or len(authkey)!=32:
            raise AccountingError('Reviewed native broker identity required')
        self.address=address;self.authkey=authkey;self.writers=frozenset(writers)
        self.sequence=0;self.lock=threading.RLock();self.failed=False;self.server_identity=server_identity
        self.max_requests=session_limit(max_requests);self.connection=None;self.session=None;self.requests=0;self.closed=False

    def _connect(self):
        connection=Client(self.address,family='AF_PIPE',authkey=None)
        self.connection=connection
        self._verify_server()
        challenge=receive(connection,32)
        nonce=os.urandom(28)+struct.pack('>I',self.max_requests)
        if len(challenge)!=32:raise AccountingError('Broker challenge unavailable')
        connection.send_bytes(nonce+signature(self.authkey,b'client',challenge,nonce))
        if not hmac.compare_digest(receive(connection,32),signature(self.authkey,b'server',challenge,nonce)):
            raise AccountingError('Broker server authentication failed')
        self.session=challenge+nonce;self.requests=0

    def _verify_server(self):
        pid=native_pipe_pid(self.connection,server=True)
        if (pid,native_creation(pid))!=self.server_identity:
            raise AccountingError('Unregistered or reused broker server')

    def _disconnect(self):
        if self.connection is not None:self.connection.close()
        self.connection=None;self.session=None;self.requests=0

    def close(self):
        with self.lock:
            self.closed=True
            try:
                if self.connection is not None and not self.failed and self.max_requests>1:
                    self._verify_server()
                    frame_session=self.session+struct.pack('>I',self.requests)
                    self.connection.send_bytes(session_frame(self.authkey,b'request',frame_session,b''))
                    if read_session_frame(self.connection,self.authkey,b'response',frame_session)!=b'':
                        raise AccountingError('Broker close reply uncertain')
            except BaseException:
                self.failed=True;raise
            finally:self._disconnect()

    def call(self,method,*args):
        with self.lock:
            if self.failed or self.closed:raise AccountingError('Closed or uncertain broker route; explicit recovery required')
            self.sequence+=1
            try:
                if self.connection is None:self._connect()
                self._verify_server()  # Retained pipe is not permission to cache PID identity.
                request={'sequence':self.sequence,'method':method,'args':list(args)}
                encoded=json.dumps(pack(request),separators=(',',':')).encode()
                if len(encoded)>1024*1024:raise AccountingError('Broker request outside bound')
                frame_session=self.session+struct.pack('>I',self.requests)
                self.connection.send_bytes(session_frame(self.authkey,b'request',frame_session,encoded) if self.max_requests>1 else encoded)
                raw=(read_session_frame(self.connection,self.authkey,b'response',frame_session) if self.max_requests>1
                     else receive(self.connection,1024*1024))
                response=unpack(json.loads(raw))
                if response.get('ok') is not True:raise AccountingError('Broker rejected request')
                self.requests+=1
                if self.requests==self.max_requests:self._disconnect()
                return response['value']
            except BaseException:
                self.failed=True;self._disconnect();raise AccountingError('Broker outcome uncertain; no replay') from None

    def __getattr__(self,name):
        if name.startswith('_'):raise AttributeError(name)
        return lambda *args:self.call(name,*args)

    def issue(self,owner,role,generation,epoch):return self.call('issue',owner,role,generation,epoch)

    def begin_command(self,*args):
        result=self.call('begin_command',*args)
        if result=={'pre_dispatch_busy':True}:
            raise DispatchBusy('Authenticated pre-intent backpressure')
        if type(result) is not int or result<=0:
            self.failed=True
            raise AccountingError('Broker command admission reply uncertain')
        return result

    def complete_command(self,token,reply,serialized,endpoint):
        if serialized!=reply_bytes(reply):
            self.failed=True
            raise AccountingError('Local receipt serialization differs')
        return self.call('complete_reply',token,reply,endpoint)

    def seal(self,ticket,owner,role,generation,epoch,cid):
        # Broker verifies the claimed native owner before invoking credentials.
        return self.call('seal',owner,ticket,role,generation,epoch,cid)
