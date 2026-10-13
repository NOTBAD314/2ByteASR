"""Interface zoom for the main pages and dialogs (2026-10-10).

Ctrl+wheel and Ctrl+= / Ctrl+- / Ctrl+0 change one remembered factor shared
by the home, settings, result and proofreading pages and by dialogs. A zoom
step scales stylesheet geometry (font sizes, paddings, radii, minimum sizes),
sizes fixed in code, layout margins and spacing, icon sizes and fonts set in
code; painted widgets read ``zoom_factor()`` or implement
``apply_ui_zoom(factor)``. Nothing is rebuilt: widgets keep their state,
scroll position, selection and focus.

Subtitle Studio keeps its own layout: Ctrl+wheel over it is left to Studio
(the timeline zooms time; Ctrl+drag trimming is untouched). Graphics
canvases (cover editor) keep their own wheel zoom. This is the reading size
of the application only — video subtitle styles and exports never read it.
"""

from __future__ import annotations

import ctypes
import os
import re

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QDialog, QGraphicsView, QLabel,
                               QScrollBar, QSplitterHandle, QWidget)

SETTINGS_KEY = "ui/zoom_percent"
STEPS = (80, 90, 100, 110, 120, 135, 150, 175, 200)
DEFAULT_PERCENT = 100
_QWIDGETSIZE_MAX = (1 << 24) - 1
_PX = re.compile(r"(?<![\w.#-])(\d+(?:\.\d+)?)px")
_state = {"percent": None, "touched": False}
_WHEEL, _CTRL = QEvent.Type.Wheel, Qt.KeyboardModifier.ControlModifier
_SHEET_CACHE: dict[tuple[str, int], str] = {}


def _settings():
    from PySide6.QtCore import QSettings
    return QSettings("2ByteASR", "2ByteASR")


def zoom_percent() -> int:
    if _state["percent"] is None:
        try:
            value = int(float(_settings().value(SETTINGS_KEY, DEFAULT_PERCENT) or DEFAULT_PERCENT))
        except (TypeError, ValueError):
            value = DEFAULT_PERCENT
        _state["percent"] = min(STEPS[-1], max(STEPS[0], value))
    return _state["percent"]


def zoom_factor() -> float:
    return zoom_percent() / 100.0


def px(value: float) -> int:
    """``value`` logical pixels at the current zoom (never below 1)."""
    return max(1, round(float(value) * zoom_factor()))


def logical(value: float) -> int:
    """A measured size in 100% pixels. Responsive breakpoints compare this,
    so a zoomed page picks the layout of a correspondingly smaller window
    (as a browser's zoom narrows the page) instead of overflowing."""
    return round(float(value) / zoom_factor())


def _scale_px(value: float, factor: float) -> str:
    # Hairlines (borders, 1–2 px gaps) stay crisp; everything else scales.
    if value <= 2:
        return f"{value:g}px"
    return f"{max(1, round(value * factor))}px"


def scale_qss(sheet: str, factor: float | None = None) -> str:
    factor = zoom_factor() if factor is None else float(factor)
    if not sheet or abs(factor - 1.0) < 1e-6:
        return sheet
    key = (sheet, round(factor * 100))
    cached = _SHEET_CACHE.get(key)
    if cached is None:
        cached = _PX.sub(lambda match: _scale_px(float(match.group(1)), factor), sheet)
        if len(_SHEET_CACHE) > 256:
            _SHEET_CACHE.clear()
        _SHEET_CACHE[key] = cached
    return cached


def set_zoom_percent(percent: int) -> int:
    value = min(STEPS[-1], max(STEPS[0], int(percent)))
    _state["percent"] = value
    _state["touched"] = True
    settings = _settings()
    settings.setValue(SETTINGS_KEY, value)
    settings.sync()
    return value


def step(direction: int) -> int:
    current = zoom_percent()
    if direction > 0:
        larger = [value for value in STEPS if value > current]
        return larger[0] if larger else STEPS[-1]
    smaller = [value for value in STEPS if value < current]
    return smaller[-1] if smaller else STEPS[0]


