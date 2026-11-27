"""The little speech bubble over 兔白's head while her chat card is tucked away (2026-11-26).

User (2026-11-26): picked up, 兔白's dialog box should fold away by default so people can
play with her and throw her about; a small speech bubble stays over her head, and one more
click on it brings the dialog box back. It lives on the puck's clear layer (``_Carrier``), so
the layer's click mask includes it.

It shows three dots; a short line of hers (a touch reaction) for a moment; and a small dot when
something longer arrived that waits in the card.

2026-11-27 (user: while idle she talks, but the bubble shows only "…" and has to be clicked):
what she says now shows in the bubble itself, wrapped over a few lines, for as long as it takes to
read; only an answer to the user (or a very long line) also leaves the dot for the card.

2026-11-26 (user, later): when the card was folded by its own button (or the software opened with
only her), the bubble has no idle dots: it comes up only for a short line or with the dot of
something waiting, and goes away again after (``dots_when_idle``).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..i18n import tr

SHORT_LINE = 12          # (kept for callers) a line this short always fits on one row
LINE_MS = 2600           # the shortest time a line stays
READ_MS_PER_CHAR = 130   # and this much longer per character, up to READ_MAX_MS
READ_MAX_MS = 9000
SHOWN_CHARS = 64         # longer than this: cut with "…", the whole of it waits in the card
MAX_W = 236              # px: wider lines wrap
PAD_X = 11
PAD_Y = 6
TAIL = 7                 # px of the tail below the bubble
HEIGHT = 28


WRAP = int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)


def reading_ms(text: str) -> int:
    return int(min(READ_MAX_MS, max(LINE_MS, 1200 + READ_MS_PER_CHAR * len(text))))


class HeadBubble(QWidget):
    clicked = Signal()

    def __init__(self, parent, theme, family: str = ''):
        super().__init__(parent)
        self.setObjectName('bunnyHeadBubble')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(tr('点一下打开对话框')))
        self.setAccessibleName(str(tr('打开兔白的对话框')))
        self.theme = theme
        self.family = family
        self.text = ''
        self.unread = False
        self.hover = False
        self.dots_when_idle = True          # False: hidden while it has nothing to say
        self._line = QTimer(self)
        self._line.setSingleShot(True)
        self._line.timeout.connect(lambda: self.show_line(''))
        self.hide()

    # ------------------------------------------------------------ what it says
    def _font(self) -> QFont:
        font = QFont(self.font())
        if self.family:
            font.setFamily(self.family)
        font.setPixelSize(13)
        return font

    def _text_box(self) -> QSize:
        """The size the text takes: one row when it fits, else wrapped at MAX_W."""
        # Measured by a painter, the way it is drawn: her font (猫啃) leaves many characters to a
        # fallback font with taller rows, which QFontMetrics alone does not count.
        from PySide6.QtGui import QImage
        cached = getattr(self, '_measured', None)
        key = (self.text, self.family, self.devicePixelRatioF())
        if cached is not None and cached[0] == key:
            return cached[1]
        self._wrap_w = MAX_W - 2 * PAD_X
        image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.devicePixelRatioF())
        painter = QPainter(image)
        painter.setFont(self._font())
        single = painter.boundingRect(QRect(0, 0, 4000, 400), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                                      self.text)
        if single.width() + 2 * PAD_X <= MAX_W:
            size = QSize(single.width() + 1, single.height())
        else:
            widest = MAX_W - 2 * PAD_X
            box = painter.boundingRect(QRect(0, 0, widest, 4000), WRAP, self.text)
            # Balanced rows: the narrowest width that needs no more rows (no lone "～" on the last one).
            low, high = widest // 2, widest
            while high - low > 3:
                middle = (low + high) // 2
                if painter.boundingRect(QRect(0, 0, middle, 4000), WRAP, self.text).height() > box.height():
                    low = middle
                else:
                    high = middle
            self._wrap_w = high
            box = painter.boundingRect(QRect(0, 0, high, 4000), WRAP, self.text)
            size = QSize(min(high, box.width() + 1), box.height())
        painter.end()
        self._measured = (key, size, self._wrap_w)
        return size

    def _body_height(self) -> int:
        if not self.text:
            return HEIGHT
        return max(HEIGHT, self._text_box().height() + 2 * PAD_Y)

    def sizeHint(self):  # noqa: N802 - Qt override
        if self.text:
            width = self._text_box().width() + 2 * PAD_X
        else:
            width = 40
        return QSize(max(40, width), self._body_height() + TAIL)

    def show_line(self, text: str, ms: int | None = None):
        """A line of hers for as long as it takes to read; '' goes back to the dots."""
        if len(text) > SHOWN_CHARS:
            text = text[:SHOWN_CHARS - 1].rstrip() + '…'
        self.text = text
        self._line.stop()
        if text:
            self._line.start(ms if ms is not None else reading_ms(text))
            self.show()
        elif not self.dots_when_idle and not self.unread:
            self.hide()
        self.resize(self.sizeHint())
        self.update()
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, 'bubble_changed'):
            parent.bubble_changed()

    def note(self, lines, answer: bool):
        """She said ``lines`` while the card is away."""
        from .tour_mascot import plain
        said = [plain(line).strip() for line in lines if line]
        said = [line for line in said if line]
        if not said:
            return
        text = ' '.join(said)
        if answer or len(text) > SHOWN_CHARS:
            self.unread = True                 # the whole of it (an answer to them) waits in the card
        self.show_line(text)

    def reset(self):
        self.unread = False
        self.show_line('')

    # ------------------------------------------------------------ the pointer
    def enterEvent(self, event):  # noqa: N802 - Qt override
        self.hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        self.hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        event.accept()

    # ------------------------------------------------------------ painting
    def paintEvent(self, _event):  # noqa: N802 - Qt override
        t = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(1.5, 1.5, self.width() - 3, self._body_height() - 3)
        radius = min(body.height() / 2, (HEIGHT - 3) / 2)
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        tail = QPainterPath()
        x = min(body.left() + 14, body.center().x())
        tail.moveTo(x - 5, body.bottom() - 2)
        tail.lineTo(x - 4, body.bottom() + TAIL - 1)
        tail.lineTo(x + 6, body.bottom() - 2)
        tail.closeSubpath()
        path = path.united(tail)
        fill = QColor(t.surface_elevated if self.hover else t.surface)
        painter.setPen(QPen(QColor(t.accent), 2 if self.hover else 1.5))
        painter.setBrush(fill)
        painter.drawPath(path)
        ink = QColor(t.text)
        if self.text:
            painter.setPen(ink)
            painter.setFont(self._font())
            if body.height() <= HEIGHT:
                painter.drawText(body, Qt.AlignmentFlag.AlignCenter, self.text)
            else:
                # Wrapped at the very width it was measured with, so the rows break exactly as sized.
                text = self._text_box()
                top = body.top() + (body.height() - text.height()) / 2
                painter.drawText(QRectF(body.left() + PAD_X - 1.5, top, self._measured[2], text.height() + 2), WRAP,
                                 self.text)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            dots = QColor(t.accent)
            for index in (-1, 0, 1):
                painter.setBrush(dots)
                painter.drawEllipse(QPointF(body.center().x() + index * 8, body.center().y()), 2.6, 2.6)
        if self.unread:
            painter.setPen(QPen(fill, 2))
            painter.setBrush(QColor('#c4532c'))
            painter.drawEllipse(QPointF(body.right() - 3, body.top() + 4), 4.5, 4.5)
        painter.end()


__all__ = ['HeadBubble']
