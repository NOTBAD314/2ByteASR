"""Native callbacks only consume existing HWNDs, including Qt teardown reentry."""
from __future__ import annotations

import ast
import copy
import ctypes
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.app import window_native_frame as frame
from twobyteasr.app import window_constraints as bounds


class Window:
    def __init__(self):
        self.created=True;self.hwnd=77;self.winid_calls=0
        self._native_frame_active=self._native_caption_active=True
        self._native_frame_hwnd=77
        self._resize_border=5;self._resize_corner=14
    def testAttribute(self,_):return self.created
    def internalWinId(self):return self.hwnd
    def winId(self):
        self.winid_calls+=1
        if self.winid_calls>4:raise RuntimeError('controlled native recreation recursion')
        # Mirrors the real Qt contract when winId() recreates a platform window:
        # creation synchronously sends another WM_NCCALCSIZE to nativeEvent.
        frame.handle_message(self,0x0083,1,1)
        return self.hwnd
    def isFullScreen(self):return False
    def isMaximized(self):return False
    def minimumWidth(self):return 320
    def minimumHeight(self):return 240
    def devicePixelRatioF(self):return 1.5
    def _native_resize_edge_at(self,*_):return None
    def nativeEvent(self,*_):return False,0


def test_teardown_with_created_flag_but_no_handle_does_not_recreate(monkeypatch):
    window=Window();window.hwnd=0
    api_calls=[]
    monkeypatch.setattr(frame,'_api',lambda:NS(IsZoomed=lambda hwnd:api_calls.append(hwnd) or False))
    assert frame.handle_message(window,0x0083,1,1) is None
    assert frame.caption_hit(window,100,100,1.) is False
    assert window.winid_calls==0 and not api_calls


@pytest.mark.parametrize('state',['uncreated','closing','finalizing','deleted','foreign_hwnd','null_hwnd'])
def test_invalid_callback_owner_uses_default_processing(monkeypatch,state):
    window=Window();hwnd=77
    if state=='uncreated':window.created=False
    elif state=='closing':window._studio_close_pending=True
    elif state=='finalizing':window._studio_close_finalizing=True
    elif state=='deleted':
        def deleted(_):raise RuntimeError('Internal C++ object already deleted')
        window.testAttribute=deleted
    elif state=='foreign_hwnd':hwnd=88
    else:hwnd=0
    monkeypatch.setattr(frame,'_api',lambda:pytest.fail('retired callback reached user32'))
    assert frame.handle_message(window,0x0083,1,1,hwnd=hwnd) is None
    assert not frame.caption_hit(window,100,100,1.,hwnd=hwnd)
    assert window.winid_calls==0


def test_nccalc_retains_normal_client_contract_without_winid(monkeypatch):
    window=Window();calls=[]
    monkeypatch.setattr(frame,'_api',lambda:NS(IsZoomed=lambda hwnd:calls.append(hwnd) or False))
    assert frame.handle_message(window,0x0083,1,1,hwnd=77)==0
    assert calls==[77] and window.winid_calls==0


def test_maximized_nccalc_keeps_client_inside_physical_work_area(monkeypatch):
    class Monitor(ctypes.Structure):
        _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD)]
    window=Window();rect=wintypes.RECT(-1928,-8,8,1088);seen=[]
    def monitor(_handle,pointer):
        value=ctypes.cast(pointer,ctypes.POINTER(Monitor)).contents
        value.rcWork=wintypes.RECT(-1920,0,0,1040)
        return True
    monkeypatch.setattr(frame,'_api',lambda:NS(IsZoomed=lambda hwnd:seen.append(hwnd) or True,MonitorFromRect=lambda *a:1))
    monkeypatch.setattr(bounds,'_user32',lambda:NS(MONITORINFO=Monitor,GetMonitorInfoW=monitor))
    assert frame.handle_message(window,0x0083,1,ctypes.addressof(rect),hwnd=77)==0
    assert (rect.left,rect.top,rect.right,rect.bottom)==(-1920,0,0,1040)
    assert seen==[77] and window.winid_calls==0


