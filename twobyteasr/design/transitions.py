"""Page and dialog transitions in the calm feel 「A 沉穩」 (2026-11-18).

User (2026-11-18): after the smooth wheel and the press motion they still saw no motion: the
transitions from the demo (pages, dialogs growing out of their button) were not built yet.

Rule of the whole module: **state first, picture follows.** The new page or dialog is real and
usable from the first frame; the motion is only a picture laid over it that never takes a click,
so nothing waits for an animation and turning motion off changes no behaviour.

- Pages (``capture_page`` + ``start_page_crossfade``): just before the switch the old page's
  on-screen pixels are taken; after it, they lie over the live new page, step back to
  ``PAGE_OUT_SCALE`` and fade out (``PAGE_CROSSFADE``). The new page is live underneath, so a
  page that is still filling in (the workshop list) never jumps when the motion ends.
- Dialogs (``install``): every top-level ``QDialog`` that shows grows out of the button just
  pressed (``press_motion.last_pressed``) on ``DIALOG_IN``, and when it hides it shrinks back into
  it on ``DIALOG_OUT``. A frameless "ghost" window that ignores the mouse draws the dialog's
  picture while it moves; the real dialog is open (focus, keys, clicks) underneath at opacity 0
  and is shown the moment the ghost arrives, with a safety timer so it can never stay invisible.

Off under 「减少动态效果」, with ``TWOBYTEASR_TRANSITIONS=0``, for widgets with the dynamic
property ``transitionMotion`` set to False, and wherever a native child window (video) is involved.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from . import motion_tokens as tokens
from .device_pixels import draw_picture

GHOST_SAFETY_MS = 1500
_SUBSTEP = 1 / 480
# A frame never advances the motion by more than this. When the GUI thread is busy (a page that
# builds itself on first open), the motion waits and then plays every frame, instead of jumping to
# its middle and looking like a cut (measured 2026-11-18: 250-330 ms first-open blocks).
MAX_FRAME_STEP_S = 1 / 40


_SUSPENDED_UNTIL = 0.0


def enabled() -> bool:
    if os.environ.get('TWOBYTEASR_TRANSITIONS') == '0' or time.perf_counter() < _SUSPENDED_UNTIL:
        return False
    from .ui_motion import reduced_motion
    return not reduced_motion()


def _frame_ms(widget) -> int:
    screen = widget.screen() if widget is not None else None
    rate = screen.refreshRate() if screen is not None else 60.0
    return max(4, int(1000 / max(30.0, min(240.0, rate or 60.0))))


_heap_quiet = None


def _keep_heap_quiet() -> None:
    """A frame of motion is playing: automatic garbage collection waits until it is over.

    2026-11-19 (user: every animation stutters the first time a page, panel or dialog opens).
    Building a surface the first time allocates many Python objects, so the GUI-thread collector
    (playback_gc_budget) found its thresholds crossed on the next tick and scanned the heap in the
    middle of the motion that followed; a dialog flight then dropped to its last frame. Every
    frame counts as interaction for that collector: it waits, within its existing memory guards
    (a bounded growth, never while memory is low), and runs a moment after the motion ends.
    Called when a motion starts as well: after a long build the collector's timer is already due
    and would otherwise run before the first frame.
    """
    global _heap_quiet
    if _heap_quiet is None:
        try:
            from ..playback.playback_gc_budget import note_gui_interaction
        except Exception:  # noqa: BLE001 - motion never depends on the collector
            note_gui_interaction = lambda: None  # noqa: E731
        _heap_quiet = note_gui_interaction
    _heap_quiet()


# ====================================================================== pages
_OWNED: set[int] = set()            # stacks whose switch the main window animates itself


def _desktop_pixels(widget: QWidget) -> QPixmap | None:
    """``widget``'s rectangle as composited on the desktop, video windows included.

    Only capture a visible region fully inside the active window's current screen.
    """
    window = widget.window()
    screen = widget.screen()
    if window is None or screen is None or not window.isActiveWindow():
        return None
    ratio = widget.devicePixelRatioF() or 1.0
    bounds = QRect(widget.mapToGlobal(widget.rect().topLeft()), widget.size())
    if not screen.geometry().contains(bounds):
        return None
    at = bounds.topLeft() - screen.geometry().topLeft()
    try:
        grabbed = screen.grabWindow(0, at.x(), at.y(), widget.width(), widget.height())
    except Exception:  # noqa: BLE001
        return None
    if grabbed.isNull() or abs(grabbed.width() - widget.width() * ratio) > 2:
        return None
    grabbed.setDevicePixelRatio(ratio)
    return grabbed


def _screen_pixels(widget: QWidget) -> QPixmap | None:
    """What ``widget`` shows on screen right now: a copy of its native window's pixels, not a
    fresh render (fast, and exactly the picture the user saw), or a render when that fails.

    With a visible video (native child window) inside, only the desktop holds the whole picture:
    see ``_desktop_pixels``."""
    if has_visible_native_child(widget):
        return _desktop_pixels(widget)
    ratio = widget.devicePixelRatioF() or 1.0
    native = widget if widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow) else widget.nativeParentWidget()
    pixmap = None
    if native is not None:
        try:
            screen = widget.screen()
            if screen is not None:
                if native is widget:
                    grabbed = screen.grabWindow(int(native.winId()))
                else:
                    at = widget.mapTo(native, widget.rect().topLeft())
                    grabbed = screen.grabWindow(int(native.winId()), at.x(), at.y(), widget.width(), widget.height())
                if not grabbed.isNull() and abs(grabbed.width() - widget.width() * ratio) <= 2 \
                        and abs(grabbed.height() - widget.height() * ratio) <= 2:
                    grabbed.setDevicePixelRatio(ratio)
                    pixmap = grabbed
        except Exception:  # noqa: BLE001 - fall back to rendering it
            pixmap = None
    if pixmap is None:
        pixmap = widget.grab()
    return None if pixmap.isNull() else pixmap


def _frame_step(motion, now: float):
    """Seconds to move ``motion`` on for the frame at ``now`` (its ``_last`` is the frame before),
    or None when it should end on its final picture. A late frame moves it one normal frame, so
    nothing jumps; ``MAX_LATE_FRAMES`` late frames end it (a GUI thread too busy for a motion)."""
    gap = (now - motion._last) * 1000
    motion._last = now
    if gap <= tokens.MAX_FRAME_GAP_MS:
        return gap / 1000
    motion._late = getattr(motion, '_late', 0) + 1
    if motion._late >= tokens.MAX_LATE_FRAMES:
        return None
    return _frame_ms(motion) / 1000


def capture_region(widget: QWidget, *, minimum=(2, 2)) -> QPixmap | None:
    """``widget``'s current on-screen picture, or None when there should be no motion there."""
    if not enabled() or widget is None or not widget.isVisible():
        return None
    if widget.width() < minimum[0] or widget.height() < minimum[1]:
        return None
    window = widget.window()
    if window is None or window.isMinimized() or widget.property('transitionMotion') is False:
        return None
    direct = Qt.FindChildOption.FindDirectChildrenOnly
    for old in (list(_FLOATING.get(_key(widget), ())) + widget.findChildren(PageCrossfade, options=direct)
                + widget.findChildren(PageHold, options=direct)):
        old.finish()
    return _screen_pixels(widget)


_FLOATING: dict[int, list] = {}      # target key -> floating overlays over it
_ACTIVE_FADES: set = set()           # fades now running: one at a time (nested ones flashed)


def _remove_floating(key, overlay):
    overlays = _FLOATING.get(key)
    if overlays and overlay in overlays:
        overlays.remove(overlay)
        if not overlays:
            del _FLOATING[key]


# ====================================================================== the stage cover
class StageCover(QWidget):
    """A click-through window that always lies over the main window, fully transparent, so a
    picture put into it is on the screen at once (2026-11-19).

    User (2026-11-19): going into the project library and the subtitle workbench still flashes.
    Recorded from the screen (another process reading the desktop every 30 ms): the loading card
    appeared, then Home came back for a moment, then the card faded in; leaving the workbench, Home
    appeared, then the workbench with its video came back and faded out. Every picture that has to
    lie above the video (a native child window) was drawn in a top-level window created for that
    one fade, and Windows puts a new window on the screen only after the app has gone back to its
    event loop: 80-150 ms later, after what it was meant to hide had already changed under it.

    Measured in isolation (tmp/anim/cover_sync.py, the window under it changes right after and the
    app is then busy 300 ms): a new picture window, shown and repainted at once, even waiting for
    the desktop to compose, was not on the screen in time; neither was one shown before and hidden
    since. One that *stays shown* (transparent) and is only repainted was there every time.

    So each main window has one, made when it is first up and kept with it (it follows its place
    and size and lies directly above it, under its dialogs). Picture overlays that must cover video
    become children of it (``PageCrossfade(floating=True)``) and paint into it synchronously.
    Nothing is drawn while no overlay is in it; it never takes the mouse or the focus.
    """

    def __init__(self, window: QWidget):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        super().__init__(window, flags)
        self.setObjectName('stageCover')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.owner = window
        self._ready_at = None
        window.installEventFilter(self)
        self.follow()
        self.winId()
        try:
            from ..app import floating_anchor
            floating_anchor.no_system_animation(self)
        except Exception:  # noqa: BLE001
            pass
        self._show_kept()

    def _show_kept(self):
        self._ready_at = None
        self.show()
        self.follow()
        self.stack_over_owner()
        # Usable once Windows has had an event-loop turn to put it on the screen.
        QTimer.singleShot(60, self, self._mark_ready)

    def _mark_ready(self):
        if self.isVisible():
            self._ready_at = time.perf_counter()

    def ready(self) -> bool:
        from shiboken6 import isValid
        owner = self.owner
        return (self._ready_at is not None and isValid(owner) and owner.isVisible() and not owner.isMinimized()
                and self.isVisible())

    def follow(self):
        from shiboken6 import isValid
        if not isValid(self.owner):
            return
        try:
            from ..app import floating_anchor
            floating_anchor.cover_window(self, self.owner)
        except Exception:  # noqa: BLE001
            self.setGeometry(QRect(self.owner.mapToGlobal(QPoint(0, 0)), self.owner.size()))

    def stack_over_owner(self):
        """Directly above the main window (and so above its video), below its own dialogs."""
        from ..app import floating_anchor
        mine, owner = floating_anchor._handle(self), floating_anchor._handle(self.owner)
        if not mine or not owner:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user = ctypes.WinDLL('user32')
            user.GetWindow.restype = wintypes.HWND
            user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
            user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, wintypes.UINT]
            above = user.GetWindow(owner, 3) or 0          # GW_HWNDPREV: the window just above the owner
            if int(above or 0) == mine:
                return
            # Placed under ``above`` = right over the owner; HWND_TOP when nothing is above it.
            user.SetWindowPos(mine, above or 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0200)
        except (OSError, AttributeError, ValueError):
            pass

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if watched is self.owner:
            kind = event.type()
            if kind in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.WindowStateChange):
                self.follow()
            elif kind == QEvent.Type.Show and not self.isVisible():
                self._show_kept()
            elif kind == QEvent.Type.Hide:
                self._ready_at = None
                self.hide()
        return False

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        return                         # transparent: only overlays put into it are drawn


