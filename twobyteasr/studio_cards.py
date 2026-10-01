"""Small studio card/editor widgets shared by the AI panel, review flow,
and canvas inline editing."""

from __future__ import annotations

import difflib
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
)

from .studio_qc import QCCandidate

class AIDesignVariantCard(QFrame):
    """Clickable AI design card: clicking anywhere on the card selects it."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiDesignVariant")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ReviewCandidateCard(QFrame):
    """Distinct selectable card for a review candidate.

    Shows:
    - Large keyboard number badge
    - Source badges (secondary)
    - Full readable candidate text
    - Click to adopt
    Visual states: hover ring, selected green border.
    """
    clicked = Signal(int)

    def __init__(
        self,
        index: int,
        candidate: "QCCandidate",
        is_current: bool = False,
        current_text: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._index = index
        self._candidate = candidate
        self._current_text = current_text
        self._is_current = is_current
        self._selected = bool(is_current)
        self.setObjectName("reviewCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(86)
        self.setMaximumHeight(124)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(9)

        # Number badge
        num = QLabel(str(index + 1))
        num.setObjectName("reviewCardNum")
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setFixedSize(30, 30)
        lay.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)

        # Body
        body = QVBoxLayout()
        body.setSpacing(5)

        # Source row (badges)
        src_row = QHBoxLayout()
        src_row.setSpacing(4)
        for src in (candidate.sources or ("?",)):
            label = "当前" if str(src) == "Current" else str(src)
            badge = QLabel(label)
            badge.setObjectName("reviewSourceBadge")
            badge.setProperty("current", label == "当前")
            src_row.addWidget(badge, 0)
        src_row.addStretch(1)
        body.addLayout(src_row)

        # Text (readable size, not crushed)
        self.text_label = QLabel(self._diff_markup(candidate.text or "", current_text))
        self.text_label.setTextFormat(Qt.TextFormat.RichText)
        self.text_label.setWordWrap(True)
        self.text_label.setMinimumHeight(34)
        self.text_label.setMaximumHeight(62)
        self.text_label.setObjectName("reviewCandidateText")
        body.addWidget(self.text_label)

        lay.addLayout(body, 1)

        # Click anywhere adopts
        self.set_selected(self._selected)

    @staticmethod
    def _diff_markup(candidate: str, current: str) -> str:
        if not current or candidate == current:
            return html.escape(candidate).replace("\n", "<br>")
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        theme = theme_definition(theme_key())
        chunks: list[str] = []
        matcher = difflib.SequenceMatcher(None, current, candidate, autojunk=False)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            text = html.escape(candidate[j1:j2]).replace("\n", "<br>")
            if tag == "equal":
                chunks.append(text)
            elif text:
                chunks.append(f"<span style='background:{theme.warning_soft}; color:{theme.warning}; border-radius:3px; padding:1px 2px;'>{text}</span>")
        return "".join(chunks)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._index)
            event.accept()
            return
        super().mousePressEvent(event)

    def set_selected(self, on: bool):
        self._selected = bool(on)
        self.setProperty("selected", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def refresh_theme_palette(self):
        self.text_label.setText(self._diff_markup(self._candidate.text or "", self._current_text))



class _SubtitleEditCardEditor(QPlainTextEdit):
    """IME-safe editor hosted in the Qt layout, never over mpv's HWND."""

    commit_requested = Signal(bool)
    cancel_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.commit_requested.emit(bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _CanvasInlineEdit(QPlainTextEdit):
    """Visible Studio canvas editor with explicit IME diagnostics."""

    input_method_received = Signal(str, str, str)
    diagnostic = Signal(str, object)

    def inputMethodEvent(self, event) -> None:
        preedit = str(event.preeditString())
        commit = str(event.commitString())
        super().inputMethodEvent(event)
        self.input_method_received.emit(preedit, commit, self.toPlainText())
