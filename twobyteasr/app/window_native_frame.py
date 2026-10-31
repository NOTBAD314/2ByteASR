"""Native move/resize/Snap capability with the existing client-drawn chrome.

Windows requires a sizing frame for HTLEFT/HTBOTTOMRIGHT and Aero Snap.
WM_NCCALCSIZE removes only the painted nonclient area; the native capability
remains. All MINMAXINFO coordinates below are physical pixels.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication

_API = None
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000


class MINMAXINFO(ctypes.Structure):
    _fields_ = [('ptReserved',wintypes.POINT),('ptMaxSize',wintypes.POINT),
                ('ptMaxPosition',wintypes.POINT),('ptMinTrackSize',wintypes.POINT),
                ('ptMaxTrackSize',wintypes.POINT)]


def _api():
    global _API
    if _API is None:
        u = ctypes.WinDLL('user32',use_last_error=True)
        u.GetWindowLongPtrW.argtypes = [wintypes.HWND,ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND,ctypes.c_int,ctypes.c_ssize_t]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,
                                  ctypes.c_int,ctypes.c_int,wintypes.UINT]
        u.GetDpiForWindow.argtypes = [wintypes.HWND]
        u.GetDpiForWindow.restype = wintypes.UINT
        u.IsZoomed.argtypes = [wintypes.HWND]
        u.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
        u.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT),wintypes.DWORD]
        u.MonitorFromRect.restype = wintypes.HMONITOR
        _API = u
    return _API


def configure(window):
    if (QApplication.platformName() != 'windows' or window.isFullScreen()
            or not window.testAttribute(Qt.WA_WState_Created)):
        return
    api = _api()
    from .window_constraints import existing_native_handle
    hwnd = existing_native_handle(window)
    if not hwnd:
        window._native_frame_active = window._native_caption_active = False
        return
    window._native_frame_hwnd = hwnd
    current = api.GetWindowLongPtrW(hwnd,GWL_STYLE)
    wanted = (current | WS_THICKFRAME) & ~WS_CAPTION
    window._native_frame_active = True  # before the synchronous NCCALCSIZE
    window._native_caption_active = True
    if current == wanted or getattr(window,'_configuring_native_frame',False):
        return
    window._configuring_native_frame = True
    try:
        ctypes.set_last_error(0)
        previous = api.SetWindowLongPtrW(hwnd,GWL_STYLE,wanted)
        if not previous and ctypes.get_last_error():
            window._native_frame_active = False
            window._native_caption_active = False
            return
        api.SetWindowPos(hwnd,None,0,0,0,0,0x0001|0x0002|0x0004|0x0010|0x0020)
    finally:
        window._configuring_native_frame = False


def fill_minmax(info, work, monitor, minimum, dpr):
    """No scaling of physical monitor origins or work areas (including <0)."""
    width,height = work[2]-work[0],work[3]-work[1]
    info.ptMaxPosition.x,info.ptMaxPosition.y = work[0]-monitor[0],work[1]-monitor[1]
    info.ptMaxSize.x,info.ptMaxSize.y = width,height
    info.ptMinTrackSize.x = max(1,min(width,round(minimum[0]*dpr)))
    info.ptMinTrackSize.y = max(1,min(height,round(minimum[1]*dpr)))


def handle_message(window, message, wparam, lparam, *, hwnd=None):
    if not getattr(window,'_native_frame_active',False):
        return None
    from .window_constraints import existing_native_handle
    hwnd = existing_native_handle(window, hwnd=hwnd)
    if not hwnd:
        return None
    if message in (0x0085, 0x0086) and not window.isMinimized() and not window.isFullScreen():
        # NCCALCSIZE assigns the complete frame to our Qt-painted client.
        # DefWindowProc must not paint a second native sizing frame when
        # activation changes (including an editor confirmation). Keep the
        # sizing/Snap style and allow activation to complete normally.
        # WM_NCACTIVATE: https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-ncactivate
        return 1 if message == 0x0086 else 0
    if message == 0x0083:  # WM_NCCALCSIZE: entire rect stays our Qt client area
        if wparam and lparam and not window.isFullScreen() and _api().IsZoomed(hwnd):
            # Native maximization includes an invisible sizing border beyond
            # the work area. Keep the Qt client (and title controls) inside it.
            # Select by the proposed physical rect, not the old Qt screen.
            from .window_constraints import _user32
            rect=wintypes.RECT.from_address(lparam)
            monitor=_api().MonitorFromRect(ctypes.byref(rect),2)
            u=_user32()
            info=u.MONITORINFO()
            info.cbSize=ctypes.sizeof(info)
            if monitor and u.GetMonitorInfoW(monitor,ctypes.byref(info)):
                work=info.rcWork
                left,top=max(rect.left,work.left),max(rect.top,work.top)
                right,bottom=min(rect.right,work.right),min(rect.bottom,work.bottom)
                if right>left and bottom>top:
                    rect.left,rect.top,rect.right,rect.bottom=left,top,right,bottom
        return 0
    if message == 0x0024 and lparam and not window.isFullScreen():  # WM_GETMINMAXINFO
        from .window_constraints import native_frame
        native = native_frame(window, hwnd=hwnd)
        if native is None:
            return None
        dpi = _api().GetDpiForWindow(hwnd) or 96
        info = MINMAXINFO.from_address(lparam)
        fill_minmax(info,native['work'],native['monitor'],
                    (window.minimumWidth(),window.minimumHeight()),dpi/96)
        return 0
    return None


def caption_target(window, point):
    """Qt client point -> existing passive title surface; controls stay client."""
    bar=getattr(window,'window_title_bar',None)
    if bar is not None and bar.isVisible():
        local=point-bar.mapTo(window,QPoint())
        if bar.rect().contains(local) and bar.childAt(local) in (None,getattr(bar,'title',None)):
            return 'windowTitleBar'
    pages=getattr(window,'pages',None)
    page=pages.currentWidget() if pages is not None else None
    toolbar=getattr(page,'studio_toolbar',None)
    if toolbar is not None and toolbar.isVisible():
        for name in ('filename','save_state'):
            label=getattr(page,name,None)
            if label is not None and label.isVisible() and label.rect().contains(point-label.mapTo(window,QPoint())):
                return label.objectName()
        local=point-toolbar.mapTo(window,QPoint())
        if toolbar.rect().contains(local) and toolbar.childAt(local) is None:
            return 'studioToolbar'
    return None


def caption_hit(window, screen_x, screen_y, dpr, *, hwnd=None):
    if not getattr(window,'_native_caption_active',False):
        return False
    from .window_constraints import existing_native_handle
    hwnd = existing_native_handle(window, hwnd=hwnd)
    if not hwnd or window.isFullScreen():
        return False
    origin=wintypes.POINT()
    if not _api().ClientToScreen(hwnd,ctypes.byref(origin)):
        return False
    point=QPoint(round((screen_x-origin.x)/dpr),round((screen_y-origin.y)/dpr))
    target=caption_target(window,point)
    if target:
        window._native_caption_target=target
    return target is not None
