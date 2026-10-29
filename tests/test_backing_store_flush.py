"""Guard shared Raster flush submission without opening any native window."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, QThread, Qt
from PySide6.QtGui import QSurface, QWindow

from twobyteasr.design import backing_store_flush as flush


class Window:
    valid = True

    def __init__(self, parent=None):
        self.parent_window = parent
        self.surface = QSurface.SurfaceType.RasterSurface

    def isAncestorOf(self, other, mode):
        assert mode == QWindow.AncestorMode.ExcludeTransients
        return other.parent_window is self

    def surfaceType(self):
        return self.surface


class Store:
    valid = True

    def __init__(self, window):
        self.owner = window
        self.calls = []
        self.failure = None

    def window(self):
        return self.owner

    def flush(self, region, window, offset):
        if self.failure:
            raise self.failure
        self.calls.append((region, window, offset))

    def paintDevice(self):
        pytest.fail("must not acquire a paint device")

    def beginPaint(self, *_args):
        pytest.fail("must not repaint")

    def resize(self, *_args):
        pytest.fail("must not create/resize backing storage")


class Widget:
    valid = True

    def __init__(self, hwnd, root=None):
        self.root = root or self
        self.hwnd = hwnd
        self.created = True
        self.qwindow = Window(root.qwindow if root else None)
        self.store = root.store if root else Store(self.qwindow)
        self.thread_value = QThread.currentThread()
        self.rectangle = QRect(0, 0, 120, 80)
        self.offset = QPoint(17, 29)

    def isWindow(self):
        return self.root is self

    def window(self):
        return self.root

    def thread(self):
        return self.thread_value

    def testAttribute(self, attribute):
        assert attribute == Qt.WidgetAttribute.WA_WState_Created
        return self.created

    def internalWinId(self):
        return self.hwnd

    def windowHandle(self):
        return self.qwindow

    def backingStore(self):
        return self.store

    def rect(self):
        return self.rectangle

    def mapTo(self, root, point):
        assert root is self.root and point == QPoint()
        return self.offset

    def winId(self):
        pytest.fail("must not create a native window")

    def devicePixelRatioF(self):
        pytest.fail("QBackingStore owns DPR conversion")

    def repaint(self):
        pytest.fail("fallback belongs to caller")

    def resize(self, *_args):
        pytest.fail("must not relayout or resize")


@pytest.fixture
def widgets(monkeypatch):
    monkeypatch.setattr(flush, "isValid", lambda obj: bool(getattr(obj, "valid", False)))
    root = Widget(11)
    page = Widget(22, root)
    return root, page


def test_submits_existing_store_in_logical_child_coordinates(widgets):
    root, page = widgets
    result = flush.flush_existing_widget_backing_store(root, page)
    assert result["status"] == "submitted"
    assert result["measurement"] == "submission_only_not_presentation"
    assert "presented" not in result
    assert result["region_logical"] == [0, 0, 120, 80]
    assert result["offset_logical"] == [17, 29]
    assert len(root.store.calls) == 1
    region, target, offset = root.store.calls[0]
    assert region.boundingRect() == QRect(0, 0, 120, 80)
    assert target is page.qwindow and offset == QPoint(17, 29)


@pytest.mark.parametrize("which", [0, 1])
def test_retired_widgets_are_rejected_before_any_widget_call(widgets, which):
    root, page = widgets
    retired = widgets[which]
    retired.valid = False
    retired.isWindow = lambda: pytest.fail("retired QWidget access")
    result = flush.flush_existing_widget_backing_store(root, page)
    assert result["status"] == "unavailable" and result["reason"] == "invalid_widget"
    assert not root.store.calls


@pytest.mark.parametrize("missing", ["uncreated_root", "uncreated_page", "root_hwnd", "page_hwnd", "root_qwindow", "page_qwindow", "store"])
def test_missing_native_resources_are_not_created(widgets, missing):
    root, page = widgets
    store = root.store
    if missing == "uncreated_root":
        root.created = False
    elif missing == "uncreated_page":
        page.created = False
    elif missing == "root_hwnd":
        root.hwnd = 0
    elif missing == "page_hwnd":
        page.hwnd = 0
    elif missing == "root_qwindow":
        root.qwindow = None
    elif missing == "page_qwindow":
        page.qwindow = None
    else:
        root.store = page.store = None
    result = flush.flush_existing_widget_backing_store(root, page)
    assert result["status"] == "unavailable"
    assert not store.calls


@pytest.mark.parametrize("mismatch", ["widget_root", "qwindow_root", "page_store", "store_owner", "root_surface", "page_surface"])
def test_other_roots_and_non_raster_surfaces_never_receive_pixels(widgets, mismatch):
    root, page = widgets
    original_store = root.store
    if mismatch == "widget_root":
        page.root = Widget(33)
    elif mismatch == "qwindow_root":
        page.qwindow.parent_window = Window()
    elif mismatch == "page_store":
        page.store = Store(root.qwindow)
    elif mismatch == "store_owner":
        root.store.owner = Window()
    elif mismatch == "root_surface":
        root.qwindow.surface = QSurface.SurfaceType.OpenGLSurface
    else:
        page.qwindow.surface = QSurface.SurfaceType.OpenGLSurface
    result = flush.flush_existing_widget_backing_store(root, page)
    assert result["status"] == "unsupported"
    assert not original_store.calls


def test_wrong_thread_and_empty_region_do_not_submit(widgets):
    root, page = widgets
    page.thread_value = object()
    result = flush.flush_existing_widget_backing_store(root, page)
    assert result["reason"] == "wrong_thread"
    page.thread_value = root.thread_value
    page.rectangle = QRect()
    result = flush.flush_existing_widget_backing_store(root, page)
    assert result["reason"] == "empty_region"
    assert not root.store.calls


@pytest.mark.parametrize("change", ["hwnd", "qwindow", "store", "retire"])
def test_resource_retirement_or_replacement_before_submission_is_rejected(widgets, change):
    root, page = widgets
    original_store = root.store
    def changed_map(_root, _point):
        if change == "hwnd":
            page.hwnd = 99
        elif change == "qwindow":
            page.qwindow = Window(root.qwindow)
        elif change == "store":
            page.store = Store(root.qwindow)
        else:
            page.valid = False
        return page.offset
    page.mapTo = changed_map
    result = flush.flush_existing_widget_backing_store(root, page)
    assert result["status"] == "unavailable"
    assert result["reason"] in {"retired_before_flush", "identity_changed_before_flush"}
    assert not original_store.calls


def test_void_flush_exception_is_explicit_and_never_calls_repaint(widgets):
    root, page = widgets
    root.store.failure = RuntimeError("controlled flush failure")
    result = flush.flush_existing_widget_backing_store(root, page)
    assert result["status"] == "error" and result["phase"] == "flush"
    assert result["error"] == "RuntimeError: controlled flush failure"
    assert not root.store.calls
