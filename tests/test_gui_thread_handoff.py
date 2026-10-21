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


def test_release_respects_an_external_policy_change():
    previous=sys.getswitchinterval();lease=GuiThreadHandoff()
    try:
        lease.acquire();sys.setswitchinterval(.002);lease.release()
        assert sys.getswitchinterval()==.002
    finally:lease.release();sys.setswitchinterval(previous)
