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
import threading
from multiprocessing.connection import Client, Listener

from stinky_core.transport.redis_accounting import AccountingError, identity,reply_bytes
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
        elif not (name.startswith('genesis-redis-c67-') and volume.startswith('project-genesis_checkpoint67-') and port in (16570,16571,16572,16573) and certification=='checkpoint67'):
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
    def __init__(self, ledger, credentials, manifest, verify_native, retention, *, server_epoch, endpoint):
        if not manifest or len(manifest)>128:raise AccountingError('Writer manifest unavailable')
        self.manifest={pid:identity(owner) for pid,owner in manifest.items()}
        if any(pid != owner['pid'] for pid,owner in self.manifest.items()):raise AccountingError('Manifest PID differs')
        self.ledger=ledger;self.credentials=credentials;self.verify_native=verify_native
        self.retention=retention;self.fenced=False;self.held=False;self.lock=threading.RLock()
        self.sequences={};self.current_owner=None
        if not isinstance(server_epoch,str) or not re.fullmatch('[0-9a-f]{40}',server_epoch) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',endpoint):
            raise AccountingError('Reviewed broker route required')
        self.server_epoch=server_epoch;self.endpoint=endpoint;self.generation=1

    def owner(self, pid):
        owner=self.manifest.get(pid)
        if owner is None or identity(self.verify_native(pid)) != owner:
            raise AccountingError('Unregistered or stale native writer')
        return owner

    def hold(self):
        self.held=True;self.fenced=True
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
                    return getattr(self.credentials,method)(*args)
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
                    self.retention.before(args[1],args[2])
                allowed={'register_connection','retire_connection','begin_command','complete_command','reject_group_exists','settled'}
                if method not in allowed:raise AccountingError('Broker method not allowlisted')
                if method in ('register_connection','retire_connection','begin_command'):
                    if not str(args[0]).startswith(f"{pid}-{owner['creation_ticks']}-"):
                        raise AccountingError('Writer identity spoofed')
                if method in ('complete_command','reject_group_exists'):
                    writer=self.ledger.commands[args[0]]['writer']
                    if not writer.startswith(f"{pid}-{owner['creation_ticks']}-"):
                        raise AccountingError('Acknowledgement owner differs')
                    if args[-1]!=self.endpoint or self.ledger.commands[args[0]]['generation']!=self.generation:
                        raise AccountingError('Acknowledgement route differs')
                    if method=='complete_command' and args[2]!=reply_bytes(args[1]):
                        raise AccountingError('Acknowledgement serialization differs')
                return getattr(self.ledger,method)(*args)
            except BaseException:
                self.hold();raise

    def quiesce(self, observed_ids):
        with self.lock:
            self.fenced=True;self.credentials.set_fenced(True)
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


class PipeServer:
    """One serialized bounded RPC; use recv_bytes, never unpickle client objects."""
    def __init__(self,address,authkey,broker):
        if os.name!='nt' or not address.startswith('\\\\.\\pipe\\genesis-') or len(authkey)!=32:
            raise AccountingError('Authenticated Genesis named pipe required')
        self.listener=Listener(address,family='AF_PIPE',authkey=None);self.broker=broker;self.authkey=authkey

    def serve_one(self):
        connection=self.listener.accept()
        try:
            pid=native_pipe_pid(connection)
            self.broker.owner(pid)
            challenge=os.urandom(32);connection.send_bytes(challenge)
            answer=receive(connection,64)
            if len(answer)!=64 or not hmac.compare_digest(answer[32:],signature(self.authkey,b'client',challenge,answer[:32])):
                raise AccountingError('Broker client authentication failed')
            connection.send_bytes(signature(self.authkey,b'server',challenge,answer[:32]))
            request=unpack(json.loads(receive(connection,1024*1024)))
            response=self.broker.dispatch(pid,request)
            encoded=json.dumps(pack({'ok':True,'value':response})).encode()
            if len(encoded)>1024*1024:raise AccountingError('Broker response outside bound')
            connection.send_bytes(encoded)
        except BaseException:
            self.broker.hold()
            try:connection.send_bytes(json.dumps(pack({'ok':False})).encode())
            except (OSError,EOFError):pass
        finally:connection.close()

    def close(self):self.listener.close()


class PipeProxy:
    def __init__(self,address,authkey,writers,*,server_identity):
        if not isinstance(server_identity,tuple) or len(server_identity)!=2 or any(type(v) is not int or v<=0 for v in server_identity) or len(authkey)!=32:
            raise AccountingError('Reviewed native broker identity required')
        self.address=address;self.authkey=authkey;self.writers=frozenset(writers)
        self.sequence=0;self.lock=threading.RLock();self.failed=False;self.server_identity=server_identity

    def call(self,method,*args):
        with self.lock:
            if self.failed:raise AccountingError('Lost broker reply; explicit recovery required')
            self.sequence+=1
            try:
                with Client(self.address,family='AF_PIPE',authkey=None) as connection:
                    pid=native_pipe_pid(connection,server=True)
                    if (pid,native_creation(pid))!=self.server_identity:raise AccountingError('Unregistered or reused broker server')
                    challenge=receive(connection,32);nonce=os.urandom(32)
                    if len(challenge)!=32:raise AccountingError('Broker challenge unavailable')
                    connection.send_bytes(nonce+signature(self.authkey,b'client',challenge,nonce))
                    if not hmac.compare_digest(receive(connection,32),signature(self.authkey,b'server',challenge,nonce)):
                        raise AccountingError('Broker server authentication failed')
                    request={'sequence':self.sequence,'method':method,'args':list(args)}
                    encoded=json.dumps(pack(request)).encode()
                    if len(encoded)>1024*1024:raise AccountingError('Broker request outside bound')
                    connection.send_bytes(encoded)
                    response=unpack(json.loads(receive(connection,1024*1024)))
                    if response.get('ok') is not True:raise AccountingError('Broker rejected request')
                    return response['value']
            except BaseException:
                self.failed=True;raise AccountingError('Broker outcome uncertain; no replay') from None

    def __getattr__(self,name):
        if name.startswith('_'):raise AttributeError(name)
        return lambda *args:self.call(name,*args)

    def issue(self,owner,role,generation,epoch):return self.call('issue',owner,role,generation,epoch)

    def seal(self,ticket,owner,role,generation,epoch,cid):
        # Broker verifies the claimed native owner before invoking credentials.
        return self.call('seal',owner,ticket,role,generation,epoch,cid)
