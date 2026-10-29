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


def test_proofread_responsiveness_applies_only_while_its_page_is_on_screen(monkeypatch):
    """2026-10-28 (user's 1-hour stream): back in Studio while the proofread
    check still ran, the page's 0.3 ms stayed; a filter click took 1.4 s."""
    import twobyteasr.studio.gui_thread_handoff as handoff
    from twobyteasr.glossary import glossary_proofread as proofread
    calls=[];monkeypatch.setattr(handoff,'_timer_period',lambda begin:calls.append(begin) or True)
    monkeypatch.setitem(proofread._RESPONSIVE,'count',0);monkeypatch.setitem(proofread._RESPONSIVE,'visible',True)
    previous=sys.getswitchinterval();studio=GuiThreadHandoff()
    try:
        proofread.responsive_background(True)             # page shown, check starts
        assert sys.getswitchinterval()==.0003
        proofread.responsive_visible(False);studio.acquire()  # user goes back to Studio
        assert sys.getswitchinterval()==.001 and calls==[True]
        proofread.responsive_background(False)            # check ends later
        assert sys.getswitchinterval()==.001
        studio.release()
        assert sys.getswitchinterval()==previous and calls==[True,False]
        proofread.responsive_background(True);studio.acquire()  # either order
        proofread.responsive_visible(True)
        assert sys.getswitchinterval()==.0003
        proofread.responsive_background(False)
        assert sys.getswitchinterval()==.001
    finally:
        studio.release();proofread.responsive_visible(True)
        while proofread._RESPONSIVE['count']:proofread.responsive_background(False)
        sys.setswitchinterval(previous)


def test_proofread_owner_can_leave_while_studio_is_still_active():
    from twobyteasr.studio.gui_thread_handoff import request_switch_interval, release_switch_interval
    previous=sys.getswitchinterval();studio=GuiThreadHandoff()
    try:
        studio.acquire()
        request_switch_interval('proofread-test',.0003)
        assert sys.getswitchinterval()<=.0003
        release_switch_interval('proofread-test')
        assert sys.getswitchinterval()==min(previous,.001)
        studio.release()
        assert sys.getswitchinterval()==previous
    finally:
        release_switch_interval('proofread-test');studio.release();sys.setswitchinterval(previous)
