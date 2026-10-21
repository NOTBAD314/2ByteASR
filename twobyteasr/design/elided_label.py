"""Single-line label that elides instead of clipping or widening its parent."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QLabel


class ElidedLabel(QLabel):
    """``text()`` keeps the full string; the painted text is elided to fit.

    The full text doubles as the tooltip, so long project or file names stay
    readable on hover without pushing toolbar or form widths.
    """

    def __init__(self, text: str = "", parent=None, *,
                 mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle, minimum: int = 80):
        super().__init__(parent)
        self._full_text = ""
        self._mode = mode
        self._minimum = int(minimum)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setText(text)

    def text(self) -> str:  # noqa: D401 - Qt override
        return self._full_text

    def setText(self, text) -> None:  # noqa: N802 - Qt override
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._elide()
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        margins = self.contentsMargins()
        width = self.fontMetrics().horizontalAdvance(self._full_text) + margins.left() + margins.right() + 4
        return QSize(width, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(min(self.sizeHint().width(), self._minimum), super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(self._full_text, self._mode, max(20, self.contentsRect().width()))
        if shown != super().text():
            super().setText(shown)