# ---------------------------------------------------------------- applying
def _excluded(widget: QWidget) -> bool:
    if widget.objectName() == "subtitleStudio" or widget.property("uiZoomExclude"):
        return True
    return isinstance(widget, (QScrollBar, QSplitterHandle))


def _scaled_size(value: int, factor: float, *, maximum: bool) -> int:
    if maximum and value >= _QWIDGETSIZE_MAX:
        return value
    if value <= 0:
        return value
    return min(_QWIDGETSIZE_MAX, max(1, round(value * factor)))


def _apply_sheet(widget: QWidget, factor: float) -> None:
    if hasattr(widget, "_theme_root_sheet"):
        return  # window theme sheets are scaled by theme_manager.apply_root
    sheet = widget.styleSheet()
    if not sheet and widget.property("_uiZoomSheetLast") in (None, ""):
        return
    base = widget.property("_uiZoomSheetBase")
    if sheet != widget.property("_uiZoomSheetLast"):
        base = sheet  # set (or replaced) by code since the last zoom step
    scaled = scale_qss(base or "", factor)
    widget.setProperty("_uiZoomSheetBase", base or "")
    widget.setProperty("_uiZoomSheetLast", scaled)
    if scaled != sheet:
        widget.setStyleSheet(scaled)


# One entry per dimension: (getter index, property, Qt's stylesheet marker).
_DIMENSIONS = (("min_w", "_q_stylesheet_minw"), ("min_h", "_q_stylesheet_minh"),
               ("max_w", "_q_stylesheet_maxw"), ("max_h", "_q_stylesheet_maxh"))


def _current_sizes(widget):
    minimum, maximum = widget.minimumSize(), widget.maximumSize()
    return {"min_w": minimum.width(), "min_h": minimum.height(), "max_w": maximum.width(), "max_h": maximum.height()}


def _write_sizes(widget, values, current):
    if values["min_w"] != current["min_w"] or values["min_h"] != current["min_h"]:
        widget.setMinimumSize(values["min_w"], values["min_h"])
    if values["max_w"] != current["max_w"] or values["max_h"] != current["max_h"]:
        widget.setMaximumSize(values["max_w"], values["max_h"])


def set_size(widget: QWidget, **logical: int) -> None:
    """Sizes set by code in logical px (min_w/min_h/max_w/max_h; fixed_w and
    fixed_h set both). The current zoom is applied now and on every later
    zoom step; at 100% this is exactly the plain Qt setter."""
    for key, axis in (("fixed_w", "w"), ("fixed_h", "h")):
        if key in logical:
            value = logical.pop(key)
            logical[f"min_{axis}"] = logical[f"max_{axis}"] = value
    factor = zoom_factor()
    current = _current_sizes(widget)
    values = dict(current)
    for name, value in logical.items():
        target = _scaled_size(int(value), factor, maximum=name.startswith("max"))
        widget.setProperty(f"_uiZoom_{name}", [int(value), target])
        values[name] = target
    _write_sizes(widget, values, current)


def set_sheet(widget: QWidget, sheet: str) -> None:
    """A widget's own style sheet written in logical px, applied at the
    current zoom right away. The first zoom pass over a lazily built page then
    finds nothing to change, instead of replacing (and re-polishing the whole
    subtree under) a large page sheet a second time (2026-10-12)."""
    factor = zoom_factor()
    if abs(factor - 1.0) < 1e-6 and not _state["touched"]:
        widget.setStyleSheet(sheet)
        return
    scaled = scale_qss(sheet, factor)
    widget.setProperty("_uiZoomSheetBase", sheet)
    widget.setProperty("_uiZoomSheetLast", scaled)
    widget.setStyleSheet(scaled)


def set_layout(layout, margins=None, spacing=None) -> None:
    """Layout margins/spacing set by code in logical px (see set_size)."""
    current_margins = layout.contentsMargins()
    base = layout.property("_uiZoomLayout")
    values = list(base) if base is not None else [current_margins.left(), current_margins.top(),
                                                   current_margins.right(), current_margins.bottom(), layout.spacing()]
    if margins is not None:
        values[:4] = [int(value) for value in margins]
    if spacing is not None:
        values[4] = int(spacing)
    factor = zoom_factor()
    target = [value if value <= 0 else max(1, round(value * factor)) for value in values]
    layout.setProperty("_uiZoomLayout", values)
    layout.setProperty("_uiZoomLayoutLast", target)
    layout.setContentsMargins(*target[:4])
    if values[4] >= 0:
        layout.setSpacing(target[4])


