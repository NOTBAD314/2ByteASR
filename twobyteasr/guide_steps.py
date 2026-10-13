"""Picture steps: ① ② ③ cards with a drawn icon, a few words and one button (2026-10-14).

For flows a new user should be able to finish without reading: each step is
an icon, a short title and, when it helps, a button that does the step
(open the official page, focus the field, run the check). ``set_done``
ticks a step off. The API setup dialog fills it per provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .i18n import bind_text, tr

ICONS = ('account', 'globe', 'key', 'paste', 'check', 'download', 'folder', 'chat')


@dataclass(frozen=True)
class GuideStep:
    title: str
    icon: str = 'check'
    action_label: str = ''
    url: str = ''
    callback: Callable[[], None] | None = None


class StepIcon(QWidget):
    """A simple line icon in the accent colour (no image files, every theme)."""

    def __init__(self, kind: str, color: str, parent=None):
        super().__init__(parent)
        self.kind, self.color, self.done = kind, color, False
        self.setFixedSize(52, 52)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.color)
        soft = QColor(color)
        soft.setAlphaF(0.16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color if self.done else soft)   # a finished step is a filled badge
        painter.drawEllipse(QRectF(2, 2, 48, 48))
        if self.done:
            color = QColor('#ffffff')
        pen = QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        c = QPointF(26, 26)
        kind = 'check' if self.done else self.kind
        if kind == 'account':
            painter.drawEllipse(QPointF(26, 20), 6, 6)
            painter.drawArc(QRectF(15, 27, 22, 18), 0, 180 * 16)
        elif kind == 'globe':
            painter.drawEllipse(c, 12, 12)
            painter.drawEllipse(c, 5, 12)
            painter.drawLine(QPointF(14, 26), QPointF(38, 26))
        elif kind == 'key':
            painter.drawEllipse(QPointF(19, 26), 6, 6)
            painter.drawLine(QPointF(25, 26), QPointF(38, 26))
            painter.drawLine(QPointF(34, 26), QPointF(34, 31))
            painter.drawLine(QPointF(38, 26), QPointF(38, 30))
        elif kind == 'paste':
            painter.drawRoundedRect(QRectF(16, 15, 20, 24), 3, 3)
            painter.drawRoundedRect(QRectF(21, 12, 10, 6), 2, 2)
            for y in (25, 30):
                painter.drawLine(QPointF(21, y), QPointF(31, y))
        elif kind == 'download':
            painter.drawLine(QPointF(26, 14), QPointF(26, 32))
            painter.drawLine(QPointF(20, 26), QPointF(26, 32))
            painter.drawLine(QPointF(32, 26), QPointF(26, 32))
            painter.drawLine(QPointF(16, 37), QPointF(36, 37))
        elif kind == 'folder':
            path = QPainterPath(QPointF(14, 18))
            for x, y in ((22, 18), (25, 21), (38, 21), (38, 36), (14, 36), (14, 18)):
                path.lineTo(x, y)
            painter.drawPath(path)
        elif kind == 'chat':
            painter.drawRoundedRect(QRectF(14, 15, 24, 17), 6, 6)
            painter.drawLine(QPointF(20, 32), QPointF(18, 38))
            painter.drawLine(QPointF(18, 38), QPointF(25, 32))
        else:  # check
            painter.drawLine(QPointF(18, 26), QPointF(24, 32))
            painter.drawLine(QPointF(24, 32), QPointF(35, 19))
        painter.end()


class StepCards(QFrame):
    """A row of picture steps; the first unfinished one is highlighted."""

    def __init__(self, steps: list[GuideStep], accent: str | None = None, parent=None):
        super().__init__(parent)
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        theme = theme_definition(theme_key())
        self.accent = accent or theme.accent
        self.setObjectName('stepCards')
        self.setStyleSheet(
            f"QFrame#stepCard {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 14px; }}"
            f"QFrame#stepCard[current=\"true\"] {{ border: 2px solid {self.accent}; }}"
            f"QLabel#stepNumber {{ color: {self.accent}; font-weight: 800; font-size: 13px; }}"
            f"QLabel#stepTitle {{ color: {theme.text}; font-size: 14px; font-weight: 600; }}"
            f"QLabel#stepArrow {{ color: {theme.text_muted}; font-size: 18px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.cards, self.icons, self.buttons = [], [], []
        for index, step in enumerate(steps):
            if index:
                arrow = QLabel('›')
                arrow.setObjectName('stepArrow')
                row.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)
            card = QFrame()
            card.setObjectName('stepCard')
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            body = QVBoxLayout(card)
            body.setContentsMargins(12, 12, 12, 12)
            body.setSpacing(6)
            top = QHBoxLayout()
            icon = StepIcon(step.icon, self.accent, card)
            top.addWidget(icon)
            number = QLabel(f'{index + 1}')
            number.setObjectName('stepNumber')
            top.addWidget(number, 0, Qt.AlignmentFlag.AlignTop)
            top.addStretch(1)
            body.addLayout(top)
            title = QLabel()
            bind_text(title, step.title)
            title.setObjectName('stepTitle')
            title.setWordWrap(True)
            body.addWidget(title)
            button = None
            if step.action_label:
                from .design.presentation import button_role
                button = button_role(QPushButton(), 'secondary', size='compact')
                bind_text(button, step.action_label)
                button.setObjectName(f'stepAction_{index}')
                if step.url:
                    button.setToolTip(step.url)
                    button.clicked.connect(lambda _=False, url=step.url: QDesktopServices.openUrl(QUrl(url)))
                elif step.callback is not None:
                    button.clicked.connect(lambda _=False, callback=step.callback: callback())
                body.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            body.addStretch(1)
            row.addWidget(card, 1)
            self.cards.append(card)
            self.icons.append(icon)
            self.buttons.append(button)
        self._done = [False] * len(self.cards)
        self._refresh()

    def set_done(self, index: int, done: bool = True) -> None:
        if 0 <= index < len(self._done):
            self._done[index] = bool(done)
            self._refresh()

    def _refresh(self) -> None:
        current = next((i for i, done in enumerate(self._done) if not done), -1)
        for index, (card, icon) in enumerate(zip(self.cards, self.icons)):
            card.setProperty('current', index == current)
            icon.done = self._done[index]
            icon.update()
            card.style().unpolish(card)
            card.style().polish(card)


def api_key_steps(console_url: str, key_url: str, *, focus_key=None, run_check=None,
                  signup_title: str = '注册并登录') -> list[GuideStep]:
    """The usual four steps of getting a cloud API key."""
    return [
        GuideStep(signup_title, 'account', '打开网页', console_url),
        GuideStep('创建 API Key', 'key', '打开网页', key_url),
        GuideStep('复制，贴到下面', 'paste', '去填写' if focus_key else '', callback=focus_key),
        GuideStep('检查并保存', 'check', '免费检查' if run_check else '', callback=run_check),
    ]