def test_minmax_uses_message_hwnd_and_physical_negative_monitor_coordinates(monkeypatch):
    window=Window();seen=[];info=frame.MINMAXINFO()
    monkeypatch.setattr(bounds,'native_frame',lambda widget,*,hwnd:seen.append(hwnd) or
                        dict(work=(-1920,0,0,1040),monitor=(-1920,0,0,1080)))
    monkeypatch.setattr(frame,'_api',lambda:NS(GetDpiForWindow=lambda hwnd:144))
    assert frame.handle_message(window,0x0024,0,ctypes.addressof(info),hwnd=77)==0
    assert seen==[77] and window.winid_calls==0
    assert (info.ptMaxPosition.x,info.ptMaxPosition.y)==(0,0)
    assert (info.ptMaxSize.x,info.ptMaxSize.y)==(1920,1040)
    assert (info.ptMinTrackSize.x,info.ptMinTrackSize.y)==(480,360)


def test_caption_hit_preserves_dpi_mapping_using_existing_message_hwnd(monkeypatch):
    window=Window();seen=[]
    def client(hwnd,pointer):
        seen.append(hwnd);point=ctypes.cast(pointer,ctypes.POINTER(wintypes.POINT)).contents
        point.x,point.y=100,-40
        return True
    monkeypatch.setattr(frame,'_api',lambda:NS(ClientToScreen=client))
    monkeypatch.setattr(frame,'caption_target',lambda widget,point:
                        'windowTitleBar' if (point.x(),point.y())==(10,10) else None)
    assert frame.caption_hit(window,115,-25,1.5,hwnd=77)
    assert seen==[77] and window.winid_calls==0 and window._native_caption_target=='windowTitleBar'


def test_native_frame_and_move_loop_queries_never_create_handles(monkeypatch):
    class Monitor(ctypes.Structure):
        _fields_=[('cbSize',wintypes.DWORD),('rcMonitor',wintypes.RECT),('rcWork',wintypes.RECT),('dwFlags',wintypes.DWORD)]
    class GuiThread(ctypes.Structure):
        _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),('hwndMoveSize',wintypes.HWND)]
    window=Window();seen=[]
    def rect(hwnd,pointer):
        seen.append(hwnd);value=ctypes.cast(pointer,ctypes.POINTER(wintypes.RECT)).contents
        value.left,value.top,value.right,value.bottom=10,20,810,620
        return True
    def monitor(_handle,pointer):
        value=ctypes.cast(pointer,ctypes.POINTER(Monitor)).contents
        value.rcWork=wintypes.RECT(0,0,1920,1040);value.rcMonitor=wintypes.RECT(0,0,1920,1080)
        return True
    def gui(_thread,pointer):
        value=ctypes.cast(pointer,ctypes.POINTER(GuiThread)).contents
        value.flags,value.hwndMoveSize=2,77
        return True
    api=NS(GetWindowRect=rect,GetClientRect=rect,ClientToScreen=lambda *a:True,
           MonitorFromWindow=lambda *a:1,GetMonitorInfoW=monitor,MONITORINFO=Monitor,
           GetDpiForWindow=lambda hwnd:144,GetWindowLongPtrW=lambda *a:0,
           IsZoomed=lambda hwnd:False,IsIconic=lambda hwnd:False,GUITHREADINFO=GuiThread,
           GetWindowThreadProcessId=lambda *a:1,GetGUIThreadInfo=gui)
    monkeypatch.setattr(QApplication,'platformName',staticmethod(lambda:'windows'))
    monkeypatch.setattr(bounds,'_user32',lambda:api)
    assert bounds.native_frame(window,hwnd=77)['rect']==(10,20,810,620)
    assert bounds.native_move_size_loop(window)
    assert not bounds._native_window_is_special(window)
    assert seen==[77,77] and window.winid_calls==0
    window.hwnd=0
    assert bounds.native_frame(window) is None and not bounds.native_move_size_loop(window)
    assert seen==[77,77]


def native_handler_harness():
    """Execute the actual nativeEvent body without constructing any GUI."""
    path=Path(__file__).resolve().parents[1]/'twobyteasr/app/ui.py'
    tree=ast.parse(path.read_text('utf-8-sig'))
    owner=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='MainWindow')
    method=copy.deepcopy(next(node for node in owner.body if isinstance(node,ast.FunctionDef) and node.name=='nativeEvent'))
    cls=ast.ClassDef(name='NativeHarness',bases=[ast.Name(id='Window',ctx=ast.Load())],keywords=[],body=[method],decorator_list=[])
    namespace={'Window':Window,'os':NS(name='nt'),'__package__':'twobyteasr.app'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),str(path),'exec'),namespace)
    return namespace['NativeHarness']


