"""Application-only shutdown: exact native ownership, no dependency operations."""
from __future__ import annotations
import subprocess
import os
from scripts import safe_genesis_start as safe

MAINTAIN_SCRIPTS = ('run_intelligence_execution_v2.py','run_intelligence_shadow_scorer.py',
                    'run_intelligence_paper_decisions.py','run_intelligence_paper_execution_plans.py')

def stop_plan(launcher, rows):
    """Prove the complete observed trees before terminating anything.

    PID files/heartbeats are not ownership evidence for shutdown. Native argv,
    exact repository runner paths, ancestry and creation instants are required.
    """
    nodes={p:(parent,exe,cmd) for p,parent,exe,cmd in rows}
    roots={}; owners={}
    for name in safe.SERVICES:
        candidates={p:safe.runner_command(exe,cmd,name) for p,parent,exe,cmd in rows}
        candidates={p:value for p,value in candidates.items() if value is not None}
        for p,parsed in candidates.items():
            parent=nodes[p][0]
            if not safe.repository_runner(launcher,parsed):
                if parent not in candidates or not safe.repository_runner(launcher,candidates[parent]):
                    raise RuntimeError('Supervisor repository ownership unavailable; nothing stopped')
            owners[p]=name
        top=[p for p in candidates if nodes[p][0] not in candidates]
        if len(top)>1:raise RuntimeError('Multiple supervisor chains; nothing stopped')
        roots.update({p:name for p in top})
    for _ in range(24):
        changed=False
        for p,(parent,exe,cmd) in nodes.items():
            if p in owners or parent not in owners:continue
            name=owners[parent]
            valid=safe.application_command(launcher,name,exe,cmd)
            # Windows creates a dedicated console host beneath each owned app.
            # Only its exact system executable and observed console argv qualify.
            if exe.casefold()=='conhost.exe':
                tokens=safe.command_tokens(cmd)
                valid=(len(tokens)==2 and tokens[1]=='0x4' and
                    safe.windows_path(tokens[0].removeprefix('\\??\\'))==
                    safe.windows_path(str(safe.ntpath.join(os.environ.get('SystemRoot','C:\\Windows'),'System32','conhost.exe'))))
            if name=='maintain':
                parsed=safe.invocation(exe,cmd)
                if parsed:
                    tokens,index=parsed
                    valid=valid or safe.application_command(launcher,'collector',exe,cmd)
                    valid=valid or (index<len(tokens) and safe.windows_path(tokens[index]) in
                        [safe.windows_path(str(launcher.ROOT/'scripts'/s)) for s in MAINTAIN_SCRIPTS])
            if not valid:raise RuntimeError('Unverified process in application tree; nothing stopped')
            owners[p]=name;changed=True
        if not changed:break
    if any(parent in owners and p not in owners for p,(parent,exe,cmd) in nodes.items()):
        raise RuntimeError('Application ancestry exceeds bound; nothing stopped')
    # Supervisors first to prevent respawn, then only individually verified children.
    return [p for p in roots]+[p for p in owners if p not in roots]

def stop(launcher, *, dry_run=False):
    from scripts.start_paper_runtime import _windows_process_started_at
    with safe.startup_lock(launcher.LOG_DIR/'application-start.lock'):
        rows=safe.inventory(launcher);plan=stop_plan(launcher,rows)
        identities={p:_windows_process_started_at(p) for p in plan}
        if any(value is None for value in identities.values()):
            raise RuntimeError('Native creation identity unavailable; nothing stopped')
        expected={p:(parent,exe,cmd) for p,parent,exe,cmd in rows if p in plan}
        if dry_run:return plan
        for p in plan:
            current={pid:(parent,exe,cmd) for pid,parent,exe,cmd in safe.inventory(launcher)}
            if p not in current:continue  # Parent termination can already remove child.
            # Parent may disappear; command identity and creation instant must persist.
            if current[p][1:]!=expected[p][1:] or _windows_process_started_at(p)!=identities[p]:
                raise RuntimeError('Native process identity changed; remaining processes untouched')
            result=subprocess.run(['taskkill','/PID',str(p),'/F'],capture_output=True,timeout=15)
            if result.returncode and _windows_process_started_at(p)==identities[p]:
                raise RuntimeError(f'Application PID {p} termination failed; dependencies untouched')
        remaining=safe.inventory(launcher)
        if stop_plan(launcher,remaining):
            raise RuntimeError('Application processes remain; dependencies untouched')
        for name in safe.SERVICES:
            safe.reject_orphan(launcher,name,remaining)
        return plan

def main():
    import start_genesis as launcher
    try:
        stopped=stop(launcher)
        launcher.log_line('application-stop','STOPPED',reason=f'{len(stopped)} verified processes; dependencies untouched')
        print('Genesis applications stopped. Docker, databases, Redis history and Atlas untouched.')
        return 0
    except Exception as exc:
        launcher.log_line('application-stop','FAILED',reason=str(exc))
        print('Genesis shutdown not certified; inspect startup.log. Dependencies untouched.')
        return 1

if __name__=='__main__':
    import sys
    sys.exit(main())
