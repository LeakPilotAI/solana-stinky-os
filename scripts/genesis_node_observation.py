"""Explicit Node launch adapter; no HMR descendant exemption or CP77 activation."""
from pathlib import Path

from scripts.genesis_private_child_channel import PrivatePythonChildChannel


class PrivateNodeChildChannel(PrivatePythonChildChannel):
    accepted_services=frozenset({'web'})
    def __init__(self, *, command, **kwargs):
        super().__init__(service='web',**kwargs)
        if (not isinstance(command,tuple) or len(command)<2 or len(command)>32 or
                any(not isinstance(s,str) for s in command) or
                not Path(command[0]).is_absolute() or not Path(command[0]).is_file() or Path(command[0]).name.casefold() not in ('node','node.exe') or
                not Path(command[1]).is_absolute() or not Path(command[1]).is_file()):
            raise ValueError('Exact trusted Node command required')
        self.expected=command
        self.expected_executable=str(Path(command[0]).resolve())

    def command_for(self, command):
        if self.phase!='PREPARED' or tuple(command)!=self.expected:
            self.phase='HOLD';raise ValueError('Node command changed; HOLD')
        entry=str(Path(__file__).with_name('genesis_private_node_entry.cjs').resolve())
        self.command=(command[0],entry,*command[1:]);self.phase='SPAWNING'
        return list(self.command)