_COVERS: dict[int, StageCover] = {}


def install_stage_cover(window: QWidget) -> StageCover | None:
    """Give ``window`` (shown, on Windows) its kept cover. Idempotent; None where it cannot work."""
    from shiboken6 import isValid
    if window is None or not window.isWindow() or not window.isVisible():
        return None
    if QApplication.platformName() != 'windows' or os.environ.get('TWOBYTEASR_STAGE_COVER', '1') == '0':
        return None
    cover = _COVERS.get(_key(window))
    if cover is not None and isValid(cover):
        return cover
    cover = StageCover(window)
    _COVERS[_key(window)] = cover
    cover.destroyed.connect(lambda *_a, key=_key(window): _COVERS.pop(key, None))
    return cover


def stage_cover(widget: QWidget) -> StageCover | None:
    """The ready kept cover over ``widget``'s window, or None."""
    from shiboken6 import isValid
    window = widget.window() if widget is not None else None
    cover = _COVERS.get(_key(window)) if window is not None else None
    if cover is None or not isValid(cover) or not cover.ready():
        return None
    return cover


def capture_page(stack: QWidget) -> QPixmap | None:
    """The main window's page stack before a switch it animates itself (see ``start_page_crossfade``)."""
    pixmap = capture_region(stack)
    if pixmap is not None:
        _OWNED.add(_key(stack))
    return pixmap


class PageCrossfade(QWidget):
    """The old page's picture over the live new page: steps back and fades out, then goes.

    ``floating``: a frameless, click-through top-level window over the target instead of a child.
    A child widget is drawn under native child windows (Studio's mpv video, previews); a top-level
    window owned by the main window is drawn above them, so the fade also covers the video.
    """

    def __init__(self, stack: QWidget, pixmap: QPixmap | None, *, step_back: bool = True, color=None,
                 floating: bool = False, global_rect: QRect | None = None):
        cover = stage_cover(stack) if floating else None
        if cover is not None:
            # 2026-11-19: inside the window's kept cover, drawn synchronously (see StageCover).
            super().__init__(cover)
            window = stack.window()
            if global_rect is not None:
                self.setGeometry(QRect(window.mapFromGlobal(global_rect.topLeft()), global_rect.size()))
            else:
                self.setGeometry(QRect(stack.mapTo(window, QPoint(0, 0)), stack.size()))
        elif floating:
            flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                     | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
            super().__init__(stack.window(), flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setGeometry(global_rect if global_rect is not None
                             else QRect(stack.mapToGlobal(stack.rect().topLeft()), stack.size()))
        else:
            super().__init__(stack)
            self.setGeometry(stack.rect())
        if floating:
            key = _key(stack)
            _FLOATING.setdefault(key, []).append(self)
            self.destroyed.connect(lambda *_: _remove_floating(key, self))
        self.destroyed.connect(lambda *_: _ACTIVE_FADES.discard(self))
        self.cover = cover
        self.setObjectName('pageCrossfade')
        self.target = stack
        self.floating = floating
        self.step_back = step_back
        self.color = color                 # a plain veil (``reveal``) instead of a picture
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pixmap = pixmap
        self.progress = 0.0
        self._elapsed = 0.0
        self._curve = tokens.easing_curve(tokens.PAGE_CROSSFADE)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)
        self._last = time.perf_counter()
        stack.installEventFilter(self)
        if floating and stack.window() is not None:
            stack.window().installEventFilter(self)

    def _settle_floating(self):
        """2026-11-19: the picture window is put over its place in physical pixels (with screens
        at different scales Qt's own coordinates put it somewhere else, see app.floating_anchor)
        and Windows does not animate it in: it must cover the page in full from its first frame."""
        try:
            from ..app import floating_anchor
            window = self.target.window()
            rect = self.geometry()
            self.winId()
            floating_anchor.no_system_animation(self)
            floating_anchor.move_over(self, window, window.mapFromGlobal(rect.topLeft()), inside=False)
        except Exception:  # noqa: BLE001 - placed by Qt as before
            pass

    def start(self, *, hold: bool = False):
        _keep_heap_quiet()                 # before the overdue collector tick, too
        """Show the picture (in the kept cover: on the screen before this returns) and fade it
        out from the next frame the GUI thread gets to. ``hold``: show it, fade only at ``release``."""
        if self.cover is not None:
            self.cover.follow()
            self.cover.stack_over_owner()
        elif self.floating:
            self._settle_floating()
        self.raise_()
        self.show()
        if self.cover is not None:
            self.repaint()                 # into the kept window now, not at the next event loop
        self._last = None                  # the clock starts at the first frame the GUI gets to
        _ACTIVE_FADES.add(self)
        if not hold:
            self._timer.start(_frame_ms(self))

    def release(self):
        """Begin the fade of a picture started with ``hold=True``."""
        from shiboken6 import isValid
        if isValid(self) and not self._timer.isActive() and self in _ACTIVE_FADES:
            self._last = None
            self._timer.start(_frame_ms(self))

    def _step(self):
        _keep_heap_quiet()
        now = time.perf_counter()
        if self._last is None:
            self._last = now
            return
        step = _frame_step(self, now)
        if step is None:
            # 2026-11-18 evening (user: 5 fps, twitching, sluggish): a busy GUI thread gets the
            # final picture at once, never a slow or stretched motion.
            self.finish()
            return
        self._elapsed += step
        p = min(1.0, self._elapsed * 1000 / tokens.PAGE_CROSSFADE.ms)
        self.progress = self._curve.valueForProgress(p)
        self.update()
        if p >= 1.0:
            self.finish()

    def finish(self):
        from shiboken6 import isValid
        if not isValid(self):
            return
        self._timer.stop()
        _ACTIVE_FADES.discard(self)
        target = self.target if isValid(self.target) else None
        if target is not None:
            target.removeEventFilter(self)
            if self.floating and target.window() is not None:
                target.window().removeEventFilter(self)
            _remove_floating(_key(target), self)
        self.hide()
        self.deleteLater()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        kind = event.type()
        if watched is not self.target:     # the main window (floating overlays only)
            if kind in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide, QEvent.Type.WindowStateChange):
                self.finish()
            return False
        if kind == QEvent.Type.Resize and self.color is not None:
            self.setGeometry(watched.rect())   # a plain veil just follows the panel's new size
        elif kind == QEvent.Type.Resize and self.cover is not None:
            pass                           # in the window's cover it stays where the old page was
        elif kind in (QEvent.Type.Resize, QEvent.Type.Hide):
            self.finish()                  # the picture no longer matches: stop pretending
        return False

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        k = self.progress
        if k >= 1.0:
            return
        painter = QPainter(self)
        painter.setOpacity(1.0 - k)
        if self.color is not None:
            painter.fillRect(self.rect(), self.color)
            painter.end()
            return
        scale = 1.0 - (1.0 - tokens.PAGE_OUT_SCALE) * k if self.step_back else 1.0
        if scale != 1.0:
            centre = QPointF(self.width() / 2, self.height() / 2)
            painter.translate(centre)
            painter.scale(scale, scale)
            painter.translate(-centre)
        draw_picture(painter, QPoint(0, 0), self.pixmap)
        painter.end()


