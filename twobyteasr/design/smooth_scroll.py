"""App-wide smooth wheel scrolling (2026-11-18).

User (2026-11-18): the app should feel like macOS — they picked the calm feel 「A 沉穩」, and the
plan (docs/exec-plans/active/2026-11-18-premium-motion.md, layer 3) starts with scrolling, the
motion people touch every second. Qt jumps a whole wheel notch at once (three lines); here the
same distance is covered on the calm spring (``motion_tokens.SCROLL``): fast spins add up and
keep their speed, nothing overshoots, and it stops exactly where Qt would have stopped.

Installed once on the application (``install``) as a listener of the shared event hub. It takes
a wheel event only where Qt itself would have scrolled a plain scroll area with it, so anything
with its own wheel behaviour keeps it:

- only events arriving at a scroll area's viewport; a child that uses the wheel (combo box, spin
  box, slider, timeline) has accepted it before it gets there;
- not with a modifier held (Ctrl zooms the UI, Shift/Ctrl page-scroll in Qt);
- not touchpad gestures that carry pixel deltas or a scroll phase (they are smooth already);
- not views whose bars count lines or items (``QPlainTextEdit``, item views scrolling per item),
  graphics views, popups, or scroll areas whose Python class handles the wheel itself;
- not when the bar is already at that end, so the wheel still reaches an outer scroll area;
- not under 「减少动态效果」 or with ``TWOBYTEASR_SMOOTH_SCROLL=0``; a widget can opt out with
  the dynamic property ``smoothScroll`` set to False.

A drag of the scroll bar, a key press or code moving the bar during the glide hands control
back at once.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QApplication, QGraphicsView,
                               QPlainTextEdit)

from .motion_tokens import SCROLL

_CUSTOM_WHEEL_CACHE: dict[type, bool] = {}
_SUBSTEP = 1 / 480


def _key(bar) -> int:
    """The C++ object's address: Python wrappers (and their id) can be reused after a delete."""
    from shiboken6 import getCppPointer
    return int(getCppPointer(bar)[0])


def enabled() -> bool:
    if os.environ.get('TWOBYTEASR_SMOOTH_SCROLL') == '0':
        return False
    from .ui_motion import reduced_motion
    return not reduced_motion()


def _handles_wheel_itself(area: QAbstractScrollArea) -> bool:
    """True when a Python class between this widget and Qt's own classes deals with the wheel."""
    kind = type(area)
    cached = _CUSTOM_WHEEL_CACHE.get(kind)
    if cached is None:
        cached = False
        if getattr(kind, 'smooth_wheel', False):      # its wheelEvent only adds a side effect
            _CUSTOM_WHEEL_CACHE[kind] = False
            return False
        for cls in kind.__mro__:
            if cls.__module__.startswith(('PySide6', 'shiboken6')) or cls is object:
                break
            if any(name in cls.__dict__ for name in ('wheelEvent', 'viewportEvent')):
                cached = True
                break
        _CUSTOM_WHEEL_CACHE[kind] = cached
    return cached


def scroll_area_for(watched) -> QAbstractScrollArea | None:
    """The scroll area whose viewport received this event, if it is one we smooth."""
    area = watched.parent() if hasattr(watched, 'parent') else None
    if not isinstance(area, QAbstractScrollArea) or area.viewport() is not watched:
        return None
    if isinstance(area, (QGraphicsView, QPlainTextEdit)):
        return None
    if isinstance(area, QAbstractItemView) and (
            area.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerItem):
        return None
    if area.property('smoothScroll') is False or _handles_wheel_itself(area):
        return None
    window = area.window()
    if window is not None and window.windowType() == Qt.WindowType.Popup:
        return None
    return area


class _Glide:
    __slots__ = ('bar', 'pos', 'vel', 'target', 'last_set')

    def __init__(self, bar):
        self.bar = bar
        self.pos = float(bar.value())
        self.vel = 0.0
        self.target = float(bar.value())
        self.last_set = bar.value()