def _apply_sizes(widget: QWidget, factor: float) -> None:
    if widget.property("uiZoomOwnSize"):
        return  # the widget sizes itself from zoom_factor()
    current = _current_sizes(widget)
    values = dict(current)
    for name, qss_marker in _DIMENSIONS:
        if widget.property(qss_marker):
            continue  # set by the (already scaled) stylesheet
        value = current[name]
        record = widget.property(f"_uiZoom_{name}")
        if record is None:
            if value <= 0 or value >= _QWIDGETSIZE_MAX:
                continue
            base = value  # first sight: what the code set at construction
        else:
            base, last = int(record[0]), int(record[1])
            if value != last:
                base = value  # set again by code since the last zoom step
        target = _scaled_size(base, factor, maximum=name.startswith("max"))
        widget.setProperty(f"_uiZoom_{name}", [base, target])
        values[name] = target
    _write_sizes(widget, values, current)


def _apply_icon(widget: QWidget, factor: float) -> None:
    if not isinstance(widget, (QAbstractButton, QAbstractItemView)):
        return
    size = widget.iconSize()
    current = (size.width(), size.height())
    base, last = widget.property("_uiZoomIcon"), widget.property("_uiZoomIconLast")
    if base is None or last is None or tuple(last) != current:
        base = current
    target = (max(1, round(base[0] * factor)), max(1, round(base[1] * factor)))
    widget.setProperty("_uiZoomIcon", list(base))
    widget.setProperty("_uiZoomIconLast", list(target))
    if target != current:
        widget.setIconSize(QSize(*target))


def _apply_font(widget: QWidget, factor: float) -> None:
    if not widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
        return
    font = widget.font()
    pixel = font.pixelSize()
    current = pixel if pixel > 0 else font.pointSizeF()
    base, last = widget.property("_uiZoomFont"), widget.property("_uiZoomFontLast")
    if base is None or last is None or abs(float(last) - float(current)) > 1e-3:
        base = current
    target = max(1, round(base * factor)) if pixel > 0 else max(1.0, float(base) * factor)
    widget.setProperty("_uiZoomFont", float(base))
    widget.setProperty("_uiZoomFontLast", float(target))
    if abs(float(target) - float(current)) > 1e-3:
        if pixel > 0:
            font.setPixelSize(int(target))
        else:
            font.setPointSizeF(float(target))
        widget.setFont(font)


def _apply_layout(layout, factor: float) -> None:
    if layout is None:
        return
    margins = layout.contentsMargins()
    current = (margins.left(), margins.top(), margins.right(), margins.bottom(), layout.spacing())
    base, last = layout.property("_uiZoomLayout"), layout.property("_uiZoomLayoutLast")
    if base is None or last is None or tuple(last) != current:
        base = current
    target = tuple(value if value <= 0 else max(1, round(value * factor)) for value in base)
    layout.setProperty("_uiZoomLayout", list(base))
    layout.setProperty("_uiZoomLayoutLast", list(target))
    if target != current:
        layout.setContentsMargins(*target[:4])
        if base[4] >= 0:
            layout.setSpacing(target[4])
    for index in range(layout.count()):
        item = layout.itemAt(index)
        child = item.layout() if item is not None else None
        if child is not None:
            _apply_layout(child, factor)


def protect_studio(page: QWidget | None, factor: float | None = None) -> None:
    """Keep Subtitle Studio at its own size while the rest is zoomed.

    The window sheet (scaled) also reaches Studio's widgets. A widget's own
    sheet always wins over inherited ones, so Studio's sheet is prefixed
    with the unscaled window sheet whenever the zoom is not 100%."""
    if page is None:
        return
    factor = zoom_factor() if factor is None else float(factor)
    app = QApplication.instance()
    window_sheet = getattr(app, "_theme_window_qss", "") if app is not None else ""
    current = page.styleSheet()
    base = page.property("_uiZoomStudioBase")
    if base is None or current != page.property("_uiZoomStudioLast"):
        base = current  # Studio or the theme manager set a new sheet
    target = (window_sheet + base) if abs(factor - 1.0) > 1e-6 and window_sheet else base
    page.setProperty("_uiZoomStudioBase", base)
    page.setProperty("_uiZoomStudioLast", target)
    if target != current:
        page.setStyleSheet(target)