class PageHold(QWidget):
    """The old page's picture, opaque, until the new page under it has finished building; then one
    cross-fade between two finished pictures (2026-11-19).

    User (2026-11-19): going to the model workshop still flashes Home and the workshop two or
    three times before it is there; the same to the term library, the history, back Home and into
    the project library. Recorded frame by frame, a first visit showed the old page, then an
    empty page or grey placeholders, then half of the content, then all of it (0.8-1.4 s), and
    the fade itself repainted the whole live page under a translucent picture for every frame.

    Now the stack is switched under this widget and nothing of that is seen:

    * ``hold``: the old picture is drawn as it was. The pointer shows that something is coming
      and clicks are kept from the page that cannot be seen yet. The new page counts as finished
      when no widget in it was added, laid out, shown, hidden or resized for
      ``PAGE_SETTLE_QUIET_MS`` and ``settled()`` agrees (a scan in the background), or after
      ``PAGE_SETTLE_LIMIT_MS`` (it then finishes in view). A page that was shown before does not
      wait (``wait=False``).
    * ``fade``: the new page is rendered once into a picture, and the two pictures are blended.
      This widget is opaque, so Qt paints nothing under it during the fade: two copies a frame.
    """

    STRUCTURAL = frozenset({QEvent.Type.ChildAdded, QEvent.Type.LayoutRequest, QEvent.Type.ShowToParent,
                            QEvent.Type.HideToParent, QEvent.Type.Resize})

    def __init__(self, stack: QWidget, pixmap: QPixmap, *, settled=None, wait: bool = True, on_settled=None,
                 motion=None):
        super().__init__(stack)
        self.setObjectName('pageHold')
        self.motion = motion                   # callable -> PageMotion, asked once the new page is drawn
        self.choreo = None
        self.setGeometry(stack.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.target = stack
        self.old = pixmap
        self.new = None
        self.new_at = QPoint()
        self.phase = 'hold'
        self.settled = settled
        self.on_settled = on_settled
        self.wait = bool(wait)
        self.progress = 0.0
        self._capturing = False
        self._elapsed = 0.0
        self._curve = tokens.easing_curve(tokens.PAGE_ENTER)
        self._late = 0
        self._began = self._changed = time.perf_counter()
        self._last = None
        self._done = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        stack.installEventFilter(self)
        if self.wait:
            self.setCursor(Qt.CursorShape.BusyCursor)
        QApplication.instance().installEventFilter(self)     # also a shown page's own late work

    def start(self):
        _keep_heap_quiet()                 # before the overdue collector tick, too
        self.raise_()
        self.show()
        _ACTIVE_FADES.add(self)
        self._timer.start(_frame_ms(self))

    # ------------------------------------------------------------ waiting for the page
    def _page(self):
        current = getattr(self.target, 'currentWidget', None)
        return current() if callable(current) else None

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        kind = event.type()
        if watched is self.target:
            if kind in (QEvent.Type.Resize, QEvent.Type.Hide):
                self.finish()                  # the picture no longer matches: stop pretending
            return False
        if self.phase == 'hold' and kind in self.STRUCTURAL and watched is not self and isinstance(watched, QWidget):
            page = self._page()
            try:
                if page is not None and (watched is page or page.isAncestorOf(watched)):
                    self._changed = time.perf_counter()
            except RuntimeError:
                pass
        return False

    def _ready(self, now: float) -> bool:
        if not self.wait:
            # Shown before: nothing to build, but let the work its showing queued run first.
            waited = (now - self._began) * 1000
            return waited >= tokens.PAGE_SHOWN_QUIET_LIMIT_MS or (
                waited >= _frame_ms(self) and (now - self._changed) * 1000 >= _frame_ms(self))
        if (now - self._began) * 1000 >= tokens.PAGE_SETTLE_LIMIT_MS:
            return True
        if (now - self._changed) * 1000 < tokens.PAGE_SETTLE_QUIET_MS:
            return False
        try:
            return self.settled is None or bool(self.settled())
        except Exception:  # noqa: BLE001 - a page that cannot say is not waited for
            return True

    def _tick(self):
        _keep_heap_quiet()
        now = time.perf_counter()
        if self.phase == 'hold':
            if self._ready(now):
                self._begin_fade()
            return
        if self._last is None:                 # the clock starts at the first frame the GUI gets to
            self._last = now
            return
        step = _frame_step(self, now)
        if step is None:
            self.finish()                      # a busy GUI thread gets the final picture at once
            return
        self._elapsed += step
        elapsed_ms = self._elapsed * 1000
        if self.choreo is not None:
            self.progress = min(1.0, elapsed_ms / self.choreo.total_ms)
            self.update()
            if elapsed_ms >= self.choreo.total_ms:
                self.finish()
            return
        enter = (elapsed_ms - tokens.PAGE_IN_DELAY_MS) / tokens.PAGE_ENTER.ms
        self.progress = self._curve.valueForProgress(min(1.0, max(0.0, enter)))
        self.update()
        if enter >= 1.0:
            self.finish()

    def _begin_fade(self):
        from shiboken6 import isValid
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self.wait:
            self.unsetCursor()
        if callable(self.on_settled):
            try:
                self.on_settled()
            except Exception:  # noqa: BLE001
                pass
        target = self.target
        if not enabled() or not isValid(target) or not target.isVisible():
            self.finish()
            return
        if callable(self.motion):
            try:
                self.choreo = self.motion()
                if self.choreo is not None:
                    self.choreo.prepare(self)
            except Exception:  # noqa: BLE001 - use the regular page fade
                self.choreo = None
        # The stack as it will look without this widget: for the render this widget draws nothing
        # and is not opaque, so everything under it is painted into the picture.
        self._capturing = True
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        try:
            picture = target.grab() if self.choreo is None else self.choreo.capture(target)
        except Exception:  # noqa: BLE001
            picture = None
        finally:
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            self._capturing = False
        if picture is None or picture.isNull():
            self.finish()
            return
        self.new = picture
        self.phase = 'fade'
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # the page is what is seen now
        self._last = None
        self.update()

    def finish(self):
        from shiboken6 import isValid
        if self._done or not isValid(self):
            return
        self._done = True
        self._timer.stop()
        _ACTIVE_FADES.discard(self)
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self.phase == 'hold' and callable(self.on_settled):
            try:
                self.on_settled()
            except Exception:  # noqa: BLE001
                pass
        if isValid(self.target):
            self.target.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    # ------------------------------------------------------------ input and picture
    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        event.accept()                         # the page under the old picture is not clicked blind

    mouseReleaseEvent = mouseDoubleClickEvent = mousePressEvent

    def wheelEvent(self, event):  # noqa: N802 - Qt override
        event.accept()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        if self._capturing:
            return
        painter = QPainter(self)
        if self.choreo is not None and self.new is not None:
            self.choreo.paint(painter, self, self._elapsed * 1000)
            painter.end()
            return
        # The stack can grow when leaving Home and hiding its bottom bar.
        # Fill the area outside either snapshot before blending the shifted page.
        painter.fillRect(self.rect(), self.palette().window())
        if self.new is None or self.progress <= 0.0:
            draw_picture(painter, QPoint(0, 0), self.old)
        elif self.progress >= 1.0:
            draw_picture(painter, self.new_at, self.new)
        else:
            # The new page rises into place and fades in over the old one (``PAGE_ENTER``). Both
            # are pictures and only shifted, never scaled: two copies a frame.
            draw_picture(painter, QPoint(0, 0), self.old)
            painter.setOpacity(self.progress)
            shift = round(tokens.PAGE_SHIFT_PX * (1.0 - self.progress))
            draw_picture(painter, self.new_at + QPoint(0, shift), self.new)
        painter.end()


def start_page_hold(stack: QWidget, pixmap: QPixmap | None, *, settled=None, wait: bool = True,
                    on_settled=None, motion=None) -> PageHold | None:
    """Keep ``pixmap`` (``capture_page`` before the switch) over ``stack`` until its new page is
    finished, then fade to it (see ``PageHold``). Without a picture nothing is held."""
    if stack is not None:
        _OWNED.discard(_key(stack))
    if pixmap is None or stack is None or not stack.isVisible():
        if callable(on_settled):
            on_settled()
        return None
    hold = PageHold(stack, pixmap, settled=settled, wait=wait, on_settled=on_settled, motion=motion)
    hold.start()
    return hold


def spring_progress(spring, ms: float) -> float:
    """Where a critically damped spring from 0 to 1 is after ``ms`` (0 before it starts)."""
    if ms <= 0:
        return 0.0
    import math
    omega = 2 * math.pi / spring.response
    t = ms / 1000
    return 1.0 - (1.0 + omega * t) * math.exp(-omega * t)


def _spring_rest_ms(spring, distance: float) -> float:
    """When a spring travelling ``distance`` px is within half a pixel of its place."""
    ms = 0.0
    while ms < 3000 and distance * (1.0 - spring_progress(spring, ms)) > 0.5:
        ms += 4
    return ms


class PageMotion:
    """A page switch that slides along the navigation order, its parts arriving one after
    another (2026-11-19; the user's pick: option 1's slide with option 3's cascade, sideways).

    Drawn from two pictures (the old page, the finished new page), so it costs a few picture
    copies a frame whatever the pages hold, and nothing in the pages is moved or relaid out.

    ``direction``: +1 the new page comes from the right (further down the navigation), -1 from the
    left. ``keep``: a part both pages share (the sidebar), drawn from the new picture at once and
    never moved. ``glide``: the sidebar highlight's old and new rectangle. ``parts``: rectangles of
    the new page, in the order they arrive; whatever lies outside them arrives first, with the
    page's background.
    """

    def __init__(self, direction: int = 1, *, keep: QRect | None = None, glide=None, parts=(),
                 background=None, selected_button=None):
        self.direction = 1 if direction >= 0 else -1
        self.keep = QRect(keep) if keep is not None and not keep.isEmpty() else None
        self.glide = glide
        self.parts = [QRect(rect) for rect in parts]
        self.background = background
        self.selected_button = selected_button
        self.total_ms = 1.0

    def capture(self, target: QWidget) -> QPixmap:
        button = self.selected_button
        if self.glide is None or button is None:
            return target.grab()
        # Keep the live selection and paint its background only in the moving highlight.
        stylesheet = button.styleSheet()
        button.setStyleSheet(stylesheet + '\nQPushButton#workspaceNav { background: transparent; }')
        try:
            return target.grab()
        finally:
            button.setStyleSheet(stylesheet)

    def prepare(self, hold) -> None:
        from PySide6.QtGui import QColor, QRegion
        rect = hold.rect()
        if self.keep is not None and self.keep.left() <= rect.left() + 4:
            self.area = QRect(self.keep.right() + 1, rect.top(), rect.right() - self.keep.right(), rect.height())
        else:
            if self.keep is not None:
                self.glide = None
            self.keep = None
            self.area = QRect(rect)
        self.parts = [part.intersected(self.area) for part in self.parts]
        self.parts = [part for part in self.parts if part.width() > 2 and part.height() > 2][:tokens.PAGE_SLIDE_PARTS_MAX]
        rest = QRegion(self.area)
        for part in self.parts:
            rest = rest.subtracted(QRegion(part))
        self.rest = rest
        if self.background is None:
            self.background = QColor('#19151c')
        self.distance = tokens.PAGE_SLIDE_PX
        self.fade = tokens.easing_curve(tokens.PAGE_SLIDE_FADE)
        self.leave = tokens.easing_curve(tokens.PAGE_SLIDE_OLD)
        self.glide_fade = tokens.easing_curve(tokens.NAV_GLIDE_FADE)
        rest_ms = _spring_rest_ms(tokens.PAGE_SLIDE_IN, self.distance)
        last = self._delay(len(self.parts) - 1) if self.parts else tokens.PAGE_SLIDE_DELAY_MS
        self.total_ms = max(last + max(rest_ms, tokens.PAGE_SLIDE_FADE.ms), tokens.PAGE_SLIDE_OLD.ms,
                            _spring_rest_ms(tokens.NAV_GLIDE, 40) + tokens.NAV_GLIDE_FADE.ms if self.glide else 0)

    def _delay(self, index: int) -> float:
        return tokens.PAGE_SLIDE_DELAY_MS + min(index + 1, tokens.PAGE_SLIDE_STAGGER_STEPS) * tokens.PAGE_SLIDE_STAGGER_MS

    def _arrival(self, delay: float, ms: float):
        """(x offset, opacity) of something that starts arriving after ``delay`` ms."""
        local = ms - delay
        if local <= 0:
            return self.direction * self.distance, 0.0
        offset = self.direction * self.distance * (1.0 - spring_progress(tokens.PAGE_SLIDE_IN, local))
        return offset, self.fade.valueForProgress(min(1.0, local / tokens.PAGE_SLIDE_FADE.ms))

    def paint(self, painter, hold, ms: float) -> None:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QRegion
        new, old = hold.new, hold.old
        ratio_new = new.devicePixelRatio() or 1.0
        ratio_old = old.devicePixelRatio() or 1.0
        painter.fillRect(hold.rect(), self.background)
        if self.keep is not None:
            draw_picture(painter, QPointF(self.keep.topLeft()), new, _source(self.keep, ratio_new))
        painter.save()
        painter.setClipRect(self.area)
        # The old content steps the other way and fades.
        k = min(1.0, ms / tokens.PAGE_SLIDE_OLD.ms)
        if k < 1.0:
            eased = self.leave.valueForProgress(k)
            painter.setOpacity(1.0 - eased)
            shift = -self.direction * self.distance * tokens.PAGE_SLIDE_OLD_SHARE * eased
            draw_picture(painter, QPointF(self.area.x() + shift, self.area.y()), old, _source(self.area, ratio_old))
        # Everything that is not one of the parts arrives first, then the parts one after another.
        offset, opacity = self._arrival(tokens.PAGE_SLIDE_DELAY_MS, ms)
        if opacity > 0.0:
            painter.save()
            painter.setClipRegion(self.rest.translated(round(offset), 0).intersected(QRegion(self.area)))
            painter.setOpacity(opacity)
            draw_picture(painter, QPointF(self.area.x() + offset, self.area.y()), new, _source(self.area, ratio_new))
            painter.restore()
        for index, part in enumerate(self.parts):
            offset, opacity = self._arrival(self._delay(index), ms)
            if opacity <= 0.0:
                continue
            painter.setOpacity(opacity)
            draw_picture(painter, QPointF(part.x() + offset, part.y()), new, _source(part, ratio_new))
        painter.restore()
        if self.glide:
            start, end = self.glide
            travel = spring_progress(tokens.NAV_GLIDE, ms)
            rest_ms = _spring_rest_ms(tokens.NAV_GLIDE, abs(end.center().y() - start.center().y()) or 1)
            fade = 1.0 - self.glide_fade.valueForProgress(min(1.0, max(0.0, (ms - rest_ms) / tokens.NAV_GLIDE_FADE.ms)))
            if fade > 0.0:
                y = start.y() + (end.y() - start.y()) * travel
                pill = QRectF(end.x(), y, end.width(), end.height())
                accent = QColor(getattr(self, 'accent', None) or '#d9538f')
                painter.setOpacity(fade)
                painter.setPen(Qt.PenStyle.NoPen)
                tint = QColor(accent)
                tint.setAlpha(56)
                painter.setBrush(tint)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.drawRoundedRect(pill, 10, 10)
                painter.setBrush(accent)
                painter.drawRoundedRect(QRectF(pill.x(), pill.y() + pill.height() * .25, 3, pill.height() * .5), 1.5, 1.5)
                painter.setOpacity(1.0)


def _source(rect: QRect, ratio: float):
    from PySide6.QtCore import QRectF
    return QRectF(rect.x() * ratio, rect.y() * ratio, rect.width() * ratio, rect.height() * ratio)


def page_parts(page: QWidget, stack: QWidget, keep: QRect | None = None, limit: int | None = None) -> list:
    """The new page's parts that arrive one after another, in reading order, as rectangles in
    ``stack``: its cards and panels, a grid of small items row by row, never inside ``keep``.

    Found from the widgets themselves, so every page gets sensible parts without listing them: a
    widget that covers much of the page is split into its children, one that does not is a part;
    what a scroll area shows is cut to its viewport."""
    from PySide6.QtWidgets import QAbstractScrollArea
    limit = limit or tokens.PAGE_SLIDE_PARTS_MAX
    bounds = QRect(0, 0, stack.width(), stack.height())
    area = bounds if keep is None else QRect(keep.right() + 1, 0, max(0, bounds.width() - keep.right() - 1), bounds.height())
    total = max(1, area.width() * area.height())
    found = []
    direct = Qt.FindChildOption.FindDirectChildrenOnly

    def place(widget, clip):
        return QRect(widget.mapTo(stack, QPoint(0, 0)), widget.size()).intersected(clip)

    def visit(widget, clip, depth):
        if isinstance(widget, QAbstractScrollArea):
            clip = clip.intersected(place(widget.viewport(), clip))
        rect = place(widget, clip)
        if rect.isEmpty() or (keep is not None and keep.contains(rect)):
            return
        children = []
        for child in widget.findChildren(QWidget, options=direct):
            if child.isVisible() and not child.isWindow() and not isinstance(child, (PageHold, PageCrossfade)):
                child_rect = place(child, clip)
                if child_rect.width() >= 24 and child_rect.height() >= 16:
                    children.append((child, child_rect))
        large = rect.width() * rect.height() > total * 0.22
        crosses_keep = keep is not None and rect.intersects(keep)
        if not children or depth >= 7 or not (depth == 0 or large or crosses_keep):
            found.append(rect)
            return
        if len(children) > 8 and not crosses_keep:
            found.extend(_rows([child_rect for _child, child_rect in children]))
            return
        for child, _child_rect in children:
            visit(child, clip, depth + 1)

    visit(page, area, 0)
    parts = [rect for rect in found if rect.width() * rect.height() >= total * 0.006 and not (keep and keep.contains(rect))]
    parts.sort(key=lambda rect: (rect.top(), rect.left()))
    if len(parts) > limit:
        parts = _rows(parts)
    while len(parts) > limit:
        parts = [parts[i].united(parts[i + 1]) if i + 1 < len(parts) else parts[i] for i in range(0, len(parts), 2)]
    return parts


def _rows(rects) -> list:
    """Rectangles that share a row (overlap vertically by half the smaller) merged, top to bottom."""
    rows = []
    for rect in sorted(rects, key=lambda r: (r.top(), r.left())):
        if rows:
            last = rows[-1]
            overlap = min(last.bottom(), rect.bottom()) - max(last.top(), rect.top())
            if overlap >= min(last.height(), rect.height()) / 2:
                rows[-1] = last.united(rect)
                continue
        rows.append(QRect(rect))
    return rows


def is_held(widget: QWidget) -> bool:
    """``widget`` is under a page that is being held back (it builds unseen: no need for its own
    placeholders and fades, and it may take bigger steps)."""
    if widget is None:
        return False
    for fade in tuple(_ACTIVE_FADES):
        try:
            if isinstance(fade, PageHold) and fade.phase == 'hold' and (
                    fade.target is widget or fade.target.isAncestorOf(widget)):
                return True
        except RuntimeError:
            continue
    return False


def start_page_crossfade(stack: QWidget, pixmap: QPixmap | None) -> PageCrossfade | None:
    """Lay ``pixmap`` (from ``capture_page`` before the switch) over the new page and fade it out."""
    if stack is not None:
        _OWNED.discard(_key(stack))
    if pixmap is None or stack is None or not stack.isVisible():
        return None
    # A page-sized picture is only faded: scaling it every frame cost 30-45 ms a frame in a
    # software-rendered window (measured 2026-11-18), for a 1.5 % step back nobody sees on a page.
    big = stack.width() * stack.height() > 420_000
    overlay = PageCrossfade(stack, pixmap, floating=has_visible_native_child(stack), step_back=not big)
    overlay.start()
    # 2026-11-18 evening: no staggered card veils after the fade any more (user: they flashed a
    # blank background, and fought the workshop's own progressive card building).
    return overlay


def cover_page(stack: QWidget, pixmap: QPixmap | None) -> PageCrossfade | None:
    """Put ``pixmap`` (``capture_page``) over ``stack`` in its window's kept cover, on the screen
    before this returns, without fading yet: change the page under it, then ``release()`` it.
    None when there is no ready cover (then nothing is shown; fade afterwards as before)."""
    if pixmap is None or stack is None or not stack.isVisible() or stage_cover(stack) is None:
        return None
    _OWNED.discard(_key(stack))
    big = stack.width() * stack.height() > 420_000
    overlay = PageCrossfade(stack, pixmap, floating=True, step_back=not big)
    if overlay.cover is None:
        overlay.deleteLater()
        return None
    overlay.start(hold=True)
    return overlay


def _stagger_after(target):
    from shiboken6 import isValid
    from PySide6.QtWidgets import QAbstractScrollArea, QStackedWidget
    if not isValid(target) or not target.isVisible():
        return
    if isinstance(target, QStackedWidget):
        stagger_page(target.currentWidget())
    elif isinstance(target, QAbstractScrollArea):
        stagger_list(target)


def reveal(widget: QWidget) -> PageCrossfade | None:
    """A panel that just appeared fades its content in (a veil in its own background colour lifts).

    For panels whose size cannot animate (beside Studio's native video). The veil's colour is read
    from a few rendered pixels of the panel's edge, so it matches whatever its style sheet paints.
    """
    if not enabled() or widget is None or not widget.isVisible() or widget.width() < 80 or widget.height() < 60:
        return None
    if widget.property('transitionMotion') is False or has_visible_native_child(widget):
        return None
    sample = widget.grab(QRect(2, max(0, widget.height() - 6), 4, 4)).toImage()
    if sample.isNull():
        return None
    overlay = PageCrossfade(widget, None, step_back=False, color=sample.pixelColor(1, 1))
    overlay.start()
    return overlay


class _ShowHideFade(QObject):
    """A widget that appears or disappears in place (the Studio loading card) fades instead of cutting.

    Show: before it is drawn, the desktop under it is copied and fades out over it (it fades in).
    Hide: its own picture (rendered, since a native window is gone from the screen at once) fades
    out over whatever is under it. Both in a click-through window above video.
    """

    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self._hide_covered = False
        widget.installEventFilter(self)

    def before_hide(self) -> None:
        """Call right before hiding the widget: its picture is put over it while it is still on the
        screen (Qt's Hide event comes after a native window has already gone), then fades."""
        widget = self.widget
        if not widget.isVisible() or self._hide_covered:
            return
        self._hide_covered = self._fade(widget, QEvent.Type.Hide)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        kind = event.type()
        if watched is not self.widget or kind not in (QEvent.Type.Show, QEvent.Type.Hide):
            return False
        if kind == QEvent.Type.Hide and self._hide_covered:
            self._hide_covered = False         # already faded by before_hide
            return False
        if kind == QEvent.Type.Show:
            self._hide_covered = False
        self._fade(self.widget, kind)
        return False

    def _fade(self, widget, kind) -> bool:
        window = widget.window()
        if (not enabled() or widget.isWindow() or window is None or not window.isVisible()
                or window.isMinimized() or not window.isActiveWindow() or QApplication.closingDown()
                or widget.width() < 80 or widget.height() < 60):
            return False
        host = widget.parentWidget()
        if host is None or not host.isVisible():
            return False
        rect = QRect(widget.mapToGlobal(widget.rect().topLeft()), widget.size())
        if kind == QEvent.Type.Show:
            screen = widget.screen()
            if screen is None:
                return False
            at = rect.topLeft() - screen.geometry().topLeft()
            ratio = widget.devicePixelRatioF() or 1.0
            pixmap = screen.grabWindow(0, at.x(), at.y(), rect.width(), rect.height())
            if pixmap.isNull():
                return False
            pixmap.setDevicePixelRatio(ratio)
        else:
            pixmap = widget.grab()
            if pixmap.isNull():
                return False
        overlay = PageCrossfade(host, pixmap, step_back=kind == QEvent.Type.Hide, floating=True, global_rect=rect)
        overlay.start()
        return True


def fade_on_show_and_hide(widget: QWidget) -> None:
    """Make ``widget`` fade in when shown and fade out when hidden (see ``_ShowHideFade``)."""
    if widget is not None and not hasattr(widget, '_show_hide_fade'):
        widget._show_hide_fade = _ShowHideFade(widget)


class StaggerVeils(QWidget):
    """Cards come in one after another: a veil in the list's background colour lies over each
    visible card and lifts after the one before it (``STAGGER_MS`` apart, at most ``STAGGER_MAX``
    steps). One overlay for the whole list, nothing per card, so it costs a few fills a frame."""

    ITEM_MS = 260

    def __init__(self, container: QWidget, rects: list, color, area=None):
        super().__init__(container)
        self.setObjectName('staggerVeils')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(container.rect())
        self.rects = rects
        self.color = color
        self._curve = tokens.easing_curve(tokens.Tween(self.ITEM_MS, tokens.APPLE_EASE))
        self._elapsed = 0.0
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)
        self.container = container
        container.installEventFilter(self)
        if area is not None:
            for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
                bar.valueChanged.connect(lambda _value: self.finish())   # scrolled: veils would drift

    def start(self):
        _keep_heap_quiet()                 # before the overdue collector tick, too
        self.raise_()
        self.show()
        self._last = time.perf_counter()
        self._timer.start(_frame_ms(self))

    def _alpha(self, index: int) -> float:
        delay = min(index, tokens.STAGGER_MAX) * tokens.STAGGER_MS / 1000
        p = (self._elapsed - delay) * 1000 / self.ITEM_MS
        return 1.0 - self._curve.valueForProgress(max(0.0, min(1.0, p)))

    def _step(self):
        _keep_heap_quiet()
        now = time.perf_counter()
        self._elapsed += min(MAX_FRAME_STEP_S, max(0.0, now - self._last))
        self._last = now
        self.update()
        if self._alpha(len(self.rects) - 1) <= 0.0:
            self.finish()

    def finish(self):
        from shiboken6 import isValid
        if not isValid(self):
            return
        self._timer.stop()
        if isValid(self.container):
            self.container.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Hide):
            self.finish()
        return False

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        for index, rect in enumerate(self.rects):
            alpha = self._alpha(index)
            if alpha <= 0.0:
                continue
            painter.setOpacity(alpha)
            painter.fillRect(rect.adjusted(-2, -2, 2, 2), self.color)
        painter.end()


