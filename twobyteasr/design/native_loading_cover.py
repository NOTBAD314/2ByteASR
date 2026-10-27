"""Read-only Windows child-cover evidence and an exact input-enabled lease.

This module never creates HWNDs or changes native styles. Qt owns the child
surface and paints it; the main-window owner owns navigation and retirement.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import os
import sys
import weakref

from PySide6.QtCore import Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


def native_cover_supported(owner) -> bool:
    app = QApplication.instance()
    supported = bool(sys.platform == 'win32' and app is not None and app.platformName() == 'windows'
                     and isinstance(owner, QWidget) and isValid(owner) and owner.isWindow())
    if not supported:
        return False
    handle = owner.windowHandle()  # Existing QWindow only; never call winId().
    return handle is None or handle.surfaceType().name == 'RasterSurface'


def existing_handle(widget) -> int:
    if not isinstance(widget, QWidget) or not isValid(widget):
        return 0
    if not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
        return 0
    return int(widget.internalWinId() or 0)


class _WindowsCoverApi:
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.IsWindow.argtypes = [W.HWND]
        self.user.IsWindowVisible.argtypes = [W.HWND]
        self.user.IsIconic.argtypes = [W.HWND]
        self.user.GetParent.argtypes = [W.HWND]
        self.user.GetParent.restype = W.HWND
        self.user.GetWindow.argtypes = [W.HWND, W.UINT]
        self.user.GetWindow.restype = W.HWND
        self.user.GetWindowLongPtrW.argtypes = [W.HWND, ctypes.c_int]
        self.user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
        self.user.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
        self.user.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
        self.user.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
        self.user.GetWindowRgnBox.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]

    def observe(self, child, root):
        if not self.user.IsWindow(child) or not self.user.IsWindow(root):
            raise RuntimeError('cover or root HWND has retired')
        child_pid, root_pid = W.DWORD(), W.DWORD()
        self.user.GetWindowThreadProcessId(child, ctypes.byref(child_pid))
        self.user.GetWindowThreadProcessId(root, ctypes.byref(root_pid))
        rect, client = W.RECT(), W.RECT()
        if not self.user.GetWindowRect(child, ctypes.byref(rect)) or not self.user.GetClientRect(root, ctypes.byref(client)):
            raise ctypes.WinError(ctypes.get_last_error())
        origin = W.POINT(client.left, client.top)
        if not self.user.ClientToScreen(root, ctypes.byref(origin)):
            raise ctypes.WinError(ctypes.get_last_error())
        top, order = int(self.user.GetWindow(root, 5) or 0), []  # GW_CHILD
        first_visible = 0
        while top and len(order) < 64:
            order.append(top)
            if not first_visible and self.user.IsWindowVisible(top):
                first_visible = top
            top = int(self.user.GetWindow(top, 2) or 0)  # GW_HWNDNEXT
        ctypes.set_last_error(0)
        box = W.RECT()
        region_kind = self.user.GetWindowRgnBox(child, ctypes.byref(box))
        region_error = ctypes.get_last_error()
        region_full = (region_kind == 0 and region_error == 0) or (region_kind == 2
            and box.left <= 0 and box.top <= 0
            and box.right >= rect.right - rect.left and box.bottom >= rect.bottom - rect.top)
        return dict(child_pid=child_pid.value, root_pid=root_pid.value,
            parent=int(self.user.GetParent(child) or 0),
            style=int(self.user.GetWindowLongPtrW(child, -16)) & 0xffffffff,
            ex_style=int(self.user.GetWindowLongPtrW(child, -20)) & 0xffffffff,
            root_ex_style=int(self.user.GetWindowLongPtrW(root, -20)) & 0xffffffff,
            child_visible=bool(self.user.IsWindowVisible(child)),
            root_visible=bool(self.user.IsWindowVisible(root)), root_minimized=bool(self.user.IsIconic(root)),
            child_rect=[rect.left, rect.top, rect.right, rect.bottom],
            root_client_rect=[origin.x, origin.y, origin.x + client.right - client.left,
                              origin.y + client.bottom - client.top],
            first_visible_root_child=first_visible, root_children=order,
            root_children_truncated=bool(top), native_region_full=region_full,
            native_region_kind=region_kind, native_region_error=region_error)


_API = None


def native_cover_state(view, owner, *, requested, supported, complete_paint,
                       opaque_background, _api=None):
    """Inspect existing resources only; verified means Qt submission, not scanout."""
    result = dict(requested=bool(requested), supported=bool(supported), verified=False,
                  measurement='Qt raster submission; not physical presentation', reasons=[])
    if not requested or not supported:
        result['reasons'] = ['not requested' if not requested else 'native child cover unsupported']
        return result
    if not isValid(view) or not isValid(owner):
        result['reasons'] = ['cover or owner deleted']
        return result
    child, root = existing_handle(view), existing_handle(owner)
    result.update(hwnd=child, root_hwnd=root, logical_rect=list(view.geometry().getRect()),
                  root_logical_rect=list(owner.rect().getRect()),
                  logical_visible=view.isVisible(), complete_paint=bool(complete_paint),
                  opaque_background=bool(opaque_background))
    if not child or not root:
        result['reasons'] = ['native handles not created']
        return result
    handle = view.windowHandle()
    result['alpha_buffer_size'] = handle.format().alphaBufferSize() if handle is not None else None
    result['surface_type'] = handle.surfaceType().name if handle is not None else None
    mask = view.mask()
    result['qt_region_full'] = mask.isEmpty() or QRegion(view.rect()).subtracted(mask).isEmpty()
    try:
        global _API
        if _api is None:
            if _API is None:
                _API = _WindowsCoverApi()
            _api = _API
        native = _api.observe(child, root)
        result.update(native)
    except Exception as error:
        result['reasons'] = ['native observation failed: ' + str(error)]
        return result
    a, b = native['child_rect'], native['root_client_rect']
    checks = {
        'owned root child': (view.parentWidget() is owner and view.window() is owner and not view.isWindow()
            and native['parent'] == root and native['child_pid'] == native['root_pid'] == os.getpid()),
        'layered child style': (bool(native['style'] & 0x40000000) and not native['style'] & 0x80000000
            and bool(native['ex_style'] & 0x80000) and not native['ex_style'] & 8),
        'nonlayered root': not native['root_ex_style'] & 0x80000,
        'native raster alpha': result['alpha_buffer_size'] == 8 and result['surface_type'] == 'RasterSurface',
        'full root geometry': (view.geometry() == owner.rect() and not owner.rect().isEmpty()
            and a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]),
        'full region': result['qt_region_full'] and native['native_region_full'],
        'top root child': native['first_visible_root_child'] == child and not native['root_children_truncated'],
        'visible owner and cover': result['logical_visible'] and native['child_visible']
            and native['root_visible'] and not native['root_minimized'],
        'complete opaque Qt paint': bool(complete_paint and opaque_background),
    }
    result['checks'] = checks
    result['reasons'] = [name for name, passed in checks.items() if not passed]
    result['verified'] = all(checks.values())
    return result


class InputHostLease:
    """Remember explicit enabled state once, including across loading generations."""
    def __init__(self, host=None):
        self._host = weakref.ref(host) if host is not None else None
        self._restore = None

    @property
    def held(self):
        return self._restore is not None

    def acquire(self, owner, cover):
        if self._host is None:
            return True
        host = self._host()
        if (host is None or not isValid(host) or host.window() is not owner
                or host is cover or host.isAncestorOf(cover)):
            return False
        if self._restore is None:
            # Preserve the host's own setting rather than an ancestor's modal
            # disabled state. False is a real original value, not a sentinel.
            self._restore = (weakref.ref(host), not host.testAttribute(Qt.WidgetAttribute.WA_ForceDisabled))
        host.setEnabled(False)
        return True

    def release(self, *_):
        restore, self._restore = self._restore, None
        if restore is not None:
            host = restore[0]()
            if host is not None and isValid(host):
                host.setEnabled(restore[1])