def _fit_dialog(dialog: QWidget, factor: float) -> None:
    """A dialog grows with the zoom from its own 100% size, within the screen."""
    current = (dialog.width(), dialog.height())
    record = dialog.property("_uiZoomWindow")
    if record is None:
        base = (round(current[0] / factor), round(current[1] / factor)) if dialog.property("_uiZoomShownAt") else current
    else:
        base, last = tuple(record[:2]), tuple(record[2:])
        if current != last:
            base = (round(current[0] / factor), round(current[1] / factor))  # resized by the user or by code
    screen = dialog.screen() or QApplication.primaryScreen()
    area = screen.availableGeometry() if screen is not None else None
    target = (round(base[0] * factor), round(base[1] * factor))
    if area is not None:
        target = (min(target[0], int(area.width() * 0.92)), min(target[1], int(area.height() * 0.92)))
    target = (max(target[0], dialog.minimumWidth()), max(target[1], dialog.minimumHeight()))
    dialog.setProperty("_uiZoomWindow", [base[0], base[1], target[0], target[1]])
    if target != current:
        dialog.resize(*target)
        parent = dialog.parentWidget()
        anchor = parent.window().frameGeometry() if parent is not None else (area if area is not None else None)
        if anchor is not None:
            frame = dialog.frameGeometry()
            frame.moveCenter(anchor.center())
            if area is not None:
                frame.moveLeft(max(area.left(), min(frame.left(), area.right() - frame.width())))
                frame.moveTop(max(area.top(), min(frame.top(), area.bottom() - frame.height())))
            dialog.move(frame.topLeft())


def apply_to(root: QWidget | None, factor: float | None = None) -> int:
    """Scale ``root``'s subtree to ``factor``; returns widgets visited."""
    if root is None:
        return 0
    factor = zoom_factor() if factor is None else float(factor)
    if abs(factor - 1.0) < 1e-6 and not _state["touched"] and root.property("_uiZoomApplied") is None:
        return 0  # nothing was ever scaled: leave startup alone
    root.setProperty("_uiZoomApplied", round(factor * 100))
    visited = 0
    if isinstance(root, QDialog) and root.isWindow():
        _fit_dialog(root, factor)
    stack = [root]
    while stack:
        widget = stack.pop()
        if widget.objectName() == "subtitleStudio":
            protect_studio(widget, factor)
            continue
        if _excluded(widget):
            continue
        visited += 1
        _apply_sheet(widget, factor)
        if not widget.isWindow():
            _apply_sizes(widget, factor)
        _apply_icon(widget, factor)
        _apply_font(widget, factor)
        _apply_layout(widget.layout(), factor)
        if type(widget).__module__.startswith("twobyteasr"):
            widget.updateGeometry()  # painted widgets measure from zoomed fonts
        hook = getattr(widget, "apply_ui_zoom", None)
        if callable(hook):
            try:
                hook(factor)
            except Exception:
                pass
        stack.extend(widget.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly))
    return visited


def apply_to_changed(root: QWidget | None, factor: float | None = None) -> int:
    """``apply_to`` for a page being switched to, skipped when nothing changed.

    A page already scaled at this zoom whose widget count is the same as after
    its last pass keeps its state; widgets added since (lazily built content)
    or a zoom step trigger a full pass. Window resizes re-run ``apply_to`` on
    the current page for responsive code that re-sets sizes (2026-10-12).
    """
    if root is None:
        return 0
    factor = zoom_factor() if factor is None else float(factor)
    if abs(factor - 1.0) < 1e-6 and not _state["touched"] and root.property("_uiZoomApplied") is None:
        return 0
    count = len(root.findChildren(QWidget))
    if root.property("_uiZoomApplied") == round(factor * 100) and root.property("_uiZoomCount") == count:
        return 0
    visited = apply_to(root, factor)
    root.setProperty("_uiZoomCount", len(root.findChildren(QWidget)))
    return visited


