"""The optional wait remains polling and closes only after native wait exits."""
import gc
import sys
import threading

import pytest

from twobyteasr.playback import windows_poll_timer as timer


class API:
    def __init__(self,outcome=1):
        self.outcome=outcome;self.closed=[];self.armed=[];self.waits=[];self.cancelled=[];self.signalled=[]
        self.waiting=False;self.on_wait=None
    def timer(self):return 10
    def event(self):return 20
    def arm(self,handle,seconds):self.armed.append((handle,seconds))
    def cancel(self,handle):self.cancelled.append(handle)
    def signal(self,event):self.signalled.append(event)
    def wait(self,handles,timeout_ms):
        self.waits.append((handles,timeout_ms));self.waiting=True
        try:
            if self.on_wait:self.on_wait()
            if isinstance(self.outcome,BaseException):raise self.outcome
            return self.outcome
        finally:self.waiting=False
    def close(self,handle):
        assert not self.waiting,'closed handle while native wait still uses it'
        self.closed.append(handle)


@pytest.mark.parametrize('outcome,status',[(1,'timer_signalled'),(258,'bounded_timeout')])
def test_one_shot_poll_wait_is_bounded_and_never_retried(outcome,status):
    api=API(outcome);wait=timer.HighResolutionPollTimer(_api=api)
    assert wait.wait(.001)==status
    assert api.armed==[(10,.001)] and api.waits==[([20,10],2)]
    assert api.cancelled==[10]
    wait.close();wait.close()
    assert api.closed==[10,20]


def test_close_during_wait_signals_stop_and_defers_handle_retirement():
    api=API(0);wait=timer.HighResolutionPollTimer(_api=api)
    api.on_wait=wait.close
    with pytest.raises(timer.TimerCancelled):wait.wait(.001)
    assert api.signalled==[20] and api.closed==[10,20]
    assert api.cancelled==[10]


def test_wait_failure_disarms_before_later_close():
    api=API(OSError('wait failed'));wait=timer.HighResolutionPollTimer(_api=api)
    with pytest.raises(OSError):wait.wait(.001)
    assert api.cancelled==[10]
    wait.close();assert api.closed==[10,20]


def test_partial_constructor_failure_closes_created_timer():
    api=API()
    def fail():raise OSError('event failed')
    api.event=fail
    with pytest.raises(OSError):timer.HighResolutionPollTimer(_api=api)
    assert api.closed==[10]


@pytest.mark.parametrize('value',[0,-1,float('nan'),float('inf'),2])
def test_invalid_interval_never_arms(value):
    api=API();wait=timer.HighResolutionPollTimer(_api=api)
    with pytest.raises(ValueError):wait.wait(value)
    assert not api.armed
    wait.close()


def test_closed_timer_never_rearms():
    api=API();wait=timer.HighResolutionPollTimer(_api=api);wait.close()
    with pytest.raises(timer.TimerCancelled):wait.wait(.001)
    assert not api.armed


@pytest.mark.skipif(sys.platform!='win32',reason='Windows kernel primitive')
def test_real_timer_cycles_close_without_handle_leak():
    import psutil
    baseline=psutil.Process().num_handles()
    for _ in range(6):
        wait=timer.HighResolutionPollTimer()
        try:
            for _ in range(3):assert wait.wait(.001) in ('timer_signalled','bounded_timeout')
        finally:wait.close()
    del wait;gc.collect()
    assert psutil.Process().num_handles()<=baseline+2


@pytest.mark.skipif(sys.platform!='win32',reason='Windows kernel primitive')
def test_real_stop_event_wakes_wait_and_retires_on_owner_thread():
    wait=timer.HighResolutionPollTimer();entered=threading.Event();errors=[]
    native_wait=wait._api.wait
    def observe(*args):entered.set();return native_wait(*args)
    wait._api.wait=observe
    def run():
        try:wait.wait(1.)
        except BaseException as error:errors.append(error)
    thread=threading.Thread(target=run);thread.start()
    try:
        assert entered.wait(1)
        wait.close();thread.join(2)
        assert not thread.is_alive()
        assert len(errors)==1 and isinstance(errors[0],timer.TimerCancelled)
        assert wait._timer is None and wait._stop is None
    finally:wait.close();thread.join(2)
