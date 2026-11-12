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

2026-10-22 (user): one tutorial again - "进阶" made people think the basics
were enough. Right after the video the plan step opens the cloud / local
comparison by itself (``TourStep.auto``). The AI step opens AI 设置 and the
next steps live in that window (``TourStep.host``): the overlay stays above it
(raised without taking the keyboard from it) instead of stepping aside, points
at its parts, and goes on after them once the window closes. Motion: the
outline sets off at once and follows a target that is still moving (it used to
wait ~200 ms for it to hold still); the bubble fades in as one picture drawn by
the overlay (a QGraphicsOpacityEffect re-rendered all its widgets on every
frame); only an interactive step's ring pulses, twice. While a page answers a
click (the workbench takes seconds to open) the shade stays and lets clicks
through; hiding it made the whole window flash bright and dark again.

2026-11-11 (user): 兔白, the user's own PNGTuber bunny, stands beside the
card (``TourBubble``) on the side away from the outline. The words are typed
one by one while it babbles (``tour_mascot``); a click on the words shows
them at once. ``==marked==`` words stand out on a bright marker. A click on
the bunny makes it hop and say something friendly in a small balloon. Its
voice can be switched off in the bubble.
"""
from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import (QEasingCurve, QElapsedTimer, QEvent, QPoint, QPointF, QRect, QRectF, QSize, QSizeF, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QImage, QMovie, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRegion
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..i18n import bind_text, tr
from .tour_mascot import GREETING, MascotVoice, Typewriter, marked_html, marker_colors, next_chat_line, speaking_ms


@dataclass
class TourAction:
    label: str
    run: Callable[[], None]
    advance: bool = False   # go to the next step after running
    modal: bool = False     # opens a window: the tutorial steps aside until it closes
    big: bool = False       # the step's main suggestion: a large primary button that takes the row
    goto: str = ''          # go on at the step with this ``name`` instead (2026-10-22)


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
    # 2026-10-22: a step inside a window of its own (AI 设置): the tutorial stays above that
    # window instead of stepping aside, and goes on after the window's steps once it closes.
    host: Callable[[], QWidget | None] | None = None
    name: str = ''                                       # for TourAction.goto
    auto: TourAction | None = None                       # runs once, a moment after the step has appeared
    chapter: str = ''                                    # the counter counts within it: "做字幕 · 3 / 19"
    group: str = ''                                      # alternatives (only one is shown) count once
    # 2026-10-24: the page keeps changing for a moment after this step (the demo video loading, the
    # 「还差一步」 banner answering): the next step is judged and shown only once this is true.
    settle: Callable[[], bool] | None = None


def tutorial_anim_path(name: str, light: bool, still: bool = False):
    """assets/onboarding/tutorial/<name>-<dark|light>.webp (or -still.png), rendered from source/tutorial.html."""
    from .main_ui_helpers import APP_ROOT
    file = f"{name}-{'light' if light else 'dark'}" + ('-still.png' if still else '.webp')
    path = APP_ROOT / 'assets' / 'onboarding' / 'tutorial' / file
    return path if path.is_file() else None


class TourAnim(QWidget):
    """The gesture animation in the bubble.

    Original WebP gestures take precedence. Program-drawn scenes remain for
    newer steps without an original asset, and as a resource-error fallback.
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
        self.source = ''
        self.resource_error = ''

    def load(self, name: str, light: bool) -> bool:
        """Prepare ``name`` without playing it yet."""
        self.stop()
        self.name = name or ''
        if not name:
            return False
        from ..design.ui_motion import reduced_motion
        # The language selector was renamed when the cloud-first tour grew.
        asset_name = {'spoken': 'language'}.get(name, name)
        path = tutorial_anim_path(asset_name, light, still=reduced_motion())
        if path is not None:
            if reduced_motion():
                self._still = QImage(str(path))
                if not self._still.isNull():
                    self.source = 'original-still'
                    self.update()
                    return True
            else:
                movie = QMovie(str(path), parent=self)
                movie.setCacheMode(QMovie.CacheMode.CacheNone)
                if movie.isValid() and movie.jumpToFrame(0):
                    movie.frameChanged.connect(self.update)
                    self._movie = movie
                    self.source = 'original-webp'
                    self.update()
                    return True
                movie.deleteLater()
            self.resource_error = str(path.name)
        from .tour_motion import SCENES, Look, refresh_keys
        scene = SCENES.get(name)
        if scene is not None:
            refresh_keys()   # the key caps name the keys as set (2026-10-24)
            from ..design.theme_manager import theme_key
            from ..design.ui_theme import theme_definition
            self._scene = scene
            self._look = Look(theme_definition(theme_key()))
            self.source = 'program-scene'
            self.update()
            return True
        return False

    def start(self):
        from ..design.ui_motion import reduced_motion
        if reduced_motion():
            return
        if self._scene is not None:
            if not self._ticker.isActive():
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
        self._look = None
        self.source = ''
        self.resource_error = ''
        if self._movie is not None:
            self._movie.stop()
            self._movie.frameChanged.disconnect()
            self._movie.deleteLater()
        self._movie = None
        self._still = None

    def hideEvent(self, event):  # noqa: N802
        self._ticker.stop()
        if self._movie is not None:
            self._movie.setPaused(True)
        super().hideEvent(event)

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
        size = QSizeF(image.size())
        size.scale(QSizeF(self.size()), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2,
                        size.width(), size.height())
        painter.drawImage(target, image)
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


class TourBubble(QWidget):
    """The bubble (2026-11-11): 兔白 standing at the card's lower corner, on the side away from the outline.

    ``card`` holds the words and buttons; the bunny overlaps its edge a little.
    Without the bunny's pictures the bubble is just the card."""

    TUCK = 16                                            # the bunny's side tucked behind the card edge
    HEIGHTS = {'full': 168, 'compact': 140, 'mini': 112}

    @property
    def overlap(self) -> int:
        """Its transparent side margin (room for the swing) plus a little of the bunny over the card."""
        return (self.mascot.pad_x + self.TUCK) if self.mascot is not None else 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('tourBubble')
        self.card = QFrame(self)
        self.card.setObjectName('tourCard')
        self.side = 'left'
        self.mascot = None
        self.docked = True                               # False while the bunny is out on its own
        try:
            from ..design.bunny_mascot import BunnyMascot
            mascot = BunnyMascot(self, height=self.HEIGHTS['full'])
        except Exception:  # noqa: BLE001 - no pictures: the card alone
            mascot = None
        if mascot is not None and mascot.available:
            mascot.setObjectName('tourMascot')
            mascot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            mascot.setCursor(Qt.CursorShape.OpenHandCursor)   # 2026-11-11: drag it, or click it
            mascot._timer.setInterval(33)   # calm enough; the overlay is a large translucent window
            self.mascot = mascot
        elif mascot is not None:
            mascot.deleteLater()

    def set_size_key(self, key: str) -> None:
        if self.mascot is not None:
            from . import ui_zoom
            self.mascot.set_mascot_height(ui_zoom.px(self.HEIGHTS.get(key, self.HEIGHTS['full'])))
        self._arrange()

    def set_side(self, side: str) -> None:
        self.side = 'right' if side == 'right' else 'left'
        self._arrange()

    def fit(self, size: QSize) -> None:
        """Resize and lay out now (a hidden widget gets its resize event only when shown)."""
        self.resize(size)
        self._arrange()

    def sizeHint(self):  # noqa: N802 - Qt override
        card = self.card.sizeHint()
        if self.mascot is None:
            return card
        bunny = self.mascot.size()
        return QSize(card.width() + bunny.width() - self.overlap, max(card.height(), bunny.height()))

    def card_rect(self) -> QRect:
        """Where the card is inside the bubble (it stands on the bubble's bottom edge)."""
        if self.mascot is None:
            return QRect(QPoint(0, 0), self.size())
        bunny = self.mascot.size()
        width = max(1, self.width() - bunny.width() + self.overlap)
        height = min(self.height(), self.card.sizeHint().height())
        x = bunny.width() - self.overlap if self.side == 'left' else 0
        return QRect(x, self.height() - height, width, height)

    def _arrange(self) -> None:
        self.card.setGeometry(self.card_rect())
        if self.mascot is not None and self.docked:
            bunny = self.mascot.size()
            x = 0 if self.side == 'left' else self.width() - bunny.width()
            self.mascot.move(x, self.height() - bunny.height())
            self.mascot.raise_()

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._arrange()


