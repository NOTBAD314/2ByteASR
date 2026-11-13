"""Caption card editor inside the nonmodal native tool window.

2026-11-10 (user, design round 4 "字卡"): the subtitle being edited turns into
a cream card laid over the video subtitle. A perforated strip under the card
holds the actions with their keys; a clay bubble above the suspect word holds
the typo candidates. Every control keeps its attribute name; the editing
logic lives in caption_editor.py and is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QTextOption
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)
from ..design.typography import emphasis_qss, weighted_font

# The card sits on the video in every theme, so its body is always light;
# only the accent (tag, confirm, caret, focus) follows the theme.
CREAM = "#FFF6EA"
CHIP = "#F5E5D0"
CHIP_HOVER = "#EDD7BC"
PERFORATION = "#E3CBAE"
INK = "#3B2417"
MUTED = "#8A6248"
KEY = "#A07A5E"
CLAY = "#FFF4E6"
CLAY_EDGE = "#EAD2B4"
AMBER = "#FFC94D"
AMBER_EDGE = "#D9A21E"
AMBER_SOFT = "#FFE6A3"


def _signature(row):
    return (row.start, row.end, row.original, str(row.kind), tuple(o.text for o in row.options))


@dataclass
class _DisplayRow:
    row: object
    status: str = "pending"
    replacement: str = ""


class CaptionSuggestionView(QScrollArea):
    """Candidate rows; only the selected row is shown, as one bubble.

    Navigation (Shift+A/D/W, space) still walks every row in reading order;
    handled rows retain their navigation position.
    """
    activated = Signal(int, int)
    selected_changed = Signal()
    location_requested = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("captionSuggestionScroll")
        self.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.setProperty('uiZoomOwnSize', True)
        self._fit_pending = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(False)
        self._maximum_width, self._maximum_height = 700, 220
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._body = QWidget(self)
        self._body.setObjectName("captionSuggestionsBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setWidget(self._body)
        self._body.installEventFilter(self)
        self._suggestions = ()
        self._display = []
        self._text = self._expected_text = ""
        self._selection = None
        self._frames = []
        self._buttons = {}
        self._rows_generation = 0

    def reset(self):
        self._display = []
        self._text = self._expected_text = ""
        self._selection = None
        self.update_rows("", ())

    @property
    def selected(self):
        if self._selection is None:
            return (-1, -1)
        index, option = self._selection
        if not 0 <= index < len(self._display):
            return (-1, -1)
        item = self._display[index]
        if item.status != "pending":
            return (-1, -1)
        key = _signature(item.row)
        for mark, row in enumerate(self._suggestions):
            if _signature(row) == key:
                return mark, option
        return (-1, -1)

    @selected.setter
    def selected(self, value):
        mark, option = value
        if not 0 <= mark < len(self._suggestions):
            self._selection = None
        else:
            key = _signature(self._suggestions[mark])
            index = next((i for i, item in enumerate(self._display)
                          if item.status == "pending" and _signature(item.row) == key), None)
            self._selection = None if index is None else (index, option)
        self._paint_selection()

    def current_row(self):
        """The display row the bubble points at, or None."""
        if not self._display:
            return None
        index = self._selection[0] if self._selection else 0
        if not 0 <= index < len(self._display):
            return None
        return self._display[index]

    def pending_rows(self):
        return [item.row for item in self._display if item.status == "pending"]

    def owns_focus(self):
        focus = QApplication.focusWidget()
        return focus is self or (focus is not None and self.isAncestorOf(focus))

    def has_rows(self):
        return bool(self._display)

    def update_rows(self, text, rows):
        focused = self.owns_focus()
        rows = tuple(rows)
        preserve = text == self._text or text == self._expected_text
        if not preserve:
            self._display = []
            self._selection = None
        by_key = {_signature(row): row for row in rows}
        merged = []
        selected_item = (self._display[self._selection[0]]
                         if self._selection and self._selection[0] < len(self._display) else None)
        selected_option = self._selection[1] if self._selection else 0
        for item in self._display:
            if item.status != "pending":
                merged.append(item)
                continue
            row = by_key.pop(_signature(item.row), None)
            if row is not None:
                item.row = row
                merged.append(item)
        merged.extend(_DisplayRow(row) for row in by_key.values())
        self._display = sorted(merged, key=lambda item: (item.row.start, item.row.end))
        self._suggestions = rows
        self._text = self._expected_text = text
        if selected_item is not None and selected_item in self._display:
            self._selection = (self._display.index(selected_item), selected_option)
        elif self._display:
            first = next((i for i, item in enumerate(self._display) if item.status == "pending"), 0)
            self._selection = (first, 0)
        else:
            self._selection = None
        self._rebuild()
        if focused:
            self.focus_current()

    def stage_patch(self, start, end, replacement, new_text):
        """Only a validated draft patch can carry old row locations forward."""
        from dataclasses import replace
        delta = len(replacement) - (end - start)
        for item in self._display:
            row = item.row
            if row.start == start and row.end == end and item.status == "pending":
                item.status, item.replacement = "applied", replacement
                item.row = replace(row, end=start + len(replacement))
            elif row.start >= end:
                item.row = replace(row, start=row.start + delta, end=row.end + delta)
        self._expected_text = new_text

    def stage_ignore(self):
        if self._selection is not None and self.selected[0] >= 0:
            self._display[self._selection[0]].status = "ignored"
            self._expected_text = self._text

    def select_first(self):
        first = next((i for i, item in enumerate(self._display) if item.status == "pending"), None)
        if first is None:
            return False
        self._selection = (first, 0)
        self.focus_current()
        return True

    def navigate(self, vertical=0, horizontal=0):
        """Return False on down from the final row, to return to the draft."""
        if not self._display:
            return False
        index, option = self._selection or (0, 0)
        if vertical > 0 and index == len(self._display) - 1:
            return False
        index = max(0, min(len(self._display) - 1, index + vertical))
        count = max(1, len(self._display[index].row.options))
        option = max(0, min(count - 1, option + horizontal))
        self._selection = index, option
        self.focus_current()
        return True

    def cycle(self, direction, *, from_body=False):
        """Read-order candidates plus one body stop, shared by A and D."""
        entries = [(index, option) for index, item in enumerate(self._display)
                   for option in range(max(1, len(item.row.options)) if item.status == 'pending' else 1)]
        if not entries:
            return False
        if from_body:
            target = entries[0] if direction > 0 else entries[-1]
        else:
            index = entries.index(self._selection) if self._selection in entries else 0
            next_index = index + (1 if direction > 0 else -1)
            if not 0 <= next_index < len(entries):
                return False
            target = entries[next_index]
        self._selection = target
        self.focus_current()
        return True

    def focus_current(self):
        if self._selection is None:
            return
        # Show the bubble row first: a hidden button cannot take focus.
        self._show_row(self._selection[0])
        target = self._buttons.get(self._selection) or self._frames[self._selection[0]]
        # Explicit candidate navigation may cross from the timeline into the
        # non-activating tool; activation belongs to this user action only.
        QApplication.setActiveWindow(self.window())
        target.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.ensureWidgetVisible(target, 0, 0)
        self._paint_selection()
        item = self._display[self._selection[0]]
        if item.status == "pending":
            self.location_requested.emit(item.row.start, item.row.end)
        self.selected_changed.emit()

    def candidate_button(self, mark, option):
        self.selected = mark, option
        return self._buttons.get(self._selection)

    def _choose(self, index, option):
        self._selection = index, option
        self._paint_selection()
        self.selected_changed.emit()

    def _activate(self, index, option):
        self._choose(index, option)
        mark, selected = self.selected
        if mark >= 0:
            self.activated.emit(mark, selected)

    def _rebuild(self):
        self._rows_generation += 1
        generation = self._rows_generation
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self._frames, self._buttons = [], {}
        for index, item in enumerate(self._display):
            frame = QFrame(self._body)
            frame.setObjectName("captionSuggestionRow")
            frame.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            from ..design.soft_widgets import WrapLayout
            row_layout = WrapLayout(frame, spacing=4, fill=False, center=True)
            row_layout.setContentsMargins(0, 0, 0, 0)
            # The suspect word and its position stay for accessibility and
            # keyboard location; the bubble itself points at the word.
            suspect = QPushButton(f"「{item.row.original or '∅'}」".replace('&', '&&'), frame)
            suspect.setObjectName("captionSuspect")
            suspect.setToolTip(f"第 {item.row.start + 1}–{item.row.end} 字；只处理这一处")
            suspect.setEnabled(item.status == "pending")
            suspect.clicked.connect(lambda checked=False, i=index, g=generation: self._locate(i) if g == self._rows_generation else None)
            suspect.hide()
            row_layout.addWidget(suspect)
            if item.status == "pending":
                for option, value in enumerate(item.row.options):
                    button = QPushButton((value.text or "∅").replace('&', '&&'), frame)
                    button._candidate_text = value.text if isinstance(value.text, str) else "候选不可用"
                    button.setObjectName("captionCandidateButton")
                    button.setAccessibleName(f"将{item.row.original}替换为{value.text}")
                    button.setToolTip(f"「{item.row.original}」→「{value.text}」 · 点击或空格采纳")
                    button.setCheckable(True)
                    button.setAutoExclusive(False)
                    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                    button.setCursor(Qt.CursorShape.PointingHandCursor)
                    button.clicked.connect(lambda checked=False, i=index, j=option, g=generation: self._activate(i, j) if g == self._rows_generation else None)
                    button.installEventFilter(self)
                    button._caption_choice = (index, option)
                    button._caption_generation = generation
                    self._buttons[index, option] = button
                    row_layout.addWidget(button)
            else:
                text = f"{item.replacement} · 已采纳" if item.status == "applied" else "已忽略"
                result = QLabel(text, frame)
                result.setObjectName("captionSuggestionHandled")
                row_layout.addWidget(result)
            self._layout.addWidget(frame)
            frame.setVisible(False)
            self._frames.append(frame)
        count = len(self._display)
        self._paint_selection()
        self._fit_rows()
        self._schedule_fit()
        self.setVisible(bool(count))
        self.selected_changed.emit()
        owner = self.window()
        if hasattr(owner, 'schedule_fit'):
            owner.schedule_fit()

    def _locate(self, index):
        self._selection = index, 0
        self.focus_current()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self._body and event.type() == QEvent.Type.LayoutRequest:
            self._schedule_fit()
        if (event.type() == QEvent.Type.FocusIn and hasattr(watched, "_caption_choice")
                and watched._caption_generation == self._rows_generation):
            self._choose(*watched._caption_choice)
        return super().eventFilter(watched, event)

    def _schedule_fit(self):
        if self._fit_pending:
            return
        self._fit_pending = True
        QTimer.singleShot(0, self, self._fit_rows)

    def _visible_frame(self):
        return next((frame for frame in self._frames if not frame.isHidden()), None)

    def set_budget(self, width, height):
        budget = max(48, int(width)), max(38, int(height))
        if budget != (self._maximum_width, self._maximum_height):
            self._maximum_width, self._maximum_height = budget
            self._fit_rows()

    def _fit_rows(self):
        self._fit_pending = False
        frame = self._visible_frame()
        if frame is None:
            size = QSize(0, 0)
        else:
            natural = 0
            for button in frame.findChildren(QPushButton):
                if not hasattr(button, '_candidate_text'): continue
                button.ensurePolished()
                metrics = button.fontMetrics()
                value = button._candidate_text or '∅'
                width = max(24, self._maximum_width - 22)
                lines, line = [], ''
                for char in value:
                    if char == '\n' or line and metrics.horizontalAdvance(line+char) > width:
                        lines.append(line); line = ''
                    if char != '\n': line += char
                lines.append(line)
                label = '\n'.join(lines).replace('&', '&&')
                if button.text() != label: button.setText(label)
                wanted = max(38, max(metrics.horizontalAdvance(v) for v in lines) + 22)
                button.setFixedSize(min(self._maximum_width, wanted), max(38, len(lines)*metrics.lineSpacing()+14))
                natural += button.width()+4
            width = min(self._maximum_width, max(38, natural-4, frame.minimumSizeHint().width()))
            if frame.width() != width: frame.setFixedWidth(width)
            layout = frame.layout()
            layout.activate()
            height = max(38, layout.heightForWidth(width), layout.sizeHint().height())
            frame.setFixedHeight(height)
            self._body.setFixedSize(width, height)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            size = QSize(width + (self.verticalScrollBar().sizeHint().width() if height > self._maximum_height else 0),
                         min(height, self._maximum_height))
        if self.size() != size or self.minimumSize() != size or self.maximumSize() != size:
            self.setFixedSize(size)
            self.updateGeometry()

    def _show_row(self, index):
        if 0 <= index < len(self._frames) and self._frames[index].isHidden():
            self._frames[index].setVisible(True)
            self._fit_rows()

    def _paint_selection(self):
        current = self._selection[0] if self._selection is not None else (0 if self._frames else -1)
        self._show_row(current)
        for key, button in self._buttons.items():
            button.setChecked(key == self._selection)
        for index, frame in enumerate(self._frames):
            chosen = index == current
            if frame.isHidden() == chosen:
                frame.setVisible(chosen)
            if frame.property("selected") != chosen:
                frame.setProperty("selected", chosen)
                frame.style().unpolish(frame)
                frame.style().polish(frame)
        self._fit_rows()


class CaptionSuggestionBubble(QWidget):
    """Clay bubble around the candidate row, with a tail at the suspect word."""
    TAIL = 7
    PAD = 5

    def __init__(self, view, parent):
        super().__init__(parent)
        self.setObjectName("captionSuggestionBubble")
        self.view = view
        self._tail_x = 0.0
        self._tail_down = True
        layout = QVBoxLayout(self)
        layout.addWidget(view)
        self._apply_margins()
        view.installEventFilter(self)
        self.hide()

    def _apply_margins(self):
        pad, tail = self.PAD, self.TAIL
        # The bottom of the clay body is 3 px deeper, like a pressed key.
        if self._tail_down:
            self.layout().setContentsMargins(pad, pad, pad, pad + 3 + tail)
        else:
            self.layout().setContentsMargins(pad, pad + tail, pad, pad + 3)

    def set_tail(self, x, down):
        down = bool(down)
        if down != self._tail_down:
            self._tail_down = down
            self._apply_margins()
        if abs(x - self._tail_x) > 0.5:
            self._tail_x = float(x)
        self.update()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self.view:
            kind = event.type()
            if kind in (QEvent.Type.Show, QEvent.Type.Hide):
                QTimer.singleShot(0, self, self._follow_view)
            elif kind in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
                self.adjustSize()
                owner = self.parentWidget()
                if hasattr(owner, 'place_bubble'):
                    QTimer.singleShot(0, owner, owner.place_bubble)
        return super().eventFilter(watched, event)

    def _follow_view(self):
        owner = self.parentWidget()
        if hasattr(owner, 'place_bubble'):
            owner.place_bubble()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tail = self.TAIL
        top = 0 if self._tail_down else tail
        bottom = self.height() - (tail if self._tail_down else 0)
        body = QRectF(0.5, top + 0.5, self.width() - 1, bottom - top - 1)
        x = max(18.0, min(self.width() - 18.0, self._tail_x))
        path = QPainterPath()
        path.addRoundedRect(body, 15, 15)
        tip = QPainterPath()
        if self._tail_down:
            tip.moveTo(x - 8, body.bottom() - 2)
            tip.quadTo(x - 2, body.bottom() + tail - 2, x, body.bottom() + tail)
            tip.quadTo(x + 2, body.bottom() + tail - 2, x + 8, body.bottom() - 2)
        else:
            tip.moveTo(x - 8, body.top() + 2)
            tip.quadTo(x - 2, body.top() - tail + 2, x, body.top() - tail)
            tip.quadTo(x + 2, body.top() - tail + 2, x + 8, body.top() + 2)
        tip.closeSubpath()
        painter.setPen(QColor(PERFORATION))
        painter.setBrush(QColor(CLAY_EDGE))
        painter.drawPath(path.united(tip))
        painter.setPen(Qt.PenStyle.NoPen)
        face = QPainterPath()
        face.addRoundedRect(QRectF(body.left() + 1, body.top() + 1, body.width() - 2, body.height() - 4), 14, 14)
        # The tail keeps the deeper clay edge colour: on the cream card a
        # cream tail would vanish.
        painter.setBrush(QColor(CLAY))
        painter.drawPath(face)
        painter.setPen(QColor(255, 255, 255, 200))
        painter.drawLine(QPointF(body.left() + 14, body.top() + 1.5), QPointF(body.right() - 14, body.top() + 1.5))
        painter.end()


class CaptionShortcutHint(QWidget):
    """Wrap complete shortcut groups; never split an instruction mid-word."""
    def __init__(self, parent=None):
        super().__init__(parent)
        from ..design.soft_widgets import WrapLayout
        self._flow = WrapLayout(self, spacing=10, fill=False)
        self._text = ''
        self.groups = []
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy = self.sizePolicy(); policy.setHeightForWidth(True); self.setSizePolicy(policy)

    def text(self):
        return self._text

    def setText(self, text):
        text = str(text)
        if text == self._text:
            return
        self._text = text
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item.widget() is not None:
                item.widget().hide(); item.widget().deleteLater()
        self.groups = []
        for part in text.split(' · '):
            label = QLabel(part, self); label.setObjectName('subtitleEditCardHint')
            label.setWordWrap(False); label.setTextFormat(Qt.TextFormat.PlainText)
            self._flow.addWidget(label); label.show(); self.groups.append(label)
        self.setAccessibleName(text)
        self._flow.invalidate(); self.updateGeometry()


class CaptionKeyCap(QWidget):
    """A small keycap. Shift and Enter are drawn, not taken from a font, so
    they never fall back to a missing glyph and keep exact spacing."""
    HEIGHT = 18

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self._spec = spec
        self._shift = spec.startswith('⇧')
        self._enter = spec == '↵'
        self._label = spec.lstrip('⇧').strip() if not self._enter else ''
        self._background = QColor(CREAM)
        self._foreground = QColor(KEY)
        font = QFont(self.font())
        font.setPixelSize(11)
        weighted_font(font, QFont.Weight.Bold)
        self.setFont(font)
        self.setFixedSize(self.sizeHint())

    def text(self):
        return self._spec

    def set_colors(self, background, foreground):
        self._background, self._foreground = QColor(background), QColor(foreground)
        self.update()

    def sizeHint(self):
        width = 10
        if self._shift:
            width += 8 + 3
        if self._enter:
            width += 11
        if self._label:
            width += QFontMetrics(self.font()).horizontalAdvance(self._label)
        return QSize(max(self.HEIGHT, width), self.HEIGHT)

    def paintEvent(self, event):
        from PySide6.QtGui import QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._background)
        painter.drawRoundedRect(QRectF(self.rect()), 5, 5)
        pen = QPen(self._foreground, 1.4)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        x = 5.0
        mid = self.height() / 2
        if self._shift:
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            arrow = QPainterPath()
            arrow.moveTo(x + 4, mid - 4.5)
            arrow.lineTo(x + 8, mid)
            arrow.lineTo(x + 6, mid)
            arrow.lineTo(x + 6, mid + 4)
            arrow.lineTo(x + 2, mid + 4)
            arrow.lineTo(x + 2, mid)
            arrow.lineTo(x, mid)
            arrow.closeSubpath()
            painter.drawPath(arrow)
            x += 8 + 3
        if self._enter:
            painter.setPen(pen)
            hook = QPainterPath()
            hook.moveTo(x + 10, mid - 4.5)
            hook.lineTo(x + 10, mid + 1.5)
            hook.lineTo(x + 1, mid + 1.5)
            painter.drawPath(hook)
            head = QPainterPath()
            head.moveTo(x + 4, mid - 1.5)
            head.lineTo(x + 1, mid + 1.5)
            head.lineTo(x + 4, mid + 4.5)
            painter.drawPath(head)
        if self._label:
            painter.setPen(self._foreground)
            painter.setFont(self.font())
            painter.drawText(QRectF(x, 0, self.width() - x - 5, self.height()),
                             Qt.AlignmentFlag.AlignCenter, self._label)
        painter.end()


class CaptionStripButton(QPushButton):
    """A strip action: optional icon, a label and its key as a small keycap."""
    HEIGHT = 30

    def __init__(self, text='', key='', icon='', parent=None, *, primary=False):
        super().__init__(parent)
        self.setObjectName('captionStripPrimary' if primary else 'captionStrip')
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon_name = icon
        self._primary = primary
        row = QHBoxLayout(self)
        icon_only = bool(icon) and not text and not key
        row.setContentsMargins(0 if icon_only else 10, 0, 0 if icon_only else (6 if key else 10), 0)
        row.setSpacing(0)
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName('captionStripIcon')
        self.icon_label.setFixedSize(14, 14)
        self.text_label = QLabel(text, self)
        self.text_label.setObjectName('captionStripText')
        self.key_label = CaptionKeyCap(key, self)
        self.key_label.setObjectName('captionStripKey')
        if primary:
            self.key_label.set_colors(QColor(255, 255, 255, 56), QColor(255, 255, 255))
        if icon_only:
            row.addStretch(1)
        row.addWidget(self.icon_label)
        if icon and text:
            row.addSpacing(5)
        row.addWidget(self.text_label)
        if key:
            row.addSpacing(6)
        row.addWidget(self.key_label)
        if icon_only:
            row.addStretch(1)
        for label in (self.icon_label, self.text_label, self.key_label):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.icon_label.setVisible(bool(icon))
        self.text_label.setVisible(bool(text))
        self.key_label.setVisible(bool(key))
        self.setFixedHeight(self.HEIGHT)
        if icon_only:
            self.setFixedWidth(self.HEIGHT)
        self.setAccessibleName(text or key)
        self.paint_icon(INK)

    def paint_icon(self, color):
        if not self._icon_name:
            return
        try:
            from ..design.themed_icons import colored_icon
            ratio = self.devicePixelRatioF() if self.window() is not None else 1.0
            self.icon_label.setPixmap(colored_icon(self._icon_name, color).pixmap(QSize(14, 14), ratio))
        except Exception:
            self.icon_label.clear()

    def setText(self, text):
        self.text_label.setText(text)
        self.text_label.setVisible(bool(text))
        self.setAccessibleName(text)
        self.updateGeometry()

    def text(self):
        return self.text_label.text()

    def sizeHint(self):
        hint = self.layout().sizeHint()
        return QSize(max(hint.width(), self.HEIGHT), self.HEIGHT)

    def minimumSizeHint(self):
        return self.sizeHint()


class CaptionEditorPanel(QFrame):
    """The caption card (2026-11-10, design round 4 "字卡").

    Layout, top to bottom: a lane for the candidate bubble, the cream card
    face with the draft, then the perforated strip with the actions. When
    there is no room under the subtitle the strip goes above the face and
    the bubble below it (``set_strip_above``).
    """
    TEXT_PX = 22
    MIN_CARD = 380
    TAG_OVERHANG = 11
    FACE_GUTTER = 36

    def __init__(self, editor_type, parent=None):
        super().__init__(parent)
        self.setObjectName("subtitleEditCard")
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self._resize_queued = False
        self._place_pending = False
        self._strip_above = False
        self._accent = "#D9623A"
        self._on_accent = "#FFFFFF"
        self.setMinimumWidth(0)
        self.setMaximumWidth(1100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy = self.sizePolicy(); policy.setHeightForWidth(True); self.setSizePolicy(policy)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._outer = outer

        # Controls that left the visible card stay real widgets (callers and
        # tests drive them); the More menu exposes the useful ones.
        self._spare = QWidget(self)
        self._spare.hide()
        self.title = QLabel("编辑字幕", self._spare)
        self.title.setObjectName("subtitleEditCardTitle")
        self.role = QLabel(self._spare)
        self.role.setObjectName("captionEditorRole")
        self.meta = QLabel(self._spare)
        self.meta.setObjectName("captionEditorMeta")
        self.help_button = QPushButton("?", self._spare)
        self.help_button.setCheckable(True)
        self.help_button.setToolTip("显示快捷键")
        self.reference_button = QPushButton("原文参考", self._spare)
        self.reference_button.setCheckable(True)
        self.reference_button.hide()
        self.ignore_button = QPushButton("忽略此建议", self._spare)
        self.ignore_button.setToolTip("仅忽略当前词、本条字幕和当前语言层；确认后生效")
        self.ignore_button.hide()
        self.split_mode = QPushButton('C 切割', self._spare)
        self.split_mode.setCheckable(True)
        self.split_playhead = QPushButton('播放头定切点', self._spare)
        self.split_playhead.setCheckable(True)
        self.split_playhead.setToolTip('开启后：播放头位置就是声音切点，光标位置是文字切点。'
                                       '适合没有字级时间的语言；播放头须在本条字幕内部')

        self.lane = QWidget(self)
        self.lane.setFixedHeight(self.TAG_OVERHANG + 1)
        self.card = QFrame(self)
        self.card.setObjectName("captionCard")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        self._card_layout = card_layout

        self.face = QFrame(self.card)
        self.face.setObjectName("captionCardFace")
        face_layout = QVBoxLayout(self.face)
        face_layout.setContentsMargins(self.FACE_GUTTER, 16, self.FACE_GUTTER, 12)
        face_layout.setSpacing(6)
        self.reference = QLabel(self.face)
        self.reference.setObjectName("captionEditorReference")
        self.reference.setTextFormat(Qt.TextFormat.PlainText)
        self.reference.setWordWrap(True)
        self.reference.setMaximumHeight(65)
        self.reference.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        face_layout.addWidget(self.reference)
        self.reference.hide()
        # Created before the editor and focusable, as before: when the tool
        # window is merely activated, Qt focuses the first widget in the
        # chain, and that must not be the draft (focus there locks follow).
        self.close_button = QPushButton("×", self.face)
        self.close_button.setObjectName("captionClose")
        self.close_button.setAccessibleName("取消修改并关闭编辑浮窗")
        self.close_button.setToolTip("取消修改并关闭")
        self.close_button.setFixedSize(22, 22)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.editor = editor_type(self.face)
        self.editor.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        self.editor.setObjectName("subtitleEditCardInput")
        self.editor.setMinimumWidth(0)
        self.editor.setTabChangesFocus(True)
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont(self.editor.font())
        font.setPixelSize(self.TEXT_PX)
        weighted_font(font, QFont.Weight.DemiBold)
        self.editor.setFont(font)
        self.editor.document().setDocumentMargin(0)
        option = self.editor.document().defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.editor.document().setDefaultTextOption(option)
        self.editor.setFixedHeight(36)
        face_layout.addWidget(self.editor)

        self.strip = QFrame(self.card)
        self.strip.setObjectName("captionCardStrip")
        strip_layout = QVBoxLayout(self.strip)
        strip_layout.setContentsMargins(10, 8, 10, 9)
        strip_layout.setSpacing(6)
        self.strip_row = QWidget(self.strip)
        from ..design.soft_widgets import WrapLayout
        controls = WrapLayout(self.strip_row, spacing=5, fill=False, center=True)
        self._controls = controls

        self.parts_host = QWidget(self.strip_row)
        parts_row = QHBoxLayout(self.parts_host)
        parts_row.setContentsMargins(0, 0, 0, 0)
        parts_row.setSpacing(5)
        self.split_previous = CaptionStripButton(icon='fa5s.chevron-left', parent=self.parts_host)
        self.split_previous.setToolTip('上一段')
        self.split_part = QLabel(self.parts_host)
        self.split_part.setObjectName('captionPartLabel')
        self.split_part.setWordWrap(False)
        self.split_next = CaptionStripButton(icon='fa5s.chevron-right', parent=self.parts_host)
        self.split_next.setToolTip('下一段')
        self.split_undo = CaptionStripButton(icon='fa5s.undo-alt', parent=self.parts_host)
        self.split_undo.setToolTip('撤销切割 · Ctrl+Z')
        self.split_redo = CaptionStripButton(icon='fa5s.redo-alt', parent=self.parts_host)
        self.split_redo.setToolTip('重做切割 · Ctrl+Y')
        for button in (self.split_previous, self.split_next, self.split_undo, self.split_redo):
            button.setEnabled(False)
        for widget in (self.split_previous, self.split_part, self.split_next, self.split_undo, self.split_redo):
            parts_row.addWidget(widget)
        self.parts_divider = QFrame(self.parts_host)
        self.parts_divider.setObjectName('captionStripDivider')
        self.parts_divider.setFixedSize(2, 16)
        parts_row.addSpacing(2)
        parts_row.addWidget(self.parts_divider)
        parts_row.addSpacing(2)
        self.parts_host.hide()

        self.split_button = CaptionStripButton('切割', '⇧ C', 'fa5s.cut', self.strip_row)
        self.split_button.setToolTip('在文字光标处切开 · Shift+C')
        self.pronoun_button = CaptionStripButton('他/她', '⇧ P', parent=self.strip_row)
        self.pronoun_button.setToolTip("Shift+P · 切换当前草稿里的全部人称，不需要移动光标")
        self.more_button = CaptionStripButton(icon='fa5s.ellipsis-h', parent=self.strip_row)
        self.more_button.setToolTip('更多')
        self.more_menu = QMenu(self.more_button)
        self.more_menu.setObjectName('captionMoreMenu')
        self.more_menu.aboutToShow.connect(self._fill_more_menu)
        self.more_button.clicked.connect(self._show_more_menu)
        self.cancel_button = CaptionStripButton("取消", "Esc", parent=self.strip_row)
        self.cancel_button.setToolTip("Esc · 取消并还原草稿")
        self.confirm_button = CaptionStripButton("确认", "↵", parent=self.strip_row, primary=True)
        self.confirm_button.setToolTip("Enter / Shift+R · 保存成功后关闭")
        # Two-step cut: the playhead gives the audio cut, the caret the text
        # cut. The window refreshes this from the clock while it is shown.
        self.cut_status = QLabel(self.strip_row)
        self.cut_status.setObjectName("captionCutStatus")
        self.cut_status.hide()
        for widget in (self.parts_host, self.split_button, self.pronoun_button, self.more_button,
                       self.cancel_button, self.confirm_button, self.cut_status):
            controls.addWidget(widget)
        strip_layout.addWidget(self.strip_row)

        self.split_status = QLabel(self.strip)
        self.split_status.setObjectName('captionEditorMeta')
        self.split_status.setWordWrap(True)
        self.split_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        strip_layout.addWidget(self.split_status)
        self.error_label = QLabel(self.strip)
        self.error_label.setObjectName("captionEditorError")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        error_row = QHBoxLayout()
        error_row.setContentsMargins(0, 0, 0, 0)
        error_row.setSpacing(6)
        error_row.addWidget(self.error_label, 1)
        self.copy_draft_button = QPushButton('复制草稿', self.strip)
        self.copy_draft_button.setObjectName('captionQuiet')
        self.reload_current_button = QPushButton('复制草稿并载入当前文本', self.strip)
        self.reload_current_button.setObjectName('captionQuiet')
        self.reload_current_button.hide()
        self.error_toggle = QToolButton(self.strip)
        self.error_toggle.setText("技术详情")
        self.error_toggle.setCheckable(True)
        error_row.addWidget(self.error_toggle)
        recovery_row = QHBoxLayout(); recovery_row.setContentsMargins(0, 0, 0, 0)
        recovery_row.addWidget(self.copy_draft_button)
        recovery_row.addWidget(self.reload_current_button)
        recovery_row.addStretch(1)
        self.error_host = QWidget(self.strip)
        error_layout = QVBoxLayout(); error_layout.setContentsMargins(0, 0, 0, 0); error_layout.setSpacing(2)
        error_layout.addLayout(error_row); error_layout.addLayout(recovery_row)
        self.error_host.setLayout(error_layout)
        strip_layout.addWidget(self.error_host)
        self.error_host.hide()
        self.error_detail = QLabel(self.strip)
        self.error_detail.setObjectName("captionEditorReference")
        self.error_detail.setWordWrap(True)
        self.error_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.error_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_detail.hide()
        strip_layout.addWidget(self.error_detail)
        self.error_toggle.toggled.connect(self.error_detail.setVisible)
        self.hint = CaptionShortcutHint(self.strip)
        strip_layout.addWidget(self.hint)
        self.hint.hide()

        self.tag = QLabel("编辑", self)
        self.tag.setObjectName("captionCardTag")
        self.tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tag.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.suggestions = CaptionSuggestionView(self)
        self.suggestions.hide()
        self.bubble = CaptionSuggestionBubble(self.suggestions, self)

        self._arrange()
        self.help_button.toggled.connect(self._toggle_hint)
        self.reference_button.toggled.connect(self.reference.setVisible)
        self.split_mode.toggled.connect(self.update_hint)
        self.split_playhead.toggled.connect(self.update_hint)
        self.split_status.installEventFilter(self)
        self.editor.cursorPositionChanged.connect(self._paint_marks)
        self.split_playhead.toggled.connect(self._paint_marks)
        self.editor.textChanged.connect(self.resize_editor)
        self.editor.textChanged.connect(self._queue_place)
        self.suggestions.selected_changed.connect(self.update_hint)
        self.suggestions.selected_changed.connect(self._paint_marks)
        self.suggestions.selected_changed.connect(self._queue_place)
        self.editor.installEventFilter(self)
        self.update_hint()

    # -- layout ----------------------------------------------------------
    def _arrange(self):
        """Lane on the bubble side of the face; strip on the other side."""
        for widget in (self.lane, self.card):
            self._outer.removeWidget(widget)
        for widget in (self.face, self.strip):
            self._card_layout.removeWidget(widget)
        if self._strip_above:
            self._card_layout.addWidget(self.strip)
            self._card_layout.addWidget(self.face)
            self._outer.addWidget(self.card)
            self._outer.addWidget(self.lane)
        else:
            self._card_layout.addWidget(self.face)
            self._card_layout.addWidget(self.strip)
            self._outer.addWidget(self.lane)
            self._outer.addWidget(self.card)
        self.face.setProperty('stripAbove', self._strip_above)
        self.strip.setProperty('stripAbove', self._strip_above)
        for widget in (self.face, self.strip):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._queue_place()

    def strip_above(self):
        return self._strip_above

    def set_strip_above(self, above):
        above = bool(above)
        if above != self._strip_above:
            self._strip_above = above
            self._arrange()
            self.updateGeometry()

    def preferred_width(self, maximum, minimum_text=0):
        """Card width: the strip, the draft and the covered subtitle all fit."""
        self.strip_row.layout().activate()
        strip = self.strip_row.sizeHint().width() + 20
        metrics = QFontMetrics(self.editor.font())
        text = max((metrics.horizontalAdvance(line[:512]) for line in self.editor.toPlainText().split('\n')), default=0)
        text = max(text, int(minimum_text)) + 2*self.FACE_GUTTER + 12
        bubble = 0
        item = self.suggestions.current_row()
        if item is not None:
            # Intrinsic candidate content, not last frame's constrained view.
            # Feeding the wrapped viewport width back here drifts a few pixels
            # on every cursor/layout event near a width limit.
            buttons = [b for (index,_),b in self.suggestions._buttons.items()
                       if self.suggestions._display[index] is item]
            if buttons:
                fm = buttons[0].fontMetrics()
                bubble = sum(max(38,fm.horizontalAdvance(str(option.text or '')[:512])+22)
                             for option in item.row.options) + 4*max(0,len(item.row.options)-1) + 34
            else:
                bubble = self.bubble.sizeHint().width()+24
        return int(max(160, min(int(maximum), max(self.MIN_CARD, strip, text, bubble))))

    def _queue_place(self, *_args):
        if self._place_pending:
            return
        self._place_pending = True
        QTimer.singleShot(0, self, self.place_bubble)

    def prepare_geometry(self, width, maximum_height):
        self.setFixedWidth(max(120, int(width)))
        self.resize_editor(max(80, width-2*self.FACE_GUTTER))
        self._card_layout.activate()
        content_height = self._card_layout.totalHeightForWidth(width) if self._card_layout.hasHeightForWidth() else self.card.sizeHint().height()
        self.suggestions.set_budget(max(48, width-24), max(38, maximum_height-max(80, content_height)-24))
        self.bubble.adjustSize()
        lane = max(self.TAG_OVERHANG+1, self.bubble.sizeHint().height()+4) if self.suggestions.has_rows() else self.TAG_OVERHANG+1
        if self.lane.height() != lane: self.lane.setFixedHeight(lane)
        self._outer.invalidate()
        self._outer.activate()

    def place_bubble(self):
        """Put the tag on the face edge and the bubble over the suspect word."""
        self._place_pending = False
        face = self.face.geometry().translated(self.card.pos())
        self.close_button.move(self.face.width() - self.close_button.width() - 8, 8)
        self.close_button.raise_()
        self.tag.adjustSize()
        tag_y = face.top() - self.TAG_OVERHANG if not self._strip_above else face.bottom() - self.tag.height() + self.TAG_OVERHANG
        self.tag.move(face.left() + 16, tag_y)
        self.tag.raise_()
        row = self.suggestions.current_row() if self.suggestions.has_rows() else None
        lane = self.TAG_OVERHANG + 1
        if row is None or self.suggestions.isHidden():
            if not self.bubble.isHidden():
                self.bubble.hide()
        else:
            from .caption_editor import qt_position
            text = self.editor.toPlainText()
            try:
                start = qt_position(text, min(row.row.start, len(text)))
                end = qt_position(text, min(row.row.end, len(text)))
            except Exception:
                start = end = 0
            from PySide6.QtGui import QTextCursor
            cursor = QTextCursor(self.editor.document())
            cursor.setPosition(min(start, self.editor.document().characterCount() - 1))
            first = self.editor.cursorRect(cursor)
            cursor.setPosition(min(end, self.editor.document().characterCount() - 1))
            last = self.editor.cursorRect(cursor)
            centre = (first.left() + last.left()) / 2 if last.top() == first.top() and end > start else first.left() + 8
            viewport = self.editor.viewport()
            above = viewport.mapTo(self, QPoint(int(centre), first.top()))
            below = viewport.mapTo(self, QPoint(int(centre), first.bottom()))
            self.bubble.adjustSize()
            width, height = self.bubble.width(), self.bubble.height()
            x = max(0, min(self.width() - width, above.x() - width // 2))
            down = not self._strip_above
            self.bubble.set_tail(above.x() - x, down)
            # Reserve the complete measured bubble before window placement.
            # This is independent of the previous lane/window geometry.
            lane = max(lane, height + 4)
            y = face.top() - height + 2 if down else face.bottom() + 2
            self.bubble.move(x, y)
            self.bubble.show()
            self.bubble.raise_()
        if self.lane.height() != lane:
            self.lane.setFixedHeight(lane)
            self.updateGeometry()
            owner = self.window()
            if hasattr(owner, 'schedule_fit'):
                owner.schedule_fit()

    def _show_more_menu(self):
        self.more_menu.popup(self.more_button.mapToGlobal(QPoint(0, self.more_button.height() + 4)))

    def _fill_more_menu(self):
        menu = self.more_menu
        menu.clear()
        def toggle(label, button):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(button.isChecked())
            action.toggled.connect(button.setChecked)
            return action
        toggle('播放头定切点（无字级时间时用）', self.split_playhead)
        toggle('C 键直接切割', self.split_mode)
        if not self.reference_button.isHidden():
            toggle('显示同条原文', self.reference_button)
        if not self.ignore_button.isHidden():
            action = menu.addAction('忽略这个错字提示')
            action.setEnabled(self.ignore_button.isEnabled())
            action.triggered.connect(self.ignore_button.click)
        menu.addSeparator()
        toggle('显示快捷键', self.help_button)

    # -- state -----------------------------------------------------------
    def reset(self):
        self.suggestions.reset()
        self.reference_button.setChecked(False)
        self.reference.hide()
        self.error_host.hide()
        self.error_toggle.setChecked(False)
        self.error_label.clear()
        self.error_detail.clear()
        self.reload_current_button.hide()

    def set_error(self, summary, detail):
        self.error_label.setText(summary)
        self.error_label.show()
        self.error_detail.setText(detail)
        self.error_toggle.setChecked(False)
        self.error_host.show()
        self.updateGeometry()
        if hasattr(self.window(), 'schedule_fit'): self.window().schedule_fit()

    def _toggle_hint(self, shown):
        self.hint.setVisible(bool(shown))
        self.updateGeometry()
        owner = self.window()
        if hasattr(owner, 'schedule_fit'):
            owner.schedule_fit()

    def _paint_marks(self, *_args):
        """Amber marks under suspect words; playhead mode tints both halves."""
        from PySide6.QtGui import QTextCharFormat, QTextCursor
        selections = []
        document = self.editor.document()
        limit = document.characterCount() - 1
        def mark(start, stop, color):
            if stop <= start:
                return
            selection = QTextEdit.ExtraSelection()
            cursor = QTextCursor(document)
            cursor.setPosition(max(0, min(start, limit)))
            cursor.setPosition(max(0, min(stop, limit)), QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(color))
            selection.format = fmt
            selections.append(selection)
        if self.split_playhead.isChecked():
            caret = self.editor.textCursor().position()
            mark(0, caret, QColor(232, 122, 92, 70))
            mark(caret, limit, QColor(95, 179, 194, 80))
        if self.suggestions.has_rows():
            from .caption_editor import qt_position
            text = self.editor.toPlainText()
            current = self.suggestions.current_row()
            for row in self.suggestions.pending_rows():
                try:
                    start, stop = qt_position(text, row.start), qt_position(text, row.end)
                except Exception:
                    continue
                chosen = current is not None and current.status == 'pending' and current.row is row
                mark(start, stop, AMBER if chosen else AMBER_SOFT)
        if selections or self.editor.extraSelections():
            self.editor.setExtraSelections(selections)

    def _paint_cut_halves(self, *_args):
        self._paint_marks()

    def update_cut_status(self, playhead_ms, start_ms, end_ms):
        """Show where the audio cut would land (playhead mode only)."""
        if not self.split_playhead.isChecked() or start_ms is None:
            if not self.cut_status.isHidden():
                self.cut_status.hide()
            return
        from .studio_helpers import _format_ms
        inside = start_ms + 50 <= playhead_ms <= end_ms - 50
        text = (f'声音切点 {_format_ms(playhead_ms)}' if inside else '播放头不在本条内')
        if self.cut_status.text() != text:
            self.cut_status.setText(text)
        if self.cut_status.property('outside') != (not inside):
            self.cut_status.setProperty('outside', not inside)
            self.cut_status.style().unpolish(self.cut_status)
            self.cut_status.style().polish(self.cut_status)
        if self.cut_status.isHidden():
            self.cut_status.show()

    def update_hint(self):
        self.split_mode.setToolTip('C 切割模式：' + ('开，按 C 在光标处切割' if self.split_mode.isChecked() else '关，c 正常输入'))
        candidate_mode = self.suggestions.owns_focus()
        if candidate_mode:
            text = "Shift+A/D 候选↔正文 · Shift+W 上一行 · 空格采纳 · Shift+C 切割 · Shift+Enter 换行"
        else:
            text = "Shift+A/D 光标 · Shift+C 切割 · Shift+Enter 换行"
            if self.suggestions.has_rows():
                text = "Shift+A/D 候选↔正文 · Shift+W 候选 · Shift+C 切割 · Shift+Enter 换行"
        if self.split_mode.isChecked():
            text += ' · C 切割（输入法选字时暂停）'
        navigation = self.property('navigationKey')
        if navigation:
            text += f' · {navigation} 字幕起点／终点'
        text += ' · Enter/Shift+R 保存并关闭'
        self.hint.setText(text)
        self.ignore_button.setEnabled(self.suggestions.selected[0] >= 0)
        self.updateGeometry()
        owner = self.window()
        if hasattr(owner, 'schedule_fit'): owner.schedule_fit()

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self.editor and event.type() == QEvent.Type.FocusIn:
            self.update_hint()
        if watched is self.split_status and event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.updateGeometry()
        return super().eventFilter(watched, event)

    def resize_editor(self, available_width=None):
        # Bound this small field using font metrics, without forcing full
        # document layout on each key or recursively resizing from show events.
        import math
        metrics = self.editor.fontMetrics()
        width = max(80, (self.editor.viewport().width() if available_width is None else available_width) - 8)
        lines = 0
        for text in self.editor.toPlainText().split('\n'):
            lines += max(1, math.ceil(metrics.horizontalAdvance(text[:512]) / width))
            if lines >= 4:
                break
        target = max(36, min(124, metrics.lineSpacing() * min(4, max(1, lines)) + 6))
        if self.editor.height() != target:
            self.editor.setFixedHeight(target)
            self.updateGeometry()
        self.split_status.setVisible(bool(self.split_status.text()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._queue_place()
        if (not hasattr(self, 'editor') or event.size().width() == event.oldSize().width()
                or self._resize_queued):
            return
        self._resize_queued = True
        def resized():
            self._resize_queued = False
            self.resize_editor()
        QTimer.singleShot(0, self, resized)

    def refresh_theme_palette(self, theme=None):
        # ThemeRootFilter invokes this callback without arguments when a
        # previously hidden panel is shown after an application theme change.
        from ..design.ui_theme import theme_definition
        if theme is None:
            from ..design.theme_manager import theme_key
            theme = theme_definition(theme_key())
        accent, on_accent = theme.accent, theme.text_on_accent
        self._accent, self._on_accent = accent, on_accent
        radius = 14
        self.setStyleSheet(
            emphasis_qss("QFrame#subtitleEditCard{background:transparent;border:0;}"
            f"QFrame#captionCardFace{{background:{CREAM};border:0;border-top-left-radius:{radius}px;border-top-right-radius:{radius}px;}}"
            f"QFrame#captionCardFace[stripAbove=\"true\"]{{border-radius:0;border-bottom-left-radius:{radius}px;border-bottom-right-radius:{radius}px;}}"
            f"QFrame#captionCardStrip{{background:{CREAM};border:0;border-top:2px dashed {PERFORATION};border-bottom-left-radius:{radius}px;border-bottom-right-radius:{radius}px;}}"
            f"QFrame#captionCardStrip[stripAbove=\"true\"]{{border-top:0;border-bottom:2px dashed {PERFORATION};border-radius:0;border-top-left-radius:{radius}px;border-top-right-radius:{radius}px;}}"
            f"QLabel#captionCardTag{{background:{accent};color:{on_accent};border-radius:11px;padding:0 10px;min-height:22px;max-height:22px;font-size:11px;font-weight:700;}}"
            f"QPushButton#captionClose{{background:transparent;color:{MUTED};border:0;border-radius:11px;font-size:15px;padding:0;}}"
            f"QPushButton#captionClose:hover{{background:{CHIP};color:{INK};}}"
            f"QPlainTextEdit#subtitleEditCardInput{{background:transparent;color:{INK};border:0;padding:0;font-size:{self.TEXT_PX}px;font-weight:700;selection-background-color:{accent};selection-color:{on_accent};}}"
            f"QLabel#captionEditorMeta,QLabel#subtitleEditCardHint{{color:{MUTED};font-size:11px;}}"
            f"QLabel#captionPartLabel{{color:{INK};font-size:12px;font-weight:600;padding:0 2px;}}"
            f"QFrame#captionStripDivider{{background:{PERFORATION};border-radius:1px;}}"
            f"QPushButton#captionStrip{{background:{CHIP};border:0;border-radius:9px;}}"
            f"QPushButton#captionStrip:hover{{background:{CHIP_HOVER};}}"
            f"QPushButton#captionStrip:disabled{{background:rgba(245,229,208,0.45);}}"
            f"QPushButton#captionStripPrimary{{background:{accent};border:0;border-radius:9px;}}"
            f"QPushButton#captionStripPrimary:hover{{background:{theme.accent_hover};}}"
            f"QPushButton#captionStrip QLabel#captionStripText{{color:{INK};font-size:12px;font-weight:600;background:transparent;}}"
            f"QPushButton#captionStrip QLabel#captionStripKey{{color:{KEY};background:{CREAM};border-radius:5px;padding:0 5px;min-height:18px;max-height:18px;font-size:11px;font-weight:600;}}"
            f"QPushButton#captionStripPrimary QLabel#captionStripText{{color:{on_accent};font-size:12px;font-weight:700;background:transparent;}}"
            f"QPushButton#captionStripPrimary QLabel#captionStripKey{{color:{on_accent};background:rgba(255,255,255,0.22);border-radius:5px;padding:0 5px;min-height:18px;max-height:18px;font-size:11px;font-weight:700;}}"
            f"QLabel#captionCutStatus{{background:{accent};color:{on_accent};padding:2px 9px;border-radius:9px;font-size:11px;font-weight:600;}}"
            f"QLabel#captionCutStatus[outside=\"true\"]{{background:{CHIP};color:#B4432A;}}"
            f"QPushButton#captionQuiet{{background:{CHIP};color:{INK};border:0;border-radius:9px;padding:3px 10px;font-size:11px;min-height:20px;}}"
            f"QPushButton#captionQuiet:hover{{background:{CHIP_HOVER};}}"
            f"QToolButton{{color:{MUTED};background:transparent;border:0;font-size:11px;}}"
            "QScrollArea#captionSuggestionScroll,QWidget#captionSuggestionsBody{background:transparent;border:0;}"
            "QFrame#captionSuggestionRow{background:transparent;border:0;}"
            f"QPushButton#captionCandidateButton{{background:transparent;color:{INK};border:0;border-radius:13px;min-width:38px;min-height:38px;padding:0 9px;font-size:19px;font-weight:700;}}"
            f"QPushButton#captionCandidateButton:hover{{background:{CHIP};}}"
            f"QPushButton#captionCandidateButton:checked,QPushButton#captionCandidateButton:focus{{background:{AMBER};border-bottom:3px solid {AMBER_EDGE};}}"
            f"QLabel#captionSuggestionHandled{{color:{MUTED};font-size:12px;padding:0 10px;min-height:38px;}}"
            f"QLabel#captionEditorReference{{color:{MUTED};background:{CHIP};padding:4px 8px;font-size:12px;border-radius:8px;}}"
            "QLabel#captionEditorError{color:#B4432A;font-size:12px;font-weight:600;}"
            f"QMenu#captionMoreMenu{{background:{CREAM};color:{INK};border:1px solid {PERFORATION};border-radius:10px;padding:5px;}}"
            f"QMenu#captionMoreMenu::item{{padding:6px 16px 6px 10px;border-radius:7px;font-size:12px;}}"
            f"QMenu#captionMoreMenu::item:selected{{background:{CHIP};}}"
            f"QMenu#captionMoreMenu::separator{{height:1px;background:{PERFORATION};margin:4px 6px;}}")
        )
        for button in (self.split_button, self.more_button, self.split_previous, self.split_next,
                       self.split_undo, self.split_redo):
            button.paint_icon(INK)
        veil = QColor(on_accent)
        veil.setAlpha(56)
        self.confirm_button.key_label.set_colors(veil, QColor(on_accent))
        palette = self.editor.palette()
        from PySide6.QtGui import QPalette
        palette.setColor(QPalette.ColorRole.Text, QColor(INK))
        palette.setColor(QPalette.ColorRole.Base, QColor(CREAM))
        self.editor.setPalette(palette)
        self.editor.setCursorWidth(2)