# --------------------------------------------------------------- controller
def window_shown(window: QWidget) -> None:
    """A top-level window (dialog, menu, popup) was shown: give it the zoom.

    Called from the theme manager's existing Show hook, so the zoom adds no
    Python call to every other Qt event."""
    if zoom_percent() == DEFAULT_PERCENT and not _state["touched"]:
        return
    controller = getattr(QApplication.instance(), "_ui_zoom_controller", None)
    if controller is not None and window is controller._toast:
        return
    apply_to(window)


def _zoomable(widget) -> bool:
    if not isinstance(widget, QWidget):
        return False
    current = widget
    while current is not None:
        if current.objectName() == "subtitleStudio" or current.property("ownsCtrlWheel"):
            return False  # Studio: the timeline zooms time; Ctrl+drag trims
        if isinstance(current, QGraphicsView):
            return False  # canvases zoom their own content
        current = current.parentWidget()
    return True


if os.name == "nt":
    from ctypes import wintypes as _wt

    class _MSG(ctypes.Structure):
        _fields_ = [("hwnd", _wt.HWND), ("message", _wt.UINT), ("wParam", _wt.WPARAM), ("lParam", _wt.LPARAM),
                    ("time", _wt.DWORD), ("pt", _wt.POINT)]


def _widget_at_native_point(hwnd, lparam):
    """The widget under a WM_MOUSEWHEEL point (screen pixels in lParam)."""
    from ctypes import wintypes
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    root = ctypes.windll.user32.GetAncestor(wintypes.HWND(hwnd), 2) if hwnd else 0  # GA_ROOT
    window = QWidget.find(int(root or hwnd)) if (root or hwnd) else None
    if window is None:
        return None
    window = window.window()
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(wintypes.HWND(int(window.winId())), ctypes.byref(rect)):
        return None
    ratio = window.devicePixelRatioF() or 1.0
    frame = window.frameGeometry()
    from PySide6.QtCore import QPoint
    global_point = QPoint(frame.x() + round((x - rect.left) / ratio), frame.y() + round((y - rect.top) / ratio))
    local = window.mapFromGlobal(global_point)
    return window.childAt(local) or window


