"""Submit existing Raster QWidget backing-store pixels after native occlusion.

No window, backing store or paint device is created here. This is a bounded
submission of pixels the caller has already painted, not a presentation fence.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QThread, Qt
from PySide6.QtGui import QRegion, QSurface, QWindow
from shiboken6 import isValid


def _valid(value):
    if value is None:
        return False
    try:
        return isValid(value)
    except (RuntimeError, TypeError):
        return False


def flush_existing_widget_backing_store(root, page):
    """Flush one live native child's already-painted shared Raster store.

    ``region`` and ``offset`` stay in logical pixels, exactly as Qt's QWidget
    repaint manager supplies them. QBackingStore performs fractional-DPI
    conversion. A successful void ``flush`` call is reported as ``submitted``;
    callers choose their own fallback for every other status.
    """
    result = {"status": "unavailable", "method": "QBackingStore.flush",
              "measurement": "submission_only_not_presentation"}

    def reject(status, reason):
        return dict(result, status=status, reason=reason)

    phase = "ownership"
    try:
        if not _valid(root) or not _valid(page):
            return reject("unavailable", "invalid_widget")
        if root is page or not root.isWindow() or page.isWindow():
            return reject("unsupported", "native_child_required")
        if root.window() is not root or page.window() is not root:
            return reject("unsupported", "different_widget_root")
        if root.thread() != QThread.currentThread() or page.thread() != root.thread():
            return reject("unavailable", "wrong_thread")
        if not root.testAttribute(Qt.WidgetAttribute.WA_WState_Created) or not page.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return reject("unavailable", "native_window_not_created")
        root_id, page_id = int(root.internalWinId() or 0), int(page.internalWinId() or 0)
        if not root_id or not page_id or root_id == page_id:
            return reject("unavailable", "native_child_handle_missing")
        result.update(root_hwnd=root_id, target_hwnd=page_id)

        phase = "window_handles"
        root_window, page_window = root.windowHandle(), page.windowHandle()
        if not _valid(root_window) or not _valid(page_window) or root_window is page_window:
            return reject("unavailable", "qwindow_missing")
        if not root_window.isAncestorOf(page_window, QWindow.AncestorMode.ExcludeTransients):
            return reject("unsupported", "different_native_window_root")
        if (root_window.surfaceType() != QSurface.SurfaceType.RasterSurface
                or page_window.surfaceType() != QSurface.SurfaceType.RasterSurface):
            return reject("unsupported", "non_raster_surface")

        phase = "backing_store"
        root_store, page_store = root.backingStore(), page.backingStore()
        if not _valid(root_store) or not _valid(page_store):
            return reject("unavailable", "backing_store_missing")
        if root_store is not page_store or root_store.window() is not root_window:
            return reject("unsupported", "different_backing_store")
        rect, offset = page.rect(), page.mapTo(root, QPoint())
        if rect.isEmpty():
            return reject("unavailable", "empty_region")
        result.update(region_logical=list(rect.getRect()), offset_logical=[offset.x(), offset.y()])

        # Read-only guards immediately before submission. Never use winId(),
        # QWindow.create(), paintDevice(), resize() or a painting/layout API.
        phase = "revalidate"
        if not all(_valid(value) for value in (root, page, root_window, page_window, root_store)):
            return reject("unavailable", "retired_before_flush")
        if (int(root.internalWinId() or 0) != root_id or int(page.internalWinId() or 0) != page_id
                or page.window() is not root or root.windowHandle() is not root_window
                or page.windowHandle() is not page_window or root.backingStore() is not root_store
                or page.backingStore() is not root_store or root_store.window() is not root_window):
            return reject("unavailable", "identity_changed_before_flush")
        phase = "flush"
        started = time.perf_counter()
        root_store.flush(QRegion(rect), page_window, offset)
        result.update(status="submitted", duration_ms=(time.perf_counter() - started) * 1000)
        return result
    except Exception as error:
        return dict(result, status="error", phase=phase, error=f"{type(error).__name__}: {error}")
