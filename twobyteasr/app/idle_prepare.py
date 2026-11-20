"""Prepare the surfaces people open next while Home is idle (2026-11-18).

The user asked for every load to show within 0.2 s. The first Application
Settings window, the first model workshop visit and Studio's first sheet were
built at click time (221-470 ms before anything showed). This runs that work
earlier, on the GUI thread (Qt widgets live there), as short steps with an
event-loop turn between them, only while Home is idle: no pressed mouse button,
no popup, no modal window, no tour and no recent navigation. Leaving Home
pauses it; the click paths still build anything that is not ready yet.
"""
from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

STEP_GAP_MS = 16
WAIT_MS = 400


class IdlePreparation(QObject):
    """Drive a generator of GUI-thread steps one event-loop turn at a time."""

    def __init__(self, parent, steps, *, allowed):
        super().__init__(parent)
        self._steps = steps
        self._allowed = allowed
        self.done = False
        self.timings: list[float] = []
        self._pointer = None
        self._pointer_seen = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._step)

    def start(self) -> None:
        if not self.done and not self._timer.isActive():
            self._timer.start(STEP_GAP_MS)

    def _idle(self) -> bool:
        if (QApplication.mouseButtons() != Qt.MouseButton.NoButton or QApplication.activePopupWidget()
                or QApplication.activeModalWidget()):
            return False
        # 2026-11-19: not while the pointer is moving. A step takes up to 0.3 s on the GUI thread,
        # and a moving pointer is about to click something: preparation waits until it rests.
        from PySide6.QtGui import QCursor
        at = QCursor.pos()
        moved, self._pointer = at != self._pointer, at
        if moved and self._pointer_seen:
            return False
        self._pointer_seen = True
        try:
            return bool(self._allowed())
        except Exception:  # noqa: BLE001 - a closing window is simply not idle
            return False

    def _step(self) -> None:
        if self.done:
            return
        if not self._idle():
            self._timer.start(WAIT_MS)
            return
        began = time.perf_counter()
        try:
            next(self._steps)
        except StopIteration:
            self.done = True
            return
        except Exception:  # noqa: BLE001 - preparation is optional; the click path still works
            log.exception('idle preparation stopped')
            self.done = True
            return
        finally:
            self.timings.append((time.perf_counter() - began) * 1000)
        self._timer.start(STEP_GAP_MS)


def window_steps(window):
    """Studio's sheet, the settings window, then whatever ``page_steps`` has not done yet."""
    yield from _studio_sheet_steps()
    from .application_settings import prepare_application_settings_steps
    yield from prepare_application_settings_steps(window)
    yield from page_steps(window)


def page_steps(window):
    """The model workshop, the term library and the recognition history, complete while hidden.

    2026-11-19 (user: going to a page flashes two or three times before it is there): a first
    visit built the page in front of the user (placeholders, then half, then all). The pages are
    built here, soon after startup and before Studio's modules, down to the last model card, so a
    visit finds a finished page. A visit before this is done waits behind the old page's picture
    (``design.transitions.PageHold``) instead of showing the stages.
    """
    yield from _workshop_steps(window)
    yield from _term_library_steps(window)
    yield from _history_steps(window)


def _studio_sheet_steps():
    # Cached per theme. Its first build writes the control icons and loads the
    # loading font (about 0.1 s) while Studio's construction step waited on it.
    from ..design.studio_theme import build_studio_qss
    build_studio_qss()
    yield


def _workshop_steps(window):
    page = window.built_page('workshop')
    if page is None:
        page = window.workshop_page   # constructing it starts its background status check
        yield
    yield from page.prepare_hidden_steps()
    yield from presize_hidden_page(page)
    # Every model card, not only the first ones: left for the visit they were built in front of
    # the user behind a grey placeholder list (about a second). One card a turn; the layout pass
    # for all of them is paid here (presize), not by a later click.
    viewport = getattr(page, '_card_viewport', None)
    built = False
    for card in list((getattr(viewport, 'cards', None) or {}).values()):
        if page.isVisible():
            return
        if getattr(card, '_card', True) is None:
            card.materialize()
            built = True
            yield
    if built:
        yield from presize_hidden_page(page)
    yield from prerender_hidden_page(window, page)


def _history_steps(window):
    # Built on the first visit until 2026-11-19 (its module, the page and the first read of the
    # reports). The reports are read in its own thread; the cards come with the first showing.
    if window.built_page('history') is None:
        window._construct_lazy_page('history')
        yield
    page = window.built_page('history')
    if page is not None:
        yield from presize_hidden_page(page)
        yield from prerender_hidden_page(window, page)