class SmoothScroller(QObject):
    """Turns wheel notches on plain scroll areas into a calm glide."""

    def __init__(self, app):
        super().__init__(app)
        self.setObjectName('smoothScroller')
        self._glides: dict[int, _Glide] = {}
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)
        self._last = time.perf_counter()
        self._stiffness, self._coefficient = SCROLL.constants()

    # ------------------------------------------------------------------ wheel
    def take_wheel(self, watched, event) -> bool:
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if not event.pixelDelta().isNull() or event.phase() != Qt.ScrollPhase.NoScrollPhase:
            return False
        if not enabled():
            return False
        area = scroll_area_for(watched)
        if area is None:
            return False
        angle = event.angleDelta()
        horizontal = abs(angle.x()) > abs(angle.y())
        raw = angle.x() if horizontal else angle.y()
        if not raw:
            return False
        bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
        if bar is None or bar.maximum() <= bar.minimum() or not bar.isEnabled():
            return False
        # The distance Qt's own QAbstractSlider::scrollByDelta would have scrolled for this notch
        # (scroll bars have invertedControls on by default: wheel up lowers the value).
        distance = raw / 120 * QApplication.wheelScrollLines() * bar.singleStep()
        if bar.invertedControls():
            distance = -distance
        if not self.glide(bar, distance):
            return False
        hook = getattr(area, 'on_smooth_wheel', None)
        if callable(hook):
            hook()
        event.accept()
        return True

    def glide(self, bar, distance: float) -> bool:
        """Glide ``bar`` by ``distance`` (its own units); False when it is already at that end.

        For widgets that keep their own scroll bar and handle the wheel themselves (custom lists):
        call this from ``wheelEvent`` instead of ``bar.setValue(...)``.
        """
        if bar is None or not distance or bar.maximum() <= bar.minimum():
            return False
        key = _key(bar)
        glide = self._glides.get(key)
        if glide is not None and (bar.value() != glide.last_set or bar.isSliderDown()):
            glide = None                                   # moved by someone else meanwhile
        if glide is None:
            at_end = (distance < 0 and bar.value() <= bar.minimum()) or (distance > 0 and bar.value() >= bar.maximum())
            if at_end:
                self._glides.pop(key, None)
                return False                               # let an outer scroll area have it
            glide = self._glides[key] = _Glide(bar)
        glide.target = max(bar.minimum(), min(bar.maximum(), glide.target + distance))
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start(self._frame_ms(bar))
        return True

    @staticmethod
    def _frame_ms(widget) -> int:
        screen = widget.screen() if widget is not None else None
        rate = screen.refreshRate() if screen is not None else 60.0
        return max(4, int(1000 / max(30.0, min(240.0, rate or 60.0))))

    # ------------------------------------------------------------------ glide
    def _step(self):
        from shiboken6 import isValid
        now = time.perf_counter()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        for key, glide in list(self._glides.items()):
            bar = glide.bar
            if not isValid(bar) or bar.value() != glide.last_set or bar.isSliderDown():
                self._glides.pop(key, None)                # dragged, keyed or moved by code: theirs now
                continue
            glide.target = max(bar.minimum(), min(bar.maximum(), glide.target))
            left = dt
            while left > 0:
                h = min(left, _SUBSTEP)
                glide.vel += (-self._stiffness * (glide.pos - glide.target) - self._coefficient * glide.vel) * h
                glide.pos += glide.vel * h
                left -= h
            done = abs(glide.pos - glide.target) < 0.5 and abs(glide.vel) < 8
            value = round(glide.target if done else glide.pos)
            if value != bar.value():
                bar.setValue(value)
            if not isValid(bar):
                self._glides.pop(key, None)
                continue
            glide.last_set = bar.value()
            if done or glide.last_set != value:            # arrived, or clamped by a shrinking range
                self._glides.pop(key, None)
        if not self._glides:
            self._timer.stop()

    def gliding(self, bar=None) -> bool:
        return bool(self._glides) if bar is None else _key(bar) in self._glides


def glide_wheel(bar, event, distance_per_notch: float) -> None:
    """For a custom list's ``wheelEvent``: glide when smooth scrolling is on, jump otherwise.

    ``distance_per_notch`` is how far one wheel notch moves ``bar`` (in its own units).
    """
    distance = -event.angleDelta().y() / 120 * distance_per_notch
    app = QApplication.instance()
    scroller = getattr(app, '_smooth_scroller', None) if app is not None else None
    smooth = (scroller is not None and enabled() and event.pixelDelta().isNull()
              and event.phase() == Qt.ScrollPhase.NoScrollPhase
              and event.modifiers() == Qt.KeyboardModifier.NoModifier)
    if not (smooth and scroller.glide(bar, distance)):
        bar.setValue(round(bar.value() + distance))
    event.accept()


def install(app=None) -> SmoothScroller | None:
    """Turn on smooth wheel scrolling for the whole application (once)."""
    app = app or QApplication.instance()
    if app is None:
        return None
    existing = getattr(app, '_smooth_scroller', None)
    if existing is not None:
        return existing
    from .app_events import listen
    scroller = app._smooth_scroller = SmoothScroller(app)
    listen(scroller, (QEvent.Type.Wheel,), scroller.take_wheel)
    return scroller


__all__ = ['SmoothScroller', 'enabled', 'glide_wheel', 'install', 'scroll_area_for']
