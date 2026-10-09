"""Bounded read-only Redis census and immutable RDB artifact verification.

No configuration changes, restore operations, key writes or container controls.
Redis's redis-check-rdb must additionally verify checksum/structure before restore.
Manifests contain fingerprints, not values or raw key/group/consumer identifiers.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

MAX_SNAPSHOT_BYTES=128*1024*1024
MAX_KEYS=1000
MAX_KEY_BYTES=64*1024*1024

# Each DB is measured atomically, but separate DB measurements are not a global
# point-in-time snapshot. Only a restored immutable RDB defines that global state.
CENSUS = """
local count=redis.call('DBSIZE')
if count>tonumber(ARGV[1]) then return redis.error_reply('key bound exceeded') end
local result={}
local total=0
for _,key in ipairs(redis.call('KEYS','*')) do
  local size=redis.call('MEMORY','USAGE',key) or 0
  if size>tonumber(ARGV[2]) then return redis.error_reply('key byte bound exceeded') end
  local kind=redis.call('TYPE',key).ok
  local value=redis.call('DUMP',key)
  if #value>tonumber(ARGV[2]) then return redis.error_reply('serialized bound exceeded') end
  total=total+#value
  if total>tonumber(ARGV[2]) then return redis.error_reply('dataset byte bound exceeded') end
  local groups={}
  local length=-1
  local streammeta={}
  if kind=='stream' then
    length=redis.call('XLEN',key)
    groups=redis.call('XINFO','GROUPS',key)
    local info=redis.call('XINFO','STREAM',key)
    for i=1,#info,2 do
      local field=info[i]
      if field=='last-generated-id' or field=='entries-added' or field=='max-deleted-entry-id' then
        table.insert(streammeta,field);table.insert(streammeta,info[i+1])
      elseif (field=='first-entry' or field=='last-entry') and info[i+1] then
        table.insert(streammeta,field);table.insert(streammeta,info[i+1][1])
      end
    end
  end
  table.insert(result,{key,kind,value,redis.call('PEXPIRETIME',key),length,groups,streammeta})
end
return result
"""

def fingerprint(value:bytes)->str:
    return hashlib.sha256(value).hexdigest()

def inspect_rdb(path:Path)->dict:
    size=path.stat().st_size
    if not 18<=size<=MAX_SNAPSHOT_BYTES:
        raise ValueError('RDB size outside verification bound')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        header=stream.read(9)
        if not header.startswith(b'REDIS') or not header[5:].isdigit():
            raise ValueError('Invalid RDB header')
        digest.update(header)
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return {'bytes':size,'sha256':digest.hexdigest(),'format':header.decode('ascii'),
            'checksum_verified':False}

def verify_same_snapshot(original:Path,copy:Path)->dict:
    expected=inspect_rdb(original);actual=inspect_rdb(copy)
    if actual!=expected:raise ValueError('Snapshot copy fingerprint differs')
    return expected

def census(client)->dict:
    result=[]
    for key,kind,value,expires,length,groups,streammeta in client.eval(CENSUS,0,MAX_KEYS,MAX_KEY_BYTES):
        mapped=[]
        for group in groups:
            fields=dict(zip(group[::2],group[1::2]))
            mapped.append({
                'name_sha256':fingerprint(fields[b'name']),
                'consumers':fields[b'consumers'],'pending':fields[b'pending'],
                'last_delivered_id':fields[b'last-delivered-id'].decode('ascii'),
                'entries_read':fields.get(b'entries-read'), 'lag':fields.get(b'lag')})
        stream_fields={k.decode('ascii'):(v.decode('ascii') if isinstance(v,bytes) else v)
                       for k,v in zip(streammeta[::2],streammeta[1::2])}
        result.append({'key_sha256':fingerprint(key),'type':kind.decode('ascii'),
            'serialized_sha256':fingerprint(value),'serialized_bytes':len(value),
            'expires_at_ms':expires,'stream_length':None if length<0 else length,
            'groups':sorted(mapped,key=lambda g:g['name_sha256']), 'stream_metadata':stream_fields})
    return {'key_count':len(result),'keys':sorted(result,key=lambda r:r['key_sha256'])}

def verify_recovery(expected:dict,recovered:dict)->None:
    if expected!=recovered:
        raise ValueError('Recovered snapshot census differs; recovery not certified')

def verify_aof_ready(info:dict)->None:
    required={'aof_enabled':1,'aof_rewrite_in_progress':0,'aof_rewrite_scheduled':0,
              'aof_last_bgrewrite_status':'ok','aof_last_write_status':'ok'}
    if any(info.get(key)!=value for key,value in required.items()):
        raise ValueError('AOF durability evidence incomplete or unhealthy')

def verify_config_file_startup(command:list[str])->None:
    # A persisted config cannot override conflicting command-line flags. This
    # deliberately certifies only the explicit isolated config-file design.
    if command!=['redis-server','/data/redis.conf']:
        raise ValueError('Startup may override persistence; conversion not certified')
