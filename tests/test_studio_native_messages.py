"""Native mpv keyboard messages must preserve shortcut/focus ownership."""
import ctypes
import os
from types import SimpleNamespace

import pytest

from twobyteasr.studio.studio_shortcuts import _StudioNativeKeyFilter, _WindowsMessage


pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Win32 message ABI')


def test_native_key_routes_once_and_leaves_editing_and_repeat_alone(monkeypatch):
    sent = []
    page = SimpleNamespace(isVisible=lambda: True, _editing_has_focus=lambda: False,
        window=lambda: SimpleNamespace(winId=lambda: 123),
        _dispatch_shortcut_sequence=lambda value: sent.append(value) or True)
    user32 = SimpleNamespace(IsChild=lambda *args: True, GetKeyState=lambda key: 0)
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user32))
    filter_ = _StudioNativeKeyFilter(page)
    msg = _WindowsMessage(hwnd=123, message=0x0100, wParam=0x47)
    assert filter_.nativeEventFilter(b'windows_generic_MSG', ctypes.addressof(msg)) == (True, 0)
    assert sent == ['G']
    msg.lParam = 1 << 30
    assert filter_.nativeEventFilter(b'windows_generic_MSG', ctypes.addressof(msg)) == (False, 0)
    msg.lParam = 0
    page._canvas_editor = object()
    assert filter_.nativeEventFilter(b'windows_generic_MSG', ctypes.addressof(msg)) == (False, 0)
    assert sent == ['G']


def test_native_paints_do_not_accumulate_ctypes_pointer_types():
    filter_ = _StudioNativeKeyFilter(None)
    msg = _WindowsMessage(message=0x000F)
    initial = len(ctypes._pointer_type_cache)
    for _ in range(10000):
        assert filter_.nativeEventFilter(b'windows_generic_MSG', ctypes.addressof(msg)) == (False, 0)
    assert len(ctypes._pointer_type_cache) == initial
