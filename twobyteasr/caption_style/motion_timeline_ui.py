"""The 动效 stage timeline (2026-11-15, the user's pick A from the drafts).

The four stage tabs became one strip in playback order: 入场 | 停留 · 循环 | 出场,
each segment as wide as its real duration (with a readable minimum), and a 逐词
lane under it. A white playhead follows the preview above. Dragging the handle
between two segments changes the entry or exit duration; the inspector turns
one drag into one undo step.

It keeps the old stage bar's surface (``buttons`` in ``STAGES`` order,
``setCurrentIndex``, ``currentChanged``, ``set_value``) so callers, tests and
audits address stages exactly as before.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, Signal, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton, QWidget, QSizePolicy

from ..i18n import tr

STAGES = ('entry', 'exit', 'loop', 'words')
TITLES = {'entry': '入场', 'exit': '出场', 'loop': '停留 · 循环', 'words': '逐词'}
#: The reading part of the strip is drawn as if it lasted this long, so a
#: short entry still looks short next to it.
HOLD_MS = 1900
TRACK, LANE, GAP, SPACING, MIN_SEGMENT = 46, 26, 5, 3, 64
#: Text inset on both sides plus a little air; a segment never asks for more than MAX_NEEDED.
TEXT_PADDING, MAX_NEEDED = 22, 132
WORD_COLOR = '#7DD3FC'


def _tokens():
    from ..design.soft_qss import soft_tokens
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    t = theme_definition(theme_key())
    return t, soft_tokens(t)


class TimelineSegment(QPushButton):
    """One stage: its name (and duration) over the current choice, painted
    directly so app-wide button rules cannot clip or recolour it."""

    def __init__(self, stage, parent):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName('motionTimelineSegment')
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.title_text, self.value_text, self.active = tr(TITLES[stage]), '', False
        self.duration_ms = 0
        self.lit = -1.  # 逐词 lane: share of the reading time already spoken
        self.setAccessibleName(self.title_text)

    def set_value(self, text, active):
        changed = (text, active) != (self.value_text, self.active)
        self.value_text, self.active = text, active
        self.setToolTip(f'{self.title_text}：{text}')
        self.setAccessibleDescription(text)
        self.update()
        if changed and isinstance(self.parentWidget(), MotionTimeline):
            self.parentWidget().relayout()   # a longer name may need a wider segment

    def title_line(self):
        if self.stage in ('entry', 'exit') and self.active and self.duration_ms:
            return f'{self.title_text} · {self.duration_ms/1000:.2f}s'
        return self.title_text

    def title_lines(self):
        """The title from fullest to shortest; the duration is kept longest (2026-11-15)."""
        full = self.title_line()
        if full == self.title_text:
            return [full]
        seconds = f'{self.duration_ms/1000:.2f}s'
        return [full, f'{self.title_text} {seconds}', seconds]

    def fonts(self):
        title_font = QFont(self.font()); title_font.setPixelSize(11); title_font.setWeight(QFont.Normal)
        value_font = QFont(self.font()); value_font.setPixelSize(13)
        value_font.setWeight(QFont.Bold if self.active else QFont.Normal)
        return title_font, value_font

    def needed_width(self):
        """Width that shows the whole title (with the duration) and the choice unclipped."""
        title_font, value_font = self.fonts()
        text = max(QFontMetrics(title_font).horizontalAdvance(self.title_line()),
                   QFontMetrics(value_font).horizontalAdvance(self.value_text))
        return max(MIN_SEGMENT, min(MAX_NEEDED, text+TEXT_PADDING))

    def enterEvent(self, event):
        self.update(); super().enterEvent(event)

    def leaveEvent(self, event):
        self.update(); super().leaveEvent(event)

    def paintEvent(self, event):
        t, k = _tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath(); path.addRoundedRect(rect, 10, 10)
        checked = self.isChecked()
        painter.fillPath(path, QColor(k.chip if checked else k.fill_hover if self.underMouse() else k.fill))
        if not self.active and not checked:
            # An unset stage is striped, so 「无」 reads as empty at a glance.
            painter.save(); painter.setClipPath(path)
            stripe = QColor(t.text); stripe.setAlphaF(.045)
            painter.setPen(QPen(stripe, 4))
            for x in range(-int(rect.height()), int(rect.width()), 11):
                painter.drawLine(QPointF(x, rect.bottom()), QPointF(x+rect.height(), rect.top()))
            painter.restore()
        if checked:
            painter.setPen(QPen(QColor(t.accent), 2)); painter.drawPath(path)
        muted = QColor(t.text_muted)
        title_font, value_font = self.fonts()
        title_color = QColor(t.accent_text) if checked else muted
        value_color = QColor(t.text) if self.active else muted
        inner = rect.adjusted(9, 4, -9, -4)
        if self.stage == 'words':
            painter.setFont(title_font); painter.setPen(title_color)
            title_width = QFontMetrics(title_font).horizontalAdvance(self.title_text)
            painter.drawText(inner, Qt.AlignLeft | Qt.AlignVCenter, self.title_text)
            bars_width = 8*14+7*3
            value_rect = inner.adjusted(title_width+8, 0, -(bars_width+8), 0)
            painter.setFont(value_font); painter.setPen(value_color)
            painter.drawText(value_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             QFontMetrics(value_font).elidedText(self.value_text, Qt.ElideRight, int(value_rect.width())))
            painter.setPen(Qt.NoPen)
            off = QColor(t.text); off.setAlphaF(.16)
            for i in range(8):
                x = inner.right()-bars_width+i*17
                lit = self.active and self.lit >= i/8
                painter.setBrush(QColor(WORD_COLOR) if lit else off)
                painter.drawRoundedRect(QRectF(x, inner.center().y()-3, 14, 6), 3, 3)
        else:
            half = inner.height()/2
            painter.setFont(title_font); painter.setPen(title_color)
            metrics = QFontMetrics(title_font)
            # A narrow segment drops the 「·」, then the stage name, before it ever cuts the duration.
            title = next((line for line in self.title_lines() if metrics.horizontalAdvance(line) <= inner.width()),
                         self.title_lines()[-1])
            painter.drawText(QRectF(inner.left(), inner.top(), inner.width(), half), Qt.AlignLeft | Qt.AlignBottom,
                             metrics.elidedText(title, Qt.ElideRight, int(inner.width())))
            painter.setFont(value_font); painter.setPen(value_color)
            painter.drawText(QRectF(inner.left(), inner.top()+half+1, inner.width(), half-1), Qt.AlignLeft | Qt.AlignTop,
                             QFontMetrics(value_font).elidedText(self.value_text, Qt.ElideRight, int(inner.width())))
        painter.end()


class DurationGrip(QWidget):
    """The handle between two segments; dragging it resizes entry or exit."""
    pressed = Signal(str)
    moved = Signal(str, int)
    released = Signal(str)

    def __init__(self, stage, parent):
        super().__init__(parent)
        self.stage, self._x0, self.dragging = stage, None, False
        self.setObjectName('motionTimelineGrip')
        self.setCursor(Qt.SizeHorCursor)
        self.setFixedSize(12, TRACK-16)
        self.setToolTip(tr('拖动调整入场时长') if stage == 'entry' else tr('拖动调整出场时长'))
        self.setAccessibleName(self.toolTip())

    def paintEvent(self, event):
        t, k = _tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hot = self.dragging or self.underMouse()
        color = QColor(t.accent) if hot else QColor(t.text_muted)
        if not hot:
            color.setAlphaF(.7)
        painter.setPen(Qt.NoPen); painter.setBrush(color)
        painter.drawRoundedRect(QRectF(3, 0, 6, self.height()), 3, 3)
        painter.end()

    def enterEvent(self, event):
        self.update(); super().enterEvent(event)

    def leaveEvent(self, event):
        self.update(); super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._x0, self.dragging = event.globalPosition().x(), True
            self.pressed.emit(self.stage); self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.moved.emit(self.stage, round(event.globalPosition().x()-self._x0))

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.dragging = False
            self.released.emit(self.stage); self.update()


class _Playhead(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.x = None

    def paintEvent(self, event):
        if self.x is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        glow = QColor('#FFFFFF'); glow.setAlphaF(.25)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow); painter.drawRoundedRect(QRectF(self.x-3, 0, 6, TRACK), 3, 3)
        painter.setBrush(QColor('#FFFFFF')); painter.drawRoundedRect(QRectF(self.x-1, 0, 2, TRACK), 1, 1)
        painter.end()


class MotionTimeline(QWidget):
    """入场 | 停留 · 循环 | 出场 over a 逐词 lane; the stage switcher of the 动效 page."""
    currentChanged = Signal(int)
    #: (stage, milliseconds) while a handle is dragged; started/finished frame one gesture.
    durationDragStarted = Signal(str)
    durationDragged = Signal(str, int)
    durationDragFinished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('motionTimeline')
        self.setFixedHeight(TRACK+GAP+LANE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(3*MIN_SEGMENT+2*SPACING)
        self.buttons = []
        for i, stage in enumerate(STAGES):
            button = TimelineSegment(stage, self)
            button.clicked.connect(lambda _=False, i=i: self.setCurrentIndex(i))
            self.buttons.append(button)
        self.grips = {stage: DurationGrip(stage, self) for stage in ('entry', 'exit')}
        for grip in self.grips.values():
            grip.pressed.connect(self._grip_pressed)
            grip.moved.connect(self._grip_moved)
            grip.released.connect(self.durationDragFinished)
        self.playhead = _Playhead(self)
        self.durations = {'entry': 0, 'exit': 0}
        self._drag_start = 0
        self._spans = {}
        self._index = -1
        self.setCurrentIndex(0)

    # ---- the old stage-bar surface
    def count(self): return len(self.buttons)
    def currentIndex(self): return self._index
    def tabText(self, index): return self.buttons[index].title_text
    def setTabToolTip(self, index, text): self.buttons[index].setToolTip(text)

    def setCurrentIndex(self, index):
        index = max(0, min(len(self.buttons)-1, int(index)))
        for i, button in enumerate(self.buttons):
            button.setChecked(i == index)
        if index != self._index:
            self._index = index
            self.currentChanged.emit(index)

    def segment(self, stage):
        return self.buttons[STAGES.index(stage)]

    # ---- durations and layout
    def set_durations(self, entry_ms, exit_ms):
        """Durations of the active entry/exit (0 = none); widths follow them."""
        self.durations = {'entry': int(entry_ms), 'exit': int(exit_ms)}
        for stage in ('entry', 'exit'):
            self.segment(stage).duration_ms = self.durations[stage]
            self.segment(stage).update()
        self.relayout()

    def widths(self, width=None):
        """Pixel widths of entry, reading and exit for this widget width."""
        available = max(3*MIN_SEGMENT, (width if width is not None else self.width())-2*SPACING)
        entry, leave = self.durations['entry'], self.durations['exit']
        total = entry+HOLD_MS+leave
        # 2026-11-15: each segment is at least wide enough for its own text
        # (「入场 · 0.62s」 was cut to 「入场 · 0.…」 at the fixed minimum).
        need_first, need_middle, need_last = (self.segment(s).needed_width() for s in ('entry', 'loop', 'exit'))
        first = max(need_first, available*entry/total)
        last = max(need_last, available*leave/total)
        spare = available-need_middle
        if first+last > spare:           # long entry and exit: share what is left, text first
            floor = need_first+need_last
            if floor >= spare:
                scale = spare/max(1, floor)
                first, last = need_first*scale, need_last*scale
            else:
                extra = spare-floor
                over = (first-need_first)+(last-need_last)
                first = need_first+extra*(first-need_first)/over
                last = need_last+extra*(last-need_last)/over
        first, last = max(MIN_SEGMENT, first), max(MIN_SEGMENT, last)
        return round(first), round(available-first-last), round(last)

    def relayout(self):
        first, middle, last = self.widths()
        x_middle = first+SPACING
        x_last = x_middle+middle+SPACING
        self.segment('entry').setGeometry(0, 0, first, TRACK)
        self.segment('loop').setGeometry(x_middle, 0, middle, TRACK)
        self.segment('exit').setGeometry(x_last, 0, last, TRACK)
        self.segment('words').setGeometry(0, TRACK+GAP, self.width(), LANE)
        self._spans = {'entry': (0, first), 'loop': (x_middle, middle), 'exit': (x_last, last)}
        for stage, centre in (('entry', first+SPACING/2), ('exit', x_last-SPACING/2)):
            grip = self.grips[stage]
            grip.move(round(centre-grip.width()/2), 8)
            grip.setVisible(self.durations[stage] > 0)
            grip.raise_()
        self.playhead.setGeometry(0, 0, self.width(), TRACK)
        self.playhead.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    # ---- dragging a handle
    def _grip_pressed(self, stage):
        self._drag_start = self.durations[stage]
        self.setCurrentIndex(STAGES.index(stage))
        self.durationDragStarted.emit(stage)

    def _grip_moved(self, stage, dx):
        # Rightwards lengthens the entry; leftwards lengthens the exit.
        sign = 1 if stage == 'entry' else -1
        value = max(40, min(4000, round((self._drag_start+sign*dx*6)/10)*10))
        if value != self.durations[stage]:
            self.durationDragged.emit(stage, value)

    # ---- playback
    def set_time(self, local, duration, phases):
        """Place the playhead for a preview frame at ``local`` of ``duration`` ms."""
        if not self._spans:
            return
        entry, leave = phases or (0, 0)
        hold = max(1., duration-entry-leave)
        if entry and local < entry:
            x0, w = self._spans['entry']; x = x0+w*local/entry
        elif leave and local > duration-leave:
            x0, w = self._spans['exit']; x = x0+w*min(1., (local-(duration-leave))/leave)
        else:
            x0, w = self._spans['loop']; x = x0+w*min(1., max(0., local-entry)/hold)
        words = self.segment('words')
        lit = (local-entry)/hold if entry <= local <= duration-leave else -1.
        if abs(lit-words.lit) > .01:
            words.lit = lit; words.update()
        if self.playhead.x is None or abs(self.playhead.x-x) >= .5:
            self.playhead.x = x; self.playhead.update()


__all__ = ['MotionTimeline', 'TimelineSegment', 'DurationGrip', 'HOLD_MS']
