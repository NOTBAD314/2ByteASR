"""The first-run tutorial: do it once with demo data, one step at a time (2026-10-14).

Each step outlines a real control (or shows a centred card), says in one short
line what to do there, plays a short animation of the gesture and lets you do
it:

* the outlined control works as usual: clicks inside the outline reach the
  page (a few steps do the demo thing instead, ``TourStep.click``: 开始生成字幕
  shows the pretend result rather than recognising); a step that waits for
  something (``done``) moves on by itself once it sees it; "帮我做" does it;
* when a click leaves the page (a model card opens the workshop) the tutorial
  steps aside to a small "回到教学" chip and comes back with the page; while a
  click is being answered (the workbench opening) nothing is left on the old
  spot.

Changing step (2026-10-14 evening): the outline waits until its target holds
still, glides there once, and only then does the bubble appear - at its final
place, the free spot nearest the outline, at a size that fits there. Before,
the bubble was re-placed on every frame of the glide (in-between spots, size
and side flips: the "抽搐").

On Windows the overlay is a translucent tool window above the main window.
As a child widget it turned into a native child window as soon as the
workbench's native video existed (Qt makes siblings native), and then painted
black over the video and its subtitles and flickered whenever the outline
moved. A tool window is composed above the video, so the video shows dimmed
under the shade and the bubble may sit over it. Clicks in the outline pass
through to the main window (transparent pixels and a window mask). The
overlay never takes the keyboard focus: an application event filter gives
Enter / arrows / Esc to the tutorial on steps where keys are not the page's.

Nothing is uploaded or paid for: the media and the pretend result come from
the tutorial project (sample_project.ensure_tutorial_project), and "AI 校对"
uses an offline stand-in while the tutorial runs.

2026-10-21 (user, written for people who know nothing about AI): the steps
that set up real accounts open the real windows - 主力转写 opens the MOSS Pro
sign-up guide, AI opens the DeepSeek guide and then tests the connection.
While such a window (any dialog of the main window) is open the tutorial steps
aside completely (mode ``dialog``) and comes back when it closes. A step may
carry a smaller second line (``note``). "继续学进阶" swaps the advanced steps
into the same overlay instead of closing it and opening a new one.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import (QEasingCurve, QElapsedTimer, QEvent, QPoint, QPointF, QRect, QRectF, QSize, QSizeF, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QImage, QMovie, QPainter, QPainterPath, QPen, QPolygonF, QRegion
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..i18n import bind_text, tr


@dataclass
class TourAction:
    label: str
    run: Callable[[], None]
    advance: bool = False   # go to the next step after running
    modal: bool = False     # opens a window: the tutorial steps aside until it closes
    big: bool = False       # the step's main suggestion: a large primary button that takes the row


@dataclass
class TourStep:
    text: str | Callable[[], str]          # one short line; **marked**: the control or key to use
    # None: a centred card. A widget, or (widget, rect in that widget) for a part of it.
    target: Callable[[], object] | None = None
    actions: list = field(default_factory=list)          # TourAction
    enter: Callable[[], None] | None = None              # runs when the step opens (page switch...)
    ready: Callable[[], bool] | None = None              # wait for this (default: target visible)
    next_label: str = '下一步'
    show_next: bool = True                               # False: an action (or ``done``) moves on
    optional: bool = False                               # shown only if already there (no waiting)
    anim: str | Callable[[], str] = ''                   # assets/onboarding/tutorial/<anim>-<theme>.webp
    interactive: bool = False                            # keys go to the page (``focus``), the outline pulses
    done: Callable[[], bool] | None = None               # the user did it: move on by itself
    focus: Callable[[], QWidget | None] | None = None    # who gets the keys in an interactive step
    click: TourAction | None = None                      # a click in the outline runs this instead
    page: Callable[[], None] | None = None               # "回到教学": bring the step's page back
    note: str | Callable[[], str] = ''                   # a smaller second line (why, what it costs...)


def tutorial_anim_path(name: str, light: bool, still: bool = False):
    """assets/onboarding/tutorial/<name>-<dark|light>.webp (or -still.png), rendered from source/tutorial.html."""
    from .main_ui_helpers import APP_ROOT
    file = f"{name}-{'light' if light else 'dark'}" + ('-still.png' if still else '.webp')
    path = APP_ROOT / 'assets' / 'onboarding' / 'tutorial' / file
    return path if path.is_file() else None


class TourAnim(QWidget):
    """The gesture animation in the bubble.

    2026-10-21: scenes in ``tour_motion`` are drawn here in the theme's own
    colours (about 30 frames a second is plenty for their calm motion); other
    names are still animated WebP files drawn crisp on HiDPI.
    """

    SIZE = QSize(440, 187)
    FRAME_MS = 33

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE)
        self._movie = None
        self._still = None
        self._scene = None
        self._look = None
        self._clock = QElapsedTimer()
        self._ticker = QTimer(self)
        self._ticker.setInterval(self.FRAME_MS)
        self._ticker.timeout.connect(self.update)
        self.name = ''

    def load(self, name: str, light: bool) -> bool:
        """Prepare ``name`` without playing it yet."""
        self.stop()
        self.name = name or ''
        if not name:
            return False
        from ..design.ui_motion import reduced_motion
        from .tour_motion import SCENES, Look
        scene = SCENES.get(name)
        if scene is not None:
            from ..design.theme_manager import theme_key
            from ..design.ui_theme import theme_definition
            self._scene = scene
            self._look = Look(theme_definition(theme_key()))
            self.update()
            return True
        if reduced_motion():
            path = tutorial_anim_path(name, light, still=True)
            if path is None:
                return False
            self._still = QImage(str(path))
            self.update()
            return not self._still.isNull()
        path = tutorial_anim_path(name, light)
        if path is None:
            return False
        movie = QMovie(str(path), parent=self)
        movie.setCacheMode(QMovie.CacheMode.CacheNone)
        movie.frameChanged.connect(lambda _frame: self.update())
        self._movie = movie
        if not movie.isValid():
            self.stop()
            return False
        movie.jumpToFrame(0)
        return True

    def start(self):
        if self._scene is not None:
            from ..design.ui_motion import reduced_motion
            if not reduced_motion() and not self._ticker.isActive():
                self._clock.restart()
                self._ticker.start()
            return
        if self._movie is not None and self._movie.state() != QMovie.MovieState.Running:
            self._movie.start()

    def play(self, name: str, light: bool) -> bool:
        ok = self.load(name, light)
        self.start()
        return ok

    def stop(self):
        self._ticker.stop()
        self._scene = None
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
        self._movie = None
        self._still = None

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        if self._scene is not None:
            from .tour_motion import paint_scene
            t = self._clock.elapsed() if self._ticker.isActive() else self._scene.still * self._scene.duration
            painter = QPainter(self)
            paint_scene(painter, self._scene, t, self._look, self.font(), self.width(), self.height(),
                        self.devicePixelRatioF())
            painter.end()
            return
        image = self._movie.currentImage() if self._movie is not None else self._still
        if image is None or image.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(self.rect()), image)
        painter.end()


def _text_height(label: QLabel, width: int) -> int:
    """The height ``label``'s rich text needs at ``width``.

    2026-10-21: QLabel.heightForWidth counted a second line for text that it
    then painted on one (real window, 110 % interface zoom, 175 % scaling):
    every bubble showed an empty line under its text. The same font, text and
    width in a QTextDocument agree with what is painted.
    """
    from PySide6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(label.font())
    doc.setHtml(label.text())
    doc.setTextWidth(width)
    margins = label.contentsMargins()
    return math.ceil(doc.size().height()) + 1 + margins.top() + margins.bottom()


def _close(a: QRectF, b: QRectF, tolerance: float = 2.0) -> bool:
    return not a.isNull() and not b.isNull() and all(abs(x - y) <= tolerance for x, y in zip(a.getRect(), b.getRect()))


class GuidedTour(QWidget):
    finished = Signal(bool)  # True when the last step was passed, False when skipped

    WAIT_MS = 20000                                      # a page that never comes: skip the step
    TEXT_WIDTH = 440                                     # bubble text column (logical px)
    COMPACT_WIDTH = 340                                  # when no full-size spot near the target is free
    SETTLE_MS = 160                                      # the target must hold still this long...
    SETTLE_LIMIT_MS = 1500                               # ...or the outline goes there anyway
    GLIDE_MS = 260
    REVEAL_MS = 170
    GAP = 22                                             # bubble ↔ outline
    MARGIN = 16                                          # bubble ↔ window edge
    POLL_MS = 50
    FLOATING = None                                      # None: a tool window on Windows, a child widget elsewhere
    FOLLOW_MS = 120

    def __init__(self, window, steps: list[TourStep], avoid: Callable[[], list] | None = None):
        floating = (sys.platform == 'win32') if self.FLOATING is None else bool(self.FLOATING)
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
                 | Qt.WindowType.WindowDoesNotAcceptFocus) if floating else Qt.WindowType.Widget
        super().__init__(window, flags)
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        self.floating = floating
        if floating:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName('guidedTour')
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.window_ = window
        self.steps = steps
        self.part = ''
        self.next_part: Callable[[], tuple | None] | None = None   # (steps, part) to go on with after the last step
        self.avoid = avoid                               # rects (window coords) a child overlay must not cover
        self.index = -1
        self.theme = theme_definition(theme_key())
        self.light = QColor(self.theme.app_background).lightness() > 128
        self.mode = 'idle'                               # wait → glide → shown; pending, away
        self.hole = QRectF()
        self.pointer = None                              # (tip, base1, base2) toward the outline
        self.reveal = 0.0                                # bubble fade-in (0..1)
        self.glow = 0.0                                  # attention pulse (0..1)
        self._entered = set()
        self._advancing = False
        self._compact = False                            # the bubble is not full size (kept for audits)
        self._size_key = 'full'
        self._has_anim = False
        self._placement = None                           # (rect, pointer, side) for the outline being reached
        self._final_pos = QPoint(0, 0)                   # the bubble's place once faded in
        self._wait_left = 0
        self._wait_direction = 1
        self._settle = None                              # (rect, since) while the target settles
        self._settle_started = 0
        self._scrolled = False
        self._pending_left = 0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._poller = QTimer(self)
        self._poller.setInterval(self.POLL_MS)
        self._poller.timeout.connect(self._poll)
        # Pages keep settling after they appear and an interactive step watches for what the user did.
        self._follow = QTimer(self)
        self._follow.setInterval(self.FOLLOW_MS)
        self._follow.timeout.connect(self._follow_target)
        self._glide = QVariantAnimation(self)
        self._glide.setDuration(self.GLIDE_MS)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glide.valueChanged.connect(self._glide_step)
        self._glide.finished.connect(self._glide_done)
        self._reveal = QVariantAnimation(self)
        self._reveal.setStartValue(0.0)
        self._reveal.setEndValue(1.0)
        self._reveal.setDuration(self.REVEAL_MS)
        self._reveal.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._reveal.valueChanged.connect(self._reveal_step)
        self._reveal.finished.connect(self._reveal_done)
        self._attention = QVariantAnimation(self)
        self._attention.setStartValue(0.0)
        self._attention.setEndValue(1.0)
        self._attention.setDuration(1400)
        self._attention.valueChanged.connect(self._pulse)
        # A shown target that moves (a card growing once its media is read) carries the bubble along.
        self._carry = QVariantAnimation(self)
        self._carry.setStartValue(0.0)
        self._carry.setEndValue(1.0)
        self._carry.setDuration(180)
        self._carry.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._carry.valueChanged.connect(self._carry_step)
        self._carry.finished.connect(self._carry_done)
        self._carry_path = None
        self._modal_running = 0                          # actions opening a window that have not returned yet
        self._build_bubble()
        self._build_chip()
        self._sync_geometry()
        # The main window's moves and sizes, and the keys (the overlay never takes the focus).
        QApplication.instance().installEventFilter(self)
        pages = getattr(window, 'pages', None)
        if pages is not None and hasattr(pages, 'currentChanged'):
            pages.currentChanged.connect(self._page_changed)   # a click that opens another page: react at once

    # ------------------------------------------------------------ bubble
    def _build_bubble(self):
        t = self.theme
        accent = QColor(t.accent)
        self.bubble = QFrame(self)
        self.bubble.setObjectName('tourBubble')
        self.bubble.setStyleSheet(
            f"QFrame#tourBubble {{ background: {t.surface_elevated}; border: 2px solid {t.accent}; border-radius: 20px; }}"
            f"QLabel#tourCount {{ color: {t.accent}; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);"
            f" border-radius: 10px; padding: 2px 10px; font-size: 12px; font-weight: 700; }}"
            f"QLabel#tourText {{ color: {t.text}; font-size: 16px; }}"
            f"QLabel#tourNote {{ color: {t.text_secondary}; font-size: 13px; }}"
            f"QPushButton#tourSkip {{ background: transparent; border: 0; color: {t.text_muted}; padding: 4px 6px; }}"
            f"QPushButton#tourSkip:hover {{ color: {t.text}; }}")
        self.bubble.hide()
        layout = QVBoxLayout(self.bubble)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName('tourCount')
        top.addWidget(self.count)
        top.addStretch(1)
        self.skip = QPushButton()
        bind_text(self.skip, '跳过教学')
        self.skip.setObjectName('tourSkip')
        self.skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skip.clicked.connect(lambda: self.close_tour(False))
        top.addWidget(self.skip)
        layout.addLayout(top)
        self.anim = TourAnim(self.bubble)
        self.anim.setObjectName('tourAnim')
        layout.addWidget(self.anim)
        self.text = QLabel()
        self.text.setObjectName('tourText')
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        self.text.setFixedWidth(self.TEXT_WIDTH)
        layout.addWidget(self.text)
        self.note = QLabel()
        self.note.setObjectName('tourNote')
        self.note.setTextFormat(Qt.TextFormat.RichText)
        self.note.setWordWrap(True)
        self.note.setFixedWidth(self.TEXT_WIDTH)
        self.note.hide()
        layout.addWidget(self.note)
        # 2026-10-21: the bubble sizes these at the interface zoom itself (``_set_size``). Left to
        # ui_zoom, a label measured at 440 px was widened to 484 px afterwards and kept the height
        # of a line that no longer wrapped: an empty line under every step's text at 110 %.
        for part in (self.text, self.note, self.anim):
            part.setProperty('uiZoomOwnSize', True)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        layout.addLayout(self.buttons)
        self.action_buttons: list[QPushButton] = []
        from ..design.presentation import button_role
        self.back = button_role(QPushButton(), 'ghost')
        bind_text(self.back, '上一步')
        self.back.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.back.clicked.connect(lambda: self.go(self.index - 1, step=-1))
        self.next = button_role(QPushButton(), 'primary')
        self.next.setObjectName('tourNext')
        self.next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.next.clicked.connect(lambda: self.go(self.index + 1))

    def _build_chip(self):
        """Shown instead of the bubble while the user is on a page the tutorial does not cover."""
        from ..design.presentation import button_role
        t = self.theme
        self.chip = QFrame(self)
        self.chip.setObjectName('tourChip')
        self.chip.setStyleSheet(
            f"QFrame#tourChip {{ background: {t.surface_elevated}; border: 2px solid {t.accent}; border-radius: 18px; }}"
            f"QLabel#tourChipText {{ color: {t.text}; font-size: 14px; }}")
        row = QHBoxLayout(self.chip)
        row.setContentsMargins(16, 8, 10, 8)
        row.setSpacing(8)
        text = QLabel()
        text.setObjectName('tourChipText')
        bind_text(text, '教学已暂停')
        row.addWidget(text)
        self.chip_resume = button_role(QPushButton(), 'primary')
        self.chip_resume.setObjectName('tourResume')
        bind_text(self.chip_resume, '回到教学')
        self.chip_resume.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chip_resume.clicked.connect(lambda: self._resume())
        row.addWidget(self.chip_resume)
        self.chip_end = button_role(QPushButton(), 'ghost')
        bind_text(self.chip_end, '结束教学')
        self.chip_end.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chip_end.clicked.connect(lambda: self.close_tour(False))
        row.addWidget(self.chip_end)
        self.chip.hide()

    def _fill_buttons(self, step: TourStep):
        from ..design.presentation import button_role
        while self.buttons.count():
            item = self.buttons.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in (self.back, self.next):
                widget.deleteLater()
        self.action_buttons = []
        for index, action in enumerate(step.actions):
            primary = action.big or (not step.show_next and index == 0 and not step.interactive)
            button = button_role(QPushButton(), 'primary' if primary else 'secondary', size='large' if action.big else 'default')
            bind_text(button, action.label)
            button.setObjectName(f'tourAction_{index}')
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, a=action: self._run_action(a))
            self.buttons.addWidget(button, 1 if action.big else 0)
            button.show()  # a layout would show it a moment later, after the bubble was measured
            self.action_buttons.append(button)
        self.buttons.addStretch(1)
        self.buttons.addWidget(self.back)
        self.buttons.addWidget(self.next)
        self.back.setVisible(self.index > 0 and step.show_next)
        self.next.setVisible(step.show_next)
        bind_text(self.next, step.next_label)

    def _run_action(self, action: TourAction):
        if action.modal:
            self._set_mode('dialog')   # nothing of the tutorial over the window it opens
            self._modal_running += 1   # ...not even before that window has appeared
        index = self.index
        try:
            action.run()
        except Exception:  # noqa: BLE001 - a failing demo action must not trap the user in the tutorial
            import traceback
            traceback.print_exc()
        finally:
            if action.modal:
                self._modal_running -= 1
        if self.mode == 'closed' or index != self.index:
            return
        if action.advance:
            self.go(self.index + 1)
        elif action.modal and self.mode == 'dialog' and self._foreign_dialog() is None:
            self._resume(navigate=False)

    def _prepare_bubble(self, step: TourStep):
        from .onboarding import emphasis_html
        text = step.text() if callable(step.text) else step.text
        self.text.setText(emphasis_html(str(tr(text)), self.theme.accent))
        note = step.note() if callable(step.note) else step.note
        self.note.setText(emphasis_html(str(tr(note)), self.theme.accent) if note else '')
        self.note.setVisible(bool(note))
        self.count.setText(f'{self.index + 1} / {len(self.steps)}')
        name = step.anim() if callable(step.anim) else step.anim
        self._has_anim = self.anim.load(name, self.light)
        self._fill_buttons(step)

    def _set_size(self, key: str):
        """full: wide text and animation; compact: narrower; mini: compact text, no animation."""
        from . import ui_zoom
        self._size_key = key
        self._compact = key != 'full'
        width = ui_zoom.px(self.TEXT_WIDTH if key == 'full' else self.COMPACT_WIDTH)
        for label in (self.text, self.note):
            label.ensurePolished()   # measure with the sheet's font size, not the default one
        self.text.setFixedWidth(width)
        # A wrapped label's size hint assumes its own width; pin both so no line is clipped.
        self.text.setFixedHeight(_text_height(self.text, width))
        self.note.setFixedWidth(width)
        if self.note.text():
            self.note.setFixedHeight(_text_height(self.note, width))
        self.anim.setFixedSize(width, round(width * TourAnim.SIZE.height() / TourAnim.SIZE.width()))
        self.anim.setVisible(self._has_anim and key != 'mini')

    def _measure(self) -> QSize:
        # New action buttons get their style only when polished; measure after that, or the
        # bubble comes out a button-height short and the last text line hides behind them.
        for child in self.bubble.findChildren(QWidget):
            child.ensurePolished()
        self.bubble.layout().activate()
        return self.bubble.sizeHint()

    # ------------------------------------------------------------ steps
    def start(self):
        self._sync_geometry()
        self.show()
        self.raise_()
        self._follow.start()
        self.go(0)

    def _step(self) -> TourStep | None:
        return self.steps[self.index] if 0 <= self.index < len(self.steps) else None

    def _raw_target(self, index):
        """The step's target if it is shown on its page (it may still be covered)."""
        step = self.steps[index] if 0 <= index < len(self.steps) else None
        if step is None or step.target is None:
            return None
        try:
            target = step.target()
        except Exception:  # noqa: BLE001 - a page that is not built yet
            return None
        widget = target[0] if isinstance(target, tuple) else target
        if widget is None or not widget.isVisible():
            return None
        if isinstance(target, tuple) and (target[1] is None or target[1].isEmpty()):
            return None
        return target

    def _exposed(self, target) -> bool:
        """Nothing of the window lies over the target's centre (an in-window dialog such as the model picker)."""
        widget, point = (target[0], target[1].center().toPoint()) if isinstance(target, tuple) \
            else (target, target.rect().center())
        hit = self.window_.childAt(widget.mapTo(self.window_, point))
        node = hit
        while node is not None:
            if node is widget or node is self:   # a child overlay (not floating) hides the answer: assume yes
                return True
            node = node.parentWidget()
        return hit is None

    def _target(self, index):
        target = self._raw_target(index)
        return target if target is not None and self._exposed(target) else None

    def _covered(self, index) -> bool:
        target = self._raw_target(index)
        return target is not None and not self._exposed(target)

    def _is_ready(self, index) -> bool:
        step = self.steps[index]
        try:
            if step.ready is not None and not step.ready():
                return False
        except Exception:  # noqa: BLE001
            return False
        return step.target is None or self._target(index) is not None

    def go(self, index: int, *, step: int = 1):
        self._poller.stop()
        self._advancing = False
        if index >= len(self.steps):
            follow = self.next_part() if self.next_part is not None else None
            if follow:
                self.continue_with(*follow)
                return
            self.close_tour(True)
            return
        if index < 0:
            return
        self.index = index
        self._hide_bubble()
        current = self.steps[index]
        if index not in self._entered and current.enter is not None:
            self._entered.add(index)
            try:
                current.enter()
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
        if not self._is_ready(index):
            if current.optional:   # e.g. the proofreading page when the user chose not to open it
                self.go(index + step, step=step)
                return
            self._set_hole(QRectF())   # the old outline belongs to a page that is going away
        self._wait_left = self.WAIT_MS
        self._wait_direction = step
        self._settle = None
        self._scrolled = False
        self._set_mode('wait')
        self._poll()
        if self.mode == 'wait':
            self._poller.start()

    # Windows opened without exec() that the tutorial must not cover either (AI 设置 after the DeepSeek guide).
    PAUSING_DIALOGS = frozenset({'aiSettingsDialog'})

    def _foreign_dialog(self):
        """An open window the tutorial must wait for: one shown with exec() (a guide, a message box) or AI 设置.

        SpringDialog.exec() runs its own loop without Qt modality (an input
        guard and a backdrop over the main window instead), so it is known by
        its guard. A download window that keeps running beside the pages does
        not count."""
        from PySide6.QtWidgets import QDialog
        for widget in QApplication.topLevelWidgets():
            if widget is self or not isinstance(widget, QDialog) or not widget.isVisible():
                continue
            if (widget.isModal() or getattr(widget, '_input_guard', None) is not None
                    or widget.objectName() in self.PAUSING_DIALOGS):
                return widget
        return None

    def _poll(self):
        """Waiting for the step's page and target, then for the target to hold still."""
        if self.mode != 'wait':
            self._poller.stop()
            return
        if self._foreign_dialog() is not None:
            self._set_mode('dialog')
            return
        if not self._is_ready(self.index):
            self._settle = None
            if self._covered(self.index):   # an in-window dialog is open over it: wait on the chip
                self._poller.stop()
                self._set_hole(QRectF())
                self._set_mode('away')
                return
            self._wait_left -= self.POLL_MS
            if not self.hole.isNull():
                self._set_hole(QRectF())
            if self._wait_left <= 0:
                self._poller.stop()
                self.go(self.index + self._wait_direction, step=self._wait_direction)  # not available here
            return
        target = self._target(self.index)
        if target is None:   # a centred card
            self._poller.stop()
            self._arrive(QRectF())
            return
        widget = target[0] if isinstance(target, tuple) else target
        if not self._scrolled and not isinstance(target, tuple):
            self._scrolled = True
            scroll = widget.parent()
            while scroll is not None and not isinstance(scroll, QScrollArea):
                scroll = scroll.parent()
            if scroll is not None:
                scroll.ensureWidgetVisible(widget, 40, 60)
        rect = self._rect_of(target)
        now = self._clock.elapsed()
        if self._settle is None:
            self._settle_started = now
        if self._settle is None or not _close(rect, self._settle[0]):
            self._settle = (rect, now)
            return
        from ..design.ui_motion import reduced_motion
        still = now - self._settle[1] >= self.SETTLE_MS or reduced_motion()
        if not still and now - self._settle_started < self.SETTLE_LIMIT_MS:
            return
        self._poller.stop()
        self._arrive(rect)

    def _arrive(self, rect: QRectF):
        """Place the bubble for the final outline, glide the outline there, then show the bubble."""
        from ..design.ui_motion import reduced_motion
        step = self._step()
        self._prepare_bubble(step)
        self._placement = self._place(rect)
        if rect.isNull() or reduced_motion():
            self._glide.stop()
            self._set_hole(rect)
            self._show_bubble(animate=not reduced_motion())
            return
        start = self.hole if not self.hole.isNull() else QRectF(rect.center().x() - rect.width() * 0.35,
                                                                 rect.center().y() - rect.height() * 0.35,
                                                                 rect.width() * 0.7, rect.height() * 0.7)
        self._set_mode('glide')
        self._glide.stop()
        self._glide.setStartValue(QRectF(start))
        self._glide.setEndValue(QRectF(rect))
        self._glide.start()

    def _glide_step(self, value):
        if self.mode == 'glide':
            self._set_hole(QRectF(value))

    def _glide_done(self):
        if self.mode != 'glide':
            return
        self._set_hole(QRectF(self._glide.endValue()))
        self._show_bubble(animate=True)

    def _show_bubble(self, *, animate: bool):
        step = self._step()
        if step is None:
            return
        rect, pointer, side = self._placement or (QRectF(), None, '')
        self._set_mode('shown')
        self._final_pos = rect.topLeft().toPoint()
        self._slide = {'right': QPoint(10, 0), 'left': QPoint(-10, 0), 'below': QPoint(0, 10),
                       'above': QPoint(0, -10)}.get(side, QPoint(0, 8)) if animate else QPoint(0, 0)
        self.pointer = pointer
        self.bubble.move(self._final_pos + self._slide)
        if animate:
            effect = QGraphicsOpacityEffect(self.bubble)
            effect.setOpacity(0.0)
            self.bubble.setGraphicsEffect(effect)
            self.reveal = 0.0
        else:
            self.bubble.setGraphicsEffect(None)
            self.reveal = 1.0
        self.bubble.show()
        self.bubble.raise_()
        if self._size_key != 'mini':
            self.anim.start()
        if not self.floating:
            self.raise_()
        self._apply_mask()
        self.update()
        if animate:
            self._reveal.stop()
            self._reveal.start()
        from ..design.ui_motion import reduced_motion
        if not reduced_motion():
            self._attention.stop()
            self._attention.setLoopCount(-1 if step.interactive else 2)
            self._attention.start()
        if step.interactive:
            keys = None
            try:
                keys = step.focus() if step.focus is not None else None
            except Exception:  # noqa: BLE001
                keys = None
            (keys or self.window_).setFocus()

    def _reveal_step(self, value):
        self.reveal = float(value)
        effect = self.bubble.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(self.reveal)
        slide = getattr(self, '_slide', QPoint(0, 0))
        self.bubble.move(self._final_pos + QPoint(round(slide.x() * (1 - self.reveal)), round(slide.y() * (1 - self.reveal))))
        self.update(self._bubble_dirty())

    def _reveal_done(self):
        self.reveal = 1.0
        self.bubble.move(self._final_pos)
        self.bubble.setGraphicsEffect(None)   # no off-screen rendering while the animation plays
        self._apply_mask()
        self.update(self._bubble_dirty())

    def _hide_bubble(self):
        self._reveal.stop()
        self._carry.stop()
        self._carry_path = None
        self._attention.stop()
        self.glow = 0.0
        self.reveal = 0.0
        self.pointer = None
        self.anim.stop()
        self.bubble.setGraphicsEffect(None)
        if self.bubble.isVisible():
            dirty = self._bubble_dirty()
            self.bubble.hide()
            self.update(dirty)

    def _set_mode(self, mode: str):
        self.mode = mode
        if mode in ('pending', 'dialog'):   # the page is answering a click, or a window is open: step aside
            self._poller.stop()
            self._hide_bubble()
            self.chip.hide()
            self.hide()
        elif mode == 'away':
            self._hide_bubble()
            self.chip.ensurePolished()
            for child in self.chip.findChildren(QWidget):
                child.ensurePolished()
            self.chip.layout().activate()
            self.chip.adjustSize()
            self.chip.move(int((self.width() - self.chip.width()) / 2), self.height() - self.chip.height() - 28)
            self.chip.show()
            self.chip.raise_()
            if not self.isVisible():
                self.show()
        else:
            self.chip.hide()
            if not self.isVisible() and self.window_.isVisible():
                self._sync_geometry()
                self.show()
        self._apply_mask()
        self.update()

    def _resume(self, navigate: bool = True):
        """回到教学: back to the step's page (if it has one) and show the step again."""
        step = self._step()
        if navigate and step is not None and step.page is not None:
            try:
                step.page()
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
        self._wait_left = self.WAIT_MS
        self._settle = None
        self._scrolled = False
        self._set_mode('wait')
        self._poller.start()

    def _page_changed(self, _index):
        if self.mode in ('shown', 'pending', 'away'):
            self._follow_target()

    def _follow_target(self):
        step = self._step()
        if step is None or self.mode in ('idle', 'wait', 'glide', 'closed'):
            return
        if self.mode == 'dialog':
            if not self._modal_running and self._foreign_dialog() is None:
                self._resume(navigate=False)   # the window was closed: the same step again
            return
        if self._foreign_dialog() is not None:
            self._carry.stop()
            self._set_mode('dialog')
            return
        if step.done is not None and not self._advancing:
            try:
                did = bool(step.done())
            except Exception:  # noqa: BLE001
                did = False
            if did:
                # Done: the bubble goes at once (the outline stays a moment if its target is still there).
                self._advancing = True
                self._carry.stop()
                self._hide_bubble()
                if self._target(self.index) is None:
                    self._set_hole(QRectF())
                self._apply_mask()
                QTimer.singleShot(300, lambda index=self.index: index == self.index and self.go(index + 1))
                return
        if self._advancing or step.target is None:
            return
        target = self._target(self.index)
        if self.mode == 'shown':
            if target is None:
                # A click opened another page or an in-window dialog: nothing stays on the old spot.
                self._carry.stop()
                self._hide_bubble()
                self._set_hole(QRectF())
                self._pending_left = self.WAIT_MS
                self._set_mode('pending' if step.done is not None and not self._covered(self.index) else 'away')
                return
            if self._reveal.state() == QVariantAnimation.State.Running \
                    or self._carry.state() == QVariantAnimation.State.Running:
                return
            rect = self._rect_of(target)
            if not _close(rect, self.hole):
                self._follow_move(rect)
            return
        # pending / away: back on the step's page?
        if target is not None and self._is_ready(self.index):
            self._resume(navigate=False)
            return
        if self.mode == 'pending':
            self._pending_left -= self.FOLLOW_MS
            if self._pending_left <= 0:
                self._set_mode('away')

    def _follow_move(self, rect: QRectF):
        """The shown target moved: carry outline and bubble along when it still fits, else place it again."""
        old = QRectF(self.hole)
        delta = rect.center() - old.center()
        same_size = abs(rect.width() - old.width()) <= 3 and abs(rect.height() - old.height()) <= 3
        start = QPointF(self._final_pos)
        moved = QRectF(start, QSizeF(self.bubble.size())).translated(delta)
        if same_size and self._fits(moved, rect):
            from ..design.ui_motion import reduced_motion
            self._carry_path = (old, QRectF(rect), start, moved.topLeft(), self.pointer, delta)
            if reduced_motion():
                self._carry_step(1.0)
                self._carry_done()
            else:
                self._carry.stop()
                self._carry.start()
            return
        self._hide_bubble()
        self._settle = None
        self._set_mode('wait')
        self._poller.start()

    def _carry_step(self, value):
        if self._carry_path is None:
            return
        old, new, start, end, pointer, delta = self._carry_path
        v = float(value)
        hole = QRectF(old.x() + (new.x() - old.x()) * v, old.y() + (new.y() - old.y()) * v,
                      old.width() + (new.width() - old.width()) * v, old.height() + (new.height() - old.height()) * v)
        dirty = self._bubble_dirty()
        self._final_pos = QPoint(round(start.x() + (end.x() - start.x()) * v), round(start.y() + (end.y() - start.y()) * v))
        self.bubble.move(self._final_pos)
        if pointer is not None:
            self.pointer = tuple(point + delta * v for point in pointer)
        self._set_hole(hole)
        self.update(dirty.united(self._bubble_dirty()))

    def _carry_done(self):
        if self._carry_path is None:
            return
        self._carry_step(1.0)
        self._carry_path = None
        self._apply_mask()

    def _rect_of(self, target) -> QRectF:
        if isinstance(target, tuple):
            widget, part = target
            top_left = widget.mapTo(self.window_, part.topLeft().toPoint())
            rect = QRectF(top_left.x(), top_left.y(), part.width(), part.height()).adjusted(-6, -6, 6, 6)
        else:
            top_left = target.mapTo(self.window_, QPoint(0, 0))
            rect = QRectF(top_left.x(), top_left.y(), target.width(), target.height()).adjusted(-8, -8, 8, 8)
        return rect.intersected(QRectF(self.rect()).adjusted(6, 6, -6, -6))

    def _set_hole(self, rect: QRectF):
        if rect == self.hole:
            return
        dirty = QRectF(self.hole).united(rect) if not self.hole.isNull() and not rect.isNull() else None
        self.hole = QRectF(rect)
        if dirty is None:
            self.update()
        else:
            self.update(dirty.adjusted(-30, -30, 30, 30).toAlignedRect())

    def _apply_mask(self):
        """Clicks inside the outline reach the page; the bubble (and the chip) stay clickable."""
        if self.mode == 'away':
            self.setMask(QRegion(self.chip.geometry().adjusted(-2, -2, 2, 2)))
            return
        step = self._step()
        if self.mode != 'shown' or self.hole.isNull() or step is None or step.click is not None:
            self.clearMask()
            return
        region = QRegion(self.rect()).subtracted(QRegion(self.hole.toAlignedRect()))
        if self.bubble.isVisible():
            region = region.united(QRegion(self.bubble.geometry().adjusted(-2, -2, 2, 2)))
        self.setMask(region)

    def _sync_geometry(self):
        if self.floating:
            self.setGeometry(QRect(self.window_.mapToGlobal(QPoint(0, 0)), self.window_.size()))
        else:
            self.setGeometry(self.window_.rect())

    def _relayout(self):
        """The window changed size: everything goes to its new place at once."""
        self._sync_geometry()
        self._carry.stop()
        self._carry_path = None
        if self.mode == 'shown':
            target = self._target(self.index)
            rect = self._rect_of(target) if target is not None else QRectF()
            self._placement = self._place(rect)
            self._set_hole(rect)
            self._show_bubble(animate=False)
        elif self.mode == 'glide':
            self._glide.stop()
            self._settle = None
            self._set_mode('wait')
            self._poller.start()
        elif self.mode == 'away':
            self._set_mode('away')

    # ------------------------------------------------------------ placement
    def _avoid_rects(self) -> list:
        if self.floating or self.avoid is None:   # a tool window is drawn above the native video
            return []
        try:
            return [QRectF(rect) for rect in self.avoid() or () if rect is not None]
        except Exception:  # noqa: BLE001
            return []

    def _bounds(self) -> QRectF:
        m = self.MARGIN
        return QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m).adjusted(-0.5, -0.5, 0.5, 0.5)

    def _fits(self, rect: QRectF, hole: QRectF) -> bool:
        return (self._bounds().contains(rect) and not rect.intersects(hole)
                and not any(rect.intersects(a) for a in self._avoid_rects()))

    @staticmethod
    def _distance(rect: QRectF, hole: QRectF) -> float:
        dx = max(0.0, hole.left() - rect.right(), rect.left() - hole.right())
        dy = max(0.0, hole.top() - rect.bottom(), rect.top() - hole.bottom())
        return math.hypot(dx, dy)

    def _spots(self, hole: QRectF, size: QSize):
        w, h = size.width(), size.height()
        m, g = self.MARGIN, self.GAP
        width, height = self.width(), self.height()

        def clamp(value, low, high):
            return max(low, min(value, high))
        avoid = self._avoid_rects()
        ys = [clamp(hole.center().y() - h / 2, m, height - h - m)]
        xs = [clamp(hole.center().x() - w / 2, m, width - w - m)]
        for a in avoid:   # slide past the native video (child overlay only)
            ys += [clamp(a.bottom() + g, m, height - h - m), clamp(a.top() - g - h, m, height - h - m)]
            xs += [clamp(a.right() + g, m, width - w - m), clamp(a.left() - g - w, m, width - w - m)]
        for y in ys:
            yield 'right', QRectF(hole.right() + g, y, w, h)
            yield 'left', QRectF(hole.left() - g - w, y, w, h)
        for x in xs:
            yield 'below', QRectF(x, hole.bottom() + g, w, h)
            yield 'above', QRectF(x, hole.top() - g - h, w, h)

    def _place(self, hole: QRectF):
        """The bubble's size and spot for this outline: the free spot nearest to it (rect, pointer, side)."""
        width, height = self.width(), self.height()
        if hole.isNull():   # a centred card
            self._set_size('full')
            size = self._measure()
            self.bubble.resize(size)
            rect = QRectF((width - size.width()) / 2, (height - size.height()) / 2, size.width(), size.height())
            return rect, None, ''
        wide = hole.width() > width * 0.5
        best = None
        sizes = (('full', 0.0), ('compact', 26.0), ('mini', 80.0)) if self._has_anim else (('full', 0.0), ('compact', 26.0))
        for key, penalty in sizes:
            self._set_size(key)
            size = self._measure()
            for side, rect in self._spots(hole, size):
                if not self._fits(rect, hole):
                    continue
                preferred = side in (('below', 'above') if wide else ('right', 'left'))
                score = self._distance(rect, hole) + penalty + (0.0 if preferred else 6.0)
                if best is None or score < best[0]:
                    best = (score, key, side, rect)
        if best is None:
            # Nowhere beside it (an outline over most of the window): inside its lower part.
            self._set_size('compact' if self._has_anim else 'full')
            size = self._measure()
            w, h = size.width(), size.height()
            m = self.MARGIN
            x = max(m, min(hole.center().x() - w / 2, width - w - m))
            y = max(m, min(hole.bottom() - h - self.GAP, height - h - m))
            self.bubble.resize(size)
            return QRectF(x, y, w, h), None, ''
        _score, key, side, rect = best
        self._set_size(key)
        self.bubble.resize(self._measure())
        return rect, self._pointer_for(side, rect, hole), side

    def _pointer_for(self, side: str, rect: QRectF, hole: QRectF):
        """A short pointer from the bubble's edge to the outline (none when they do not face each other)."""
        def clamp(value, low, high):
            return max(low, min(value, high))
        if side in ('right', 'left'):
            base_y = clamp(hole.center().y(), rect.top() + 26, rect.bottom() - 26)
            tip_y = clamp(base_y, hole.top() + 8, hole.bottom() - 8)
            if abs(tip_y - base_y) > 2.5 * self.GAP:
                return None
            if side == 'right':
                return QPointF(hole.right() + 4, tip_y), QPointF(rect.left() + 1, base_y - 12), QPointF(rect.left() + 1, base_y + 12)
            return QPointF(hole.left() - 4, tip_y), QPointF(rect.right() - 1, base_y - 12), QPointF(rect.right() - 1, base_y + 12)
        base_x = clamp(hole.center().x(), rect.left() + 26, rect.right() - 26)
        tip_x = clamp(base_x, hole.left() + 8, hole.right() - 8)
        if abs(tip_x - base_x) > 2.5 * self.GAP:
            return None
        if side == 'below':
            return QPointF(tip_x, hole.bottom() + 4), QPointF(base_x - 12, rect.top() + 1), QPointF(base_x + 12, rect.top() + 1)
        return QPointF(tip_x, hole.top() - 4), QPointF(base_x - 12, rect.bottom() - 1), QPointF(base_x + 12, rect.bottom() - 1)

    # ------------------------------------------------------------ painting helpers
    def _bubble_dirty(self) -> QRect:
        box = QRectF(self.bubble.geometry()).adjusted(-28, -28, 28, 36)
        if self.pointer is not None:
            box = box.united(QPolygonF(list(self.pointer)).boundingRect())
        return box.toAlignedRect()

    def _pulse(self, value):
        self.glow = math.sin(math.pi * float(value))
        dirty = self._bubble_dirty()
        if not self.hole.isNull():
            dirty = dirty.united(self.hole.adjusted(-24, -24, 24, 24).toAlignedRect())
        self.update(dirty)

    def continue_with(self, steps: list, part: str):
        """The next part in this same overlay (继续学进阶): no window closes and reopens in between."""
        self.steps = list(steps)
        self.part = part
        self._entered = set()
        self.index = -1
        self.go(0)

    def close_tour(self, completed: bool):
        for animation in (self._glide, self._reveal, self._attention, self._carry):
            animation.stop()
        pages = getattr(self.window_, 'pages', None)
        if pages is not None and hasattr(pages, 'currentChanged'):
            try:
                pages.currentChanged.disconnect(self._page_changed)
            except (RuntimeError, TypeError):
                pass
        self._poller.stop()
        self._follow.stop()
        self.anim.stop()
        self.clearMask()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.mode = 'closed'
        self.hide()
        self.finished.emit(bool(completed))
        self.deleteLater()

    # ------------------------------------------------------------ Qt
    def _keys_are_ours(self, watched) -> bool:
        """Keys go to the tutorial on its own steps (not where the page needs them, not in dialogs)."""
        if self.mode not in ('wait', 'glide', 'shown') or not isinstance(watched, QWidget):
            return False
        step = self._step()
        if step is None or step.interactive:
            return False
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return False
        top = watched.window()
        return top is self.window_ or top is self

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        kind = event.type()
        if watched is self.window_:
            if kind == QEvent.Type.Resize:
                self._relayout()
            elif kind == QEvent.Type.Move and self.floating:
                self._sync_geometry()
            elif kind == QEvent.Type.Hide and self.floating:
                self.hide()
            elif kind == QEvent.Type.Show and self.floating and self.mode not in ('pending', 'dialog', 'closed', 'idle'):
                self._sync_geometry()
                self.show()
            return False
        if kind == QEvent.Type.ShortcutOverride:
            if self._keys_are_ours(watched):
                event.accept()   # no page shortcut fires: the key comes as a key press to the filter below
                return True
            return False
        if kind == QEvent.Type.KeyPress and self._keys_are_ours(watched):
            key = event.key()
            step = self._step()
            if key == Qt.Key.Key_Escape:
                self.close_tour(False)
            elif self.mode == 'shown' and step.show_next and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right):
                self.go(self.index + 1)
            elif self.mode == 'shown' and step.show_next and key == Qt.Key.Key_Left and self.index > 0:
                self.go(self.index - 1, step=-1)
            return True
        return False

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        event.accept()  # outside the outline the page waits until the tutorial is closed
        step = self._step()
        if (self.mode == 'shown' and step is not None and step.click is not None
                and self.hole.contains(event.position())):
            self._run_action(step.click)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.mode == 'away':   # only the chip (a child widget)
            painter.end()
            return
        step = self._step()
        shade = QPainterPath()
        shade.setFillRule(Qt.FillRule.OddEvenFill)
        shade.addRect(QRectF(self.rect()))
        if not self.hole.isNull():
            shade.addRoundedRect(self.hole, 16, 16)
        painter.fillPath(shade, QColor(12, 9, 16, 178))
        accent = QColor(self.theme.accent)
        if not self.hole.isNull():
            if self.mode == 'shown' and step is not None and step.click is not None:
                inside = QPainterPath()
                inside.addRoundedRect(self.hole, 16, 16)
                painter.fillPath(inside, QColor(0, 0, 0, 1))   # a click there comes to the tutorial
            ring = self.hole.adjusted(-2, -2, 2, 2)
            extra = 6 * self.glow if step is not None and step.interactive else 0
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for width, alpha in ((12 + extra, 36), (6 + extra / 2, 72)):
                glow = QColor(accent)
                glow.setAlpha(int(alpha))
                painter.setPen(QPen(glow, width))
                painter.drawRoundedRect(ring, 17, 17)
            painter.setPen(QPen(accent, 2.5))
            painter.drawRoundedRect(ring, 17, 17)
        if self.bubble.isVisible() and self.reveal > 0.01:
            box = QRectF(self.bubble.geometry())
            painter.setPen(Qt.PenStyle.NoPen)
            for spread, alpha in ((22, 22), (14, 30), (7, 40)):   # soft shadow under the bubble
                painter.setBrush(QColor(0, 0, 0, int(alpha * self.reveal)))
                painter.drawRoundedRect(box.adjusted(-spread / 2, -spread / 2 + 8, spread / 2, spread / 2 + 10),
                                        20 + spread / 2, 20 + spread / 2)
            if self.glow > 0.01:   # a short glow that draws the eye to the bubble
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for spread, alpha in ((16, 46), (9, 70), (4, 96)):
                    glow = QColor(accent)
                    glow.setAlpha(int(alpha * self.glow * self.reveal))
                    painter.setPen(QPen(glow, spread))
                    painter.drawRoundedRect(box.adjusted(-spread / 2, -spread / 2, spread / 2, spread / 2), 22, 22)
            if self.pointer is not None:
                tip = QColor(accent)
                tip.setAlphaF(min(1.0, self.reveal))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(tip)
                painter.drawPolygon(QPolygonF(list(self.pointer)))
        painter.end()