def _list_items(area) -> tuple:
    """(container, [rects in container]) of the cards a scroll area shows now, top to bottom."""
    from PySide6.QtWidgets import QAbstractItemView
    viewport = area.viewport()
    visible = viewport.rect()
    rects = []
    if isinstance(area, QAbstractItemView):
        model = area.model()
        if model is None:
            return viewport, []
        index = area.indexAt(QPoint(4, 4))
        row = index.row() if index.isValid() else 0
        for r in range(row, min(model.rowCount(), row + 40)):
            rect = area.visualRect(model.index(r, 0))
            if rect.isValid() and rect.intersects(visible):
                rects.append(rect)
            elif rect.top() > visible.bottom():
                break
        return viewport, rects
    content = getattr(area, 'widget', lambda: None)()
    if content is None:
        return viewport, []
    level = content
    for _depth in range(3):              # step into a lone wrapper to reach the cards
        children = [c for c in level.children() if isinstance(c, QWidget) and c.isVisible()
                    and not c.isWindow() and c.objectName() not in ('pageCrossfade', 'staggerVeils')]
        if len(children) == 1:
            level = children[0]
            continue
        break
    for child in children:
        rect = QRect(child.mapTo(viewport, QPoint(0, 0)), child.size())
        if rect.intersects(visible) and rect.width() > 24 and rect.height() > 16:
            rects.append(rect)
    rects.sort(key=lambda r: (r.top(), r.left()))
    return viewport, rects[:24]


