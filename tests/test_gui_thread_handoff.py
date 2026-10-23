import sys
import pytest
from twobyteasr.studio.gui_thread_handoff import GuiThreadHandoff

pytestmark=pytest.mark.skipif(sys.platform!='win32',reason='Windows GUI thread handoff policy')


def test_nested_windows_restore_prior_switch_interval():
    previous=sys.getswitchinterval();first=GuiThreadHandoff();second=GuiThreadHandoff()
    try:
        first.acquire();second.acquire();first.acquire()
        assert sys.getswitchinterval()<=.001
        first.release()
        assert sys.getswitchinterval()<=.001
        second.release()
        assert sys.getswitchinterval()==previous
    finally:first.release();second.release();sys.setswitchinterval(previous)


def test_timer_resolution_is_raised_once_and_restored(monkeypatch):
    # A 1 ms GIL wait lasts a 15.6 ms Windows tick unless the timer is raised.
    import twobyteasr.studio.gui_thread_handoff as handoff
    calls=[];monkeypatch.setattr(handoff,'_timer_period',lambda begin:calls.append(begin) or True)
    previous=sys.getswitchinterval();first=GuiThreadHandoff();second=GuiThreadHandoff()
    try:
        first.acquire();second.acquire()
        assert calls==[True] and sys.getswitchinterval()<=.001
        first.release();assert calls==[True]
        second.release();assert calls==[True,False]
    finally:first.release();second.release();sys.setswitchinterval(previous)


def test_real_timer_request_is_paired():
    import twobyteasr.studio.gui_thread_handoff as handoff
    assert handoff._timer_period(True) is True
    assert handoff._timer_period(False) is True


def test_release_respects_an_external_policy_change():
    previous=sys.getswitchinterval();lease=GuiThreadHandoff()
    try:
        lease.acquire();sys.setswitchinterval(.002);lease.release()
        assert sys.getswitchinterval()==.002
    finally:lease.release();sys.setswitchinterval(previous)
