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

# 2026-10-28 (user's 1-hour stream): Studio and the glossary proofread page
# each saved and restored the interval on their own. Back from the proofread
# page while its check still ran, Studio kept the page's 0.3 ms: a filter
# click took 1.4 s, Ctrl+S 7.6 s. Every owner now files a request here; the
# interval is the smallest active one, the caller's value when none is left.
_requests={}
_base=None
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


def _apply():
    global _base,_applied,_timer_raised
    current=sys.getswitchinterval()
    if _applied is not None and current!=_applied:
        # Someone set a policy of their own since: it is the new base.
        _base=current
    if not _requests:
        if _applied is not None and current==_applied and _base is not None:
            sys.setswitchinterval(_base)
        _base=_applied=None
    else:
        if _base is None:
            _base=current
        _applied=min([_base]+[interval for interval,_timer in _requests.values()])
        sys.setswitchinterval(_applied)
    wanted=any(timer for _interval,timer in _requests.values())
    if wanted and not _timer_raised:
        _timer_raised=_timer_period(True)
    elif not wanted and _timer_raised:
        _timer_raised=False
        _timer_period(False)


def request_switch_interval(owner,interval,*,timer=False):
    """Ask for at most ``interval`` seconds while ``owner`` holds the request."""
    _requests[owner]=(float(interval),bool(timer))
    _apply()


def release_switch_interval(owner):
    if _requests.pop(owner,None) is not None:
        _apply()


class GuiThreadHandoff:
    def __init__(self):self.held=False

    def acquire(self):
        if self.held or sys.platform!='win32':return
        self.held=True
        request_switch_interval(('studio-handoff',id(self)),INTERVAL,timer=True)

    def release(self):
        if not self.held:return
        self.held=False
        release_switch_interval(('studio-handoff',id(self)))
