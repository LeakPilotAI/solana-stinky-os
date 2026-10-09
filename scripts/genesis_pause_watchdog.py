"""Resume a verified process-pause lease on controller loss or deadline.

This helper never suspends/kills processes or controls Docker. Lease files are
private operator artifacts, not externally supplied process selections.
"""
import json
import sys
import time
from pathlib import Path
from scripts.guarded_redis_migration import NativePause

def main(path):
    lease=Path(path)
    root=Path(__file__).resolve().parents[1]/'logs'
    if not lease.resolve().is_relative_to(root.resolve()):raise RuntimeError('Lease outside Genesis logs')
    data=json.loads(lease.read_text());adapter=NativePause();handles=[]
    try:
        for pid,creation in data['identities']:
            h=adapter.open(pid);handles.append(h)
            if adapter.creation(h)!=creation:raise RuntimeError('Watchdog identity mismatch')
        controller=adapter.open(data['controller_pid'])
        try:
            if adapter.creation(controller)!=data['controller_creation']:raise RuntimeError('Controller identity mismatch')
        finally:adapter.close(controller)
        lease.with_suffix('.ready').write_text('READY')
        while time.monotonic()<data['deadline_monotonic']:
            if lease.with_suffix('.complete').exists():return
            try:
                h=adapter.open(data['controller_pid'])
                try:alive=adapter.creation(h)==data['controller_creation']
                finally:adapter.close(h)
            except RuntimeError:alive=False
            if not alive:break
            time.sleep(.2)
        for h in reversed(handles):adapter.resume(h)
        lease.with_suffix('.expired').write_text('RESUMED: controller loss or bounded deadline')
    finally:
        for h in handles:adapter.close(h)

if __name__=='__main__':main(sys.argv[1])