# Kept for callers of the first version.
HomeTour = GuidedTour


# ---------------------------------------------------------------- the tutorial

def tutorial_steps(window, part: str = 'basic') -> list[TourStep]:
    """The tutorial with demo data, in two parts (2026-10-15).

    ``basic``: home → pretend result → export (the first subtitle file).
    ``advanced``: pretend result → proofreading → workbench.
    """
    from .sample_project import TUTORIAL_LIBRARY
    w = window
    get = lambda name: (lambda: w.__dict__.get(name))  # noqa: E731 - resolved when shown
    on_home = lambda: w.pages.currentWidget() is w.__dict__.get('settings_scroll')  # noqa: E731
    on_completion = lambda: w.pages.currentWidget() is not None and w.pages.currentWidget().objectName() == 'completionScroll'  # noqa: E731

    def studio():
        return w.built_page('studio')

    def studio_part(name):
        return lambda: getattr(studio(), name, None) if studio() is not None else None

    def studio_ready():
        page = studio()
        readiness = getattr(page, '_readiness', None)
        return (page is not None and w.pages.currentWidget() is page and page.project is not None
                and (readiness is None or (readiness.ready and not readiness.active)))

    def proofread():
        return w.__dict__.get('glossary_proofread_page')

    def on_proofread():
        page = proofread()
        return page is not None and w.pages.currentWidget() is page

    def proofread_part(name):
        return lambda: getattr(proofread(), name, None) if proofread() is not None else None

    def set_language(code):
        combo = w.__dict__.get('recognition_language')
        if combo is not None and combo.findData(code) >= 0:
            combo.setCurrentIndex(combo.findData(code))

    # ---- where each step lives ("回到教学"): close an in-window dialog (the model picker...), go to the page
    def close_in_window_dialog():
        host = w.__dict__.get('_modal_host')
        if host is not None and host.isVisible():
            host._request_close()

    def home():
        close_in_window_dialog()
        w._return_to_settings()

    def to_completion():
        close_in_window_dialog()
        for index in range(w.pages.count()):
            page = w.pages.widget(index)
            if page.objectName() == 'completionScroll':
                w._switch_page(page)
                return

    def to_studio():
        close_in_window_dialog()
        if studio() is not None:
            w._switch_page(studio())

    # ---- proofreading page
    def library_id():
        import subtitle_core
        return subtitle_core.runtime_game_identity(TUTORIAL_LIBRARY)

    def library_item():
        page = proofread()
        if page is None:
            return None
        for row in range(page.library_list.count()):
            item = page.library_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) == library_id() or item.text() == TUTORIAL_LIBRARY:
                return item
        return None

    def library_target():
        page, item = proofread(), library_item()
        if page is None or item is None:
            return None
        page.library_list.scrollToItem(item)
        return page.library_list.viewport(), QRectF(page.library_list.visualItemRect(item))

    def library_checked():
        page = proofread()
        return page is not None and library_id() in set(page._selected_ids())

    def check_library():
        item = library_item()
        if item is not None:
            item.setCheckState(Qt.CheckState.Checked)

    def busy():
        page = proofread()
        worker = getattr(page, '_worker', None)
        return worker is not None and worker.isRunning()

    def issues(cue_id=None):
        page = proofread()
        rows = getattr(page, '_by_id', None) or {}
        return [(key, index, issue) for key, row in rows.items() if cue_id in (None, key)
                for index, issue in enumerate(row.get('issues') or ())]

    def ai_shown():
        return not busy() and any(issue.get('kind') == 'ai' for _key, _index, issue in issues())

    def fix_cue():
        return 'tutorial-2'

    def fix_target():
        page = proofread()
        if page is None:
            return None
        page.list.repaint()
        boxes = [QRectF(rect) for rect, action, cue_id, *_rest in getattr(page.list, '_hit_boxes', ())
                 if cue_id == fix_cue() and action in ('mark', 'check', 'option')]
        if not boxes:
            return None
        rect = boxes[0]
        for box in boxes[1:]:
            rect = rect.united(box)
        return page.list, rect

    def cue_text(cue_id):
        page = proofread()
        try:
            project = page._live_project()[0]
            return next(cue.text for cue in project.cues if cue.id == cue_id)
        except Exception:  # noqa: BLE001
            return ''

    def fixed():
        return '至冬' in cue_text(fix_cue())

    def fix_it():
        for cue_id, index, issue in issues(fix_cue()):
            if issue.get('kind') in ('term', 'near', 'ai') and not issue.get('checked'):
                proofread()._toggle_issue(cue_id, index)
                return

    def offline_ai():
        page = proofread()
        if page is not None:
            from .sample_project import tutorial_ai_preview
            page.ai_stand_in = tutorial_ai_preview   # 教学里的 AI 校对：不联网、不收费

    # ---- workbench
    def block_target():
        page = studio()
        timeline = getattr(page, 'timeline', None)
        if timeline is None:
            return None
        cue = next((c for c in getattr(timeline, '_cues_by_start', ()) if c.id == fix_cue()), None)
        if cue is None:
            return None
        try:
            rows, _track, _wave = timeline._track_layout()
            band = timeline._cue_band(cue, rows[cue.speaker_id])
            left = max(timeline.TRACK_HEADER_WIDTH, timeline._time_to_x(cue.start_ms))
            right = min(timeline._content_right(), timeline._time_to_x(cue.end_ms))
            rect = QRectF(left, band.top() + 7, max(4, right - left), band.height() - 14)
            return timeline, rect.intersected(timeline._track_viewport())
        except Exception:  # noqa: BLE001
            return None

    def editor():
        page = studio()
        inline = getattr(getattr(page, 'timeline', None), '_inline_editor', None)
        if inline is not None:
            return inline
        return getattr(page, 'subtitle_edit_card', None) if getattr(page, '_canvas_editor', None) is not None else None

    def open_editor():
        page = studio()
        page.select_cue(fix_cue())
        page._begin_canvas_inline_edit()

    def save_editor():
        page = studio()
        if getattr(page.timeline, '_inline_editor', None) is not None:
            page.timeline._commit_inline_edit()
        elif getattr(page, '_canvas_editor', None) is not None:
            page._commit_canvas_inline_edit(advance=False)

    review_mark = {'index': 0}

    def review_from_first():
        """Review starts at the selected line: the first one, where the three recognizers disagree."""
        page = studio()
        if page is not None and page.project is not None and not getattr(page, '_review_mode', False):
            page.select_cue('tutorial-1')

    def start_review():
        review_from_first()
        studio()._set_review_mode(True)

    def reviewing():
        page = studio()
        return bool(getattr(page, '_review_mode', False))

    def remember_undo():
        page = studio()
        review_mark['index'] = page.undo_stack.index() if page is not None else 0

    def review_picked():
        page = studio()
        return page is not None and page.undo_stack.index() > review_mark['index']

    def candidates():
        page = studio()
        area = getattr(page, 'review_dock_candidates', None)
        if area is not None and area.isVisible():
            return area
        return getattr(page, 'review_summary_strip', None)

    def tool(name):
        def find():
            page = studio()
            button = getattr(page, name, None)
            if button is not None and button.isVisible():
                return button
            toolbar = getattr(page, 'studio_toolbar', None)  # narrow window: the tool sits in "…"
            for child in toolbar.findChildren(QWidget) if toolbar is not None else ():
                if child.property('commandSource') == '更多工作区操作' and child.isVisible():
                    return child
            return None
        return find

    def studio_keys():
        page = studio()
        return getattr(page, 'timeline', None)

    def quiet(then=None):
        """The workbench holds still while the tutorial points at it: no playing video, no scrolling timeline."""
        def run():
            page = studio()
            video = getattr(page, 'video', None)
            if video is not None and not getattr(video, '_paused', True):
                try:
                    video.set_paused(True)
                    page._sync_play_button(True)
                except Exception:  # noqa: BLE001 - a player that is not ready has nothing to pause
                    pass
            if then is not None:
                then()
        return run

    def continue_advanced():
        w.__dict__['_tutorial_continue'] = 'advanced'

    def explain_key():
        opener = getattr(w, '_open_api_key_explainer', None)
        if callable(opener):
            opener()

    # ---- 2026-10-21: real accounts, for people who know nothing about AI ----------------
    def saved_models():
        return dict((getattr(getattr(w, 'legacy', None), 'RUNTIME_SETTINGS', None) or {}).get('models') or {})

    def moss_pro_chosen():
        models = saved_models()
        return models.get('primary_asr_backend') == 'api' and models.get('qwen_asr_api_provider') == 'mosi_moss_pro'

    def moss_key_saved():
        try:
            from ..providers.llm_config import read_asr_api_key
            return bool(read_asr_api_key('mosi_moss_pro', str(saved_models().get('qwen_asr_api_url') or ''))[0])
        except Exception:  # noqa: BLE001
            return False

    def role_card(role):
        return lambda: (getattr(w.__dict__.get('recognition_plan'), 'cards', None) or {}).get(role)

    def open_moss_guide():
        w._open_api_setup_guide('mosi_moss_pro')

    def ai_settings():
        return dict(getattr(getattr(w, 'legacy', None), 'RUNTIME_SETTINGS', None) or {})

    def ai_stage():
        switches = ai_settings().get('switches') or {}
        return 'polish' if switches.get('enable_ai_polish', True) else 'group'

    def ai_key_saved():
        settings = ai_settings()
        try:
            from ..providers.llm_config import effective_ai_identity, text_ai_key_missing
            return (bool(effective_ai_identity(settings, ai_stage()).get('credential_configured'))
                    and not text_ai_key_missing(settings, ai_stage()))
        except Exception:  # noqa: BLE001 - unknown: ask for the key
            return False

    def open_deepseek_guide():
        w._open_api_setup_guide('deepseek', 'text')

    connection = {'shown': None}

    def connection_editor():
        return w.__dict__.get('polish_editor' if ai_stage() == 'polish' else 'group_editor')

    def test_connection():
        editor = connection_editor()
        if editor is not None:
            editor.test_connection()

    def connection_ok():
        editor = connection_editor()
        result = getattr(editor, 'last_connection_ok', None)
        if result != connection['shown']:   # the home card shows the answer as soon as it comes
            connection['shown'] = result
            refresh = getattr(w, '_refresh_home_process_facts', None)
            if callable(refresh):
                refresh()
        return result is True

    def field(name, fallback):
        return lambda: w.__dict__.get(name) or w.__dict__.get(fallback)

    # 2026-10-15 (user: “更简单、更图文化、少读字，跟着做就能完成”): the basics are the
    # shortest road to a first subtitle file; proofreading and the workbench are 进阶.
    # 2026-10-21 (user): cloud first — 主力转写 opens the MOSS Pro sign-up (skippable),
    # 字幕时间轴 shows why it matters, AI asks for a key (DeepSeek recommended) and
    # tests it; never "no key needed".
    if moss_pro_chosen() and not moss_key_saved():
        primary_step = TourStep(
            '③ **主力转写**把说话变成文字。**点这张卡**，注册 MOSS Pro', role_card('primary'),
            [TourAction('注册 MOSS Pro', open_moss_guide, advance=True, modal=True),
             TourAction('先跳过', lambda: None, advance=True)],
            note='注册、每天签到都送免费额度，电脑配置一般也能用。拿到 Key 贴进去就行',
            show_next=False, anim='moss_signup', page=home,
            click=TourAction('', open_moss_guide, advance=True, modal=True))
    elif moss_pro_chosen():
        primary_step = TourStep('③ **主力转写**把说话变成文字：MOSS Pro 已经设置好了', role_card('primary'),
                                note='点这张卡可以换成别的模型', anim='moss_signup', page=home)
    else:
        primary_step = TourStep('③ **主力转写**把说话变成文字：保持推荐就行', role_card('primary'),
                                note='点这张卡可以换模型；电脑配置一般，推荐换成 MOSS Pro 云端',
                                anim='plan_ok', page=home)
    if ai_key_saved():
        ai_step = TourStep('⑤ **AI** 把句子改通顺、断好句，还能翻译', get('home_process_card'),
                           note='API Key 已经填好了，下一步测一下连接', anim='ai_polish', page=home)
    else:
        ai_step = TourStep(
            '⑤ **AI** 把句子改通顺、断好句，还能翻译', get('home_process_card'),
            [TourAction('填 DeepSeek 的 API Key', open_deepseek_guide, modal=True),
             TourAction('API Key 是什么？', explain_key),
             TourAction('稍后再填', lambda: None, advance=True)],
            note='翻译、AI 断句、AI 校对都要先填 **API Key**。推荐 **DeepSeek**（最适配），充 10 元就够用一阵',
            show_next=False, done=ai_key_saved, anim='ai_polish', page=home,
            click=TourAction('', open_deepseek_guide, modal=True))
    basic = [
        TourStep('跟着点几下，学会做第一份字幕', note='用的是自带的演示视频，不上传、不花钱',
                 next_label='开始', enter=w._tutorial_prepare_demo),
        TourStep('① 把视频拖到这里；现在**点一下**放入演示视频', get('media_frame'),
                 [TourAction('放入演示视频', w._tutorial_add_demo_media, advance=True)], show_next=False, ready=on_home,
                 anim='drop', click=TourAction('', w._tutorial_add_demo_media, advance=True), page=home),
        TourStep('② 视频里说的是什么话，就选什么', field('spoken_language_field', 'recognition_language'),
                 [TourAction('中文', lambda: set_language('zh')), TourAction('日本語', lambda: set_language('ja')),
                  TourAction('English', lambda: set_language('en'))],
                 note='不确定就选“自动识别”', anim='spoken', page=home),
        primary_step,
        TourStep('④ **字幕时间轴**：让每句字幕出现、消失的时间更准', role_card('timeline'),
                 note=lambda: ('字幕跟着说话一起出来，不会早一截或晚一截。教学结束后会自动下载这个模型'
                               if w.__dict__.get('_first_run_downloads') else '字幕跟着说话一起出来，不会早一截或晚一截'),
                 anim='timeline_mg', page=home),
        ai_step,
        TourStep('⑥ 测一下连接：点**测试连接**', get('home_process_card'),
                 [TourAction('测试连接', test_connection)],
                 note='看到“连接正常”就能用了；失败的话检查 Key 有没有贴全、余额够不够',
                 ready=ai_key_saved, optional=True, done=connection_ok, anim='apikey', page=home),
        TourStep('⑦ 要翻译吗？选“原文 + 翻译”，再选翻译成哪种语言', field('subtitle_output_fields', 'subtitle_output'),
                 note='翻译也是 AI 做的，要用到上一步的 API Key', anim='subtitle_lang', page=home),
        TourStep('⑧ 填游戏名，人名和术语会写对（可以不填）', get('content_profile_card'), anim='glossary', page=home),
        TourStep('⑨ 点这里开始；现在**点一下**看演示结果', get('start_button'),
                 [TourAction('看演示结果', w._tutorial_demo_completion, advance=True)], show_next=False, anim='start',
                 click=TourAction('', w._tutorial_demo_completion, advance=True), page=home),
        TourStep('做好了！字幕已经生成，下面可以先看一眼', field('result_summary_card', 'result_title'), ready=on_completion,
                 page=to_completion),
        TourStep('⑩ 点这里导出字幕文件（SRT、ASS、TXT）', get('export_result_button'),
                 ready=on_completion, anim='export', page=to_completion),
        TourStep('学会了！推荐再学 3 分钟**进阶**', show_next=False,
                 note='一键找出写错的字、在工作台改字、审核、调时间。也可以先放入你自己的视频试试',
                 actions=[TourAction('继续学进阶（约 3 分钟）', continue_advanced, advance=True, big=True),
                          TourAction('回到首页', lambda: None, advance=True)], anim='advanced'),
    ]
    advanced = [
        # Straight on from the basics the demo result is already shown: building it again
        # would move every outline of the first steps while they appear.
        TourStep('进阶：改错字、审核、调时间，约 3 分钟', next_label='开始',
                 enter=lambda: None if on_completion() else w._tutorial_demo_completion()),
        # ---- result page
        TourStep('点这里，一次找出写错的人名和术语', get('repolish_current_glossary_button'),
                 [TourAction('帮我做', lambda: w.repolish_current_glossary_button.click())], show_next=False,
                 interactive=True, done=on_proofread, ready=on_completion, page=to_completion),
        # ---- proofreading, step by step
        TourStep('① 勾选「原神」词库（本机查找，免费）',
                 library_target, [TourAction('帮我做', check_library)], show_next=False, interactive=True,
                 done=library_checked, enter=offline_ai, ready=on_proofread, anim='gl_check',
                 click=TourAction('', check_library)),
        TourStep('② 点 AI 校对，找出词库外的错字（教学里不联网、不收费）', proofread_part('ai_button'),
                 [TourAction('帮我做', lambda: proofread().ai_button.click())], show_next=False, interactive=True,
                 done=ai_shown, ready=lambda: on_proofread() and not busy(), anim='gl_ai'),
        TourStep('③ 红字是错字，点下面的建议改正（至东 → 至冬）。按 **Ctrl+Z** 撤销', fix_target,
                 [TourAction('帮我做', fix_it)], show_next=False, interactive=True, done=fixed,
                 ready=lambda: on_proofread() and not busy(), anim='gl_fix'),
        TourStep('其余建议也可以逐条点，或一次采用全部', proofread_part('select_all'),
                 ready=on_proofread, optional=True),
        TourStep('④ 改好了，点返回结果', proofread_part('back_button'),
                 [TourAction('帮我做', lambda: proofread().back_button.click())], show_next=False, interactive=True,
                 done=on_completion, ready=on_proofread, anim='gl_back'),
        # ---- result page again
        TourStep('点这里打开字幕工作台：逐条修改、审核、调时间、压制', get('open_studio_result_button'),
                 [TourAction('帮我做', lambda: w.open_studio_result_button.click())], show_next=False, interactive=True,
                 done=studio_ready, ready=on_completion, anim='studio_open', page=to_completion),
        # ---- workbench (each step first stops the player: nothing moves under the outline)
        TourStep('**双击**字幕修改文字，或按 **E** 改播放头处那条', block_target,
                 [TourAction('帮我做', open_editor)], show_next=False, interactive=True, enter=quiet(),
                 done=lambda: editor() is not None, ready=studio_ready, focus=studio_keys, anim='edit', page=to_studio),
        TourStep('按 **Enter** 保存，**Esc** 取消', editor,
                 [TourAction('帮我做', save_editor)], show_next=False, interactive=True,
                 done=lambda: editor() is None, optional=True),
        TourStep('点这里开始审核，或按 **R**', studio_part('review_entry_button'),
                 [TourAction('帮我做', start_review)], show_next=False, interactive=True, enter=quiet(review_from_first),
                 done=reviewing, ready=lambda: studio_ready() and editor() is None, focus=studio_keys, anim='review',
                 page=to_studio),
        TourStep('三份识别结果并排：按 **1 / 2 / 3** 选用（也可直接点），自动跳到下一条',
                 candidates, [TourAction('帮我做', lambda: studio()._adopt_review_candidate(1))], show_next=False,
                 interactive=True, done=review_picked, enter=remember_undo, ready=reviewing, focus=studio_keys,
                 anim='review'),
        TourStep('再按 **R** 退出审核', studio_part('review_entry_button'),
                 [TourAction('帮我做', lambda: studio()._set_review_mode(False))], show_next=False, interactive=True,
                 done=lambda: not reviewing(), focus=studio_keys),
        TourStep('说话人管理：改名、换颜色、合并重复的人', tool('speaker_manager_button'),
                 ready=studio_ready, anim='speakers', enter=quiet(), page=to_studio),
        TourStep('批量替换：一次把所有「派门」改成「派蒙」，先预览再替换', tool('studio_find_replace_button'),
                 ready=studio_ready, anim='replace', enter=quiet(), page=to_studio),
        TourStep('**拖动**字幕两端改时间；按 **Q / W** 把起止点剪到播放头', studio_part('timeline'),
                 ready=studio_ready, anim='qw', enter=quiet(), page=to_studio),
        TourStep('标点：添加、去掉或保留原文，只影响显示和导出', studio_part('punctuation_button'),
                 ready=studio_ready, anim='punct', enter=quiet(), page=to_studio),
        TourStep('导出字幕：选格式和文件夹', studio_part('studio_export_button'), ready=studio_ready,
                 anim='export', enter=quiet(), page=to_studio),
        TourStep('压制成片：把字幕烧进视频', studio_part('studio_render_button'), ready=studio_ready,
                 anim='burn', enter=quiet(), page=to_studio),
        TourStep('完成！现在放入你自己的影音开始吧', next_label='回到首页', enter=None),
    ]
    return advanced if part == 'advanced' else basic