def _term_library_steps(window):
    # 2026-11-18: its first visit imported the glossary modules and built the
    # library after the switch (320-530 ms); see TermLibraryPage.prepare_hidden_steps.
    prepare = getattr(getattr(window, 'term_library_page', None), 'prepare_hidden_steps', None)
    if prepare is not None:
        yield from prepare()
        yield from presize_hidden_page(window.term_library_page)
        yield from prerender_hidden_page(window, window.term_library_page)


def presize_hidden_page(page):
    """Lay a prepared page out at the size the page stack will give it.

    A hidden stack page keeps its old geometry (QStackedLayout sizes only the
    current page), so the first switch resized and laid out the whole page
    inside the click. Done here, the switch finds the layout already current
    unless the window was resized since.
    """
    from shiboken6 import isValid
    stack = page.parentWidget() if isValid(page) else None
    if stack is None or page.isVisible() or stack.contentsRect().isEmpty():
        return
    page.setGeometry(future_page_rect(page, stack))
    layout = page.layout()
    if layout is not None:
        yield
        if isValid(page) and not page.isVisible():
            layout.activate()


def future_page_rect(page, stack):
    """The rectangle ``page`` will have when shown. Home's start bar under the page stack is
    hidden on every other page, and the stack then grows by its height (2026-11-19: prepared at
    Home's height, a page was laid out and drawn again at its real size on the first visit)."""
    rect = stack.contentsRect()
    window = page.window()
    bar = getattr(window, 'bottom_bar', None)
    try:
        if (bar is not None and bar.isVisible() and page is not getattr(window, 'settings_scroll', None)
                and bar.parentWidget() is stack.parentWidget()):
            layout = getattr(window, 'content_layout', None)
            rect.setHeight(rect.height() + bar.height() + (layout.spacing() if layout is not None else 0))
    except RuntimeError:
        pass
    return rect


def prerender_hidden_page(window, page):
    """Do once, hidden, what a page's first showing does: the interface language and zoom are put
    on it, every widget is polished and it is drawn once into a picture nobody sees (2026-11-19).

    User (2026-11-19): going to the model workshop or the term library stalls first, so the motion
    after it is not felt at all. Recorded, a first visit kept the old page 0.3-0.5 s: the language
    pass of the switch, the layout of widgets shown for the first time and the first drawing of
    every widget (text layout, icons, style rules), all on the click. A second visit took 0.1 s.
    After this, a first visit costs what a second one does.
    """
    from shiboken6 import isValid
    if not isValid(page) or page.isVisible() or os.environ.get('TWOBYTEASR_PAGE_PRERENDER', '1') == '0':
        return
    prepare = getattr(window, '_prepare_page_presentation', None)
    if callable(prepare):
        prepare(page)
        yield
    if not isValid(page) or page.isVisible():
        return
    page.ensurePolished()
    layout = page.layout()
    if layout is not None:
        layout.activate()
    yield
    if not isValid(page) or page.isVisible() or page.width() < 2 or page.height() < 2:
        return
    from PySide6.QtGui import QPixmap
    ratio = page.devicePixelRatioF() or 1.0
    picture = QPixmap(max(1, round(page.width() * ratio)), max(1, round(page.height() * ratio)))
    picture.setDevicePixelRatio(ratio)
    picture.fill(Qt.GlobalColor.transparent)
    page.render(picture)


def _home_idle(window) -> bool:
    # _studio_idle_allowed also says yes while a Studio entry is queued (its
    # module preload must go on); preparation must not compete with it.
    if (window.__dict__.get('_studio_entry_pending') is not None
            or window.__dict__.get('_studio_page_building') is not None):
        return False
    return bool(window._studio_idle_allowed())


def start_pages(window) -> IdlePreparation:
    """Start building the pages (once per window), soon after the window is up."""
    runner = window.__dict__.get('_page_preparation')
    if runner is None:
        owner = window if isinstance(window, QObject) else None
        runner = window._page_preparation = IdlePreparation(
            owner, page_steps(window), allowed=lambda: _home_idle(window))
    runner.start()
    return runner


def start(window) -> IdlePreparation:
    """Start (once per window) after Studio's modules have been preloaded."""
    runner = window.__dict__.get('_idle_preparation')
    if runner is None:
        owner = window if isinstance(window, QObject) else None
        runner = window._idle_preparation = IdlePreparation(
            owner, window_steps(window), allowed=lambda: _home_idle(window))
    runner.start()
    return runner