def stagger_list(area) -> StaggerVeils | None:
    """Let the cards ``area`` shows come in one after another (see ``StaggerVeils``)."""
    if not enabled() or area is None or not area.isVisible() or has_visible_native_child(area):
        return None
    container, rects = _list_items(area)
    if len(rects) < 2:
        return None
    for old in container.findChildren(StaggerVeils, options=Qt.FindChildOption.FindDirectChildrenOnly):
        old.finish()
    first = rects[0]
    probe = QPoint(max(1, first.left() - 3), first.top() + 3) if first.left() > 5 else \
        QPoint(first.center().x(), max(1, first.top() - 3))
    sample = container.grab(QRect(probe, QSize(2, 2))).toImage()
    if sample.isNull():
        return None
    veils = StaggerVeils(container, rects, sample.pixelColor(0, 0), area)
    veils.start()
    return veils


def stagger_page(page: QWidget) -> StaggerVeils | None:
    """The biggest list on a page that just appeared lets its cards come in one after another."""
    from PySide6.QtWidgets import QAbstractScrollArea
    if not enabled() or page is None or not page.isVisible():
        return None
    areas = [a for a in page.findChildren(QAbstractScrollArea) if a.isVisible() and a.viewport().width() > 200
             and a.viewport().height() > 120 and a.property('staggerMotion') is not False]
    if not areas:
        return None
    area = max(areas, key=lambda a: a.viewport().width() * a.viewport().height())
    return stagger_list(area)