class _NativeWheel(QAbstractNativeEventFilter):
    """Ctrl+wheel from the Windows message itself (WM_MOUSEWHEEL only).

    An application event filter would run Python for every Qt event in the
    whole app; this sees only native messages and returns at once for all
    but a Ctrl+wheel."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller

    def nativeEventFilter(self, event_type, message):
        if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except (TypeError, ValueError):
            return False, 0
        # WM_MOUSEWHEEL with MK_CONTROL; not with Shift or a mouse button held.
        if msg.message != 0x020A or not (msg.wParam & 0x0008) or msg.wParam & 0x0007:
            return False, 0
        target = _widget_at_native_point(int(msg.hwnd or 0), msg.lParam)
        if target is None or not _zoomable(target):
            return False, 0
        delta = ctypes.c_short((msg.wParam >> 16) & 0xFFFF).value
        self.controller.wheel(delta)
        return True, 0


class ZoomController(QObject):
    """Ctrl+wheel / Ctrl+= / Ctrl+- / Ctrl+0 → one remembered interface zoom."""

    changed = Signal(int)

    def __init__(self, app: QApplication, window: QWidget):
        super().__init__(app)
        self._app, self._window = app, window
        self._pending = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._commit)
        self._toast = None
        self._wheel_rest = 0
        from PySide6.QtGui import QKeySequence, QShortcut
        self._shortcuts = []
        bindings = {}
        for action_id, keys, handler in (("app.zoom_reset", "Ctrl+0", lambda: self._key(DEFAULT_PERCENT)),
                                         ("app.zoom_in", "Ctrl+=", lambda: self._key(step(1))),
                                         ("app.zoom_in_alt", "Ctrl++", lambda: self._key(step(1))),
                                         ("app.zoom_out", "Ctrl+-", lambda: self._key(step(-1)))):
            shortcut = QShortcut(QKeySequence(keys), window)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)
            bindings[action_id] = shortcut
        try:
            from .shortcut_registry import keep_keys
            keep_keys(bindings)  # customizable in 应用设置 → 快捷键
        except Exception:
            pass  # defaults above stay in effect
        if os.name == "nt":
            self._native = _NativeWheel(self)
            app.installNativeEventFilter(self._native)
        else:
            app.installEventFilter(self)

    def _key(self, percent):
        target = QApplication.focusWidget() or QApplication.activeWindow() or self._window
        if _zoomable(target):
            self.request(percent)

    def wheel(self, delta):
        self._wheel_rest += delta
        if abs(self._wheel_rest) >= 60:
            self.request(step(1 if self._wheel_rest > 0 else -1))
            self._wheel_rest = 0

    def eventFilter(self, watched, event):
        # Non-Windows fallback only (Windows uses _NativeWheel).
        if event.type() == _WHEEL and event.modifiers() == _CTRL and _zoomable(watched):
            self.wheel(event.angleDelta().y() or event.pixelDelta().y())
            event.accept()
            return True
        return False

    # applying -------------------------------------------------------------
    def request(self, percent: int) -> None:
        self._pending = min(STEPS[-1], max(STEPS[0], int(percent)))
        self._show_toast(self._pending)
        self._timer.start()

    def _commit(self) -> None:
        percent, self._pending = self._pending, None
        if percent is None:
            return
        if percent == zoom_percent() and _state["touched"]:
            return
        set_zoom_percent(percent)
        self.apply_all()
        self.changed.emit(percent)
        # Responsive code reacts to the relayout this caused and may re-set
        # constant sizes; one more pass after it settles scales those too.
        QTimer.singleShot(180, self.apply_all)

    def apply_all(self) -> None:
        factor = zoom_factor()
        filter_ = getattr(self._app, "_theme_root_filter", None)
        for window in list(self._app.topLevelWidgets()):
            if not window.isVisible() or window is self._toast:
                continue
            if filter_ is not None and window.parentWidget() is None and window.objectName() != "subtitleStudio":
                filter_.apply_root(window)
            apply_to(window, factor)

    def _show_toast(self, percent: int) -> None:
        window = QApplication.activeWindow() or self._window
        if window is None:
            return
        if self._toast is None or self._toast.parent() is not window:
            if self._toast is not None:
                self._toast.deleteLater()
            self._toast = QLabel(window)
            self._toast.setObjectName("uiZoomToast")
            self._toast.setProperty("uiZoomExclude", True)
            self._toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._toast_timer = QTimer(self._toast)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._toast.hide)
        from .i18n import tr
        from .ui_theme import theme_definition
        from .theme_manager import theme_key
        theme = theme_definition(theme_key())
        self._toast.setStyleSheet(
            f"QLabel#uiZoomToast {{ background: {theme.surface_elevated}; color: {theme.text};"
            f" border: 1px solid {theme.border_strong}; border-radius: 10px; padding: 8px 16px;"
            f" font-size: 15px; font-weight: 600; }}")
        self._toast.setText(tr("界面大小 {percent}%  ·  Ctrl+0 恢复默认", percent=percent))
        self._toast.adjustSize()
        self._toast.move(max(0, (window.width() - self._toast.width()) // 2), 72)
        self._toast.raise_()
        self._toast.show()
        self._toast_timer.start(1400)


def reapply_all(app: QApplication | None = None) -> None:
    """After a theme change re-set pages' own sheets: scale them again."""
    app = app or QApplication.instance()
    if app is None or (zoom_percent() == DEFAULT_PERCENT and not _state["touched"]):
        return
    for window in list(app.topLevelWidgets()):
        if window.isVisible() or window.property("_uiZoomApplied") is not None:
            apply_to(window)


def install(app: QApplication, window: QWidget) -> ZoomController:
    controller = getattr(app, "_ui_zoom_controller", None)
    if controller is None:
        controller = ZoomController(app, window)
        app._ui_zoom_controller = controller
    if zoom_percent() != DEFAULT_PERCENT:
        apply_to(window)
    return controller
