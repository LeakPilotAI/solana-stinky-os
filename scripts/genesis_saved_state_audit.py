"""Non-destructive export of a stopped, pinned Genesis Redis RDB.

No restore into production, container controls, configuration or Redis commands.
An exported artifact still requires Redis checksum and isolated restore checks.
"""
import json
import os
from pathlib import Path
import subprocess
import tarfile
import threading

from scripts.redis_snapshot_integrity import MAX_SNAPSHOT_BYTES, inspect_rdb

REDIS_ID = '56a3dd9c1d9cb8e03c2242818e98fe0f53bcb5eccbf2b1ed8479d70f55917804'
VOLUME = 'project-genesis_redis-data'


def verify_source(records):
    sources = [r for r in records if r.get('Id') == REDIS_ID]
    if len(sources) != 1:
        raise ValueError('Pinned source missing or duplicated')
    source = sources[0]
    labels = source.get('Config', {}).get('Labels') or {}
    mounts = source.get('Mounts', [])
    if (source.get('Name') != '/stinky-redis' or
            source.get('State', {}).get('Status') != 'exited' or
            labels.get('com.docker.compose.project') != 'project-genesis' or
            labels.get('com.docker.compose.service') != 'redis' or
            len(mounts) != 1 or mounts[0].get('Type') != 'volume' or
            mounts[0].get('Name') != VOLUME or mounts[0].get('Destination') != '/data' or
            mounts[0].get('RW') is not True):
        raise ValueError('Saved-state source ownership/state not verified')
    for row in records:
        if row.get('State', {}).get('Status') in ('running', 'restarting', 'paused'):
            if any(m.get('Name') == VOLUME and m.get('RW') is not False
                   for m in row.get('Mounts', [])):
                raise ValueError('Production volume may have an active writer')
    return source


def copy_tar_artifact(stream, destination):
    """Stream one regular RDB, bounded before writing; never extract paths."""
    destination = Path(destination)
    with tarfile.open(fileobj=stream, mode='r|*') as archive:
        entries = 0
        for member in archive:
            entries += 1
            if (entries != 1 or member.name not in ('dump.rdb', './dump.rdb') or
                    not member.isfile() or not 18 <= member.size <= MAX_SNAPSHOT_BYTES):
                raise ValueError('Unexpected or oversized saved-state artifact')
            source = archive.extractfile(member)
            with destination.open('xb') as target:
                remaining = member.size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError('Truncated saved-state artifact')
                    target.write(chunk); remaining -= len(chunk)
                target.flush(); os.fsync(target.fileno())
        if entries != 1:
            raise ValueError('Saved RDB absent')
    return inspect_rdb(destination)


def export(destination):
    result = subprocess.run(['docker', 'ps', '-aq'], capture_output=True, text=True, timeout=15)
    ids = result.stdout.split()
    if result.returncode or not 1 <= len(ids) <= 512:
        raise RuntimeError('Complete bounded container inventory unavailable')
    result = subprocess.run(['docker', 'inspect', *ids], capture_output=True, timeout=20)
    if result.returncode or len(result.stdout) > 16 * 1024 * 1024:
        raise RuntimeError('Container ownership inventory unavailable')
    records = json.loads(result.stdout)
    if len(records) != len(ids):
        raise RuntimeError('Container inventory incomplete')
    verify_source(records)
    # Only a pinned ID is used. Production is never mounted into another container.
    proc = subprocess.Popen(['docker', 'cp', REDIS_ID + ':/data/dump.rdb', '-'],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    # Bound a blocked local export too. This controls only our retained subprocess
    # handle, never a Redis/container/service process or a discovered PID.
    timer = threading.Timer(30, proc.kill)
    timer.daemon = True
    timer.start()
    try:
        manifest = copy_tar_artifact(proc.stdout, destination)
    finally:
        timer.cancel()
        proc.stdout.close()
        code = proc.wait(timeout=20)
    if code:
        raise RuntimeError('Saved artifact export failed; retained output is not certified')
    return manifest