class PanelSlide(QWidget):
    """A side panel's picture sliding out to its side or in from it, in a click-through window.

    2026-11-18 evening (user: the tool panel should fold away to the right, the subtitle list to
    the left, not fade). The panel's width cannot animate (the native video beside it would
    resize every frame), so the layout changes in one step and only this picture moves: a pure
    translation of a panel-sized picture, which keeps 60 fps without a GPU.
    """

    def __init__(self, host: QWidget, pixmap: QPixmap, rect: QRect, side: str, entering: bool, then=None):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        super().__init__(host.window(), flags)
        self.setObjectName('panelSlide')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(rect)
        self.pixmap = pixmap
        self.side = side
        self.entering = entering
        self.then = then
        self.token = tokens.PANEL_SLIDE_IN if entering else tokens.PANEL_SLIDE_OUT
        self._curve = tokens.easing_curve(self.token)
        self.progress = 0.0
        self._elapsed = 0.0
        self._last = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)
        self.host = host
        host.window().installEventFilter(self)

    def start(self):
        _keep_heap_quiet()                 # before the overdue collector tick, too
        self.show()
        self.raise_()
        self._timer.start(_frame_ms(self))

    def _step(self):
        _keep_heap_quiet()
        now = time.perf_counter()
        if self._last is None:
            self._last = now
            return
        gap = (now - self._last) * 1000
        self._last = now
        if gap > tokens.MAX_FRAME_GAP_MS:
            self.finish()
            return
        self._elapsed += gap
        p = min(1.0, self._elapsed / self.token.ms)
        self.progress = self._curve.valueForProgress(p)
        self.update()
        if p >= 1.0:
            self.finish()

    def finish(self):
        from shiboken6 import isValid
        if not isValid(self):
            return
        self._timer.stop()
        then, self.then = self.then, None
        if isValid(self.host) and self.host.window() is not None:
            self.host.window().removeEventFilter(self)
        if then is not None:
            then()                         # the real panel appears in the same frame the picture leaves
        self.hide()
        self.deleteLater()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide,
                            QEvent.Type.WindowStateChange):
            self.finish()
        return False

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        k = self.progress
        away = (1.0 - k) if self.entering else k             # 0 = in place, 1 = fully outside
        width = self.width()
        dx = round(away * width) * (1 if self.side == 'right' else -1)
        painter = QPainter(self)
        draw_picture(painter, QPoint(dx, 0), self.pixmap)
        painter.end()


def _slidable(panel) -> bool:
    window = panel.window() if panel is not None else None
    return bool(enabled() and window is not None and window.isVisible() and not window.isMinimized()
                and window.isActiveWindow() and panel.property('transitionMotion') is not False
                and not has_visible_native_child(panel))


class panel_slide_out:
    """``with panel_slide_out(panel, 'right'): panel.hide()`` — its picture slides off to that side."""

    def __init__(self, panel: QWidget, side: str):
        self.panel, self.side = panel, side
        self.pixmap = self.rect = None

    def __enter__(self):
        panel = self.panel
        if panel is not None and panel.isVisible() and _slidable(panel) and panel.width() >= 80:
            self.pixmap = _screen_pixels(panel)
            self.rect = QRect(panel.mapToGlobal(panel.rect().topLeft()), panel.size())
        return self

    def __exit__(self, *exc):
        host = self.panel.parentWidget() if self.panel is not None else None
        if self.pixmap is not None and exc[0] is None and host is not None and host.isVisible():
            PanelSlide(host, self.pixmap, self.rect, self.side, entering=False).start()
        return False


def slide_panel_in(panel: QWidget, rect_in_parent: QRect, side: str, then) -> bool:
    """Slide ``panel``'s picture in from ``side`` into ``rect_in_parent`` (its place once shown),
    then call ``then`` (which shows the real panel). False when it should just be shown now."""
    host = panel.parentWidget() if panel is not None else None
    # The host holds the video, the hidden panel holds nothing visible: check the panel itself.
    if host is None or not host.isVisible() or not _slidable(panel) or rect_in_parent.width() < 80:
        return False
    if panel.size() != rect_in_parent.size():
        panel.resize(rect_in_parent.size())
    layout = panel.layout()
    if layout is not None:
        layout.activate()
    pixmap = panel.grab()                  # rendered while still hidden, at its final size
    if pixmap.isNull():
        return False
    rect = QRect(host.mapToGlobal(rect_in_parent.topLeft()), rect_in_parent.size())
    PanelSlide(host, pixmap, rect, side, entering=True, then=then).start()
    return True


class panel_fade_out:
    """``with panel_fade_out(panel): panel.hide()`` — its picture fades away where it was.

    Only the panel's own pixels are copied (from its native parent: about a millisecond), not the
    desktop (43-48 ms measured with video beside it), and they fade in a click-through window, so
    the widened video next to it shows through as the panel dissolves.
    """

    def __init__(self, panel: QWidget):
        self.panel = panel
        self.pixmap = None
        self.rect = None

    def __enter__(self):
        panel = self.panel
        if (panel is not None and panel.isVisible() and not has_visible_native_child(panel)
                and panel.window() is not None and panel.window().isActiveWindow()):
            self.pixmap = capture_region(panel, minimum=(80, 60))
            self.rect = QRect(panel.mapToGlobal(panel.rect().topLeft()), panel.size())
        return self

    def __exit__(self, *exc):
        host = self.panel.parentWidget() if self.panel is not None else None
        if self.pixmap is not None and exc[0] is None and host is not None and host.isVisible():
            overlay = PageCrossfade(host, self.pixmap, step_back=True, floating=True, global_rect=self.rect)
            overlay.start()
        return False


class content_change:
    """``with content_change(widget): <change what it shows>`` — the old picture fades over the new.

    For content that changes in place without a stacked page switch (a list filtered by a tab,
    another word library loaded into the same card wall, a detail panel filled in). Nothing waits:
    the new content is live at once, the picture of the old one fades out over it.
    """

    def __init__(self, widget: QWidget, *, minimum=(80, 60)):
        self.widget = widget
        self.minimum = minimum
        self.pixmap = None

    def __enter__(self):
        self.pixmap = capture_region(self.widget, minimum=self.minimum)
        return self

    def __exit__(self, *exc):
        if self.pixmap is not None and exc[0] is None:
            start_page_crossfade(self.widget, self.pixmap)
        return False


def has_visible_native_child(widget: QWidget) -> bool:
    """A visible native child window (video) under ``widget``: an overlay could not cover it."""
    if widget is None:
        return False
    return any(child.testAttribute(Qt.WidgetAttribute.WA_NativeWindow) and child.isVisible()
               for child in widget.findChildren(QWidget))


_has_visible_native_child = has_visible_native_child


class StackFades(QObject):
    """Every ``QStackedWidget`` / ``QTabWidget`` page switch in the app fades (2026-11-18).

    Qt hides the old page before it shows the new one, and at the old page's Hide the screen still
    holds its pixels: they are copied then, and laid over the new page once it is shown.
    """

    MIN_SIZE = (120, 80)

    def __init__(self, app):
        super().__init__(app)
        self.setObjectName('stackFades')
        self._pending: dict[int, tuple] = {}

    def on_event(self, watched, event) -> bool:
        kind = event.type()
        stack = watched.parentWidget() if isinstance(watched, QWidget) else None
        if stack is None or not _is_stack_page(stack, watched):
            return False
        key = _key(stack)
        if kind == QEvent.Type.Hide:
            if (key in _OWNED or not stack.isVisible() or stack.property('transitionMotion') is False
                    or key in self._pending or _ACTIVE_FADES or any(_OWNED)):
                return False               # a page fade is already showing: one layer at a time
            pixmap = capture_region(stack, minimum=self.MIN_SIZE)
            if pixmap is not None:
                self._pending[key] = (stack, pixmap, time.perf_counter())
                QTimer.singleShot(200, lambda key=key: self._pending.pop(key, None))   # no new page came
        elif kind == QEvent.Type.Show:
            pending = self._pending.pop(key, None)
            if pending is not None and time.perf_counter() - pending[2] < 0.2:
                stack_, pixmap, _at = pending
                QTimer.singleShot(0, lambda s=stack_, p=pixmap: _start_if_alive(s, p))
        return False


def _is_stack_page(stack, page) -> bool:
    from PySide6.QtWidgets import QStackedWidget
    return isinstance(stack, QStackedWidget) and stack.indexOf(page) >= 0


def _start_if_alive(stack, pixmap):
    from shiboken6 import isValid
    if isValid(stack) and stack.isVisible() and not _ACTIVE_FADES:
        start_page_crossfade(stack, pixmap)


