"""Exact, bounded Windows launch lineage; never termination authority."""
import ntpath
from datetime import datetime

from scripts.genesis_launch_provenance import descriptor


def fresh(native,pids):
    ids=tuple(dict.fromkeys(pids))
    batch=getattr(native,'batch',None)
    rows=batch(ids) if callable(batch) else {pid:native(pid) for pid in ids}
    if set(rows)!=set(ids):raise ValueError('Native phase missing identities')
    return {pid:descriptor(rows[pid]) for pid in ids}


def verify_lineage(rows, supervisor, owner, native):
    if not isinstance(rows,list) or not 1 <= len(rows) <= 4 or rows[-1]!=owner:
        raise ValueError('Bounded exact lineage required')
    parent=descriptor(supervisor);seen={parent['pid']}
    for expected in rows:
        row=descriptor(expected)
        if (row['pid'] in seen or row['parent_pid']!=parent['pid'] or
                datetime.fromisoformat(row['created'].replace('Z','+00:00')) <
                datetime.fromisoformat(parent['created'].replace('Z','+00:00')) or
                descriptor(native(row['pid']))!=row):
            raise ValueError('Lineage identity replaced or ancestry ambiguous')
        seen.add(row['pid']);parent=row


class WrapperObservation:
    """Executable pins come from trusted configuration, not discovered rows."""
    def __init__(self, *, native, census, executables):
        if (not callable(native) or not callable(census) or not isinstance(executables,tuple) or
                not 1<=len(executables)<=4 or any(not isinstance(p,str) or not ntpath.isabs(p) for p in executables)):
            raise ValueError('Pinned native wrapper configuration required')
        self.native=native;self.census=census
        self.executables=frozenset(ntpath.normcase(ntpath.normpath(p)) for p in executables)
        self.rows=None;self.command=None;self.supervisor=None

    def bind(self, root, leaf, command, supervisor):
        if self.rows is not None:raise ValueError('Wrapper claim reused')
        data=self.census();before={r['pid']:r for r in data['before']};after={r['pid']:r for r in data['after']}
        if len(before)!=len(data['before']) or len(after)!=len(data['after']):raise ValueError('Duplicate native PID')
        chain=[];pid=leaf
        for _ in range(4):
            row=after[pid]
            if descriptor(before[pid])!=descriptor(row):raise ValueError('Unstable wrapper census')
            if (ntpath.normcase(ntpath.normpath(row['executable'])) not in self.executables or
                    not isinstance(row.get('argv'),list) or len(row['argv'])!=len(command) or
                    ntpath.normcase(ntpath.normpath(row['argv'][0])) not in self.executables or
                    row['argv'][1:]!=list(command[1:])):
                raise ValueError('Unexpected wrapper executable or command')
            chain.insert(0,descriptor(row))
            if pid==root:break
            pid=row['parent_pid']
        else:raise ValueError('Wrapper ancestry exceeds bound')
        # Validate the paired census chain, then independently re-read the whole
        # native lineage in audit(). No observation is reused across IPC phases.
        verify_lineage(chain,supervisor,chain[-1],after.__getitem__)
        self.rows=chain;self.command=tuple(command);self.supervisor=descriptor(supervisor)
        self.audit()
        return list(chain)

    def verify(self):
        if self.rows is None:raise ValueError('No pinned wrapper lineage')
        observed=fresh(self.native,[self.supervisor['pid'],*[row['pid'] for row in self.rows]])
        if observed[self.supervisor['pid']]!=self.supervisor:raise ValueError('Supervisor replaced')
        verify_lineage(self.rows,self.supervisor,self.rows[-1],observed.__getitem__)

    def audit(self):
        self.verify();data=self.census()
        for phase in ('before','after'):
            rows={r['pid']:r for r in data[phase]}
            if len(rows)!=len(data[phase]):raise ValueError('Ambiguous process census')
            members={self.rows[0]['pid']}
            for _ in range(8):
                added={pid for pid,row in rows.items() if row['parent_pid'] in members}-members
                if not added:break
                members.update(added)
            if members!={r['pid'] for r in self.rows}:raise ValueError('Unexpected or missing descendants; HOLD')
            for expected in self.rows:
                if descriptor(rows[expected['pid']])!=expected:raise ValueError('Wrapper identity changed')
                row=rows[expected['pid']]
                if (not isinstance(row.get('argv'),list) or len(row['argv'])!=len(self.command) or
                        ntpath.normcase(ntpath.normpath(row['argv'][0])) not in self.executables or
                        row['argv'][1:]!=list(self.command[1:])):raise ValueError('Wrapper command evidence changed')
        return {'scope':'EXACT_NATIVE_LINEAGE_NOT_LIFECYCLE_AUTHORITY','lifecycle_authorized':False}