def tutorial_avoid(window):
    """The workbench's native video window (and its edit card) paint over any child widget."""
    def rects():
        page = window.built_page('studio') if hasattr(window, 'built_page') else None
        if page is None or window.pages.currentWidget() is not page:
            return []
        found = []
        for name in ('video', 'subtitle_edit_card'):
            widget = getattr(page, name, None)
            if widget is not None and widget.isVisible():
                top_left = widget.mapTo(window, QPoint(0, 0))
                found.append(QRectF(top_left.x(), top_left.y(), widget.width(), widget.height()))
        return found
    return rects


def start_home_tour(window, on_finished=None, part: str = 'basic') -> GuidedTour | None:
    """Start the tutorial (one at a time); ``part`` is 'basic' or 'advanced'."""
    existing = window.findChild(GuidedTour)
    if existing is not None and getattr(existing, 'mode', '') != 'closed':
        return existing
    tour = GuidedTour(window, tutorial_steps(window, part), avoid=tutorial_avoid(window))
    tour.part = part

    def next_part():
        """继续学进阶 on the last basic step: the advanced steps in the same overlay (2026-10-21)."""
        if tour.part == 'basic' and window.__dict__.pop('_tutorial_continue', '') == 'advanced':
            return tutorial_steps(window, 'advanced'), 'advanced'
        return None
    tour.next_part = next_part
    if on_finished is not None:
        tour.finished.connect(on_finished)
    tour.start()
    return tour
