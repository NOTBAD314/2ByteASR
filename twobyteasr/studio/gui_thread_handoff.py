"""Bound Python handoff latency while Windows Studio shares worker threads."""
import sys

_users=0
_previous=None
_applied=None


class GuiThreadHandoff:
    def __init__(self):self.held=False

    def acquire(self):
        global _users,_previous,_applied
        if self.held or sys.platform!='win32':return
        if not _users:
            _previous=sys.getswitchinterval()
            _applied=min(_previous,.001)
            sys.setswitchinterval(_applied)
        _users+=1;self.held=True

    def release(self):
        global _users
        if not self.held:return
        self.held=False;_users-=1
        if not _users and sys.getswitchinterval()==_applied:
            sys.setswitchinterval(_previous)
