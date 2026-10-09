"""Serialized application-only recovery. Never stops, deletes, trims or migrates."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

CORE_SERVICES = ('event-log','api','sentinel','collector','entities','web','maintain')
PAPER_SERVICES = ('paper-intake-producer','paper-runtime')
SERVICES = CORE_SERVICES + PAPER_SERVICES
URLS = {'event-log':'http://127.0.0.1:8002/health','api':'http://127.0.0.1:8010/health','web':'http://127.0.0.1:3000/operator'}
PORTS = {'event-log':8002,'api':8010,'web':3000}
MODULES = {'collector':'post_migration.cli','sentinel':'sentinel.cli','entities':'entity_resolver.cli','api':'stinky_api.cli','event-log':'event_log.cli','web':'next','paper-intake-producer':'stinky_api.prospective_paper_policy_runtime','paper-runtime':'stinky_api.paper_runtime_worker'}
DEPENDENCIES = {'stinky-postgres':('postgres','/var/lib/postgresql/data','5432/tcp','5433'), 'stinky-redis':('redis','/data','6379/tcp','6380'), 'stinky-minio':('minio','/data','9000/tcp','9010')}

@contextmanager
def startup_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream,fcntl.LOCK_UN)

def run(args, **kwargs):
    # Probe arguments are an internal allowlist. Never expose input SQL/env or raw
    # output: Docker inspect and provider errors can contain credentials.
    label=' '.join(str(a) for a in args[1:] if str(a) in (
        'inspect','exec','start','pg_isready','psql','redis-cli','PING','curl',
        'stinky-postgres','stinky-redis','stinky-minio')) or 'local probe'
    try:
        result=subprocess.run(args,capture_output=True,text=True,timeout=15,**kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'Required local probe failed: {label}; timeout=15s; no destructive fallback') from None
    if result.returncode:
        # Record bounded safe error categories, not secret-bearing free text.
        categories=[word for word in ('connection refused','does not exist','permission denied',
            'no such container','not running','authentication failed','could not connect')
            if word in (result.stderr or '').lower()]
        detail=','.join(categories) or ('stderr present (redacted)' if result.stderr else 'stderr empty')
        raise RuntimeError(f'Required local probe failed: {label}; exit={result.returncode}; {detail}; no destructive fallback')
    return result.stdout

def validate_dependency(record,name):
    service,dest,port,host=DEPENDENCIES[name]
    labels=record.get('Config',{}).get('Labels') or {}
    if record.get('Name')!='/'+name or labels.get('com.docker.compose.project')!='project-genesis' or labels.get('com.docker.compose.service')!=service:
        raise RuntimeError('Dependency ownership unavailable')
    mounts=record.get('Mounts',[])
    if not any(m.get('Destination')==dest and m.get('Type')=='volume' and m.get('Name')=='project-genesis_'+service+'-data' for m in mounts):
        raise RuntimeError('Dependency persistent volume ownership unavailable')
    binding=(record.get('HostConfig',{}).get('PortBindings',{}).get(port) or [])
    if not any(b.get('HostPort')==host for b in binding):raise RuntimeError('Dependency port ownership unavailable')
    state=record.get('State',{}).get('Status')
    if state not in ('running','exited','created'):raise RuntimeError('Dependency state unsafe')
    return state

def ensure_dependencies(launcher):
    docker=launcher.find_docker()
    if not docker:raise RuntimeError('Docker unavailable; start it separately')
    records=json.loads(run([docker,'inspect',*DEPENDENCIES]))
    if len(records)!=3:raise RuntimeError('Existing Genesis dependencies required; never create containers')
    states={name:validate_dependency(record,name) for name,record in zip(DEPENDENCIES,records)}
    for name,state in states.items():
        if state!='running':run([docker,'start',name])
    # Healthy running containers are never recycled. Redis history/config untouched.
    if 'accepting connections' not in run([docker,'exec','stinky-postgres','pg_isready','-U','stinky','-d','stinky']):raise RuntimeError('Postgres unavailable')
    if run([docker,'exec','stinky-redis','redis-cli','PING']).strip()!='PONG':raise RuntimeError('Redis unavailable')
    run([docker,'exec','stinky-minio','curl','-f','http://localhost:9000/minio/health/live'])

def verify_schema(launcher):
    from scripts.strict_startup_schema_gate import REQUIRED_TABLES
    names=(*REQUIRED_TABLES,'events','intelligence_execution_v2_registry','intelligence_execution_v2_plans','intelligence_execution_v2_results')
    expressions=','.join("to_regclass('public."+n+"') IS NOT NULL" for n in names)
    sql="BEGIN READ ONLY; SELECT "+' AND '.join(expressions.split(','))+"; ROLLBACK;"
    output=run([launcher.find_docker(),'exec','-i','stinky-postgres','psql','-U','stinky','-d','stinky','-v','ON_ERROR_STOP=1','-t','-A'],input=sql)
    if 't' not in output.splitlines():raise RuntimeError('Schema missing; recovery never applies migrations')

def inventory(launcher):
    rows=launcher.list_win_processes()
    if not rows:raise RuntimeError('Native process inventory unavailable')
    return rows

def command_tokens(command):
    # Supported runners use separate, optionally double-quoted argv tokens.
    # Reject ambiguous quoting rather than interpreting embedded command text.
    tokens=[];end=0
    for match in re.finditer(r'(?:^|\s)(?:"([^"\r\n]*)"|([^\s"]+))(?=\s|$)',command):
        if command[end:match.start()].strip():raise RuntimeError('Ambiguous native command quoting')
        tokens.append(match.group(1) if match.group(1) is not None else match.group(2));end=match.end()
    if command[end:].strip():raise RuntimeError('Ambiguous native command quoting')
    return tokens


def windows_path(value):
    return ntpath.normcase(ntpath.normpath(value.replace('/', '\\')))


def invocation(exe,command):
    executable=exe.casefold()
    if executable not in ('python.exe','pythonw.exe','node.exe'):return None
    tokens=command_tokens(command)
    if not tokens:raise RuntimeError('Native command identity unavailable')
    expected={'python.exe':('python','python.exe'),'pythonw.exe':('pythonw','pythonw.exe'),'node.exe':('node','node.exe')}[executable]
    if ntpath.basename(windows_path(tokens[0])) not in expected:raise RuntimeError('Native executable identity mismatch')
    index=1
    if executable!='node.exe':
        while index<len(tokens) and tokens[index] in ('-u','-B','-E','-s','-S','-I'):index+=1
    return tokens,index


def runner_command(exe,command,name):
    if exe.casefold() not in ('python.exe','pythonw.exe'):return None
    parsed=invocation(exe,command)
    if parsed is None or exe.casefold()=='node.exe':return None
    tokens,index=parsed
    if index>=len(tokens) or ntpath.basename(windows_path(tokens[index]))!='run_genesis_service.py':return None
    names=[]
    for i,t in enumerate(tokens[index+1:],index+1):
        if t.casefold()=='--name':
            if i+1>=len(tokens):raise RuntimeError('Missing supervisor service identity')
            names.append(tokens[i+1].casefold())
        elif t.casefold().startswith('--name='):names.append(t.split('=',1)[1].casefold())
    if name.casefold() not in names:return None
    if len(names)!=1:raise RuntimeError('Ambiguous supervisor service identity')
    return tokens[0],tokens[index]


def repository_runner(launcher,parsed):
    executable,script=parsed
    expected=windows_path(str(launcher.ROOT/'scripts/run_genesis_service.py'))
    if ntpath.isabs(script.replace('/','\\')):return windows_path(script)==expected
    # Relative runner requires an exact repo-local venv executable in this chain.
    return windows_path(script)==windows_path('scripts/run_genesis_service.py') and windows_path(executable) in (
        windows_path(str(launcher.ROOT/'.venv/Scripts/python.exe')),
        windows_path(str(launcher.ROOT/'.venv/Scripts/pythonw.exe')))


def application_command(launcher,name,exe,command):
    if name!='web' and exe.casefold() not in ('python.exe','pythonw.exe'):return False
    parsed=invocation(exe,command)
    if parsed is None:return False
    tokens,index=parsed
    if index>=len(tokens):return False
    if name=='web':
        return exe.casefold()=='node.exe' and windows_path(tokens[index]) in (
            windows_path(str(launcher.ROOT/'apps/web/node_modules/next/dist/bin/next')),
            windows_path(str(launcher.ROOT/'apps/web/node_modules/next/dist/server/lib/start-server.js')))
    if exe.casefold()=='node.exe':return False
    if name=='maintain':return windows_path(tokens[index])==windows_path(str(launcher.ROOT/'scripts/run_intelligence_execution_v2.py'))
    return tokens[index]=='-m' and index+1<len(tokens) and tokens[index+1].casefold()==MODULES[name].casefold()


def service_pid(launcher,name,rows):
    # Collapse Windows venv wrapper + actual Python into a single service chain.
    candidates={}
    parsed_commands={}
    for p,parent,exe,cmd in rows:
        parsed=runner_command(exe,cmd,name)
        if parsed is not None:
            candidates[p]=(parent,cmd);parsed_commands[p]=parsed
    leaves=[p for p in candidates if not any(parent==p for parent,cmd in candidates.values())]
    if len(leaves)>1:raise RuntimeError('Multiple supervisor chains; manual investigation required')
    if not leaves:return None
    pid=leaves[0];parent,cmd=candidates[pid]
    if not repository_runner(launcher,parsed_commands[pid]) and not (
        windows_path(parsed_commands[pid][1])==windows_path('scripts/run_genesis_service.py') and parent in candidates and repository_runner(launcher,parsed_commands[parent])):
        raise RuntimeError('Supervisor repository ownership unavailable')
    from scripts.start_paper_runtime import _windows_process_started_at
    actual=_windows_process_started_at(pid)
    try:
        with (launcher.LOG_DIR/f'runtime-state-{name}.json').open('rb') as f:state=json.loads(f.read(16384))
        start=datetime.fromisoformat(state['supervisor_started_at'].replace('Z','+00:00'))
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['as_of'].replace('Z','+00:00'))).total_seconds()
        valid=state['service']==name and state['supervisor_pid']==pid and actual is not None and abs((actual-start).total_seconds())<=5 and -5<=age<=180 and state.get('supervisor_phase') in ('RUNNING','SUPERVISING')
    except (OSError,ValueError,KeyError,TypeError):valid=False
    if not valid:raise RuntimeError('Existing supervisor identity/heartbeat unverified; no duplicate started')
    if name in URLS and not launcher.http_ok(URLS[name],3):raise RuntimeError('Existing owned service unhealthy; its watchdog owns recovery')
    if name == 'maintain':
        from scripts.genesis_pass_provenance import read_observations
        source=read_observations(launcher.LOG_DIR/'v2-pass-provenance.jsonl')
        good=[e for e in source['events'] if e['supervisor_pid']==pid and e['phase']=='FINISH' and e['return_code']==0 and e['observed_at'] and datetime.fromisoformat(e['observed_at'])>=start]
        if source.get('invalid_lines',0) or source.get('conflicting_event_ids',0) or not good or not -5<=(datetime.now(timezone.utc)-datetime.fromisoformat(good[-1]['observed_at'])).total_seconds()<=180:
            raise RuntimeError('Maintenance pass activity unverified; no second supervisor started')
    else:
        parents={p:parent for p,parent,exe,cmd in rows}
        def descendant(p):
            for _ in range(24):
                p=parents.get(p,0)
                if p==pid:return True
                if not p:return False
            return False
        if not any(descendant(p) and application_command(launcher,name,exe,cmd) for p,parent,exe,cmd in rows):
            raise RuntimeError('Owned application child unavailable; no second worker started')
    return pid

def reject_orphan(launcher,name,rows):
    if any(application_command(launcher,name,exe,cmd) for p,parent,exe,cmd in rows):
        raise RuntimeError('Possible orphan application process; no duplicate started')
    if name in PORTS and launcher.listen_pid(PORTS[name]):raise RuntimeError('Port occupied without proven Genesis supervisor; untouched')

def recover_service(launcher,name):
    if name not in SERVICES:raise ValueError('Service not allowlisted')
    rows=inventory(launcher);pid=service_pid(launcher,name,rows)
    if pid:return pid
    reject_orphan(launcher,name,rows)
    runner=launcher.ROOT/'scripts/run_genesis_service.py';exe=launcher.ROOT/'.venv/Scripts/pythonw.exe'
    if not exe.is_file():exe=launcher.ROOT/'.venv/Scripts/python.exe'
    if not exe.is_file() or not runner.is_file():raise RuntimeError('Existing environment required; recovery never installs')
    token=uuid.uuid4().hex;env={**os.environ,'GENESIS_SUPERVISOR_LAUNCH_TOKEN':token,'PYTHONUNBUFFERED':'1','BROWSER':'none'}
    flags=0x08000000|0x00000200|0x01000000 if os.name=='nt' else 0
    # Preserve prior service logs; runner writes them, parent transport goes to a separate append-only file.
    with (launcher.LOG_DIR/f'{name}-starter.log').open('a',encoding='utf-8') as log:
        proc=subprocess.Popen([str(exe),str(runner),'--name',name],cwd=str(launcher.ROOT),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if proc.poll() is not None:raise RuntimeError('Starter exited; no second launch attempted')
        try:
            with (launcher.LOG_DIR/f'runtime-state-{name}.json').open('rb') as f:state=json.loads(f.read(16384))
            if state.get('supervisor_launch_token')==token:
                pid=service_pid(launcher,name,inventory(launcher))
                if pid:return pid
        except (OSError,ValueError,KeyError,RuntimeError):pass
        time.sleep(.5)
    raise RuntimeError('Startup ownership/health not proven; existing new process left untouched')

def selected_services(args):
    if getattr(args,'core_only',False) and getattr(args,'full',False):
        raise ValueError('Choose one startup profile')
    return SERVICES if getattr(args,'full',False) else CORE_SERVICES


def recover(launcher,args):
    try:
        if args.sync or args.restart:raise RuntimeError('Sync/restart are separate reviewed operations; ordinary startup preserves code and services')
        services=selected_services(args)
        with startup_lock(launcher.LOG_DIR/'application-start.lock'):
            if not (launcher.ROOT/'.env').is_file():raise RuntimeError('Existing .env required')
            launcher.ensure_docker();launcher.apply_schema()
            procs={}
            for name in services:procs[name]=launcher.start_detached(name,required=True)
            launcher.write_pid_file(procs)
            launcher.HEALTH['DISCORD']='DISABLED'
            launcher.say(('FULL' if getattr(args,'full',False) else 'CORE-ONLY')+' startup: ALREADY RUNNING or safely recovered; no outbound notifications; paper-only, live authority locked')
            if not getattr(args,'full',False):launcher.say('Persistent paper intake/processing is not managed by CORE-ONLY; existing paper services stay untouched. Use --full explicitly for that separate workflow.')
            if not all(launcher.http_ok(url,3) for url in URLS.values()):raise RuntimeError('Final HTTP health unavailable')
            launcher.open_operator()
            return 0
    except Exception as exc:
        launcher.fail('recovery','DOWN',str(exc),next_step='Inspect ownership/dependency health; do not run a second worker or reset evidence')
        return 1