def test_native_event_forwards_exact_hwnd_and_declines_destroyed_owner(monkeypatch):
    window=native_handler_harness()();seen=[]
    monkeypatch.setattr(frame,'handle_message',lambda *a,**k:seen.append(k['hwnd']) or 0)
    msg=wintypes.MSG();msg.hWnd=77;msg.message=0x0083
    assert window.nativeEvent('windows_generic_MSG',ctypes.addressof(msg))==(True,0)
    assert seen==[77]
    window.hwnd=0
    assert window.nativeEvent('windows_generic_MSG',ctypes.addressof(msg))==(False,0)
    assert seen==[77] and window.winid_calls==0
    window.hwnd=77;msg.message=0x0082
    assert window.nativeEvent('windows_generic_MSG',ctypes.addressof(msg))==(False,0)
    assert not window._native_frame_active and not window._native_caption_active


def test_frame_configuration_uses_only_existing_handle_during_sync_nccalc(monkeypatch):
    window=Window();calls=[]
    def position(hwnd,*_):
        calls.append(('position',hwnd))
        # SetWindowPos(SWP_FRAMECHANGED) synchronously reenters the callback.
        assert frame.handle_message(window,0x0083,1,1,hwnd=hwnd)==0
        return True
    api=NS(GetWindowLongPtrW=lambda *a:frame.WS_CAPTION,
           SetWindowLongPtrW=lambda hwnd,index,value:calls.append(('style',hwnd,value)) or frame.WS_CAPTION,
           SetWindowPos=position,IsZoomed=lambda hwnd:False)
    monkeypatch.setattr(QApplication,'platformName',staticmethod(lambda:'windows'))
    monkeypatch.setattr(frame,'_api',lambda:api)
    frame.configure(window)
    assert calls==[('style',77,frame.WS_THICKFRAME),('position',77)]
    assert window._native_frame_hwnd==77 and window.winid_calls==0
    window.hwnd=0;calls.clear()
    frame.configure(window)
    assert not calls and window.winid_calls==0 and not window._native_frame_active


def test_native_event_retired_owner_does_not_reach_bounds_or_hit_testing(monkeypatch):
    window=native_handler_harness()()
    window._studio_close_pending=True
    window._window_bounds=NS(native_message=lambda *a:pytest.fail('retired message reached window bounds'))
    msg=wintypes.MSG();msg.hWnd=77;msg.message=0x0084
    assert window.nativeEvent('windows_generic_MSG',ctypes.addressof(msg))==(False,0)
    assert window.winid_calls==0
    # A delayed destroy for a different HWND cannot disable the live frame.
    window._studio_close_pending=False;msg.hWnd=88;msg.message=0x0082
    assert window.nativeEvent('windows_generic_MSG',ctypes.addressof(msg))==(False,0)
    assert window._native_frame_active and window._native_caption_active


def test_motion_diagnostics_do_not_recreate_handle_during_teardown(monkeypatch):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QCursor
    import shiboken6
    from twobyteasr.diagnostics import window_motion, event_log
    window=Window();window.hwnd=0
    window.screen=lambda:None
    window.isMinimized=lambda:False;window.isVisible=lambda:False
    window.geometry=window.frameGeometry=window.normalGeometry=lambda:QRect(0,0,640,480)
    rows=[]
    monkeypatch.setattr(window_motion,'enabled',lambda:True)
    monkeypatch.setattr(shiboken6,'isValid',lambda widget:True)
    monkeypatch.setattr(QCursor,'pos',staticmethod(lambda:QPoint(0,0)))
    monkeypatch.setattr(QApplication,'platformName',staticmethod(lambda:'windows'))
    monkeypatch.setattr(event_log,'emit',lambda *a,**k:rows.append(k))
    window_motion.record(window,'invalidate',actor='bounds',reason='close')
    assert len(rows)==1 and rows[0]['window_id']=='uncreated'
    assert rows[0]['native'] is None and window.winid_calls==0
