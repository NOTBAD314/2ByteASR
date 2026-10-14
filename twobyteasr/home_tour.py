"""The first-run tutorial: do it once with demo data, one step at a time (2026-10-14).

Each step outlines a real control (or shows a centred card), says what you
can do there in one line, plays a short animation of the gesture (where to
click, what to double-click, which key to press), and lets you do it:

* most steps you do yourself — clicks inside the outline reach the page and
  keys go to it; the step moves on by itself once it sees the result
  (``done``); "帮我做" does it for you;
* some only show where a tool lives (speaker manager, batch replace, export).

Nothing is uploaded or paid for: the media and the pretend result come from
the tutorial project (sample_project.ensure_tutorial_project), and "AI 校对"
uses an offline stand-in while the tutorial runs. The bubble sits beside its
target with a pointer and a short glow, never over the native video window.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QImage, QMovie, QPainter, QPainterPath, QPen, QPolygonF, QRegion
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .i18n import bind_text, tr


@dataclass
class TourAction:
    label: str
    run: Callable[[], None]
    advance: bool = False   # go to the next step after running


@dataclass
class TourStep:
    text: str | Callable[[], str]          # one line; **marked** words in the accent colour
    # None: a centred card. A widget, or (widget, rect in that widget) for a part of it.
    target: Callable[[], object] | None = None
    actions: list = field(default_factory=list)          # TourAction
    enter: Callable[[], None] | None = None              # runs when the step opens (page switch...)
    ready: Callable[[], bool] | None = None              # wait for this (default: target visible)
    next_label: str = '下一步'
    show_next: bool = True                               # False: an action (or ``done``) moves on
    optional: bool = False                               # shown only if already there (no waiting)
    anim: str | Callable[[], str] = ''                   # assets/onboarding/tutorial/<anim>-<theme>.webp
    interactive: bool = False                            # clicks in the outline and keys reach the page
    done: Callable[[], bool] | None = None               # the user did it: move on by itself
    focus: Callable[[], QWidget | None] | None = None    # who gets the keys in an interactive step


def tutorial_anim_path(name: str, light: bool, still: bool = False):
    """assets/onboarding/tutorial/<name>-<dark|light>.webp (or -still.png), rendered from source/tutorial.html."""
    from .main_ui_helpers import APP_ROOT
    file = f"{name}-{'light' if light else 'dark'}" + ('-still.png' if still else '.webp')
    path = APP_ROOT / 'assets' / 'onboarding' / 'tutorial' / file
    return path if path.is_file() else None


class TourAnim(QWidget):
    """The gesture animation in the bubble (an animated WebP drawn crisp on HiDPI)."""

    SIZE = QSize(440, 187)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE)
        self._movie = None
        self._still = None
        self.name = ''

    def play(self, name: str, light: bool) -> bool:
        self.stop()
        self.name = name or ''
        if not name:
            return False
        from .ui_motion import reduced_motion
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
        movie.start()
        self._movie = movie
        return movie.isValid()

    def stop(self):
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
        self._movie = None
        self._still = None

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        image = self._movie.currentImage() if self._movie is not None else self._still
        if image is None or image.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(self.rect()), image)
        painter.end()


class GuidedTour(QWidget):
    finished = Signal(bool)  # True when the last step was passed, False when skipped

    WAIT_MS = 20000
    TEXT_WIDTH = 440                                     # bubble text column (logical px)
    COMPACT_WIDTH = 340                                  # when no full-size spot beside the target is free

    def __init__(self, window, steps: list[TourStep], avoid: Callable[[], list] | None = None):
        super().__init__(window)
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        self.window_ = window
        self.steps = steps
        self.avoid = avoid                               # rects (window coords) the bubble must not cover
        self.index = -1
        self.theme = theme_definition(theme_key())
        self.light = QColor(self.theme.app_background).lightness() > 128
        self.hole = QRectF()
        self.pointer = None                              # (tip, base1, base2) toward the outline
        self._entered = set()
        self._advancing = False
        self._compact = False
        self._waiting = QTimer(self)
        self._waiting.setInterval(150)
        self._waiting.timeout.connect(self._poll)
        self._wait_left = 0
        self._waited = False   # the step waited for a page: jump there, do not glide from the old page
        # Pages keep settling after they appear (splitters restored, lazy layouts): the outline follows,
        # and an interactive step watches for what the user did.
        self._follow = QTimer(self)
        self._follow.setInterval(200)
        self._follow.timeout.connect(self._follow_target)
        self.setObjectName('guidedTour')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(window.rect())
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(280)
        self._motion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._motion.valueChanged.connect(self._move_hole)
        self.glow = 0.0                                  # attention pulse around the bubble (0..1)
        self._attention = QVariantAnimation(self)
        self._attention.setStartValue(0.0)
        self._attention.setEndValue(1.0)
        self._attention.setDuration(1400)
        self._attention.valueChanged.connect(self._pulse)
        self._build_bubble()
        window.installEventFilter(self)

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
            f"QPushButton#tourSkip {{ background: transparent; border: 0; color: {t.text_muted}; padding: 4px 6px; }}"
            f"QPushButton#tourSkip:hover {{ color: {t.text}; }}")
        shadow = QGraphicsDropShadowEffect(self.bubble)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.bubble.setGraphicsEffect(shadow)
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
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        layout.addLayout(self.buttons)
        self.action_buttons: list[QPushButton] = []
        from .design.presentation import button_role
        self.back = button_role(QPushButton(), 'ghost')
        bind_text(self.back, '上一步')
        self.back.clicked.connect(lambda: self.go(self.index - 1, step=-1))
        self.next = button_role(QPushButton(), 'primary')
        self.next.setObjectName('tourNext')
        self.next.clicked.connect(lambda: self.go(self.index + 1))

    def _fill_buttons(self, step: TourStep):
        from .design.presentation import button_role
        while self.buttons.count():
            item = self.buttons.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in (self.back, self.next):
                widget.deleteLater()
        self.action_buttons = []
        for index, action in enumerate(step.actions):
            primary = not step.show_next and index == 0 and not step.interactive
            button = button_role(QPushButton(), 'primary' if primary else 'secondary')
            bind_text(button, action.label)
            button.setObjectName(f'tourAction_{index}')
            button.clicked.connect(lambda _=False, a=action: self._run_action(a))
            self.buttons.addWidget(button)
            button.show()  # a layout would show it a moment later, after the bubble was measured
            self.action_buttons.append(button)
        self.buttons.addStretch(1)
        self.buttons.addWidget(self.back)
        self.buttons.addWidget(self.next)
        self.back.setVisible(self.index > 0 and step.show_next)
        self.next.setVisible(step.show_next)
        bind_text(self.next, step.next_label)

    def _run_action(self, action: TourAction):
        try:
            action.run()
        except Exception:  # noqa: BLE001 - a failing demo action must not trap the user in the tutorial
            import traceback
            traceback.print_exc()
        if action.advance:
            self.go(self.index + 1)
        else:
            self.raise_()

    # ------------------------------------------------------------ steps
    def start(self):
        self.show()
        self.raise_()
        self.setFocus()
        self._follow.start()
        self.go(0)

    def _follow_target(self):
        if not self.bubble.isVisible() or self._motion.state() == QAbstractAnimation.State.Running:
            return
        step = self.steps[self.index] if 0 <= self.index < len(self.steps) else None
        if step is not None and step.done is not None and not self._advancing:
            try:
                did = bool(step.done())
            except Exception:  # noqa: BLE001
                did = False
            if did:
                self._advancing = True
                QTimer.singleShot(450, lambda index=self.index: index == self.index and self.go(index + 1))
                return
        if self.bubble.size() != self.bubble.sizeHint():
            self._place_bubble()
        target = self._target(self.index)
        if target is None:
            return
        rect = self._rect_of(target)
        if any(abs(a - b) > 2 for a, b in zip(rect.getRect(), self.hole.getRect())):
            self._move_hole(rect)

    def _target(self, index):
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

    def _is_ready(self, index) -> bool:
        step = self.steps[index]
        try:
            if step.ready is not None and not step.ready():
                return False
        except Exception:  # noqa: BLE001
            return False
        return step.target is None or self._target(index) is not None

    def go(self, index: int, *, step: int = 1):
        self._waiting.stop()
        self._advancing = False
        if index >= len(self.steps):
            self.close_tour(True)
            return
        if index < 0:
            return
        self.index = index
        current = self.steps[index]
        if index not in self._entered and current.enter is not None:
            self._entered.add(index)
            try:
                current.enter()
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
        if self._is_ready(index):
            self._show(index)
            return
        if current.optional:   # e.g. the proofreading page when the user chose not to open it
            self.go(index + step, step=step)
            return
        # Wait (page switch, import, project opening) with the bubble hidden.
        self._waited = True
        self.bubble.hide()
        self.anim.stop()
        self.clearMask()
        self._wait_left = self.WAIT_MS
        self._wait_direction = step
        self._waiting.start()

    def _poll(self):
        self._wait_left -= self._waiting.interval()
        if self._is_ready(self.index):
            self._waiting.stop()
            self._show(self.index)
        elif self._wait_left <= 0:
            self._waiting.stop()
            self.go(self.index + self._wait_direction, step=self._wait_direction)  # this part is not available here

    def _show(self, index):
        from .onboarding import emphasis_html
        step = self.steps[index]
        target = self._target(index)
        widget = target[0] if isinstance(target, tuple) else target
        if widget is not None and not isinstance(target, tuple):
            scroll = widget.parent()
            while scroll is not None and not isinstance(scroll, QScrollArea):
                scroll = scroll.parent()
            if scroll is not None:
                scroll.ensureWidgetVisible(widget, 40, 60)
        text = step.text() if callable(step.text) else step.text
        self.text.setText(emphasis_html(str(tr(text)), self.theme.accent))
        self._set_compact(False)
        self.count.setText(f'{index + 1} / {len(self.steps)}')
        name = step.anim() if callable(step.anim) else step.anim
        self.anim.setVisible(self.anim.play(name, self.light))
        self._fill_buttons(step)
        self.bubble.adjustSize()
        self.raise_()
        self.bubble.show()
        rect = self._rect_of(target) if target is not None else QRectF()
        from .ui_motion import reduced_motion
        waited, self._waited = self._waited, False
        if rect.isNull() or self.hole.isNull() or waited or reduced_motion():
            self._motion.stop()
            self._move_hole(rect)
        else:
            self._motion.stop()
            self._motion.setStartValue(self.hole)
            self._motion.setEndValue(rect)
            self._motion.start()
        if not reduced_motion():
            self._attention.stop()
            self._attention.setLoopCount(-1 if step.interactive else 2)
            self._attention.start()
        if step.interactive:
            self.clearFocus()
            keys = None
            try:
                keys = step.focus() if step.focus is not None else None
            except Exception:  # noqa: BLE001
                keys = None
            (keys or self.window_).setFocus()
        else:
            (self.next if step.show_next else (self.action_buttons[0] if self.action_buttons else self.next)).setFocus()

    def _rect_of(self, target) -> QRectF:
        if isinstance(target, tuple):
            widget, part = target
            top_left = widget.mapTo(self.window_, part.topLeft().toPoint())
            rect = QRectF(top_left.x(), top_left.y(), part.width(), part.height()).adjusted(-6, -6, 6, 6)
        else:
            top_left = target.mapTo(self.window_, QPoint(0, 0))
            rect = QRectF(top_left.x(), top_left.y(), target.width(), target.height()).adjusted(-8, -8, 8, 8)
        return rect.intersected(QRectF(self.rect()).adjusted(6, 6, -6, -6))

    def _move_hole(self, rect):
        self.hole = QRectF(rect)
        self._place_bubble()
        self._apply_mask()
        self.update()

    def _apply_mask(self):
        step = self.steps[self.index] if 0 <= self.index < len(self.steps) else None
        if step is None or not step.interactive or self.hole.isNull() or not self.bubble.isVisible():
            self.clearMask()
            return
        # Clicks inside the outline reach the page; the bubble always stays clickable.
        region = QRegion(self.rect()).subtracted(QRegion(self.hole.toAlignedRect()))
        self.setMask(region.united(QRegion(self.bubble.geometry().adjusted(-2, -2, 2, 2))))

    def _avoid_rects(self) -> list:
        if self.avoid is None:
            return []
        try:
            return [QRectF(rect) for rect in self.avoid() or () if rect is not None]
        except Exception:  # noqa: BLE001
            return []

    def _set_compact(self, compact: bool):
        """Full size, or a narrower bubble (text and animation) for crowded pages."""
        self._compact = compact
        width = self.COMPACT_WIDTH if compact else self.TEXT_WIDTH
        self.text.setFixedWidth(width)
        # A wrapped label's size hint assumes its own width; pin both so no line is clipped.
        self.text.setFixedHeight(self.text.heightForWidth(width))
        self.anim.setFixedSize(width, round(width * TourAnim.SIZE.height() / TourAnim.SIZE.width()))

    def _measure(self):
        # New action buttons get their style only when polished; measure after that, or the
        # bubble comes out a button-height short and the last text line hides behind them.
        for child in self.bubble.findChildren(QWidget):
            child.ensurePolished()
        self.bubble.layout().activate()
        size = self.bubble.sizeHint()
        self.bubble.resize(size)
        return size

    def _place_bubble(self):
        self.pointer = None
        if self.hole.isNull():   # a centred card
            if self._compact:
                self._set_compact(False)
            size = self._measure()
            self.bubble.move(int((self.width() - size.width()) / 2), int((self.height() - size.height()) / 2))
            return
        for compact in (False, True):
            if compact != self._compact:
                self._set_compact(compact)
            if self._place_beside(self._measure()):
                return
        # No free spot beside the target even when compact: sit inside the outline's lower part,
        # away from the native video window.
        size = self._measure()
        width, height = self.width(), self.height()
        w, h = size.width(), size.height()
        margin, gap = 18, 24
        hole = self.hole
        x = max(margin, min(hole.center().x() - w / 2, width - w - margin))
        rect = QRectF(x, max(margin, min(hole.bottom() - h - gap, height - h - margin)), w, h)
        for a in self._avoid_rects():
            if rect.intersects(a):
                rect.moveTop(max(margin, min(a.bottom() + gap, height - h - margin)))
        self.bubble.move(int(rect.left()), int(rect.top()))

    def _place_beside(self, size) -> bool:
        width, height = self.width(), self.height()
        w, h = size.width(), size.height()
        margin, gap = 18, 24
        hole = self.hole
        cx, cy = hole.center().x(), hole.center().y()

        def clamp(value, low, high):
            return max(low, min(value, high))

        y_side = clamp(cy - h / 2, margin, height - h - margin)
        x_side = clamp(cx - w / 2, margin, width - w - margin)
        avoid = self._avoid_rects()
        places = [
            ('right', QRectF(hole.right() + gap, y_side, w, h)),
            ('left', QRectF(hole.left() - gap - w, y_side, w, h)),
            ('below', QRectF(x_side, hole.bottom() + gap, w, h)),
            ('above', QRectF(x_side, hole.top() - gap - h, w, h)),
        ]
        sides = ['right', 'left'] if cx < width / 2 else ['left', 'right']
        rows = ['below', 'above'] if cy < height / 2 else ['above', 'below']
        order = rows + sides if hole.width() > width * 0.5 else sides + rows
        places.sort(key=lambda item: order.index(item[0]))
        # Below / above, slid sideways past the native video window (toolbar buttons over the video).
        for side, rect in list(places):
            if side in ('below', 'above'):
                for a in avoid:
                    for x in (a.right() + gap, a.left() - gap - w):
                        places.append((side, QRectF(clamp(x, margin, width - w - margin), rect.top(), w, h)))
        bounds = QRectF(margin, margin, width - 2 * margin, height - 2 * margin)
        chosen = None
        for side, rect in places:
            if bounds.contains(rect) and not rect.intersects(hole) and not any(rect.intersects(a) for a in avoid):
                chosen = side
                break
        if chosen is None:
            return False
        # The pointer leaves the bubble as close to the target as it can and touches the outline.
        base_y = clamp(cy, rect.top() + 26, rect.bottom() - 26)
        base_x = clamp(cx, rect.left() + 26, rect.right() - 26)
        tip_y = clamp(base_y, hole.top() + 8, hole.bottom() - 8)
        tip_x = clamp(base_x, hole.left() + 8, hole.right() - 8)
        self.pointer = {
            'right': (QPointF(hole.right() + 4, tip_y), QPointF(rect.left() + 1, base_y - 12), QPointF(rect.left() + 1, base_y + 12)),
            'left': (QPointF(hole.left() - 4, tip_y), QPointF(rect.right() - 1, base_y - 12), QPointF(rect.right() - 1, base_y + 12)),
            'below': (QPointF(tip_x, hole.bottom() + 4), QPointF(base_x - 12, rect.top() + 1), QPointF(base_x + 12, rect.top() + 1)),
            'above': (QPointF(tip_x, hole.top() - 4), QPointF(base_x - 12, rect.bottom() - 1), QPointF(base_x + 12, rect.bottom() - 1)),
        }[chosen]
        self.bubble.move(int(rect.left()), int(rect.top()))
        return True

    def _pulse(self, value):
        self.glow = math.sin(math.pi * float(value))
        self.update()

    def close_tour(self, completed: bool):
        self._motion.stop()
        self._waiting.stop()
        self._follow.stop()
        self._attention.stop()
        self.anim.stop()
        self.clearMask()
        self.window_.removeEventFilter(self)
        self.hide()
        self.finished.emit(bool(completed))
        self.deleteLater()

    # ------------------------------------------------------------ Qt
    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if watched is self.window_ and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.window_.rect())
            target = self._target(self.index)
            self._move_hole(self._rect_of(target) if target is not None else QRectF())
        return False

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        key = event.key()
        step = self.steps[self.index] if 0 <= self.index < len(self.steps) else None
        if key == Qt.Key.Key_Escape:
            self.close_tour(False)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right) and step is not None and step.show_next:
            self.go(self.index + 1)
        elif key == Qt.Key.Key_Left and step is not None and step.show_next:
            self.go(self.index - 1, step=-1)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        event.accept()  # outside the outline the page waits until the tutorial is closed

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.setFillRule(Qt.FillRule.OddEvenFill)
        shade.addRect(QRectF(self.rect()))
        if not self.hole.isNull():
            shade.addRoundedRect(self.hole, 16, 16)
        painter.fillPath(shade, QColor(12, 9, 16, 178))
        accent = QColor(self.theme.accent)
        step = self.steps[self.index] if 0 <= self.index < len(self.steps) else None
        if not self.hole.isNull():
            ring = self.hole.adjusted(-2, -2, 2, 2)
            extra = 6 * self.glow if step is not None and step.interactive else 0
            for width, alpha in ((12 + extra, 36), (6 + extra / 2, 72)):
                glow = QColor(accent)
                glow.setAlpha(int(alpha))
                painter.setPen(QPen(glow, width))
                painter.drawRoundedRect(ring, 17, 17)
            painter.setPen(QPen(accent, 2.5))
            painter.drawRoundedRect(ring, 17, 17)
        if self.bubble.isVisible():
            box = QRectF(self.bubble.geometry())
            if self.glow > 0.01:   # a short glow that draws the eye to the bubble
                for spread, alpha in ((16, 46), (9, 70), (4, 96)):
                    glow = QColor(accent)
                    glow.setAlpha(int(alpha * self.glow))
                    painter.setPen(QPen(glow, spread))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRoundedRect(box.adjusted(-spread / 2, -spread / 2, spread / 2, spread / 2), 22, 22)
            if self.pointer is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
                painter.drawPolygon(QPolygonF(list(self.pointer)))
        painter.end()


# Kept for callers of the first version.
HomeTour = GuidedTour


# ---------------------------------------------------------------- the tutorial

def tutorial_steps(window) -> list[TourStep]:
    """The whole first subtitle with demo data: home → pretend result → proofreading → workbench."""
    from .sample_project import TUTORIAL_LIBRARY
    w = window
    get = lambda name: (lambda: w.__dict__.get(name))  # noqa: E731 - resolved when shown
    card = lambda role: (lambda: getattr(w.__dict__.get('recognition_plan'), 'cards', {}).get(role))  # noqa: E731
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

    def language():
        combo = w.__dict__.get('recognition_language')
        return str(combo.currentData() or '') if combo is not None else ''

    def set_language(code):
        combo = w.__dict__.get('recognition_language')
        if combo is not None and combo.findData(code) >= 0:
            combo.setCurrentIndex(combo.findData(code))

    def timeline_text():
        if language() == 'ja':
            return '**字幕时间轴**（日语用 CTC 对齐模型）：给**每个字**定时间（FireRedASR2 只认中文）'
        if language() == 'en':
            return '**字幕时间轴**（英语用 Qwen3-ForcedAligner）：给**每个单词**定时间，按单词断句、不切开单词'
        return '**字幕时间轴**（推荐 FireRedASR2）：给**每个字**定时间，并独立再识别一遍做对照（中文）'

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

    return [
        # ---- home
        TourStep('**两分钟带你做一遍**：用演示视频，不上传、不花钱。每一步都可以**自己动手**，也可以点“帮我做”',
                 next_label='开始', enter=w._tutorial_prepare_demo),
        TourStep('**放入影音**：把视频或音频拖到这里，一次可以放好几个。先放一段演示视频', get('media_frame'),
                 [TourAction('放入演示视频', w._tutorial_add_demo_media, advance=True)], show_next=False, ready=on_home,
                 anim='drop'),
        TourStep('放错了？点这里的 **×** 就能移除。现在先留着', get('clear_single_media_button'),
                 ready=lambda: bool(getattr(w, 'media_paths', None)), anim='remove'),
        TourStep('先选**字幕语言**：中文、日本语或英语（日语和英语会换成适合它们的时间轴模型）', get('recognition_language'),
                 [TourAction('中文', lambda: set_language('zh')), TourAction('日本語', lambda: set_language('ja')),
                  TourAction('English', lambda: set_language('en'))],
                 anim='language'),
        TourStep('**主力转写**（推荐 MOSS）：听出**谁在说话**，把多人对话分开，写出第一遍文字。点卡片可以更换',
                 card('primary'), anim='moss'),
        TourStep(timeline_text, card('timeline'), anim=lambda: 'ctc' if language() in ('ja', 'en') else 'firered'),
        TourStep('**文字复核**（推荐 Qwen3-ASR）：第三次识别。三份结果互相比对，留下最可靠的文字和**精确到字的时间**',
                 card('review'), anim='qwen'),
        TourStep('**AI 智能断句**：按语气断句、校对专有名词。需要一把 AI 服务的 API Key，没有也能先跳过',
                 get('home_process_card'), [TourAction('填写 API Key', lambda: w._open_ai_settings_dialog())], anim='apikey'),
        TourStep('**术语库**：填上游戏或节目名，打开**术语库校对**，角色名和专有名词就会按词库写对',
                 get('content_profile_card'), anim='glossary'),
        TourStep('正式使用时点 **开始生成字幕**。现在不用等，直接看**识别完成**的样子', get('start_button'),
                 [TourAction('看演示结果', w._tutorial_demo_completion, advance=True)], show_next=False, anim='start'),
        # ---- result page
        TourStep('**识别完成**：标题告诉你结果，下面可以试听预览；有需要注意的地方会列出来', get('result_title'),
                 ready=on_completion),
        TourStep('**AI 词库校对**：把写错的人名和术语一次找出来。**点它**打开', get('repolish_current_glossary_button'),
                 [TourAction('帮我做', lambda: w.repolish_current_glossary_button.click())], show_next=False,
                 interactive=True, done=on_proofread, ready=on_completion),
        # ---- proofreading, step by step
        TourStep('① 先**勾选词库**：这段聊的是原神，勾上「**原神**」。勾上后会先按词库找一遍（本机，免费）',
                 library_target, [TourAction('帮我做', check_library)], show_next=False, interactive=True,
                 done=library_checked, enter=offline_ai, ready=on_proofread, anim='gl_check'),
        TourStep('② 再点 **AI 校对**：找出词库里没写到的错字（教学里不联网、不收费）', proofread_part('ai_button'),
                 [TourAction('帮我做', lambda: proofread().ai_button.click())], show_next=False, interactive=True,
                 done=ai_shown, ready=lambda: on_proofread() and not busy(), anim='gl_ai'),
        TourStep('③ 红色是错字，下面是建议。**点一下**就改过来（至东 → 至冬）；改错了按 **Ctrl+Z**', fix_target,
                 [TourAction('帮我做', fix_it)], show_next=False, interactive=True, done=fixed,
                 ready=lambda: on_proofread() and not busy(), anim='gl_fix'),
        TourStep('其余的建议也一样：一条条点，或点 **采用全部建议**', proofread_part('select_all'),
                 ready=on_proofread, optional=True),
        TourStep('④ 改好了，点 **返回结果**', proofread_part('back_button'),
                 [TourAction('帮我做', lambda: proofread().back_button.click())], show_next=False, interactive=True,
                 done=on_completion, ready=on_proofread, anim='gl_back'),
        # ---- result page again
        TourStep('**导出字幕**：存成 SRT、ASS、TXT，放到你选的文件夹', get('export_result_button'),
                 ready=on_completion, anim='export'),
        TourStep('**字幕工作台**：逐条修改、审核、调时间、压制视频。**点它**打开', get('open_studio_result_button'),
                 [TourAction('帮我做', lambda: w.open_studio_result_button.click())], show_next=False, interactive=True,
                 done=studio_ready, ready=on_completion, anim='studio_open'),
        # ---- workbench
        TourStep('**改字幕**：**双击**时间轴上的字幕，或按 **E** 改播放头处的那一条', block_target,
                 [TourAction('帮我做', open_editor)], show_next=False, interactive=True,
                 done=lambda: editor() is not None, ready=studio_ready, focus=studio_keys, anim='edit'),
        TourStep('改好按 **Enter** 保存，**Esc** 取消；改错了按 **Ctrl+Z**', editor,
                 [TourAction('帮我做', save_editor)], show_next=False, interactive=True,
                 done=lambda: editor() is None, optional=True),
        TourStep('**审核模式**：点 **开始审核**，或按 **R**', studio_part('review_entry_button'),
                 [TourAction('帮我做', start_review)], show_next=False, interactive=True, enter=review_from_first,
                 done=reviewing, ready=lambda: studio_ready() and editor() is None, focus=studio_keys, anim='review'),
        TourStep('三份识别结果并排：按 **1 / 2 / 3** 选一个（或直接点），按 **E** 直接改字；选完自动到下一条',
                 candidates, [TourAction('帮我做', lambda: studio()._adopt_review_candidate(1))], show_next=False,
                 interactive=True, done=review_picked, enter=remember_undo, ready=reviewing, focus=studio_keys,
                 anim='review'),
        TourStep('审核完再按 **R**（或 Esc）退出审核', studio_part('review_entry_button'),
                 [TourAction('帮我做', lambda: studio()._set_review_mode(False))], show_next=False, interactive=True,
                 done=lambda: not reviewing(), focus=studio_keys),
        TourStep('**说话人管理**：给说话人改名（比如“主播”）、换颜色、合并重复的人', tool('speaker_manager_button'),
                 ready=studio_ready, anim='speakers'),
        TourStep('**批量替换**：一次把所有“派门”改成“派蒙”，先预览再替换', tool('studio_find_replace_button'),
                 ready=studio_ready, anim='replace'),
        TourStep('**时间轴**：拖动字幕两端改时间；按 **Q / W** 把起点或终点剪到播放头', studio_part('timeline'),
                 ready=studio_ready, anim='qw'),
        TourStep('**标点**：添加、去掉或保留原文，画面和导出一起变，文稿不会被改', studio_part('punctuation_button'),
                 ready=studio_ready, anim='punct'),
        TourStep('**导出字幕**：选格式和文件夹，一键导出', studio_part('studio_export_button'), ready=studio_ready,
                 anim='export'),
        TourStep('**压制成片**：把字幕烧进视频，导出成片', studio_part('studio_render_button'), ready=studio_ready,
                 anim='burn'),
        TourStep('完成！现在可以**放入你自己的影音**开始了', next_label='回到首页', enter=None),
    ]


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


def start_home_tour(window, on_finished=None) -> GuidedTour | None:
    """Start the tutorial (one at a time)."""
    existing = window.findChild(GuidedTour)
    if existing is not None:
        return existing
    tour = GuidedTour(window, tutorial_steps(window), avoid=tutorial_avoid(window))
    if on_finished is not None:
        tour.finished.connect(on_finished)
    tour.start()
    return tour
