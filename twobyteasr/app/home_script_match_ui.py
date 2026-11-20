# SPDX-License-Identifier: GPL-3.0-only
"""Parts of the 「匹配文稿」 wizard (2026-11-12, design C).

Step badges (todo / current / done), the line between them and the drop
zone of the first step. Colours come from the active theme at paint time.

2026-11-18 (user: Studio's 匹配文稿 was a plain Windows dialog that did not
match the theme): the rounded window, the stepper, the bunny's tip and the
script editor live here, so the home page and Studio build the same wizard.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizeGrip,
                               QSizePolicy, QVBoxLayout, QWidget)
from ..design.typography import weighted_font
from ..i18n import tr


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _px(value: float) -> int:
    from .ui_zoom import px
    return px(value)


class StepBadge(QWidget):
    """A numbered circle; ``current`` wears a soft ring, ``done`` a check mark."""

    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self.number = number
        self.state = 'todo'
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_state(self, state: str):
        if state != self.state:
            self.state = state
            self.update()

    def sizeHint(self):
        return QSize(_px(36), _px(36))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = _px(26)
        circle = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.state == 'current':
            painter.setBrush(QColor(t.accent_soft))
            painter.drawEllipse(circle.adjusted(-_px(5), -_px(5), _px(5), _px(5)))
            fill, ink = t.accent, '#ffffff'
        elif self.state == 'done':
            fill, ink = t.success, '#ffffff'
        else:
            fill, ink = t.border, t.text_muted
        painter.setBrush(QColor(fill))
        painter.drawEllipse(circle)
        if self.state == 'done':
            pen = QPen(QColor(ink), max(2.0, _px(2.6)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            c = circle.center()
            u = side / 26
            path = QPainterPath(QPointF(c.x() - 5.5 * u, c.y() + 0.5 * u))
            path.lineTo(QPointF(c.x() - 1.5 * u, c.y() + 4.5 * u))
            path.lineTo(QPointF(c.x() + 6 * u, c.y() - 4 * u))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        else:
            font = self.font()
            font.setPixelSize(_px(13))
            weighted_font(font, 700)
            painter.setFont(font)
            painter.setPen(QColor(ink))
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(self.number))
        painter.end()


class StepLine(QWidget):
    """The rounded bar between two steps; green once the step before is done."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(_px(24))

    def set_done(self, done: bool):
        if bool(done) != self.done:
            self.done = bool(done)
            self.update()

    def sizeHint(self):
        return QSize(_px(60), _px(36))

    def paintEvent(self, event):
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.success if self.done else t.border))
        h = max(2, _px(3))
        painter.drawRoundedRect(QRectF(0, (self.height() - h) / 2, self.width(), h), h / 2, h / 2)
        painter.end()


class DropZone(QFrame):
    """Accepts one dropped audio or video file and hands its path to ``on_media``."""

    def __init__(self, on_media, parent=None):
        super().__init__(parent)
        self.on_media = on_media
        self.setObjectName('scriptDropZone')
        self.setAcceptDrops(True)

    @staticmethod
    def _media_path(event):
        from .main_ui_helpers import SUPPORTED_MEDIA_SUFFIXES
        mime = event.mimeData()
        if not mime.hasUrls():
            return ''
        for url in mime.urls():
            path = Path(url.toLocalFile())
            if url.isLocalFile() and path.suffix.lower() in SUPPORTED_MEDIA_SUFFIXES:
                return str(path)
        return ''

    def _mark(self, dragging: bool):
        self.setProperty('dragging', 'true' if dragging else 'false')
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if self.isEnabled() and self._media_path(event):
            self._mark(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._mark(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._mark(False)
        path = self._media_path(event)
        if path:
            event.acceptProposedAction()
            self.on_media(path)


def repolish(widget, name: str, value) -> None:
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class WizardDialog(QDialog):
    """The rounded wizard window (no Windows title bar): a title, × and ``body``.

    ×, Esc and 取消 wait while ``busy()`` is true. Call ``finish()`` once the
    content is built: it themes the controls and makes the window rounded.
    """

    def __init__(self, parent, *, object_name: str, title: str, busy=None,
                 minimum=(560, 520), size=(700, 640)):
        super().__init__(parent)
        from .rounded_window import SHADOW
        self.busy = busy or (lambda: False)
        self.setObjectName(object_name)
        self.setWindowTitle(title)
        self.setMinimumSize(minimum[0] + 2 * SHADOW, minimum[1] + 2 * SHADOW)
        self.resize(size[0] + 2 * SHADOW, size[1] + 2 * SHADOW)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.root = QWidget()
        self.root.setObjectName('scriptWizardRoot')
        self.root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self.root)
        self.body = QVBoxLayout(self.root)
        self.body.setContentsMargins(26, 16, 22, 20)
        self.body.setSpacing(12)
        self.header = QFrame()
        self.header.setObjectName('scriptWizardHeader')
        top = QHBoxLayout(self.header)
        top.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName('scriptWizardTitle')
        self.close_button = QPushButton('×')
        self.close_button.setObjectName('scriptWizardClose')
        self.close_button.setToolTip(tr('关闭'))
        self.close_button.setAccessibleName(tr('关闭'))
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.reject)
        top.addWidget(self.title_label)
        top.addStretch(1)
        top.addWidget(self.close_button)
        self.body.addWidget(self.header)

    def reject(self):
        if not self.busy():
            super().reject()

    def finish(self):
        from ..design.studio_theme import apply_secondary_surface_theme
        from .rounded_window import RoundedWindow
        apply_secondary_surface_theme(self)
        self.chrome = RoundedWindow(self, self.root, title_areas=[self.header], radius=26, maximizable=False)
        for grip in self.findChildren(QSizeGrip):
            grip.setMaximumSize(0, 0)