class GuidedTour(QWidget):
    finished = Signal(bool)  # True when the last step was passed, False when skipped

    WAIT_MS = 20000                                      # a page that never comes: skip the step
    TEXT_WIDTH = 440                                     # bubble text column (logical px)
    COMPACT_WIDTH = 340                                  # when no full-size spot near the target is free
    # 2026-10-22 (user: the outline still stutters and is slow to change place): the outline
    # sets off at once and follows a target that is still moving while it glides (before, it
    # first waited for the target to hold still: about 200 ms of nothing on every step).
    GLIDE_MS = 220
    CATCH_UP_MS = 120                                    # the target moved during the glide: once more
    CATCH_UPS = 6
    REVEAL_MS = 150
    GAP = 22                                             # bubble ↔ outline
    MARGIN = 16                                          # bubble ↔ window edge
    POLL_MS = 40
    FLOATING = None                                      # None: a tool window on Windows, a child widget elsewhere
    FOLLOW_MS = 60
    JUMP = 48                                            # a shown target that moves less than this is followed at once

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
        self._catch_ups = 0
        self._auto_done = set()                          # steps whose ``auto`` action has run
        self._reveal_pixmap = None                       # the bubble, drawn by the overlay while it fades in
        self._click_through = False
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
        self._shown_target = None                        # the widget the shown step outlines (its Hide is watched)
        self._settle = None                              # (check, since ms): the last step's page is still changing
        # 2026-11-11: 兔白 types the words while it babbles; a click on it gives a chat line.
        self._colors = marker_colors(self.theme)
        self._text_source = ''
        self._note_source = ''
        self.voice = MascotVoice(self)
        self._typer = Typewriter(self)
        self._typer.spoke.connect(self._spoke)
        self._typer.finished.connect(self._typing_done)
        self._chat_typer = Typewriter(self)
        self._chat_typer.spoke.connect(self._spoke)
        self._chat_hide = QTimer(self)
        self._chat_hide.setSingleShot(True)
        self._chat_hide.timeout.connect(self._hide_chat)
        self._chat_line = ''
        self._chat_recent = []                           # the last few chat lines (no quick repeats)
        # 2026-11-11 (user): 兔白 is picked up by the mouse and follows it; let go and it is thrown:
        # it falls, bounces off the window's edges and the menu bar and rolls to a stop, flat (no
        # spin), like the dice in the user's Open Design project. Hitting the menu bar makes the
        # bar jump and glow where it was hit; a hard hit on another edge nudges the window that way.
        self._drag = None                                # press point, grab offset, whether it moved
        self._grab_target = None                         # where the pointer holds it (overlay coordinates)
        self._grab_history = []                          # (time, position) of the last moments held
        self._puck_v = QPointF()
        self._puck_pos = QPointF()
        self._puck_last = 0.0
        self._puck_started = 0.0
        self._puck = QTimer(self)
        self._puck.setTimerType(Qt.TimerType.PreciseTimer)
        self._puck.setInterval(16)
        self._puck.timeout.connect(self._puck_step)
        self._shake = QVariantAnimation(self)
        self._shake.setStartValue(0.0)
        self._shake.setEndValue(1.0)
        self._shake.setDuration(self.SHAKE_MS)
        self._shake.valueChanged.connect(self._shake_step)
        self._shake.finished.connect(self._shake_done)
        self._shake_origin = None
        self._shake_strength = 0.0
        self._shake_direction = QPointF(0, -1)
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(16)
        self._flash_timer.timeout.connect(self._flash_tick)
        self._flash = None                               # (x, y, power, started, side) of an edge hit
        self._greeted = False
        self._typed_for = None                           # the step whose words have been typed
        self._build_bubble()
        self._build_chat()
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
        self.bubble = TourBubble(self)
        self.bubble.setStyleSheet(
            f"QFrame#tourCard {{ background: {t.surface_elevated}; border: 2px solid {t.accent}; border-radius: 22px; }}"
            f"QLabel#tourCount {{ color: {t.accent}; background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16);"
            f" border-radius: 10px; padding: 2px 10px; font-size: 12px; font-weight: 700; }}"
            f"QLabel#tourText {{ color: {t.text}; font-size: 16px; }}"
            f"QLabel#tourNote {{ color: {t.text_secondary}; font-size: 13px; }}"
            f"QPushButton#tourSkip {{ background: transparent; border: 0; color: {t.text_muted}; padding: 4px 6px; }}"
            f"QPushButton#tourSkip:hover {{ color: {t.text}; }}"
            f"QPushButton#tourVoice {{ background: transparent; border: 0; border-radius: 12px; padding: 3px; }}"
            f"QPushButton#tourVoice:hover {{ background: rgba({accent.red()}, {accent.green()}, {accent.blue()}, 0.16); }}")
        self.bubble.hide()
        layout = QVBoxLayout(self.bubble.card)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName('tourCount')
        top.addWidget(self.count)
        top.addStretch(1)
        self.voice_button = QPushButton()
        self.voice_button.setObjectName('tourVoice')
        self.voice_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.voice_button.setIconSize(QSize(16, 16))
        self.voice_button.clicked.connect(self._toggle_voice)
        self._sync_voice_button()
        top.addWidget(self.voice_button)
        if self.bubble.mascot is None:   # (in its layout first: a parentless setVisible(True) opens a window)
            self.voice_button.hide()
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

    # ------------------------------------------------------------ 兔白 (2026-11-11)
    def _build_chat(self):
        """The small balloon over the bunny's head for its chat lines."""
        t = self.theme
        self.chat = QLabel(self)
        self.chat.setObjectName('tourChat')
        self.chat.setTextFormat(Qt.TextFormat.RichText)
        self.chat.setWordWrap(True)
        self.chat.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chat.setStyleSheet(
            f"QLabel#tourChat {{ background: {t.surface_elevated}; color: {t.text}; border: 2px solid {t.accent};"
            f" border-radius: 16px; padding: 8px 14px; font-size: 14px; font-weight: 600; }}")
        self.chat.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.chat.hide()

    def _sync_voice_button(self):
        from ..design.themed_icons import themed_icon
        on = self.voice.enabled
        self.voice_button.setIcon(themed_icon('fa5s.volume-up' if on else 'fa5s.volume-mute', 'accent' if on else 'muted'))
        bind_text(self.voice_button, '兔白的声音：开（点一下关掉）' if on else '兔白的声音：关（点一下打开）',
                  property='toolTip')

    def _toggle_voice(self):
        self.voice.set_enabled(not self.voice.enabled)
        if not self.voice.enabled:
            self.voice.close()
        self._sync_voice_button()

    def _spoke(self, char: str):
        if self.voice.say(char) and self.bubble.mascot is not None:
            self.bubble.mascot.open_mouth(0.075)

    def _typing_done(self):
        if not self._greeted and self.mode == 'shown' and self.bubble.mascot is not None:
            self._greeted = True
            QTimer.singleShot(250, lambda: self.mode == 'shown' and self._show_chat(GREETING))

    # ------------------------------------------------------------ 兔白 picked up and thrown (2026-11-11)
    # 2026-11-11 round 2 (user): like the DVD logo - no gravity; it bounces off all four window
    # edges, each hit glows there and the window shivers, and it slowly runs out of speed.
    FOLLOW = 26.0                                        # 1/s: how tightly it follows the pointer while held
    RESTITUTION = 0.88                                   # speed kept after an edge
    DRAG = 0.32                                          # 1/s: how slowly it loses speed between edges
    STOP_DRAG = 3.0                                      # 1/s once it is slow: it eases to a stop
    HIT_SPEED = 240.0                                    # px/s into an edge that gives feedback
    SHAKE_SPEED = HIT_SPEED
    MAX_THROW = 3800.0
    MAX_FLIGHT_S = 14.0
    SHAKE_MS = 340
    FLASH_MS = 650

    def _mascot_rect(self) -> QRectF:
        """The bunny's widget rectangle in overlay coordinates, docked or not."""
        rect = QRectF(self.bubble.mascot.geometry())
        return rect.translated(QPointF(self.bubble.pos())) if self.bubble.docked else rect

    def _undock_mascot(self):
        """Out of the bubble onto the overlay, keeping the pointer's hold (reparenting drops the grab)."""
        mascot = self.bubble.mascot
        if not self.bubble.docked:
            return
        at = self._mascot_rect().topLeft()
        self.bubble.docked = False
        mascot.setParent(self)
        mascot.move(at.toPoint())
        mascot.show()
        mascot.raise_()
        self._puck_pos = QPointF(at)

    def _dock_mascot(self):
        """Back beside the card (the step changes, the tutorial closes)."""
        self._puck.stop()
        mascot = self.bubble.mascot
        if self._drag is not None and mascot is not None:
            mascot.releaseMouse()
        self._drag = None
        self._grab_target = None
        if mascot is None or self.bubble.docked:
            return
        mascot.stretch = 0.0
        mascot.setParent(self.bubble)
        self.bubble.docked = True
        self.bubble._arrange()
        mascot.show()
        mascot.setCursor(Qt.CursorShape.OpenHandCursor)
        self._apply_mask()
        self.update()

    def _puck_limits(self) -> QRectF:
        """Where the widget's top-left may go: the drawn bunny (not its transparent margins) stays inside."""
        mascot = self.bubble.mascot
        bottom = round(mascot.mascot_height * 0.06)
        m = 4
        top = m - mascot.pad_top                         # the window's top edge (no menu bar involved)
        return QRectF(m - mascot.pad_x, top,
                      self.width() - mascot.width() + 2 * mascot.pad_x - 2 * m,
                      self.height() - mascot.height() + bottom - m - top)

    def _place_puck(self, at: QPointF):
        mascot = self.bubble.mascot
        old = self._mascot_rect()
        limits = self._puck_limits()
        at = QPointF(max(limits.left(), min(at.x(), limits.right())), max(limits.top(), min(at.y(), limits.bottom())))
        self._puck_pos = at
        mascot.move(at.toPoint())
        if self.chat.isVisible():
            self._place_chat()
        self._apply_mask()
        self.update(old.united(self._mascot_rect()).adjusted(-12, -12, 12, 24).toAlignedRect())

    def _mascot_press(self, event) -> bool:
        if self.bubble.mascot is None or self.mode != 'shown' or event.button() != Qt.MouseButton.LeftButton:
            return False
        point = QPointF(event.globalPosition())
        caught = self._puck.isActive() and not self.bubble.docked   # caught in the air: held at once
        self._puck.stop()
        self._drag = dict(start=point, grab=QPointF(event.position()), moved=caught)
        if caught:
            self._start_hold(point)
        return True

    def _start_hold(self, point: QPointF):
        mascot = self.bubble.mascot
        if self._typer.running:
            self._typer.finish()   # picked up: the words are all there at once, no babble while it flies
        self._chat_typer.stop()
        self._undock_mascot()
        mascot.grabMouse()                                # the press's hold, kept across the reparenting
        mascot.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._grab_history = [(time.perf_counter(), QPointF(self._puck_pos))]
        self._grab_target = QPointF(self.mapFromGlobal(point.toPoint())) - self._drag['grab']
        self._puck_v = QPointF()
        self._puck_last = time.perf_counter()
        self._puck.start()

    def _mascot_move(self, event) -> bool:
        drag = self._drag
        if drag is None:
            return False
        point = QPointF(event.globalPosition())
        if not drag['moved']:
            delta = point - drag['start']
            if abs(delta.x()) + abs(delta.y()) < 4:
                return True
            drag['moved'] = True
            self._start_hold(point)
        self._grab_target = QPointF(self.mapFromGlobal(point.toPoint())) - drag['grab']
        return True

    def _mascot_release(self, event) -> bool:
        drag, self._drag = self._drag, None
        if drag is None:
            return False
        mascot = self.bubble.mascot
        if not drag['moved']:
            self._mascot_clicked()
            return True
        mascot.releaseMouse()
        mascot.setCursor(Qt.CursorShape.OpenHandCursor)
        self._grab_target = None
        now = time.perf_counter()
        recent = [(t, p) for t, p in self._grab_history if now - t <= 0.09] or self._grab_history[-1:]
        (t0, p0), (t1, p1) = recent[0], self._grab_history[-1]
        velocity = (p1 - p0) / max(t1 - t0, 0.012) if now - t1 < 0.12 else QPointF()
        speed = (velocity.x() ** 2 + velocity.y() ** 2) ** 0.5
        if speed > self.MAX_THROW:
            velocity *= self.MAX_THROW / speed
        from ..design.ui_motion import reduced_motion
        if reduced_motion():
            velocity = QPointF()
        self._puck_v = velocity
        self._puck_started = now
        self._puck_last = now
        self._puck.start()
        return True

    def _puck_step(self):
        mascot = self.bubble.mascot
        if mascot is None or self.bubble.docked:
            self._puck.stop()
            return
        now = time.perf_counter()
        dt = min(0.04, max(0.001, now - self._puck_last))
        self._puck_last = now
        limits = self._puck_limits()
        if self._grab_target is not None:
            previous = QPointF(self._puck_pos)
            follow = 1 - math.exp(-dt * self.FOLLOW)
            self._place_puck(previous + (self._grab_target - previous) * follow)
            self._puck_v = (self._puck_pos - previous) / dt
            self._grab_history = [(t, p) for t, p in self._grab_history if now - t < 0.14] + [(now, QPointF(self._puck_pos))]
            speed = (self._puck_v.x() ** 2 + self._puck_v.y() ** 2) ** 0.5
            self._relax_stretch(mascot, 0.1 + min(0.08, speed / 20000), dt)   # held up: a little taller
            return
        steps = max(1, math.ceil(dt / 0.008))
        h = dt / steps
        v, at = QPointF(self._puck_v), QPointF(self._puck_pos)
        hits = []
        for _ in range(steps):
            speed = (v.x() ** 2 + v.y() ** 2) ** 0.5
            v *= math.exp(-(self.DRAG if speed > 160 else self.STOP_DRAG) * h)
            at += v * h
            if at.x() < limits.left() or at.x() > limits.right():
                hits.append(('left' if at.x() < limits.left() else 'right', abs(v.x())))
                at.setX(max(limits.left(), min(at.x(), limits.right())))
                v.setX(-v.x() * self.RESTITUTION)
            if at.y() < limits.top() or at.y() > limits.bottom():
                hits.append(('top' if at.y() < limits.top() else 'bottom', abs(v.y())))
                at.setY(max(limits.top(), min(at.y(), limits.bottom())))
                v.setY(-v.y() * self.RESTITUTION)
        self._puck_v = v
        self._place_puck(at)
        squash = 0.0
        for side, speed in hits:
            if speed < self.HIT_SPEED:
                continue
            power = max(0.3, min(1.0, speed / 2200.0))
            squash = min(squash, -0.22 * power) if side in ('top', 'bottom') else max(squash, 0.15 * power)
            self._edge_hit(side, power)
        if squash:
            mascot.stretch = squash
        self._relax_stretch(mascot, 0.0, dt)
        speed = (v.x() ** 2 + v.y() ** 2) ** 0.5
        if speed < 8 or now - self._puck_started > self.MAX_FLIGHT_S:
            self._puck_v = QPointF()
            mascot.stretch = 0.0
            mascot.update()
            self._puck.stop()

    @staticmethod
    def _relax_stretch(mascot, target: float, dt: float):
        mascot.stretch += (target - mascot.stretch) * (1 - math.exp(-dt * 14))
        if abs(mascot.stretch) < 0.002 and not target:
            mascot.stretch = 0.0
        mascot.update()

    @staticmethod
    def _kick(value: float) -> float:
        """The dice's menu-bar keyframes: out to 1 at 22 %, a small rebound at 60 %, home at 100 %."""
        if value < 0.22:
            k = value / 0.22
            return math.sin(k * math.pi / 2)
        if value < 0.6:
            k = (value - 0.22) / 0.38
            return 1 - 1.25 * (0.5 - 0.5 * math.cos(k * math.pi))
        k = (value - 0.6) / 0.4
        return -0.25 * (1 - (0.5 - 0.5 * math.cos(k * math.pi)))

    def _shake_window(self, strength: float, direction: QPointF = QPointF(0, -1)):
        """The window gives way a few pixels in the hit's direction and springs back (content when maximized)."""
        from ..design.ui_motion import reduced_motion
        if reduced_motion():
            return
        running = self._shake.state() == QVariantAnimation.State.Running
        self._shake_strength = max(strength, self._shake_strength if running else 0.0)
        self._shake_direction = QPointF(direction)
        if self._shake_origin is None:
            window = self.window_
            if window.isMaximized() or window.isFullScreen():
                layout = window.layout()
                self._shake_origin = ('margins', layout.contentsMargins()) if layout is not None else None
            else:
                self._shake_origin = ('position', window.pos())
        if self._shake_origin is None:
            return
        self._shake.stop()
        self._shake.start()

    def _shake_offset(self, value: float) -> QPoint:
        amount = (1.5 + 2.5 * self._shake_strength) * self._kick(value)   # half of before (user)
        return QPoint(round(self._shake_direction.x() * amount), round(self._shake_direction.y() * amount))

    def _shake_step(self, value):
        origin = self._shake_origin
        if origin is None:
            return
        offset = self._shake_offset(float(value))
        if origin[0] == 'position':
            self.window_.move(origin[1] + offset)
        else:
            margins = origin[1]
            self.window_.layout().setContentsMargins(margins.left() + offset.x(), margins.top() + offset.y(),
                                                     margins.right() - offset.x(), margins.bottom() - offset.y())

    def _shake_done(self):
        origin, self._shake_origin = self._shake_origin, None
        self._shake_strength = 0.0
        if origin is None:
            return
        if origin[0] == 'position':
            self.window_.move(origin[1])
        elif self.window_.layout() is not None:
            self.window_.layout().setContentsMargins(origin[1])

    def _edge_hit(self, side: str, power: float):
        """An edge was hit: it glows where the bunny touched it and the window shivers that way."""
        rect = self._mascot_rect()
        mascot = self.bubble.mascot
        if side in ('top', 'bottom'):
            x = rect.center().x()
            y = 0.0 if side == 'top' else float(self.height())
        else:
            x = 0.0 if side == 'left' else float(self.width())
            y = rect.top() + mascot.pad_top + (rect.height() - mascot.pad_top) / 2
        self._flash = (float(x), float(y), float(power), time.perf_counter(), side)
        if not self._flash_timer.isActive():
            self._flash_timer.start()
        self._shake_window(power, {'left': QPointF(-1, 0), 'right': QPointF(1, 0),
                                   'top': QPointF(0, -1), 'bottom': QPointF(0, 1)}[side])

    def _flash_tick(self):
        flash = self._flash
        if flash is None or (time.perf_counter() - flash[3]) * 1000 > self.FLASH_MS:
            self._flash = None
            self._flash_timer.stop()
            self.update()
            return
        self.update(QRect(round(flash[0] - 150), round(flash[1] - 150), 300, 300))

    def _paint_flash(self, painter):
        flash = self._flash
        if flash is None:
            return
        x, y, power, started, side = flash
        k = (time.perf_counter() - started) * 1000 / self.FLASH_MS
        if k >= 1:
            return
        from PySide6.QtGui import QRadialGradient
        glow = QColor(self.theme.accent)
        gradient = QRadialGradient(QPointF(x, y), 130)
        glow.setAlphaF(max(0.0, min(1.0, 0.9 * power * (1 - k))))
        gradient.setColorAt(0.0, glow)
        glow.setAlphaF(0.0)
        gradient.setColorAt(0.72, glow)
        painter.save()
        painter.translate(x, y)
        painter.scale(1.0, 50 / 130) if side in ('top', 'bottom') else painter.scale(50 / 130, 1.0)
        painter.translate(-x, -y)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(x, y), 130, 130)
        painter.restore()

    def _mascot_clicked(self):
        mascot = self.bubble.mascot
        if mascot is None or self.mode != 'shown':
            return
        mascot.hop()
        self._chat_line = next_chat_line(self._chat_line, self._chat_recent)
        self._chat_recent = (self._chat_recent + [self._chat_line])[-6:]
        self._show_chat(self._chat_line)

    def _show_chat(self, line: str):
        from . import ui_zoom
        mascot = self.bubble.mascot
        if mascot is None or not self.bubble.isVisible():
            return
        text = str(tr(line))
        self.chat.ensurePolished()
        self.chat.setText(marked_html(text, self._colors))
        self.chat.setFixedWidth(min(ui_zoom.px(230), max(ui_zoom.px(120), self.chat.fontMetrics().horizontalAdvance(text)
                                                            + ui_zoom.px(36))))
        self.chat.setFixedHeight(_text_height(self.chat, self.chat.width() - ui_zoom.px(32)) + ui_zoom.px(18))
        self._place_chat()
        self.chat.show()
        self.chat.raise_()
        from ..design.ui_motion import reduced_motion
        if reduced_motion():
            self._spoke(text[:1])
        else:
            self._chat_typer.prepare([(self.chat, text)], self._colors)
            self._chat_typer.start()
        self._chat_hide.start(speaking_ms(text) + 2400 + 40 * len(text))   # typed, then time to read it
        self._apply_mask()
        self.update()

    def _chat_box(self) -> QRectF:
        return QRectF(self.chat.geometry()) if self.chat.isVisible() else QRectF()

    def _place_chat(self):
        """Beside the bunny's head on its outer side (never over the card's words); else over or under the bubble."""
        mascot = self.bubble.mascot
        head = self._mascot_rect()
        box = QRectF(self.bubble.geometry())
        w, h = self.chat.width(), self.chat.height()
        m = self.MARGIN
        if not self.bubble.docked:   # out on its own: over its head, else under its feet
            x = max(m, min(head.center().x() - w / 2, self.width() - w - m))
            y = head.top() + mascot.pad_top - h - 8
            if y < m:
                y = min(self.height() - h - m, head.bottom() + 4)
            self.chat.move(round(x), round(y))
            return
        y = max(m, min(head.top() + mascot.pad_top - h * 0.25, self.height() - h - m))
        x = head.left() + mascot.pad_x - w - 6 if self.bubble.side == 'left' else head.right() - mascot.pad_x + 6
        if not (m <= x <= self.width() - w - m):
            x = max(m, min(head.center().x() - w / 2, self.width() - w - m))
            y = box.top() - h - 12
            if y < m:
                y = min(self.height() - h - m, box.bottom() + 12)
        self.chat.move(round(x), round(y))

    def _hide_chat(self):
        self._chat_typer.stop()
        self._chat_hide.stop()
        if self.chat.isVisible():
            dirty = self.chat.geometry().adjusted(-12, -12, 12, 24)
            self.chat.hide()
            self._apply_mask()
            self.update(dirty)

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
        # 上一步 never crosses into or out of a window's own steps (AI 设置 may be closed by then).
        previous = self.steps[self.index - 1] if self.index > 0 else None
        self.back.setVisible(previous is not None and step.show_next
                             and (previous.host is None) == (step.host is None))
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
        if action.goto and self._index_of(action.goto) >= 0:
            self.go(self._index_of(action.goto))
        elif action.advance:
            self.go(self.index + 1)
        elif action.modal and self.mode == 'dialog' and self._foreign_dialog() is None:
            self._resume(navigate=False)

    def _prepare_bubble(self, step: TourStep):
        self._typer.stop()
        if self._typed_for != self.index:   # 2026-11-11: the same step placed again is not typed (spoken) again
            self._typed_for = None
        text = step.text() if callable(step.text) else step.text
        self._text_source = str(tr(text))
        self.text.setText(marked_html(self._text_source, self._colors))
        note = step.note() if callable(step.note) else step.note
        self._note_source = str(tr(note)) if note else ''
        self.note.setText(marked_html(self._note_source, self._colors) if note else '')
        self.note.setVisible(bool(note))
        self.count.setText(self._progress_text(step))
        name = step.anim() if callable(step.anim) else step.anim
        self._has_anim = self.anim.load(name, self.light)
        self._fill_buttons(step)

    def _progress_text(self, step: TourStep) -> str:
        """Where we are: within the step's chapter, alternatives of one step counted once (2026-10-22).

        One tutorial counted 40 steps (three ways of saying ③, two of ⑤...), which
        looked endless; "做字幕 · 8 / 19" then "改字幕 · 2 / 18" reads as two short parts.
        """
        units = []
        for index, other in enumerate(self.steps):
            key = (other.chapter, other.group or f'#{index}')
            if other.chapter == step.chapter and key not in units:
                units.append(key)
        current = (step.chapter, step.group or f'#{self.index}')
        position = units.index(current) + 1 if current in units else self.index + 1
        count = f'{position} / {len(units)}'
        return f'{tr(step.chapter)} · {count}' if step.chapter else count

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
        self.bubble.set_size_key(key)

    def _measure(self) -> QSize:
        # New action buttons get their style only when polished; measure after that, or the
        # bubble comes out a button-height short and the last text line hides behind them.
        for child in self.bubble.findChildren(QWidget):
            child.ensurePolished()
        self.bubble.card.layout().activate()
        return self.bubble.sizeHint()

    # ------------------------------------------------------------ steps
    def start(self):
        self._sync_geometry()
        self.show()
        self.raise_()
        self._follow.start()
        if self.bubble.mascot is not None:
            QTimer.singleShot(0, self.voice.warm_up)   # while the outline glides to the first step
        self.go(0)

    def _step(self) -> TourStep | None:
        return self.steps[self.index] if 0 <= self.index < len(self.steps) else None

    def _host_of(self, step) -> QWidget | None:
        """The open window a step lives in (AI 设置), None for the main window or a closed one."""
        if step is None or step.host is None:
            return None
        try:
            host = step.host()
        except Exception:  # noqa: BLE001 - a window that is not built yet
            return None
        return host if host is not None and host.isVisible() else None

    def _step_host(self) -> QWidget | None:
        return self._host_of(self._step())

    def _host_gone(self, step) -> bool:
        return step is not None and step.host is not None and self._host_of(step) is None

    def _index_of(self, name: str) -> int:
        return next((index for index, step in enumerate(self.steps) if name and step.name == name), -1)

    def _leave_host(self):
        """The window of these steps was closed: on with the first step outside it (or back before them)."""
        index = self.index
        if self._wait_direction < 0:
            while index >= 0 and self.steps[index].host is not None:
                index -= 1
            self.go(max(0, index), step=-1)
            return
        while index < len(self.steps) and self.steps[index].host is not None:
            index += 1
        self.go(index)

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

    def _exposed(self, target, host=None) -> bool:
        """Nothing of the window lies over the target's centre (an in-window dialog such as the model picker)."""
        widget, point = (target[0], target[1].center().toPoint()) if isinstance(target, tuple) \
            else (target, target.rect().center())
        if host is not None:
            hit = host.childAt(host.mapFromGlobal(widget.mapToGlobal(point)))
        else:
            hit = self.window_.childAt(widget.mapTo(self.window_, point))
        node = hit
        while node is not None:
            if node is widget or node is self:   # a child overlay (not floating) hides the answer: assume yes
                return True
            node = node.parentWidget()
        return hit is None

    def _target(self, index):
        target = self._raw_target(index)
        host = self._host_of(self.steps[index]) if 0 <= index < len(self.steps) else None
        return target if target is not None and self._exposed(target, host) else None

    def _covered(self, index) -> bool:
        target = self._raw_target(index)
        host = self._host_of(self.steps[index]) if 0 <= index < len(self.steps) else None
        return target is not None and not self._exposed(target, host)

    def _is_ready(self, index) -> bool:
        step = self.steps[index]
        if step.host is not None and (not self.floating or self._host_of(step) is None):
            return False   # a child overlay cannot cover another window; a closed window has no steps
        try:
            if step.ready is not None and not step.ready():
                return False
        except Exception:  # noqa: BLE001
            return False
        return step.target is None or self._target(index) is not None

    SETTLE_MS = 3000                                     # never wait longer than this for a page to hold still

    def go(self, index: int, *, step: int = 1):
        if index != self.index:
            self._dock_mascot()   # a new step: 兔白 is back beside the card
        self._poller.stop()
        self._advancing = False
        leaving = self._step()
        if step > 0 and leaving is not None and leaving.settle is not None and index > self.index:
            self._settle = (leaving.settle, self._clock.elapsed())
        elif step < 0:
            self._settle = None
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
        if self._settle is not None:
            # The last step's page is still changing: wait under the shade, without outline or bubble,
            # then judge this step (an optional one may turn out not to apply).
            self._wait_direction = step
            self._set_hole(QRectF())
            self._set_mode('wait')
            self._poller.start()
            return
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
        self._catch_ups = 0
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
        not count, nor does the window the current step points into."""
        from PySide6.QtWidgets import QDialog
        host = self._step_host()
        for widget in QApplication.topLevelWidgets():
            if widget is self or widget is host or not isinstance(widget, QDialog) or not widget.isVisible():
                continue
            if (widget.isModal() or getattr(widget, '_input_guard', None) is not None
                    or widget.objectName() in self.PAUSING_DIALOGS):
                return widget
        return None

    def _poll(self):
        """Waiting for the step's page and target; the outline sets off as soon as the target is there."""
        if self.mode != 'wait':
            self._poller.stop()
            return
        if self._settle is not None:
            check, since = self._settle
            try:
                still = bool(check())
            except Exception:  # noqa: BLE001 - a failing check never holds the tutorial
                still = True
            if not still and self._clock.elapsed() - since < self.SETTLE_MS:
                return
            self._settle = None
            self.go(self.index, step=self._wait_direction)   # now judge (and show) the step
            return
        if self._host_gone(self._step()):
            self._poller.stop()
            self._leave_host()
            return
        if self._foreign_dialog() is not None:
            self._set_mode('dialog')
            return
        if not self._is_ready(self.index):
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
        self._poller.stop()
        self._arrive(self._rect_of(target))

    def _arrive(self, rect: QRectF):
        """Glide the outline to the target at once, then show the bubble beside it."""
        from ..design.ui_motion import reduced_motion
        step = self._step()
        self._prepare_bubble(step)
        self._placement = self._place(rect)
        self._placed_for = QRectF(rect)
        if self._step_host() is not None:
            self._raise_above_host()
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
        self._glide.setDuration(self.GLIDE_MS)
        self._glide.setStartValue(QRectF(start))
        self._glide.setEndValue(QRectF(rect))
        self._glide.start()

    def _current_rect(self, fallback: QRectF) -> QRectF:
        target = self._target(self.index)
        return self._rect_of(target) if target is not None else QRectF(fallback)

    def _glide_step(self, value):
        if self.mode != 'glide':
            return
        self._set_hole(QRectF(value))
        # A target still on its way (a page settling, a list scrolling): aim at where it is now.
        end = QRectF(self._glide.endValue())
        rect = self._current_rect(end)
        if not _close(rect, end):
            self._glide.setEndValue(QRectF(rect))

    def _glide_done(self):
        if self.mode != 'glide':
            return
        end = QRectF(self._glide.endValue())
        self._set_hole(end)
        rect = self._current_rect(end)
        if not _close(rect, end) and self._catch_ups < self.CATCH_UPS:
            self._catch_ups += 1
            self._glide.setDuration(self.CATCH_UP_MS)
            self._glide.setStartValue(QRectF(end))
            self._glide.setEndValue(QRectF(rect))
            self._glide.start()
            return
        if not _close(self.hole, getattr(self, '_placed_for', QRectF())):
            self._placement = self._place(self.hole)
        self._show_bubble(animate=True)

    def _bubble_picture(self):
        """The bubble as one picture, drawn by the overlay while it fades in (None: show it at once).

        2026-10-24 (user: square corners flash at the bubble's four corners on every step):
        ``grab()`` paints a widget as a window and first fills its whole rectangle with the
        palette's window colour, so the picture had opaque light squares outside the rounded
        border until the real bubble replaced it. Rendered without the window background into
        a transparent picture, only the style sheet's rounded background is painted.
        """
        try:
            for child in self.bubble.findChildren(QWidget):
                child.ensurePolished()
            self.bubble.card.layout().activate()
            ratio = self.bubble.devicePixelRatioF()
            picture = QPixmap(QSize(math.ceil(self.bubble.width() * ratio), math.ceil(self.bubble.height() * ratio)))
            if picture.isNull():
                return None
            picture.setDevicePixelRatio(ratio)
            picture.fill(Qt.GlobalColor.transparent)
            self.bubble.render(picture, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        except Exception:  # noqa: BLE001
            return None
        return picture

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
        target = self._raw_target(self.index)
        self._shown_target = target[0] if isinstance(target, tuple) else target
        self.bubble.setGraphicsEffect(None)
        self.bubble.move(self._final_pos + self._slide)
        self._begin_typing()
        # 2026-10-22: the fade-in draws one picture of the bubble; a QGraphicsOpacityEffect rendered
        # all its widgets (rich text, the animation) off screen again on every frame.
        self._reveal_pixmap = self._bubble_picture() if animate else None
        if self._reveal_pixmap is None:
            self.reveal = 1.0
            self.bubble.move(self._final_pos)
            self.bubble.show()
            self.bubble.raise_()
            if self._size_key != 'mini':
                self.anim.start()
            self._typer.start()
        else:
            self.reveal = 0.0
        if not self.floating:
            self.raise_()
        if self._step_host() is not None:
            self._raise_above_host()
        self._apply_mask()
        self.update()
        if self._reveal_pixmap is not None:
            self._reveal.stop()
            self._reveal.start()
        from ..design.ui_motion import reduced_motion
        if step.interactive and not reduced_motion():
            self._attention.stop()
            self._attention.setLoopCount(2)   # then a steady ring: no repaint for as long as the step stays
            self._attention.start()
        if step.auto is not None and self.index not in self._auto_done:
            index, action = self.index, step.auto
            tries = [0]

            def run_auto():
                # Once, when the step has settled. A banner that a background check
                # adds above the target moves it right after the step shows; the
                # box glides again and the single 450 ms try used to miss (10-23).
                if self.index != index or index in self._auto_done:
                    return
                if self.mode != 'shown':
                    tries[0] += 1
                    if tries[0] <= 40:
                        QTimer.singleShot(150, run_auto)
                    return
                self._auto_done.add(index)
                self._run_action(action)
            QTimer.singleShot(450, run_auto)
        if step.interactive and step.host is None:
            keys = None
            try:
                keys = step.focus() if step.focus is not None else None
            except Exception:  # noqa: BLE001
                keys = None
            if keys is None and self._focus_in_target():
                # 2026-10-24: the editor T (or E) just opened keeps the keyboard; taking it back to the
                # main window here made the typing of "按 Enter 保存" go nowhere.
                return
            (keys or self.window_).setFocus()

    def _focus_in_target(self) -> bool:
        """The keyboard is already inside the step's target (an open editor)."""
        target = self._raw_target(self.index)
        widget = target[0] if isinstance(target, tuple) else target
        focus = QApplication.focusWidget()
        return widget is not None and focus is not None and (focus is widget or widget.isAncestorOf(focus))

    def _reveal_step(self, value):
        dirty = self._bubble_dirty()
        self.reveal = float(value)
        slide = getattr(self, '_slide', QPoint(0, 0))
        self.bubble.move(self._final_pos + QPoint(round(slide.x() * (1 - self.reveal)), round(slide.y() * (1 - self.reveal))))
        self.update(dirty.united(self._bubble_dirty()))

    def _reveal_done(self):
        self.reveal = 1.0
        self._reveal_pixmap = None
        self.bubble.move(self._final_pos)
        if self.mode == 'shown':
            self.bubble.show()
            self.bubble.raise_()
            if self._size_key != 'mini':
                self.anim.start()
            self._typer.start()
        self._apply_mask()
        self.update(self._bubble_dirty())

    def _begin_typing(self):
        """The words wait, blank, until the bubble is there; then 兔白 types them (not with reduced motion)."""
        from ..design.ui_motion import reduced_motion
        if reduced_motion() or self._typed_for == self.index:   # shown again in place (a resize): no retyping
            self._typer.finish()
            self._typer.stop()
            return
        self._typed_for = self.index
        self._typer.prepare([(self.text, self._text_source), (self.note, self._note_source)], self._colors)

    def _hide_bubble(self):
        self._typer.stop()
        self._hide_chat()
        self._reveal.stop()
        self._carry.stop()
        self._carry_path = None
        self._attention.stop()
        self.glow = 0.0
        self.reveal = 0.0
        self.pointer = None
        self.anim.stop()
        self.bubble.setGraphicsEffect(None)
        if self.bubble.isVisible() or self._reveal_pixmap is not None:
            dirty = self._bubble_dirty()
            self._reveal_pixmap = None
            self.bubble.hide()
            self.update(dirty)

    PENDING_MS = 12000                                   # a click that leads elsewhere: the chip after this

    def _set_mode(self, mode: str):
        self.mode = mode
        if mode == 'dialog':   # a window is open: nothing of the tutorial over it
            self._poller.stop()
            self._hide_bubble()
            self.chip.hide()
            self._set_click_through(False)
            self.hide()
        elif mode == 'pending':
            # 2026-10-22 (user: entering the workbench flickers): the page is answering a click and
            # the workbench takes seconds to open. Hiding the overlay meanwhile made the whole window
            # flash bright and then dim again; the shade now stays, without outline or bubble, and
            # lets every click through to the page.
            self._poller.stop()
            self._hide_bubble()
            self.chip.hide()
            self._set_click_through(True)
            if not self.isVisible() and self.window_.isVisible():
                self._sync_geometry()
                self.show()
        elif mode == 'away':
            self._hide_bubble()
            self._set_click_through(False)
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
            self._set_click_through(False)
            if not self.isVisible() and self.window_.isVisible():
                self._sync_geometry()
                self.show()
        self._apply_mask()
        self.update()

    def _native_handle(self) -> int:
        """The overlay's HWND when it is a real Windows window (not offscreen, not a child widget)."""
        if not self.floating or QApplication.platformName() != 'windows':
            return 0
        try:
            return int(self.winId())
        except Exception:  # noqa: BLE001
            return 0

    def _set_click_through(self, on: bool):
        """Every click passes the overlay (WS_EX_TRANSPARENT on its layered window) while a page answers one."""
        if bool(on) == self._click_through:
            return
        self._click_through = bool(on)
        if not self.floating:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, bool(on))
            return
        hwnd = self._native_handle()
        if not hwnd:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            get, put = user32.GetWindowLongPtrW, user32.SetWindowLongPtrW
            get.restype, get.argtypes = ctypes.c_ssize_t, [ctypes.c_void_p, ctypes.c_int]
            put.restype, put.argtypes = ctypes.c_ssize_t, [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            style = get(hwnd, -20)                   # GWL_EXSTYLE
            put(hwnd, -20, (style | 0x20) if on else (style & ~0x20))   # WS_EX_TRANSPARENT
        except Exception:  # noqa: BLE001 - only means clicks wait until the page is back
            pass

    def _raise_above_host(self):
        """Above the window the step points into, without taking the keyboard from it."""
        if not self.floating or not self.isVisible():
            return
        hwnd = self._native_handle()
        if hwnd:
            try:
                import ctypes
                # HWND_TOP; SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
                ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(0), 0, 0, 0, 0,
                                                  0x0001 | 0x0002 | 0x0010 | 0x0200)
                return
            except Exception:  # noqa: BLE001
                pass
        self.raise_()

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
        self._catch_ups = 0
        self._scrolled = False
        self._set_mode('wait')
        self._poller.start()

    def _page_changed(self, _index):
        if self.mode in ('shown', 'pending', 'away'):
            self._follow_target()

    def _follow_target(self):
        if self._shake.state() == QVariantAnimation.State.Running:
            return   # the window is shivering: its parts move a few pixels; nothing to follow
        step = self._step()
        if step is None or self.mode in ('idle', 'wait', 'glide', 'closed'):
            return
        if self.mode == 'dialog':
            if not self._modal_running and self._foreign_dialog() is None:
                self._resume(navigate=False)   # the window was closed: the same step again
            return
        if self._host_gone(step):
            self._carry.stop()
            self._leave_host()
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
                self._pending_left = self.PENDING_MS
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
        from ..design.ui_motion import reduced_motion
        old = QRectF(self.hole)
        delta = rect.center() - old.center()
        same_size = abs(rect.width() - old.width()) <= 3 and abs(rect.height() - old.height()) <= 3
        start = QPointF(self._final_pos)
        moved = QRectF(start, QSizeF(self.bubble.size())).translated(delta)
        if same_size and self._fits(moved, rect):
            self._carry.stop()
            self._carry_path = (old, QRectF(rect), start, moved.topLeft(), self.pointer, delta)
            if reduced_motion() or abs(delta.x()) + abs(delta.y()) <= self.JUMP:
                # A few pixels (the page scrolling): stay on the target instead of trailing behind it.
                self._carry_step(1.0)
                self._carry_done()
            else:
                self._carry.start()
            return
        self._hide_bubble()
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
        if self.chat.isVisible():
            self._place_chat()
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
        widget, part = target if isinstance(target, tuple) else (target, None)
        if widget.window() is not self.window_:
            # In another window (AI 设置): through screen coordinates.
            origin = self.mapFromGlobal(widget.mapToGlobal(part.topLeft().toPoint() if part is not None else QPoint(0, 0)))
            size = part.size() if part is not None else QSizeF(widget.width(), widget.height())
            pad = 6 if part is not None else 8
            rect = QRectF(origin.x(), origin.y(), size.width(), size.height()).adjusted(-pad, -pad, pad, pad)
        elif part is not None:
            top_left = widget.mapTo(self.window_, part.topLeft().toPoint())
            rect = QRectF(top_left.x(), top_left.y(), part.width(), part.height()).adjusted(-6, -6, 6, 6)
        else:
            top_left = widget.mapTo(self.window_, QPoint(0, 0))
            rect = QRectF(top_left.x(), top_left.y(), widget.width(), widget.height()).adjusted(-8, -8, 8, 8)
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
        if self.bubble.isVisible() or self._reveal_pixmap is not None:
            region = region.united(QRegion(self.bubble.geometry().adjusted(-2, -2, 2, 2)))
        if self.chat.isVisible():
            region = region.united(QRegion(self.chat.geometry().adjusted(-12, -12, 12, 12)))
        if self.bubble.mascot is not None and not self.bubble.docked:
            region = region.united(QRegion(self._mascot_rect().toAlignedRect().adjusted(-2, -2, 2, 2)))
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
            if self.chat.isVisible():
                self._place_chat()
        elif self.mode == 'glide':
            self._glide.stop()
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
        self.bubble.set_side('left')
        if hole.isNull():   # a centred card
            self._set_size('full')
            size = self._measure()
            self.bubble.fit(size)
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
            self.bubble.fit(size)
            return QRectF(x, y, w, h), None, ''
        _score, key, side, rect = best
        self._set_size(key)
        # 2026-11-11: 兔白 stands on the side away from the outline; the pointer leaves the card.
        self.bubble.set_side('right' if side == 'right' else 'left')
        self.bubble.fit(self._measure())
        card = QRectF(self.bubble.card_rect()).translated(rect.topLeft())
        return rect, self._pointer_for(side, card, hole), side

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
        """The ring of an interactive step breathes twice (only the ring is repainted, never the bubble)."""
        self.glow = math.sin(math.pi * float(value))
        if not self.hole.isNull():
            self.update(self.hole.adjusted(-16, -16, 16, 16).toAlignedRect())

    def continue_with(self, steps: list, part: str):
        """The next part in this same overlay (继续学进阶): no window closes and reopens in between."""
        self.steps = list(steps)
        self.part = part
        self._entered = set()
        self._auto_done = set()
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
        self._typer.stop()
        self._hide_chat()
        self._dock_mascot()
        self._flash_timer.stop()
        for animation, finish in ((self._shake, self._shake_done),):
            if animation.state() == QVariantAnimation.State.Running:
                animation.stop()
                finish()
        self._flash = None
        self.voice.close()
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
        mascot = self.bubble.mascot
        if mascot is not None and watched is mascot:
            if kind == QEvent.Type.MouseButtonPress:
                return self._mascot_press(event)
            if kind == QEvent.Type.MouseMove:
                return self._mascot_move(event)
            if kind == QEvent.Type.MouseButtonRelease:
                return self._mascot_release(event)
        if kind == QEvent.Type.MouseButtonPress and self.mode == 'shown':
            if watched in (self.text, self.note) and self._typer.running:
                self._typer.finish()   # a click on the words: all of them at once
                return True
        if kind == QEvent.Type.Hide and watched is not None and watched is self._shown_target and self.mode == 'shown':
            # 2026-10-24: the outlined editor closed (Enter): outline and bubble go now, not a tick later.
            try:
                self._follow_target()
            except Exception:  # noqa: BLE001 - the next tick tries again
                pass
            return False
        if watched is self.window_:
            if kind == QEvent.Type.Resize:
                self._relayout()
            elif kind == QEvent.Type.Move and self.floating:
                self._sync_geometry()
            elif kind == QEvent.Type.Hide and self.floating:
                self.hide()
            elif kind == QEvent.Type.Show and self.floating and self.mode not in ('dialog', 'closed', 'idle'):
                self._sync_geometry()
                self.show()
            return False
        if kind == QEvent.Type.WindowActivate and self.mode in ('wait', 'glide', 'shown'):
            host = self._step_host()
            if host is not None and watched is host:   # AI 设置 came forward again (a guide closed)
                QTimer.singleShot(0, self._raise_above_host)
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
        picture = self._reveal_pixmap
        if (self.bubble.isVisible() or picture is not None) and self.reveal > 0.01:
            box = QRectF(self.bubble.geometry())
            card = QRectF(self.bubble.card_rect()).translated(box.topLeft())
            painter.setPen(Qt.PenStyle.NoPen)
            for spread, alpha in ((22, 22), (14, 30), (7, 40)):   # soft shadow under the card
                painter.setBrush(QColor(0, 0, 0, int(alpha * self.reveal)))
                painter.drawRoundedRect(card.adjusted(-spread / 2, -spread / 2 + 8, spread / 2, spread / 2 + 10),
                                        22 + spread / 2, 22 + spread / 2)
            if self.bubble.mascot is not None and self.bubble.docked:   # 兔白 stands on a soft round shadow
                feet = QRectF(self.bubble.mascot.geometry()).translated(box.topLeft())
                painter.setBrush(QColor(0, 0, 0, int(46 * self.reveal)))
                painter.drawEllipse(QRectF(feet.center().x() - feet.width() * 0.3, feet.bottom() - 9,
                                           feet.width() * 0.6, 12))
            if picture is not None:   # fading in: the overlay draws the bubble's picture
                painter.setOpacity(self.reveal)
                painter.drawPixmap(box.topLeft(), picture)
                painter.setOpacity(1.0)
            if self.pointer is not None:
                tip = QColor(accent)
                tip.setAlphaF(min(1.0, self.reveal))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(tip)
                painter.drawPolygon(QPolygonF(list(self.pointer)))
        self._paint_flash(painter)
        if self.chat.isVisible() and self.bubble.mascot is not None:   # the chat balloon's little tail
            balloon = QRectF(self.chat.geometry())
            head = self._mascot_rect()
            y = max(balloon.top() + 12, min(head.top() + head.height() * 0.4, balloon.bottom() - 12))
            x = max(balloon.left() + 22, min(head.center().x(), balloon.right() - 22))
            if balloon.right() <= head.center().x() - 10:      # beside, on its left
                tail = [QPointF(balloon.right() - 1, y - 7), QPointF(balloon.right() - 1, y + 7), QPointF(balloon.right() + 9, y + 2)]
            elif balloon.left() >= head.center().x() + 10:     # beside, on its right
                tail = [QPointF(balloon.left() + 1, y - 7), QPointF(balloon.left() + 1, y + 7), QPointF(balloon.left() - 9, y + 2)]
            elif balloon.bottom() < head.center().y():         # over it
                tail = [QPointF(x - 8, balloon.bottom() - 1), QPointF(x + 8, balloon.bottom() - 1), QPointF(x + 2, balloon.bottom() + 10)]
            else:                                              # under the bubble
                tail = [QPointF(x - 8, balloon.top() + 1), QPointF(x + 8, balloon.top() + 1), QPointF(x + 2, balloon.top() - 10)]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawPolygon(QPolygonF(tail))
        painter.end()


