"""Bound Python handoff latency while Windows Studio shares worker threads."""
import sys

# 2026-10-22 (report-eb10): CPython on Windows waits for the GIL in whole
# milliseconds, and a 1 ms wait lasts a full 15.6 ms system tick unless the
# timer resolution is raised. Measured next to one busy Python thread: a
# 1.4 ms GUI unit took ~31 ms at 1 ms (the same as the 5 ms default); below
# 1 ms the waits end at once and the threads trade the GIL constantly (GUI
# ~13 ms, worker throughput 61 %); 1 ms with a 1 ms timer: GUI ~4 ms, worker
# ~90 %. The timer request is held only while Studio is shown.
INTERVAL=.001
_users=0
_previous=None
_applied=None
_timer_raised=False


def _timer_period(begin):
    """timeBeginPeriod(1) / timeEndPeriod(1); False when unavailable."""
    try:
        import ctypes
        winmm=ctypes.WinDLL('winmm')
        call=winmm.timeBeginPeriod if begin else winmm.timeEndPeriod
        return call(1)==0
    except (OSError,AttributeError):
        return False


class GuiThreadHandoff:
    def __init__(self):self.held=False

    def acquire(self):
        global _users,_previous,_applied,_timer_raised
        if self.held or sys.platform!='win32':return
        if not _users:
            _previous=sys.getswitchinterval()
            _applied=min(_previous,INTERVAL)
            sys.setswitchinterval(_applied)
            _timer_raised=_timer_period(True)
        _users+=1;self.held=True

    def release(self):
        global _users,_timer_raised
        if not self.held:return
        self.held=False;_users-=1
        if not _users:
            if sys.getswitchinterval()==_applied:
                sys.setswitchinterval(_previous)
            if _timer_raised:
                _timer_raised=False
                _timer_period(False)
