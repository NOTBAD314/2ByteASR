"""Frameless window edge and corner hit-area regressions."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import subtitle_core as legacy  # noqa: E402
from twobyteasr.app.ui import MainWindow  # noqa: E402


def test_frameless_resize_uses_strict_logical_edge_bands():
    app = QApplication.instance() or QApplication([])
    window = MainWindow([], legacy, object(), None)
    window.resize(1200, 760)
    window.show()
    app.processEvents()

    assert window._resize_border == 8
    assert window._resize_corner == 12
    width = window.width()
    height = window.height()

    assert window._resize_edge_at(QPoint(0, 0)) == "tl"
    assert window._resize_edge_at(QPoint(12, 12)) == "tl"
    assert window._resize_edge_at(QPoint(width - 1, 1)) == "tr"
    assert window._resize_edge_at(QPoint(1, height - 1)) == "bl"
    assert window._resize_edge_at(QPoint(width - 1, height - 1)) == "br"
    assert window._resize_edge_at(QPoint(5, 100)) == "left"
    assert window._resize_edge_at(QPoint(width - 5, 100)) == "right"
    assert window._resize_edge_at(QPoint(100, 5)) == "top"
    assert window._resize_edge_at(QPoint(100, height - 5)) == "bottom"
    assert window._resize_edge_at(QPoint(13, 13)) is None
    assert window._resize_edge_at(QPoint(9, 100)) is None
    assert window._resize_edge_at(QPoint(100, 9)) is None
    assert window._resize_edge_at(QPoint(width // 2, height // 2)) is None
    assert window._resize_edge_at(QPoint(-1, height // 2)) is None
    assert window._resize_edge_at(QPoint(width, height // 2)) is None
    assert window._resize_edge_at(QPoint(width // 2, -1)) is None
    assert window._resize_edge_at(QPoint(width // 2, height)) is None

    window.close()
    window.deleteLater()


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
def test_native_resize_hit_test_keeps_each_dpi_in_physical_coordinates(scale):
    left, top = -240, 160
    width = round(1200 * scale)
    height = round(760 * scale)
    rect = (left, top, left + width, top + height)
    border = round(8 * scale)
    corner = round(12 * scale)

    hit = MainWindow._native_resize_edge_at
    assert hit(left, top, rect, scale) == "tl"
    assert hit(left + width - 1, top, rect, scale) == "tr"
    assert hit(left, top + height - 1, rect, scale) == "bl"
    assert hit(left + width - 1, top + height - 1, rect, scale) == "br"
    assert hit(left + border, top + height // 2, rect, scale) == "left"
    assert hit(left + width - border, top + height // 2, rect, scale) == "right"
    assert hit(left + width // 2, top + border, rect, scale) == "top"
    assert hit(left + width // 2, top + height - border, rect, scale) == "bottom"

    assert hit(left + width // 2, top + height // 2, rect, scale) is None
    assert hit(left + corner + 1, top + corner + 1, rect, scale) is None
    assert hit(left - 1, top + height // 2, rect, scale) is None
    assert hit(left + width, top + height // 2, rect, scale) is None
    assert hit(left + width // 2, top - 1, rect, scale) is None
    assert hit(left + width // 2, top + height, rect, scale) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows native message layout")
def test_windows_native_event_reads_the_msg_hwnd_field(monkeypatch):
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace

    app = QApplication.instance() or QApplication([])
    window = MainWindow([], legacy, object(), None)

    class FakeUser32:
        @staticmethod
        def GetWindowRect(hwnd, rect_pointer):
            assert hwnd == 123
            rect = ctypes.cast(
                rect_pointer, ctypes.POINTER(wintypes.RECT)
            ).contents
            rect.left, rect.top, rect.right, rect.bottom = 100, 200, 2410, 1740
            return 1

        @staticmethod
        def GetDpiForWindow(hwnd):
            assert hwnd == 123
            return 168

        @staticmethod
        def IsZoomed(hwnd):
            return 0

    from twobyteasr.app import window_constraints
    monkeypatch.setattr(window_constraints, '_user32', lambda: FakeUser32())
    msg = wintypes.MSG()
    msg.hWnd = 123
    msg.message = 0x0084  # WM_NCHITTEST
    screen_x, screen_y = 101, 970
    msg.lParam = ((screen_y & 0xFFFF) << 16) | (screen_x & 0xFFFF)

    assert window.nativeEvent(
        b"windows_generic_MSG", ctypes.addressof(msg)
    ) == (True, 10)  # HTLEFT

    window.close()
    window.deleteLater()


@pytest.mark.parametrize('scale',[1.0,1.25,1.5,1.75])
def test_native_work_area_is_physical_and_only_minimum_size_is_scaled(scale):
    from twobyteasr.app.window_native_frame import MINMAXINFO,fill_minmax
    info=MINMAXINFO()
    fill_minmax(info,(-1440,-521,0,2869),(-1440,-521,0,2919),(700,500),scale)
    assert (info.ptMaxPosition.x,info.ptMaxPosition.y)==(0,0)
    assert (info.ptMaxSize.x,info.ptMaxSize.y)==(1440,3390)
    assert (info.ptMinTrackSize.x,info.ptMinTrackSize.y)==(min(1440,round(700*scale)),round(500*scale))


def test_true_fullscreen_cannot_start_manual_edge_resize():
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    app=QApplication.instance() or QApplication([])
    window=MainWindow([],legacy,object(),None)
    window.showFullScreen()
    app.processEvents()
    geometry=window.geometry()
    QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,QPoint(1,1))
    QTest.mouseMove(window,QPoint(40,40))
    QTest.mouseRelease(window,Qt.LeftButton)
    assert not getattr(window,'_resize_dragging',False) and window.geometry()==geometry and window.isFullScreen()
    window.close()
    window.deleteLater()
