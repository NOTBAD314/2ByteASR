"""Native resize requests must not diverge from the Qt-painted client."""
import ctypes
from ctypes import wintypes as W
from types import SimpleNamespace
import pytest
from twobyteasr.app import window_constraints as bounds


class WINDOWPOS(ctypes.Structure):
    _fields_ = [('hwnd',W.HWND),('after',W.HWND),('x',ctypes.c_int),('y',ctypes.c_int),
                ('cx',ctypes.c_int),('cy',ctypes.c_int),('flags',W.UINT)]


def widget(*, maximum=False, fullscreen=False, minimized=False):
    return SimpleNamespace(isMaximized=lambda:maximum,isFullScreen=lambda:fullscreen,isMinimized=lambda:minimized)


def test_normal_resize_keeps_requested_client_extent_without_qt_native_reexpansion():
    pos=WINDOWPOS(1,0,50,40,1680,1138,0)
    assert bounds.native_windowpos(widget(),ctypes.addressof(pos))
    assert (pos.x,pos.y,pos.cx,pos.cy)==(50,40,1680,1138)


@pytest.mark.parametrize('flags,x,minimized',[(1,0,False),(0,-32000,False),(0,0,True)])
def test_non_sizing_and_minimized_messages_remain_owned_by_qt(flags,x,minimized):
    pos=WINDOWPOS(1,0,x,0,100,100,flags)
    assert not bounds.native_windowpos(widget(maximum=True,minimized=minimized),ctypes.addressof(pos))


@pytest.mark.parametrize('fullscreen,height',[(False,3390),(True,3440)])
def test_maximum_and_fullscreen_use_distinct_physical_monitor_bounds(monkeypatch,fullscreen,height):
    class MONITORINFO(ctypes.Structure):
        _fields_=[('cbSize',W.DWORD),('rcMonitor',W.RECT),('rcWork',W.RECT),('dwFlags',W.DWORD)]
    def monitor(_rect,_flags): return 7
    def get_info(_monitor,pointer):
        value=ctypes.cast(pointer,ctypes.POINTER(MONITORINFO)).contents
        value.rcMonitor=W.RECT(-1440,-521,0,2919)
        value.rcWork=W.RECT(-1440,-521,0,2869)
        return 1
    monkeypatch.setattr(bounds,'_user32',lambda:SimpleNamespace(MONITORINFO=MONITORINFO,
        MonitorFromRect=monitor,GetMonitorInfoW=get_info))
    pos=WINDOWPOS(1,0,-1400,-500,1800,3600,0)
    assert bounds.native_windowpos(widget(maximum=not fullscreen,fullscreen=fullscreen),ctypes.addressof(pos))
    assert (pos.x,pos.y,pos.cx,pos.cy)==(-1440,-521,1440,height)


def test_responsive_cards_do_not_reenter_with_half_updated_child_geometry():
    from twobyteasr.app.ui_recognition import RecognitionPlanWidget
    count=[]
    page=SimpleNamespace()
    def update(_comfortable):
        count.append(1)
        assert not RecognitionPlanWidget._update_responsive_profile(page)
        return True
    page._update_responsive_profile_impl=update
    assert RecognitionPlanWidget._update_responsive_profile(page)
    assert count==[1] and not page._updating_responsive_profile


def test_responsive_card_layout_guard_is_released_on_failure():
    from twobyteasr.app.ui_recognition import RecognitionPlanWidget
    def update(_comfortable):raise ValueError('controlled layout failure')
    page=SimpleNamespace(_update_responsive_profile_impl=update)
    with pytest.raises(ValueError):
        RecognitionPlanWidget._update_responsive_profile(page)
    assert not page._updating_responsive_profile