# ====================================================================== dialogs
class _Ghost(QWidget):
    """Draws a dialog's picture moving between two rects (global coordinates), ignoring the mouse.

    2026-11-19 (user: closing the settings or other windows still flashes; opening them has no
    real motion): recorded, a closing dialog vanished, Home showed for a moment, and then its
    picture came back and shrank; opening, the dim came first and the dialog only began to grow
    0.15 s later. The ghost was a top-level window made for each motion, and Windows shows a new
    window only after the event loop has run again. With the main window's kept cover
    (``StageCover``) the ghost is drawn into that, at once; elsewhere it is its own window as before.
    """

    def __init__(self, pixmap: QPixmap, area: QRect, cover=None):
        if cover is not None:
            super().__init__(cover)
        else:
            flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                     | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput
                     | Qt.WindowType.WindowStaysOnTopHint)
            super().__init__(None, flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.cover = cover
        self.setObjectName('dialogGhost')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.pixmap = pixmap
        self.area = QRect(area)
        self.rect_now = QRectF()
        self.opacity = 0.0
        self.parts = []                    # the dialog's sections rising in while it grows (opening)
        self.clock_ms = 0.0
        self.place(area)

    def cascade_ms(self) -> float:
        """When the last section has come to rest (0 without sections)."""
        if not self.parts:
            return 0.0
        return _dialog_part_delay(len(self.parts) - 1) + _spring_rest_ms(tokens.DIALOG_PART_RISE, tokens.DIALOG_PART_RISE_PX)

    def place(self, area: QRect) -> None:
        self.area = QRect(area)
        if self.cover is not None:
            self.setGeometry(QRect(self.cover.mapFromGlobal(area.topLeft()), area.size()))
        else:
            self.setGeometry(area)

    def appear(self) -> None:
        if self.cover is not None:
            self.cover.follow()
            self.cover.stack_over_owner()
        self.show()
        self.raise_()
        if self.cover is not None:
            self.repaint()                 # on the screen now, not at the next event-loop turn

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        if self.rect_now.isEmpty() or self.opacity <= 0.0:
            return
        painter = QPainter(self)
        target = self.rect_now.translated(-self.area.topLeft().x(), -self.area.topLeft().y())
        exact = abs(target.width() - self.pixmap.width() / (self.pixmap.devicePixelRatio() or 1.0)) < 0.5
        # Smooth scaling of a dialog-sized picture costs most of a frame without a GPU; while it is
        # moving a plain scale is not visible, and at rest it is drawn 1:1 anyway.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, exact)
        painter.setOpacity(max(0.0, min(1.0, self.opacity)))
        if self.parts and self.clock_ms < self.cascade_ms():
            self._paint_cascade(painter, target)
        elif exact:
            draw_picture(painter, target.topLeft(), self.pixmap)
        else:
            painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        painter.end()

    def _paint_cascade(self, painter, target: QRectF) -> None:
        """2026-11-19 (user: the settings and the tutorial open with no motion of their own): the
        window's frame grows as before, and its sections rise into place one after another."""
        from PySide6.QtGui import QRegion
        ratio = self.pixmap.devicePixelRatio() or 1.0
        width = self.pixmap.width() / ratio
        scale = target.width() / width if width else 1.0
        base_opacity = painter.opacity()
        moved = []
        for part in self.parts:
            moved.append(QRectF(target.x() + part.x() * scale, target.y() + part.y() * scale,
                                part.width() * scale, part.height() * scale))
        rest = QRegion(target.toAlignedRect())
        for rect in moved:
            rest = rest.subtracted(QRegion(rect.toAlignedRect()))
        painter.save()
        painter.setClipRegion(rest)
        painter.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        painter.restore()
        fade = tokens.easing_curve(tokens.DIALOG_PART_FADE)
        for index, (part, rect) in enumerate(zip(self.parts, moved)):
            local = self.clock_ms - _dialog_part_delay(index)
            if local <= 0:
                continue
            rise = tokens.DIALOG_PART_RISE_PX * (1.0 - spring_progress(tokens.DIALOG_PART_RISE, local)) * scale
            painter.setOpacity(base_opacity * fade.valueForProgress(min(1.0, local / tokens.DIALOG_PART_FADE.ms)))
            painter.drawPixmap(rect.translated(0, rise), self.pixmap, _source(part, ratio))
        painter.setOpacity(base_opacity)



def _dialog_part_delay(index: int) -> float:
    return tokens.DIALOG_PART_DELAY_MS + min(index, tokens.DIALOG_PART_STEPS) * tokens.DIALOG_PART_STAGGER_MS


def _lerp_rect(a: QRectF, b: QRectF, k: float) -> QRectF:
    return QRectF(a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k,
                  a.width() + (b.width() - a.width()) * k, a.height() + (b.height() - a.height()) * k)


def _shrunk_into(origin: QRect, full: QRect) -> QRectF:
    """Where a dialog starts (and ends when closing): smaller, a little toward the button it came from.

    2026-11-18 evening (user: low frame rate, twitching): it used to start at the button itself at
    a quarter of its size, so the ghost window spanned button and dialog and scaled a big picture
    a long way. Now it starts at 72 % about a point 40 % of the way from the dialog to the button.
    """
    scale = 0.72
    width, height = full.width() * scale, full.height() * scale
    dialog_centre, button = QPointF(full.center()), QPointF(origin.center())
    centre = dialog_centre + (button - dialog_centre) * 0.4
    return QRectF(centre.x() - width / 2, centre.y() - height / 2, width, height)


class _Flight:
    """One ghost flight: grow (open) or shrink (close); a spring or a tween drives ``k`` 0 → 1."""

    def __init__(self, motion, dialog, ghost: _Ghost, start: QRectF, end: QRectF, opening: bool):
        self.motion = motion
        self.dialog = dialog
        self.ghost = ghost
        self.start = start
        self.end = end
        self.opening = opening
        self.k = 0.0
        self.vel = 0.0
        self.clock = 0.0               # seconds of motion played (busy frames do not skip ahead)

    def advance(self, dt: float) -> bool:
        """Step; False when finished."""
        self.clock += dt
        self.ghost.clock_ms = self.clock * 1000
        if self.opening and self.dialog is not None:
            # The dialog may still settle its own size or place after showing (e.g. 批量替换):
            # follow it, so the ghost lands exactly where the real one is and nothing jumps.
            real = QRectF(self.dialog.frameGeometry())
            if real != self.end:
                self.end = real
                fresh = self.dialog.grab()
                if not fresh.isNull():
                    self.ghost.pixmap = fresh
                area = QRectF(self.ghost.area).united(real).toAlignedRect()
                if area != self.ghost.area:
                    self.ghost.place(area)
        if self.opening:
            stiffness, coefficient = tokens.DIALOG_IN.constants()
            left = dt
            while left > 0:
                h = min(left, _SUBSTEP)
                self.vel += (-stiffness * (self.k - 1.0) - coefficient * self.vel) * h
                self.k += self.vel * h
                left -= h
            # Within half a pixel on a dialog-sized move: hand over to the real dialog now rather
            # than spending another ~0.3 s on the spring's last invisible creep.
            done = (abs(self.k - 1.0) < 0.006 and abs(self.vel) < 0.08
                    and self.clock * 1000 >= self.ghost.cascade_ms())
            self.ghost.opacity = min(1.0, self.clock * 1000 / tokens.DIALOG_FADE_IN.ms)
        else:
            p = min(1.0, self.clock * 1000 / tokens.DIALOG_OUT.ms)
            from .motion_tokens import easing_curve
            self.k = easing_curve(tokens.DIALOG_OUT).valueForProgress(p)
            self.ghost.opacity = 1.0 - self.k
            done = p >= 1.0
        self.ghost.rect_now = _lerp_rect(self.start, self.end, 1.0 if done and self.opening else self.k)
        self.ghost.update()
        return not done


class DialogMotion(QObject):
    """Grows dialogs out of the pressed button and shrinks them back (see the module text)."""

    ORIGIN_MAX_AGE_S = 1.5

    def __init__(self, app):
        super().__init__(app)
        self.setObjectName('dialogMotion')
        self._flights: dict[int, _Flight] = {}
        self._origins: dict[int, QRect] = {}
        self.last_clicked = None           # (global QRect, perf_counter) of the last clicked card/widget
        self._click_stamp = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)
        self._last = time.perf_counter()

    # ------------------------------------------------------------------ which dialogs
    @staticmethod
    def eligible(dialog) -> bool:
        if not isinstance(dialog, QDialog) or not dialog.isWindow():
            return False
        if dialog.property('transitionMotion') is False or not enabled() or QApplication.closingDown():
            return False
        from PySide6.QtWidgets import QColorDialog, QFileDialog, QFontDialog
        if isinstance(dialog, (QFileDialog, QColorDialog, QFontDialog)):
            return False
        screen = dialog.screen()
        if screen is not None:
            available = screen.availableGeometry()
            if dialog.width() > available.width() * 0.9 or dialog.height() > available.height() * 0.9:
                return False
        if dialog.isMaximized() or dialog.isFullScreen():
            return False
        if any(child.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
               for child in dialog.findChildren(QWidget)):
            return False
        return True

    def _origin(self) -> QRect | None:
        """Where the dialog grows from: the button just pressed, or the card just clicked."""
        app = QApplication.instance()
        motion = getattr(app, '_press_motion', None)
        candidates = [c for c in (getattr(motion, 'last_pressed', None), self.last_clicked) if c is not None]
        if not candidates:
            return None
        rect, at = max(candidates, key=lambda c: c[1])
        return QRect(rect) if time.perf_counter() - at <= self.ORIGIN_MAX_AGE_S else None

    def _note_click(self, watched, event):
        """Remember the clicked card (or widget): a dialog it opens grows out of it."""
        if not isinstance(watched, QWidget) or watched.isWindow():
            return
        stamp = (event.timestamp(), round(event.globalPosition().x()), round(event.globalPosition().y()))
        if stamp == self._click_stamp:
            return                         # the same click, bubbling up to a parent
        self._click_stamp = stamp
        target, probe = watched, watched
        for _level in range(5):            # prefer a card around the clicked label
            name = type(probe).__name__ + (probe.objectName() or '')
            if 'Card' in name or 'card' in name:
                target = probe
                break
            probe = probe.parentWidget()
            if probe is None or probe.isWindow():
                break
        self.last_clicked = (QRect(target.mapToGlobal(target.rect().topLeft()), target.size()), time.perf_counter())

    # ------------------------------------------------------------------ events
    def on_event(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.DynamicPropertyChange and watched is QApplication.instance():
            if event.propertyName() == b'reduceMotion':
                _sync_menu_effects()
            return False
        if kind == QEvent.Type.MouseButtonPress:
            self._note_click(watched, event)
            return False
        if not isinstance(watched, QDialog) or not watched.isWindow():
            return False
        if kind == QEvent.Type.Show:
            self.opening(watched)
        elif kind == QEvent.Type.Hide:
            self.closing(watched)
        return False

    def opening(self, dialog) -> bool:
        key = _key(dialog)
        self._drop(key, restore=True)
        if not self.eligible(dialog):
            return False
        _keep_heap_quiet()                         # now: the flight itself starts a turn later
        origin = self._origin()
        self._origins[key] = origin
        dialog.setWindowOpacity(0.0)               # open and usable, but the ghost is what you see
        QTimer.singleShot(GHOST_SAFETY_MS, lambda d=dialog: _restore(d))
        QTimer.singleShot(0, lambda d=dialog, o=origin: self._launch_open(d, o))
        return True

    def _launch_open(self, dialog, origin):
        from shiboken6 import isValid
        if not isValid(dialog) or not dialog.isVisible():
            return
        full = QRect(dialog.frameGeometry())
        pixmap = dialog.grab()
        if pixmap.isNull():
            _restore(dialog)
            return
        if origin is not None:
            start = _shrunk_into(origin, full)
        else:                                      # opened by a key or by code: a gentle swell from 96 %
            width, height = full.width() * 0.96, full.height() * 0.96
            start = QRectF(full.center().x() - width / 2, full.center().y() - height / 2 + 8, width, height)
        area = QRectF(full).united(start).toAlignedRect().adjusted(-4, -4, 4, 4)
        ghost = _Ghost(pixmap, area, _dialog_cover(dialog, area))
        if full.width() >= 420 and full.height() >= 300 and dialog.property('contentCascade') is not False:
            try:
                ghost.parts = page_parts(dialog, dialog, None, tokens.DIALOG_PARTS_MAX)
            except Exception:  # noqa: BLE001 - it then simply grows, as before
                ghost.parts = []
        flight = _Flight(self, dialog, ghost, start, QRectF(full), opening=True)
        ghost.rect_now = start
        ghost.appear()
        self._flights[_key(dialog)] = flight
        self._run(dialog)

    def closing_now(self, dialog) -> bool:
        """The dialog is about to hide (SpringDialog.done): its picture is put up while it is still
        on the screen, so nothing is seen between it and its shrinking picture. Its Hide event then
        starts nothing more."""
        if dialog is None or not dialog.isVisible():
            return False
        started = self.closing(dialog)
        if started:
            dialog._closing_ghost_up = True
        return started

    def closing(self, dialog) -> bool:
        if dialog.__dict__.pop('_closing_ghost_up', False):
            return False                    # already done just before it hid (closing_now)
        key = _key(dialog)
        self._drop(key, restore=True)
        origin = self._origins.pop(key, None)
        owner = dialog.parentWidget().window() if dialog.parentWidget() is not None else None
        if not self.eligible(dialog) or (owner is not None and (owner.isMinimized() or not owner.isVisible())):
            _restore(dialog)
            return False
        full = QRect(dialog.frameGeometry())
        pixmap = dialog.grab()
        _restore(dialog)
        if pixmap.isNull():
            return False
        end = _shrunk_into(origin, full) if origin is not None else QRectF(
            full.center().x() - full.width() * 0.48, full.center().y() - full.height() * 0.48 + 6,
            full.width() * 0.96, full.height() * 0.96)
        area = QRectF(full).united(end).toAlignedRect().adjusted(-4, -4, 4, 4)
        ghost = _Ghost(pixmap, area, _dialog_cover(dialog, area))
        ghost.opacity = 1.0
        ghost.rect_now = QRectF(full)
        ghost.appear()
        flight = self._flights[key] = _Flight(self, None, ghost, QRectF(full), end, opening=False)
        flight.owner = owner
        self._run(ghost)
        return True

    # ------------------------------------------------------------------ frames
    def _run(self, widget):
        _keep_heap_quiet()                 # before the overdue collector tick, too
        if not self._timer.isActive():
            self._last = None              # the clock starts at the first frame the GUI gets to
            self._timer.start(_frame_ms(widget))

    def _step(self):
        _keep_heap_quiet()
        from shiboken6 import isValid
        now = time.perf_counter()
        if self._last is None:
            self._last = now
            return
        gap = now - self._last
        self._last = now
        late = gap * 1000 > tokens.MAX_FRAME_GAP_MS
        dt = min(0.05, max(0.0, gap))
        for key, flight in list(self._flights.items()):
            if flight.opening and (not isValid(flight.dialog) or not flight.dialog.isVisible()):
                self._drop(key, restore=True)
                continue
            owner = getattr(flight, 'owner', None)
            if owner is not None and (not isValid(owner) or not owner.isVisible()):
                self._drop(key, restore=True)       # its window is gone: no picture left behind
                continue
            if late:                       # busy GUI: show the end at once instead of a stutter
                self._drop(key, restore=True)
                continue
            if not flight.advance(dt):
                if flight.opening:
                    _restore(flight.dialog)        # the real dialog takes over in the same frame
                self._flights.pop(key, None)
                _close_ghost(flight.ghost)
        if not self._flights:
            self._timer.stop()

    def _drop(self, key, restore: bool):
        flight = self._flights.pop(key, None)
        if flight is None:
            return
        if restore and flight.dialog is not None:
            _restore(flight.dialog)
        _close_ghost(flight.ghost)

    def flying(self, dialog=None) -> bool:
        return bool(self._flights) if dialog is None else _key(dialog) in self._flights


def end_all(suspend_s: float = 0.0) -> None:
    """Every motion of the application ends on its final picture now, and none starts for
    ``suspend_s`` seconds.

    2026-11-19 (user: the app is already closed, but the 「确认关闭」 window is still there until
    its animation has played): the confirmation's closing picture is its own always-on-top window.
    It was shown when the dialog closed, and then the main window's closing kept the GUI thread
    busy, so the picture stood on the desktop after the main window was gone and only then played.
    The main window calls this as soon as closing is confirmed."""
    global _SUSPENDED_UNTIL
    if suspend_s > 0:
        _SUSPENDED_UNTIL = max(_SUSPENDED_UNTIL, time.perf_counter() + suspend_s)
    app = QApplication.instance()
    motion = getattr(app, '_dialog_motion', None) if app is not None else None
    if motion is not None:
        for key in list(motion._flights):
            motion._drop(key, restore=True)
        motion._timer.stop()
    for fade in list(_ACTIVE_FADES):
        try:
            fade.finish()
        except RuntimeError:
            _ACTIVE_FADES.discard(fade)
    for overlays in list(_FLOATING.values()):
        for overlay in list(overlays):
            try:
                overlay.finish()
            except RuntimeError:
                pass


def _dialog_cover(dialog, area: QRect):
    """The kept cover of the window ``dialog`` belongs to, when the whole motion fits inside it."""
    parent = dialog.parentWidget() if dialog is not None else None
    owner = parent.window() if parent is not None else None
    cover = stage_cover(owner) if owner is not None else None
    if cover is None:
        return None
    inside = QRect(cover.mapToGlobal(QPoint(0, 0)), cover.size())
    return cover if inside.contains(area) else None


def closing_now(dialog) -> bool:
    """Call right before a dialog hides itself (see ``DialogMotion.closing_now``)."""
    app = QApplication.instance()
    motion = getattr(app, '_dialog_motion', None) if app is not None else None
    if motion is None:
        return False
    try:
        return motion.closing_now(dialog)
    except Exception:  # noqa: BLE001 - it hides either way
        return False


def handles(dialog) -> bool:
    """True when the app-wide dialog motion opens and closes ``dialog``: its own fade must stand down."""
    app = QApplication.instance()
    motion = getattr(app, '_dialog_motion', None) if app is not None else None
    return motion is not None and motion.eligible(dialog)


def _restore(dialog):
    from shiboken6 import isValid
    if dialog is not None and isValid(dialog) and dialog.windowOpacity() < 1.0:
        dialog.setWindowOpacity(1.0)


def _close_ghost(ghost):
    from shiboken6 import isValid
    if ghost is not None and isValid(ghost):
        ghost.hide()
        ghost.deleteLater()


def _key(widget) -> int:
    from shiboken6 import getCppPointer
    return int(getCppPointer(widget)[0])


def _sync_menu_effects():
    animate = enabled()
    # Rounded combo popups keep their existing policy. Qt's opaque
    # roll-down effect painted black corners in the Windows theme.
    for effect in (Qt.UIEffect.UI_General, Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu,
                   Qt.UIEffect.UI_AnimateTooltip, Qt.UIEffect.UI_FadeTooltip):
        QApplication.setEffectEnabled(effect, animate)


def install(app=None) -> DialogMotion | None:
    """Give every dialog of the application its open and close motion (once)."""
    app = app or QApplication.instance()
    if app is None:
        return None
    existing = getattr(app, '_dialog_motion', None)
    if existing is not None:
        return existing
    # Installed at startup right after the QApplication: from here on a lazy import inside a
    # click or a motion frame no longer reads that module's source file (system.pyside_import_check).
    from ..system.pyside_import_check import install as install_import_check
    install_import_check()
    from .app_events import listen
    motion = app._dialog_motion = DialogMotion(app)
    listen(motion, (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.MouseButtonPress,
                    QEvent.Type.DynamicPropertyChange), motion.on_event)
    fades = app._stack_fades = StackFades(app)
    listen(fades, (QEvent.Type.Show, QEvent.Type.Hide), fades.on_event)
    _sync_menu_effects()
    return motion


__all__ = ['DialogMotion', 'PageCrossfade', 'PageHold', 'capture_page', 'enabled', 'end_all', 'install', 'is_held',
           'start_page_crossfade', 'start_page_hold']