# Kept for callers of the first version.
HomeTour = GuidedTour


# ---------------------------------------------------------------- the tutorial

def tutorial_steps(window, part: str = 'all') -> list[TourStep]:
    """The tutorial with demo data, one road from the first video to a corrected subtitle (2026-10-22).

    2026-10-15 it had two parts (basic, then 进阶 on request). User 10-22: someone who
    finished the basics thought that was enough, so there is one tutorial again, in this
    order: the video → the recognition plan (cloud or local, compared in a window) → the
    three model cards → AI 智能断句 and its key, inside the real AI 设置 window → content
    and glossary → languages → result → export → proofreading → workbench.
    ``part='advanced'`` still gives only the steps after the export (kept for audits).

    2026-10-24 (user): the plan comes first, together with the language the videos
    mainly speak (the comparison window has a language row; Chinese is timed by
    FireRedASR2, other languages by Qwen3 对齐), then the video. The workbench is a
    chapter of its own and also teaches C (razor: cut the demo line into three), B
    (merge tool: two pieces back into one), Shift+Q / Shift+W (ripple merge: the
    rest) and T (a new line at the playhead); key names follow the shortcut settings.
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

        def boxes():
            return [QRectF(rect) for rect, action, cue_id, *_rest in getattr(page.list, '_hit_boxes', ())
                    if cue_id == fix_cue() and action in ('mark', 'check', 'option')]
        found = boxes()
        if not found:   # the list lays out its hit boxes when it paints (only then: this runs every follow tick)
            page.list.repaint()
            found = boxes()
        if not found:
            return None
        rect = found[0]
        for box in found[1:]:
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
    def cue_blocks(cue_ids, pad=0.0):
        """The timeline blocks of these cues as one target (``pad``: room around them, e.g. for the razor's preview)."""
        page = studio()
        timeline = getattr(page, 'timeline', None)
        if timeline is None:
            return None
        wanted = set(cue_ids)
        rect = QRectF()
        try:
            rows, _track, _wave = timeline._track_layout()
            for cue in getattr(timeline, '_cues_by_start', ()):
                if cue.id not in wanted:
                    continue
                band = timeline._cue_band(cue, rows[cue.speaker_id])
                left = max(timeline.TRACK_HEADER_WIDTH, timeline._time_to_x(cue.start_ms))
                right = min(timeline._content_right(), timeline._time_to_x(cue.end_ms))
                block = QRectF(left, band.top() + 7, max(4, right - left), band.height() - 14)
                rect = block if rect.isNull() else rect.united(block)
            if rect.isNull():
                return None
            return timeline, rect.adjusted(-pad, -pad / 2, pad, pad / 2).intersected(timeline._track_viewport())
        except Exception:  # noqa: BLE001
            return None

    def block_target():
        return cue_blocks([fix_cue()])

    # 2026-10-24: C / B / Shift+Q·W work on one line: cut into three, then merged back twice.
    cut_cue = 'tutorial-6'   # 这期纪行的奖励还挺划算 (a cut keeps the left id, the right one is "<id>-split-…")

    def pieces():
        project = getattr(studio(), 'project', None)
        if project is None:
            return []
        return sorted((cue for cue in project.cues if cue.id == cut_cue or cue.id.startswith(cut_cue + '-split-')),
                      key=lambda cue: (cue.start_ms, cue.end_ms))

    def cut_target():
        return cue_blocks([cue.id for cue in pieces()], pad=24.0)

    def show_cut_line():
        page = studio()
        page._set_timeline_tool('selection')
        page.select_cue(cut_cue)

    def cut_into_three():
        page = studio()
        page._set_timeline_tool('razor')
        for _ in range(2):
            parts = pieces()
            if len(parts) >= 3:
                break
            longest = max(parts, key=lambda cue: cue.end_ms - cue.start_ms)
            page._split_at(longest.id, (longest.start_ms + longest.end_ms) // 2)

    merge_mark = {'count': 0}

    def remember_pieces():
        merge_mark['count'] = len(pieces())

    def merge_two():
        page = studio()
        page._set_timeline_tool('merge')
        parts = pieces()
        if len(parts) >= 2:
            page.cue_controller.merge_pair(parts[0].id, parts[1].id)

    def select_last_piece():
        page = studio()
        page._set_timeline_tool('selection')
        parts = pieces()
        if parts:
            page.select_cue(parts[-1].id)

    def ripple_merge():
        page = studio()
        page._set_timeline_tool('selection')
        for _ in range(3):
            parts = pieces()
            if len(parts) < 2:
                break
            page.select_cue(parts[-1].id)
            page.cue_controller.merge_with_neighbor(-1)

    def before_new_line():
        """T adds at the playhead on the selected line's track: a free spot after 下次带派门一起去探险."""
        page = studio()
        page._set_timeline_tool('selection')
        page.select_cue('tutorial-7')
        try:
            page._seek(21.05)
        except Exception:  # noqa: BLE001 - T still works wherever the playhead is
            pass

    def key(action_id):
        """The key bound to a workbench command, as the shortcut settings name it."""
        from ..studio.shortcut_registry import tooltip_key
        return str(tr(tooltip_key(action_id)))

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

    def field(name, fallback):
        return lambda: w.__dict__.get(name) or w.__dict__.get(fallback)

    # ---- 2026-10-22: the plan compared, the AI settings shown for real ------------------
    def choose_plan():
        chooser = getattr(w, '_choose_plan_in_tutorial', None)
        if callable(chooser):
            chooser()

    # 2026-10-24: right after the first-run chooser the plan (and language) was just picked:
    # the first step then waits for 下一步 instead of opening the comparison again.
    just_chosen = bool(w.__dict__.pop('_tutorial_plan_chosen', False))

    demo = {'added': False}

    def add_demo():
        demo['added'] = True
        w._tutorial_add_demo_media()

    def demo_settled():
        """The demo video is in and the home page holds still (2026-10-24): the import is applied
        and the 「还差一步」 banner has its answer. Both come a moment after the click; with the plan
        no longer between them, they moved ③'s card by 125 px while its bubble was showing."""
        intake = w.__dict__.get('_desktop_intake')
        if not demo['added'] or not (w.__dict__.get('media_paths') or []):
            return False
        if intake is not None and (intake.active or intake.requests):
            return False
        timer = w.__dict__.get('_next_step_probe_timer')
        if timer is not None and timer.isActive():
            return False
        return w.__dict__.get('_onboarding_rendered', 0) == w.__dict__.get('_onboarding_generation', 0)

    def spoken_code():
        try:
            options = w._subtitle_language_options()
        except Exception:  # noqa: BLE001 - no home page (tests)
            return 'auto'
        code = str(options.get('recognition_language') or 'auto')
        return 'zh-Hant' if code == 'zh' and options.get('chinese_script') == 'zh-Hant' else code

    def spoken_name():
        from .quick_setup import SPOKEN_NAMES
        return str(tr(SPOKEN_NAMES.get(spoken_code(), '自动识别语言')))

    def plan_note():
        from .quick_setup import PLANS
        key_ = w._current_plan_key() if hasattr(w, '_current_plan_key') else ''
        name = PLANS[key_].title if key_ in PLANS else ''
        if just_chosen and name:
            return tr('刚才选好了「{value0}」· {value1}；想换就点「比较两种方案」', value0=tr(name), value1=spoken_name())
        if just_chosen:   # 2026-11-11: the comparison came first and the saved roles are a custom mix
            return '现在用的是你自己搭配的模型；想换就点「比较两种方案」'
        return ('马上会弹出比较：云端不挑电脑，本机免费不上传' if not name
                else tr('现在用的是「{value0}」；马上会弹出两种方案的比较', value0=tr(name)))

    def timeline_note():
        """Which model times this language's subtitles (the plan step chose both)."""
        from ..recognition.recognition_plans import chinese_or_auto
        timeline = str(saved_models().get('firered_asr_backend') or 'off')
        if timeline != 'off':
            if not chinese_or_auto(spoken_code()):
                return tr('{value0}用 **Qwen3 对齐** 对准每个字词的时间', value0=spoken_name())
            if timeline == 'local':
                return '中文用 **FireRedASR2** 对准每个字，时间最准'
            if timeline in ('qwen_aligner', 'mlx_qwen_aligner'):
                return '用 **Qwen3 对齐** 对准每个字，不用 NVIDIA 显卡'
        return '字幕跟着说话一起出来，不会早一截或晚一截'

    def timeline_anim():
        from ..recognition.recognition_plans import chinese_or_auto
        if saved_models().get('firered_asr_backend') == 'off':return 'timeline_mg'
        return ('firered' if chinese_or_auto(spoken_code())
                and saved_models().get('firered_asr_backend') == 'local' else 'ctc')

    def spoken_note():
        if spoken_code() == 'auto':
            return '不确定就选“自动识别”'
        return tr('刚才选了「{value0}」；换别的视频时在这里改', value0=spoken_name())

    def ai_ready():
        unlocked = getattr(w, '_ai_unlocked', None)
        return bool(unlocked()) if callable(unlocked) else False

    def open_ai_settings():
        w._open_ai_settings_dialog()

    def ai_dialog():
        dialog = w.__dict__.get('_ai_settings_dialog')
        return dialog if dialog is not None and dialog.isVisible() else None

    def ai_editor():
        """The service form AI 设置 shows first (one form for both when they share a service)."""
        if ai_dialog() is None:
            return None
        for name in ('polish_editor', 'group_editor'):
            form = w.__dict__.get(name)
            if form is not None and form.isVisible():
                return form
        return None

    def editor_part(name):
        def find():
            form = ai_editor()
            part_ = getattr(form, name, None) if form is not None else None
            return part_ if part_ is not None and part_.isVisible() else None
        return find

    def editor_note():
        both = w.__dict__.get('group_editor')
        shared = both is not None and ai_editor() is both and not w.polish_editor.isVisible()
        return ('这一套服务同时做 AI 断句、翻译和校对' if shared
                else '上面管校对和翻译，「更多选项」里管 AI 断句；两边都要填')

    def pick_deepseek():
        form = ai_editor()
        index = form.service.findData('deepseek') if form is not None else -1
        if index >= 0:
            form.service.setCurrentIndex(index)

    def open_provider_guide():
        form = ai_editor()
        if form is not None:
            form.guide_button.click()

    def test_ai():
        form = ai_editor()
        if form is not None:
            form.test_connection()

    def ai_tested():
        return getattr(ai_editor(), 'last_connection_ok', None) is True

    def save_ai():
        button = w.__dict__.get('ai_dialog_save_button')
        if button is not None:
            button.click()

    def close_ai():
        dialog = ai_dialog()
        if dialog is not None:
            dialog.reject()

    def downloads_note():
        return '模型会在教学结束后开始下载' if w.__dict__.get('_first_run_downloads') else ''

    choose = TourAction('比较两种方案', choose_plan, modal=True, advance=True)
    open_ai = TourAction('打开 AI 设置看看', open_ai_settings, advance=True, big=True)
    home_steps = [
        # User 10-24: the plan - cloud or local - is the very first step, with the language the
        # videos mainly speak (it decides the subtitle-time model); the welcome card is gone.
        TourStep('① 先选==识别方案==和视频的==主要语言==', get('recognition_plan'), [choose], note=plan_note,
                 anim='plan_compare', page=home, auto=None if just_chosen else choose,
                 enter=w._tutorial_prepare_demo),
        TourStep('② 把视频==拖进这个框==；现在**点一下**放入演示视频', get('media_frame'),
                 [TourAction('放入演示视频', add_demo, advance=True)], show_next=False, ready=on_home,
                 note='用自带的演示视频，不上传、不花钱，约 6 分钟', settle=demo_settled,
                 anim='drop', click=TourAction('', add_demo, advance=True), page=home),
        TourStep('③ **主力转写**把说话变成文字：==点这张卡==注册 MOSS Pro', role_card('primary'),
                 [TourAction('注册 MOSS Pro', open_moss_guide, advance=True, modal=True),
                  TourAction('先跳过', lambda: None, advance=True)],
                 note='注册、每天签到都送==免费额度==，拿到 Key 贴进去就行',
                 show_next=False, anim='moss_signup', page=home, optional=True,
                 ready=lambda: moss_pro_chosen() and not moss_key_saved(),
                 click=TourAction('', open_moss_guide, advance=True, modal=True)),
        TourStep('③ **主力转写**把说话变成文字：MOSS Pro ==已经设置好了==', role_card('primary'),
                 note='点这张卡可以换成别的模型', anim='moss_signup', page=home, optional=True,
                 ready=lambda: moss_pro_chosen() and moss_key_saved()),
        TourStep('③ **主力转写**在==这台电脑上==把说话变成文字', role_card('primary'),
                 note=lambda: downloads_note() or '点这张卡可以换模型', anim='plan_ok', page=home, optional=True,
                 ready=lambda: not moss_pro_chosen()),
        TourStep('④ **字幕时间轴**：让每句字幕==出现、消失得刚刚好==', role_card('timeline'),
                 note=timeline_note, anim=timeline_anim, page=home),
        # User 10-22: AI 断句, translation and 术语库校对 all need the key; open the real settings.
        TourStep('⑤ **AI 智能断句**要先填 ==API Key==', get('home_process_card'),
                 [open_ai, TourAction('API Key 是什么？', explain_key), TourAction('先不设置', lambda: None, goto='after_ai')],
                 note='AI 断句、翻译字幕、术语库校对都靠它，推荐 **DeepSeek**。==没连接的话，这三样都用不了==',
                 show_next=False, anim='ai_lock', page=home, optional=True, ready=lambda: not ai_ready(),
                 click=TourAction('', open_ai_settings, advance=True)),
        TourStep('⑤ **AI 智能断句**==已经连好了==', get('home_process_card'),
                 [TourAction('打开 AI 设置看看', open_ai_settings, advance=True)],
                 note='AI 断句、翻译字幕、术语库校对都能用了', anim='ai_lock', page=home, optional=True, ready=ai_ready),
        # ---- inside AI 设置 (the tutorial stays above that window)
        TourStep('这是 **AI 设置**：「服务」选 ==DeepSeek==（推荐）', editor_part('service'),
                 [TourAction('帮我选 DeepSeek', pick_deepseek)], note=editor_note,
                 host=ai_dialog, optional=True, anim='ai_lock'),
        TourStep('还没有 Key？点「==申请教程==」', editor_part('guide_button'),
                 [TourAction('打开申请教程', open_provider_guide, modal=True, advance=True)],
                 note='一步步带你注册、充值、复制 Key；看完回到这里贴上',
                 host=ai_dialog, optional=True, anim='key_get'),
        TourStep('把 **API Key** ==贴到这里==', editor_part('key_row_host'),
                 note='Key 只存在这台电脑上，加密保存', host=ai_dialog, optional=True, interactive=True,
                 focus=editor_part('key'), anim='apikey'),
        TourStep('点**测试连接**，看到==“连接正常”==就好啦', editor_part('test_button'),
                 [TourAction('帮我点', test_ai)], note='连不上的话，看看 Key 有没有贴全、余额够不够',
                 host=ai_dialog, optional=True, interactive=True, done=ai_tested, anim='apikey'),
        TourStep('要开启 AI 吗？点「==保存设置==」就开启', get('ai_dialog_save_button'),
                 [TourAction('保存并开启', save_ai, big=True), TourAction('先不开', close_ai)],
                 note='开启后能用 AI 断句、字幕翻译和术语库校对（要测试连接通过）。不开的话这三样都用不了，首页会变灰；'
                      '以后随时可以在首页的 AI 卡片上再设置',
                 host=ai_dialog, optional=True, show_next=False, anim='ai_lock'),
        # ---- content, glossary, languages
        TourStep('⑥ 填==游戏名==，人名和术语会写对（可以不填）', get('content_choice_panel'), anim='glossary', page=home,
                 name='after_ai'),
        TourStep('⑦ **术语库校对**：照词库==改对专名和错词==', get('batch_glossary_card'),
                 note=lambda: ('右边的「联网补充核验」会再上网查一遍（可选）' if ai_ready()
                               else '要先连接 AI（填 API Key 并测试连接）才能用，现在是灰的'),
                 anim='glossary', page=home),
        # 2026-10-24: chosen with the plan in ①; here it is shown where to change it per video.
        TourStep('⑧ 视频里==说的是什么话==，就选什么', field('spoken_language_field', 'recognition_language'),
                 note=spoken_note, anim='spoken', page=home),
        TourStep('⑨ 要翻译就在「字幕显示」选==“原文 + 翻译”==', field('subtitle_output_fields', 'subtitle_output'),
                 note=lambda: ('翻译也是 AI 做的，会用上面的 API Key' if ai_ready()
                               else '没连接 AI 时只能选“只显示原文”，翻译是灰的'),
                 anim='subtitle_lang', page=home),
        TourStep('⑩ 点这里开始；现在**点一下**看==演示结果==', get('start_button'),
                 [TourAction('看演示结果', w._tutorial_demo_completion, advance=True)], show_next=False, anim='start',
                 click=TourAction('', w._tutorial_demo_completion, advance=True), page=home),
        TourStep('做好啦！字幕==已经生成==，下面先看一眼吧', field('result_summary_card', 'result_title'), ready=on_completion,
                 page=to_completion),
        TourStep('点这里==导出字幕文件==（SRT、ASS、TXT）', get('export_result_button'),
                 ready=on_completion, anim='export', page=to_completion),
    ]
    later_steps = [
        # ---- result page: find wrong names and terms
        # 2026-11-11: the entry on the page is the AI card; it clicks the
        # same button the 「帮我做」 action does.
        TourStep('接着学改字幕：点这里，==一次找出==写错的人名和术语', get('result_ai_card'),
                 [TourAction('帮我做', lambda: w.repolish_current_glossary_button.click())], show_next=False,
                 interactive=True, done=on_proofread, ready=on_completion, page=to_completion),
        # ---- proofreading, step by step
        TourStep('勾选「原神」词库（本机查找，免费）',
                 library_target, [TourAction('帮我做', check_library)], show_next=False, interactive=True,
                 done=library_checked, enter=offline_ai, ready=on_proofread, anim='gl_check',
                 click=TourAction('', check_library)),
        TourStep('点 AI 校对，找出词库外的错字（教学里不联网、不收费）', proofread_part('ai_button'),
                 [TourAction('帮我做', lambda: proofread().ai_button.click())], show_next=False, interactive=True,
                 done=ai_shown, ready=lambda: on_proofread() and not busy(), anim='gl_ai'),
        TourStep('==红字是错字==，点下面的建议改正（至东 → 至冬）。按 **Ctrl+Z** 撤销', fix_target,
                 [TourAction('帮我做', fix_it)], show_next=False, interactive=True, done=fixed,
                 ready=lambda: on_proofread() and not busy(), anim='gl_fix'),
        TourStep('其余建议也可以逐条点，或一次采用全部', proofread_part('select_all'),
                 ready=on_proofread, optional=True),
        TourStep('改好了，点返回结果', proofread_part('back_button'),
                 [TourAction('帮我做', lambda: proofread().back_button.click())], show_next=False, interactive=True,
                 done=on_completion, ready=on_proofread, anim='gl_back'),
        # ---- result page again
        TourStep('点这里打开==字幕工作台==：逐条修改、审核、调时间、压制', get('open_studio_result_button'),
                 [TourAction('帮我做', lambda: w.open_studio_result_button.click())], show_next=False, interactive=True,
                 done=studio_ready, ready=on_completion, anim='studio_open', page=to_completion),
    ]
    studio_steps = [
        # ---- workbench (each step first stops the player: nothing moves under the outline)
        TourStep('==双击==字幕修改文字，或按 **E** 改播放头处那条', block_target,
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
        # User 10-24: C cuts, B merges, Shift+Q / Shift+W ripple-merge, T adds a line. One demo
        # line is cut into three and merged back twice, so both merges join one speaker's pieces.
        TourStep(lambda: tr('按 **{value0}** 拿剃刀：在这条字幕上**点两下**，切成三段', value0=key('razor_tool')),
                 cut_target, [TourAction('帮我切开', cut_into_three)], show_next=False, interactive=True,
                 note=lambda: tr('鼠标移上去能先看到切点和两边的字；切错了按 **{value0}** 撤销', value0=key('undo')),
                 enter=quiet(show_cut_line), done=lambda: len(pieces()) >= 3, ready=studio_ready, focus=studio_keys,
                 anim='razor', page=to_studio),
        TourStep(lambda: tr('按 **{value0}** 换合并工具：点一段，**按住往旁边拖**到相邻那段', value0=key('merge_tool')),
                 cut_target, [TourAction('帮我合并', merge_two)], show_next=False, interactive=True,
                 note=lambda: tr('两段合成一段，文字接在一起；用完按 **{value0}** 换回选择工具', value0=key('selection_tool')),
                 enter=quiet(remember_pieces), done=lambda: 0 < len(pieces()) < merge_mark['count'],
                 ready=lambda: studio_ready() and len(pieces()) >= 2, optional=True, focus=studio_keys,
                 anim='merge_tool', page=to_studio),
        TourStep(lambda: tr('**{value0}** 和上一段合并，**{value1}** 和下一段合并', value0=key('merge_previous'),
                            value1=key('merge_next')),
                 cut_target, [TourAction('帮我做', ripple_merge)], show_next=False, interactive=True,
                 note=lambda: tr('这叫**波纹合并**：已经选中最后一段，按 **{value0}** 试试', value0=key('merge_previous')),
                 enter=quiet(select_last_piece), done=lambda: len(pieces()) == 1,
                 ready=lambda: studio_ready() and len(pieces()) >= 2, optional=True, focus=studio_keys,
                 anim='ripple', page=to_studio),
        TourStep(lambda: tr('按 **{value0}** 在播放头新建一条字幕，直接打字', value0=key('add_subtitle')),
                 tool('add_subtitle_button'), [TourAction('帮我做', lambda: studio()._add_subtitle_at_playhead())],
                 show_next=False, interactive=True, note='加在选中字幕的那条轨上，长 2 秒；拖两端能改长短',
                 enter=quiet(before_new_line), done=lambda: editor() is not None, ready=studio_ready,
                 focus=studio_keys, anim='add_cue', page=to_studio),
        TourStep('按 **Enter** 保存，**Esc** 取消', editor,
                 [TourAction('帮我做', save_editor)], show_next=False, interactive=True,
                 done=lambda: editor() is None, optional=True),
        TourStep('标点：添加、去掉或保留原文，只影响显示和导出', studio_part('punctuation_button'),
                 ready=studio_ready, anim='punct', enter=quiet(), page=to_studio),
        TourStep('导出字幕：选格式和文件夹', studio_part('studio_export_button'), ready=studio_ready,
                 anim='export', enter=quiet(), page=to_studio),
        TourStep('压制成片：把字幕烧进视频', studio_part('studio_render_button'), ready=studio_ready,
                 anim='burn', enter=quiet(), page=to_studio),
        TourStep('全部学会啦！现在==放入你自己的视频==开始吧', next_label='回到首页', note=downloads_note),
    ]
    for step in home_steps:
        step.chapter = '做字幕'
        if step.anim in ('moss_signup', 'plan_ok'):
            step.group = 'primary'             # ③: one of three, by the chosen plan
        elif step.anim == 'ai_lock' and step.host is None:
            step.group = 'ai'                  # ⑤: key missing or connected
    for step in later_steps:
        step.chapter = '改字幕'
    for step in studio_steps:
        step.chapter = '工作台'          # 2026-10-24: its own chapter, so no part counts past 20
    later_steps += studio_steps
    return later_steps if part == 'advanced' else home_steps + later_steps


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


def start_home_tour(window, on_finished=None, part: str = 'all') -> GuidedTour | None:
    """Start the tutorial (one at a time). 2026-10-22: one tutorial; ``part`` is kept for old callers."""
    existing = window.findChild(GuidedTour)
    if existing is not None and getattr(existing, 'mode', '') != 'closed':
        return existing
    tour = GuidedTour(window, tutorial_steps(window, part), avoid=tutorial_avoid(window))
    tour.part = part
    if on_finished is not None:
        tour.finished.connect(on_finished)
    tour.start()
    return tour