def build_stepper(names, details=None):
    """①──②──③: the row layout, its badges, captions and lines.
    ``details`` maps a step number to a small widget under its caption."""
    details = details or {}
    stepper = QHBoxLayout()
    stepper.setSpacing(8)
    badges, captions, lines = [], [], []
    for number, name in enumerate(names, 1):
        badge = StepBadge(number)
        caption = QLabel(tr(name))
        caption.setObjectName('scriptStepName')
        words = QVBoxLayout()
        words.setSpacing(0)
        words.addStretch(1)
        words.addWidget(caption)
        if number in details:
            words.addWidget(details[number])
        words.addStretch(1)
        stepper.addWidget(badge)
        stepper.addLayout(words)
        badges.append(badge)
        captions.append(caption)
        if number < len(names):
            line = StepLine()
            lines.append(line)
            stepper.addWidget(line, 1)
    return stepper, badges, captions, lines


def show_step_states(badges, captions, lines, states) -> None:
    for badge, caption, value in zip(badges, captions, states):
        badge.set_state(value)
        repolish(caption, 'stepState', value)
    for line, value in zip(lines, states):
        line.set_done(value == 'done')


def bunny_tip(text: str):
    """The bunny with a speech bubble (rich text); returns (row layout, bubble)."""
    from .settings_widgets import Bunny
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(Bunny(54), 0, Qt.AlignmentFlag.AlignBottom)
    bubble = QLabel(text)
    bubble.setObjectName('scriptWizardTip')
    bubble.setWordWrap(True)
    bubble.setTextFormat(Qt.TextFormat.RichText)
    row.addWidget(bubble, 1, Qt.AlignmentFlag.AlignBottom)
    return row, bubble


class ScriptEditor(QFrame):
    """The rounded script box: the text, its line count, 从文件读取… and 粘贴.

    ``load`` is left for the caller (each wizard reports a bad file its own
    way); 粘贴 pastes into ``input``. The frame's border follows the focus.
    """

    def __init__(self, input_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName('scriptEditorFrame')
        lines = QVBoxLayout(self)
        lines.setContentsMargins(8, 6, 10, 10)
        lines.setSpacing(4)
        self.input = QPlainTextEdit()
        self.input.setObjectName(input_name)
        self.input.setPlaceholderText(tr('每行一条字幕，例如：\n大家好，欢迎回来\n今天我们继续打洛克王国'))
        lines.addWidget(self.input, 1)
        self.tools = QHBoxLayout()
        self.tools.setSpacing(8)
        self.line_count = QLabel()
        self.line_count.setObjectName('scriptLineCount')
        self.load = QPushButton(tr('从文件读取…'))
        self.load.setObjectName('scriptEditorTool')
        self.paste = QPushButton(tr('粘贴'))
        self.paste.setObjectName('scriptEditorTool')
        for button in (self.load, self.paste):
            button.setAutoDefault(False)
        self.tools.addSpacing(6)
        self.tools.addWidget(self.line_count)
        self.tools.addStretch(1)
        self.tools.addWidget(self.load)
        self.tools.addWidget(self.paste)
        lines.addLayout(self.tools)
        self.paste.clicked.connect(self.input.paste)
        self.input.textChanged.connect(self.count_lines)
        self.input.installEventFilter(self)
        self.count_lines()

    def count_lines(self) -> int:
        from ..recognition.script_match import parse_script
        count = len(parse_script(self.input.toPlainText()))
        self.line_count.setText(tr('{count} 行 → {count} 条字幕', count=count) if count else tr('还没有文稿'))
        return count

    def eventFilter(self, watched, event):
        if watched is self.input and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            repolish(self, 'focused', 'true' if event.type() == QEvent.Type.FocusIn else 'false')
        return False


__all__ = ['DropZone', 'ScriptEditor', 'StepBadge', 'StepLine', 'WizardDialog', 'build_stepper', 'bunny_tip',
           'repolish', 'show_step_states']
