"""Immutable identity-gate evidence. No process or container control."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from scripts import genesis_process_diagnostics as diag, safe_genesis_start as safe


def command_evidence(executable, command):
    """Retain only executable/known invocation tokens, never free-text arguments."""
    digest = hashlib.sha256(command.encode()).hexdigest()
    parsed = safe.invocation(executable, command)
    allowed = []
    if parsed:
        tokens, index = parsed
        allowed = [safe.ntpath.basename(safe.windows_path(tokens[0]))]
        if index < len(tokens):
            value = tokens[index]
            if safe.ntpath.basename(safe.windows_path(value)) == 'run_genesis_service.py':
                allowed.append('run_genesis_service.py')
                for service in safe.SERVICES:
                    if safe.runner_command(executable, command, service):
                        allowed += ['--name', service]
            elif value == '-m' and index+1 < len(tokens) and tokens[index+1] in safe.MODULES.values():
                allowed += ['-m', tokens[index+1]]
            elif safe.ntpath.basename(safe.windows_path(value)) in ('next','start-server.js',
                    'run_intelligence_execution_v2.py','run_intelligence_shadow_scorer.py',
                    'run_intelligence_paper_decisions.py','run_intelligence_paper_execution_plans.py'):
                allowed.append(safe.ntpath.basename(safe.windows_path(value)))
    elif executable.casefold()=='conhost.exe':
        allowed=['conhost.exe','[arguments redacted]']
    # A redacted command is presentation only; the raw digest remains exact.
    return {'redacted_command_tokens': allowed, 'redacted_command_line':subprocess.list2cmdline(allowed),
            'arguments_redacted': True,
            'command_sha256': digest}


def classify(difference):
    if difference['status'] == 'MATCH':return 'MATCH'
    if any('creation_ticks' in r['fields'] for r in difference['changed']):return 'PID_REUSE'
    if any(n['role'].startswith('supervisor:') for n in difference['added']+difference['removed']):return 'SUPERVISOR_CHANGE'
    if difference['changed']:return 'OWNERSHIP_CHANGE'
    return 'VERIFIED_CHILD_CHURN'  # Still fails the unchanged-tree gate.


class IdentityJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def persist(self, record):
        content = json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()
        if len(content) > 4*1024*1024:raise RuntimeError('Identity journal record outside bound')
        target = self.directory/(uuid.uuid4().hex+'.json')
        with target.open('xb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        return target

    def gate(self, phase, before, after):
        if phase not in ('BEFORE','DURING','AFTER'):raise RuntimeError('Unknown identity phase')
        try:difference = diag.compare_snapshots(before, after)
        except RuntimeError:
            self.persist({'phase':phase,'gate':'REJECTED','classification':'INVALID_SNAPSHOT',
                          'before_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
                          'after_sha256':hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest()})
            raise RuntimeError('Invalid identity snapshot; failure evidence persisted') from None
        record = {'phase': phase, 'before': before, 'after': after,
                  'difference': difference, 'classification': classify(difference)}
        try:diag.verify_unchanged(before, after)
        except RuntimeError:
            record['gate'] = 'REJECTED'
            if difference['status']=='MATCH':record['classification']='STALE_OR_CLOCK_ORDER_FAILURE'
            path = self.persist(record)
            raise RuntimeError(f'Identity gate rejected; exact evidence persisted at {path.name}') from None
        record['gate'] = 'PASSED'
        return self.persist(record)

    def capture(self, phase, launcher, adapter):
        if phase not in ('BEFORE','DURING','AFTER'):raise RuntimeError('Unknown identity phase')
        rows = []
        observations = []
        try:
            rows = safe.inventory(launcher)
            if len(rows) > diag.MAX_ROWS:raise RuntimeError('Inventory bound exceeded')
            identities = {}
            def creation(pid):
                identities[pid] = diag.native_identity(adapter, pid)
                return identities[pid][0]
            snapshot = diag.owned_snapshot(launcher, rows, creation, lambda p: identities[p][1])
            selected = {n['pid'] for n in snapshot['nodes']}
            nodes = {n['pid']:n for n in snapshot['nodes']}
            for p, parent, executable, command in rows:
                if p in selected:
                    ancestor=p
                    for _ in range(24):
                        node=nodes.get(ancestor)
                        if node is None:raise RuntimeError('Ownership ancestor unavailable')
                        if node['role'].startswith('supervisor:'):
                            service=node['role'].split(':',1)[1];break
                        ancestor=node['parent_pid']
                    else:raise RuntimeError('Ownership ancestry outside bound')
                    observations.append({'pid': p,'service':service,
                                         'process_role':nodes[p]['role'],
                                         'ownership_evidence':'VERIFIED_RUNNER_AND_NATIVE_ANCESTRY',
                                         **command_evidence(executable, command)})
            record = {'phase': phase, 'capture': 'VERIFIED', 'snapshot': snapshot,
                      'command_evidence': sorted(observations, key=lambda n:n['pid']),
                      'repository_path':str(launcher.ROOT),
                      'ownership_basis': 'EXACT_REPOSITORY_RUNNER_SERVICE_AND_VALIDATED_ANCESTRY'}
            self.persist(record)
            return snapshot
        except (RuntimeError, OSError):
            # Retain bounded candidate identity fingerprints even if ancestry fails.
            candidates = [{'pid':p,'parent_pid':parent,'executable':executable,
                           'command_sha256':hashlib.sha256(command.encode()).hexdigest()}
                          for p,parent,executable,command in rows[:diag.MAX_ROWS]
                          if executable.casefold() in ('python.exe','pythonw.exe','node.exe')]
            self.persist({'phase':phase,'capture':'UNVERIFIED','classification':'UNKNOWN_OWNERSHIP',
                          'candidates':candidates,'observed_monotonic_ns':time.monotonic_ns()})
            raise RuntimeError('Identity capture failed closed; candidate evidence persisted') from None


@contextmanager
def recorded_identity_window(journal, capture, pause):
    """Sequence an independently authorized actor and always record after resume.

    pause is supplied by the caller; this module grants no process authority.
    Every difference remains a rejection, even verified child churn.
    """
    before = capture('BEFORE')
    try:
        with pause(before):
            during = capture('DURING')
            journal.gate('DURING', before, during)
            yield during
    finally:
        after = capture('AFTER')
        journal.gate('AFTER', before, after)
