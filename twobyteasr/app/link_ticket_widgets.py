"""Ticket pieces of the link download window (2026-11-25, user picked draft A 票根).

The parsed video is a ticket: the video on top, a dashed perforation with a
half-round notch at each edge, then the choices in three pale framed rows and
the download button with two bunny ears. The home page keeps the login choice
in one small dashed "ticket" chip and lists recent parses as mini tickets.
Draft: ``tmp/download-ui-drafts-20261125/``.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlparse

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..design.elided_label import ElidedLabel
from ..design.soft_qss import blend_hex, soft_tokens
from ..i18n import tr
from ..i18n_widgets import user_text
from .link_download_widgets import active_theme, icon_label, named_label

# Pale per-row hues, blended over the theme's surface so every theme keeps
# them as tints (2026-11-23 lesson: colour only as pale tints and thin lines).
ROW_HUES = {"film": "#8a55a0", "subtitles": "#3d7f9c", "place": "#7d7633", "key": "#b06a2a"}
SITE_COLORS = {"youtube": "#d8443c", "bilibili": "#3b9fd6"}


def _light(t) -> bool:
    return QColor(t.app_background).lightness() > 128


def row_tint(kind: str, t=None) -> tuple[str, str]:
    """(fill, ink) of a row's icon square."""
    t = t or active_theme()
    hue = ROW_HUES[kind]
    return blend_hex(t.surface, hue, .16 if _light(t) else .26), blend_hex(hue, t.text, .2 if _light(t) else .45)


def ticket_qss(t=None) -> str:
    t = t or active_theme()
    k = soft_tokens(t)
    rows = "\n".join(
        f"QLabel#linkRowIcon[kind=\"{kind}\"] {{ background: {row_tint(kind, t)[0]}; border-radius: 9px; }}"
        for kind in ROW_HUES)
    return f"""
QFrame#linkCard[ticket="true"] {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 18px; }}
QFrame#linkTicketRow {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 14px; }}
QLabel#linkRowTitle {{ color: {t.text}; font-size: 14px; font-weight: 700; }}
QLabel#linkPairLabel {{ color: {t.text_muted}; font-size: 13px; }}
{rows}
QPushButton#linkPass {{
    background: {t.surface_elevated}; color: {t.text_secondary}; border: 1px dashed {t.border_strong};
    border-radius: 15px; min-height: 30px; max-height: 30px; padding: 0 12px 0 10px; font-size: 13px; font-weight: 500;
}}
QPushButton#linkPass:hover {{ background: {k.chip}; color: {t.accent_text}; border-color: {t.accent}; }}
QPushButton#linkPass[active="true"] {{ background: {k.chip}; color: {t.accent_text}; border: 1px solid {t.accent}; }}
QPushButton#linkMiniTicket {{
    background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 13px;
    min-height: 52px; max-height: 52px; text-align: left; padding: 0;
}}
QPushButton#linkMiniTicket:hover {{ border-color: {t.border_strong}; background: {t.surface}; }}
QPushButton#linkMiniTicket QLabel {{ background: transparent; }}
QLabel#linkMiniTitle {{ color: {t.text}; font-size: 13px; font-weight: 500; }}
QLabel#linkMiniNote {{ color: {t.text_muted}; font-size: 11px; }}
QPushButton#linkBrowserTile {{
    background: {t.surface_elevated}; color: {t.text_secondary}; border: 1px solid {t.border}; border-radius: 14px;
    min-height: 58px; padding: 6px 8px; font-size: 13px; font-weight: 500;
}}
QPushButton#linkBrowserTile:hover {{ border-color: {t.border_strong}; }}
QPushButton#linkBrowserTile:checked {{ background: {k.chip}; color: {t.accent_text}; border-color: {t.accent}; }}
QPushButton#linkBrowserTile:disabled {{ color: {t.disabled}; background: transparent; }}
QLabel#linkStepNumber {{
    background: {k.fill}; color: {t.text_muted}; border: 1px solid {t.border}; border-radius: 14px;
    font-size: 13px; font-weight: 700;
}}
QLabel#linkStepNumber[tone="ok"] {{ background: {k.ok}; color: {t.surface_elevated}; border-color: {k.ok}; }}
QPushButton#linkStepStub {{
    background: {t.surface_elevated}; color: {t.text_muted}; border: 1px solid {t.border}; border-radius: 10px;
    min-height: 38px; max-height: 38px; padding: 0 8px; font-size: 12px; font-weight: 500; text-align: left;
}}
QPushButton#linkStepStub:hover {{ border-color: {t.border_strong}; }}
QPushButton#linkStepStub[state="now"] {{ background: {k.chip}; color: {t.accent_text}; border-color: {t.accent}; }}
QPushButton#linkStepStub[state="done"] {{ background: transparent; color: {k.ok}; border: 1px dashed {k.ok}; }}
QLabel#linkStepKicker {{ color: {t.accent_text}; font-size: 12px; font-weight: 500; }}
QFrame#linkPathRow {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 10px; }}
QLabel#linkPathText {{ color: {t.text_secondary}; font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; }}
QFrame#linkTipBox {{ background: {t.surface}; border: 1px dashed {t.border_strong}; border-radius: 14px; }}
QFrame#linkTipBox QLabel {{ background: transparent; }}
QFrame#linkTipBox[stuck="true"] {{ background: {k.warn_tint}; border: 1px solid {k.warn}; }}
QPushButton#linkBrowserTile[big="true"] {{ min-height: 96px; font-size: 14px; }}
QPushButton#linkGhost[tall="true"] {{ min-height: 42px; max-height: 42px; border-radius: 14px; padding: 0 16px; }}
QFrame#linkUpdateBar {{ background: {k.warn_tint}; border: 0; border-radius: 14px; }}
QLabel#linkUpdateText {{ color: {k.warn}; font-size: 13px; font-weight: 500; background: transparent; }}
QFrame#linkTicketRow[absent="true"] {{ background: transparent; border-style: dashed; }}
QFrame#linkCounter {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 22px; }}
QFrame#linkCounter[compact="true"] {{ background: transparent; border: 0; }}
QFrame#linkBubble {{ background: {t.surface_elevated}; border: 1px solid {t.border}; border-radius: 16px; border-bottom-left-radius: 4px; }}
QFrame#linkBubble QLabel {{ background: transparent; }}
QLabel#linkBubbleTitle {{ color: {t.text}; font-size: 18px; font-weight: 700; }}
QLabel#linkBubbleNote {{ color: {t.text_secondary}; font-size: 14px; }}
"""


class ClampLabel(QLabel):
    """Wrapped text cut to a few lines with an ellipsis; ``text()`` and the
    tooltip keep the whole string, so a very long video title stays two lines
    instead of pushing the ticket taller."""

    def __init__(self, text="", parent=None, *, lines=2):
        super().__init__(parent)
        self._full = ""
        self._lines = int(lines)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def text(self) -> str:
        return self._full

    def setText(self, text):  # noqa: N802 - Qt override
        self._full = str(text or "")
        self.setToolTip(self._full)
        self._clamp()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._clamp()

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._clamp()

    def _clamp(self):
        from PySide6.QtGui import QTextLayout
        width = max(40, self.contentsRect().width())
        layout = QTextLayout(self._full, self.font())
        layout.beginLayout()
        ends = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            ends.append(line.textStart() + line.textLength())
        layout.endLayout()
        if len(ends) <= self._lines:
            shown = self._full
        else:
            start = ends[self._lines - 2] if self._lines > 1 else 0
            tail = self.fontMetrics().elidedText(self._full[start:], Qt.TextElideMode.ElideRight, width)
            shown = self._full[:start] + tail
        if shown != super().text():
            super().setText(shown)


class RowLabel(QWidget):
    """A ticket row's name with its pale icon square."""

    def __init__(self, kind, icon, text, parent=None):
        super().__init__(parent)
        from .ui_zoom import set_size
        set_size(self, fixed_w=92)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 3, 0, 0)
        row.setSpacing(8)
        self.kind, self._icon = kind, icon
        self.square = QLabel()
        self.square.setObjectName("linkRowIcon")
        self.square.setProperty("kind", kind)
        self.square.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_size(self.square, fixed_w=26, fixed_h=26)
        row.addWidget(self.square)
        row.addWidget(named_label(text, "linkRowTitle"))
        row.addStretch(1)
        self.refresh()

    def refresh(self):
        import qtawesome
        ink = row_tint(self.kind)[1]
        size = max(10, round(self.square.width() * .52))
        self.square.setPixmap(qtawesome.icon(self._icon, color=ink).pixmap(size, size))

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.StyleChange:
            self.refresh()


class Perforation(QWidget):
    """Dashed tear line across the ticket with a half notch at each edge.

    It spans the card's full inner width, so each notch, filled with the
    window background, bites into the card's border."""

    def __init__(self, parent=None, *, vertical=False):
        super().__init__(parent)
        from .ui_zoom import set_size
        self.vertical = vertical
        if vertical:
            set_size(self, fixed_w=24)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            set_size(self, fixed_h=24)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        t = active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        across = self.width() if self.vertical else self.height()
        along = self.height() if self.vertical else self.width()
        middle = across / 2
        radius = across * .46
        pen = QPen(QColor(t.border), max(1.6, across / 12))
        pen.setDashPattern([3, 2.4])
        painter.setPen(pen)
        point = (lambda a: QPointF(middle, a)) if self.vertical else (lambda a: QPointF(a, middle))
        painter.drawLine(point(radius + 8), point(along - radius - 8))
        painter.setPen(QPen(QColor(t.border), 1))
        painter.setBrush(QColor(t.app_background))
        for end in (-1.0, along + 1.0):
            painter.drawEllipse(point(end), radius, radius)


class EarsButton(QPushButton):
    """The primary download button with two bunny ears on its top edge.

    Painted by hand: the ears stand in the space above the body and tilt a
    little apart on hover (a short fade-length tween, no bounce)."""

    EAR_ROOM = 10

    def __init__(self, text="", icon="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("linkEarsButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon:
            from ..design.themed_icons import install_themed_icon
            install_themed_icon(self, icon, "on_accent")
        self._tilt = 0.0
        from ..design.motion_tokens import NAV_GLIDE_FADE, easing_curve
        from ..design.ui_motion import motion_duration
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(motion_duration(NAV_GLIDE_FADE.ms))
        self._motion.setEasingCurve(easing_curve(NAV_GLIDE_FADE))
        self._motion.valueChanged.connect(self._set_tilt)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _set_tilt(self, value):
        self._tilt = float(value)
        self.update()

    def _scale(self) -> float:
        from .ui_zoom import effective_factor
        return effective_factor(self)

    def sizeHint(self) -> QSize:
        f = self._scale()
        font = self.font()
        font.setPixelSize(max(1, round(15 * f)))
        font.setBold(True)
        width = QFontMetrics(font).horizontalAdvance(self.text()) + round((22 * 2 + 16 + 8) * f)
        return QSize(width, round((42 + self.EAR_ROOM) * f))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def setText(self, text):  # noqa: N802 - Qt override
        super().setText(text)
        self.updateGeometry()

    def enterEvent(self, event):
        self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate(0.0)
        super().leaveEvent(event)

    def _animate(self, target):
        self._motion.stop()
        self._motion.setStartValue(self._tilt)
        self._motion.setEndValue(target if self.isEnabled() else 0.0)
        self._motion.start()

    def paintEvent(self, event):
        t = active_theme()
        k = soft_tokens(t)
        f = self._scale()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            fill, ink = QColor(k.fill), QColor(t.text_muted)
        elif self.isDown():
            fill, ink = QColor(t.accent_pressed), QColor(t.text_on_accent)
        elif self.underMouse():
            fill, ink = QColor(t.accent_hover), QColor(t.text_on_accent)
        else:
            fill, ink = QColor(t.accent), QColor(t.text_on_accent)
        room = self.EAR_ROOM * f
        body = QRectF(0, room, self.width(), self.height() - room)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        for x, angle in ((20, -14 - 8 * self._tilt), (35, 10 - 6 * self._tilt)):
            painter.save()
            painter.translate(x * f + 5.5 * f, room + 6 * f)
            painter.rotate(angle)
            ear = QPainterPath()
            ear.addRoundedRect(QRectF(-5.5 * f, -16 * f, 11 * f, 20 * f), 5.5 * f, 5.5 * f)
            painter.drawPath(ear)
            painter.restore()
        painter.drawRoundedRect(body, 14 * f, 14 * f)
        font = self.font()
        font.setPixelSize(max(1, round(15 * f)))
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        icon_size = round(16 * f)
        gap = round(8 * f)
        text_width = metrics.horizontalAdvance(self.text())
        total = (icon_size + gap if not self.icon().isNull() else 0) + text_width
        x = (self.width() - total) / 2
        if not self.icon().isNull():
            mode = self.icon().Mode.Normal if self.isEnabled() else self.icon().Mode.Disabled
            pixmap = self.icon().pixmap(QSize(icon_size, icon_size), self.devicePixelRatioF(), mode)
            painter.drawPixmap(round(x), round(body.center().y() - icon_size / 2), pixmap)
            x += icon_size + gap
        painter.setPen(ink)
        painter.drawText(QRectF(x, body.top(), text_width + 2, body.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class PassChip(QPushButton):
    """The login choice as a small dashed ticket.

    Keeps the field-like API the controller and tests used on the old
    read-only ``cookie`` line edit: ``setText``/``text``/``clear`` hold the
    authorization status, the placeholder is shown while it is empty."""

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setObjectName("linkPass")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._status = ""
        self._placeholder = str(placeholder)
        self._refresh()

    def setPlaceholderText(self, text):  # noqa: N802 - line edit API
        self._placeholder = str(text)
        self._refresh()

    def placeholderText(self) -> str:  # noqa: N802
        return self._placeholder

    def setReadOnly(self, _value):  # noqa: N802 - line edit API, always read-only
        pass

    def setText(self, text):  # noqa: N802
        self._status = str(text or "")
        self._refresh()

    def text(self) -> str:
        return self._status

    def clear(self):
        self.setText("")

    def _refresh(self):
        from ..design.themed_icons import install_themed_icon
        active = bool(self._status)
        super().setText(self._status or self._placeholder)
        install_themed_icon(self, "fa5s.key" if active else "fa5s.lock-open", "accent" if active else "secondary")
        self.setIconSize(QSize(13, 13))
        if self.property("active") != active:
            self.setProperty("active", active)
            self.style().unpolish(self)
            self.style().polish(self)
        self.setToolTip(self._status or tr("网站要求登录时，选择一种方式提供这个视频的授权"))


def site_kind(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    if host.endswith("youtube.com") or host == "youtu.be":
        return "youtube"
    if host.endswith("bilibili.com") or host == "b23.tv":
        return "bilibili"
    return "web"


class SiteBadge(QWidget):
    def __init__(self, size=32, parent=None):
        super().__init__(parent)
        from .ui_zoom import set_size
        set_size(self, fixed_w=size, fixed_h=size)
        self.kind = "web"

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def paintEvent(self, event):
        t = active_theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(SITE_COLORS.get(self.kind, soft_tokens(t).chip)))
        painter.drawRoundedRect(rect, rect.width() * .3, rect.width() * .3)
        ink = QColor("#ffffff") if self.kind in SITE_COLORS else QColor(t.accent_text)
        painter.setBrush(ink)
        s = rect.width()
        if self.kind in SITE_COLORS:
            play = QPainterPath(QPointF(s * .40, s * .32))
            play.lineTo(QPointF(s * .70, s * .5))
            play.lineTo(QPointF(s * .40, s * .68))
            play.closeSubpath()
            painter.drawPath(play)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(ink, max(1.4, s / 18)))
            painter.drawEllipse(rect.center(), s * .26, s * .26)
            painter.drawLine(QPointF(s * .24, s * .5), QPointF(s * .76, s * .5))


class MiniTicket(QPushButton):
    """A recent parse as a ticket stub (2026-11-26, draft A 售票窗口): the site's
    badge on a stub, a dashed tear, then the title over "site · length · when"."""

    chosen = Signal(str)
    STUB = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("linkMiniTicket")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.url = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 12, 0)
        row.setSpacing(0)
        self.stub = QWidget()
        from .ui_zoom import set_size
        set_size(self.stub, fixed_w=self.STUB)
        stub = QHBoxLayout(self.stub)
        stub.setContentsMargins(0, 0, 0, 0)
        self.badge = SiteBadge(28)
        stub.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.stub)
        row.addSpacing(12)
        words = QVBoxLayout()
        words.setSpacing(2)
        words.addStretch(1)
        self.title = user_text(ElidedLabel("", mode=Qt.TextElideMode.ElideRight, minimum=60))
        self.title.setObjectName("linkMiniTitle")
        self.note = ElidedLabel("", mode=Qt.TextElideMode.ElideRight, minimum=40)
        self.note.setObjectName("linkMiniNote")
        words.addWidget(self.title)
        words.addWidget(self.note)
        words.addStretch(1)
        row.addLayout(words, 1)
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.clicked.connect(lambda: self.chosen.emit(self.url))

    def set_entry(self, entry: dict):
        self.url = str(entry.get("url", ""))
        self.title.setText(entry.get("title") or self.url)
        kind = site_kind(self.url)
        self.badge.set_kind(kind)
        parts = [{"youtube": "YouTube", "bilibili": "Bilibili"}.get(kind, urlparse(self.url).hostname or "")]
        if entry.get("duration"):
            from ..media.link_choices import duration_text
            try:
                parts.append(duration_text(entry["duration"]))
            except (TypeError, ValueError, OverflowError):
                pass
        if entry.get("saved"):
            parts.append(_when_saved(entry["saved"]))
        self.note.setText(" · ".join(part for part in parts if part))
        self.setToolTip(self.url)

    def paintEvent(self, event):
        super().paintEvent(event)
        t = active_theme()
        painter = QPainter(self)
        pen = QPen(QColor(t.border), 2)
        pen.setDashPattern([2.5, 2])
        painter.setPen(pen)
        x = self.stub.geometry().right() + 1
        painter.drawLine(QPointF(x, 1), QPointF(x, self.height() - 1))


def _when_saved(stamp: float) -> str:
    try:
        day = date.fromtimestamp(float(stamp))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
    today = date.today()
    if day == today:
        return tr("今天")
    if day == today - timedelta(days=1):
        return tr("昨天")
    return day.strftime("%m/%d")


class KindTicket(QPushButton):
    """One download kind as a small ticket (2026-11-26, user: no notches cut into
    the edges, make it look like a real ticket): a stub holding the icon, a dashed
    tear line, the label. Chosen: the stub fills with the accent colour."""

    def __init__(self, text, icon, parent=None):
        super().__init__(text, parent)
        self.setObjectName("linkKindTicket")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._icon_name = icon

    def _scale(self) -> float:
        from .ui_zoom import effective_factor
        return effective_factor(self)

    def _font(self):
        font = QFont(self.font())
        font.setPixelSize(max(1, round(13 * self._scale())))
        return font

    def sizeHint(self) -> QSize:
        f = self._scale()
        width = QFontMetrics(self._font()).horizontalAdvance(self.text()) + round((30 + 12 + 14) * f)
        return QSize(width, round(36 * f))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def setText(self, text):  # noqa: N802 - Qt override
        super().setText(text)
        self.updateGeometry()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        import qtawesome
        t = active_theme()
        k = soft_tokens(t)
        f = self._scale()
        chosen = self.isChecked()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        radius = 9 * f
        border = QColor(t.accent if chosen else (t.border_strong if self.underMouse() else t.border))
        if not self.isEnabled():
            border = QColor(t.border)
        outline = QPainterPath()
        outline.addRoundedRect(body, radius, radius)
        painter.fillPath(outline, QColor(k.chip if chosen else t.surface_elevated))
        stub_width = 30 * f
        stub = QPainterPath()
        stub.addRect(QRectF(body.left(), body.top(), stub_width, body.height()))
        painter.save()
        painter.setClipPath(outline)
        painter.fillPath(stub, QColor(t.accent if chosen else k.fill))
        painter.restore()
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(outline)
        if self.hasFocus():
            focus = QPen(QColor(t.accent), 1, Qt.PenStyle.DashLine)
            painter.setPen(focus)
            painter.drawRoundedRect(body.adjusted(2, 2, -2, -2), radius - 2, radius - 2)
        tear = QPen(QColor(t.accent if chosen else t.border_strong), max(1.2, 1.4 * f))
        tear.setDashPattern([2, 2])
        painter.setPen(tear)
        x = body.left() + stub_width
        painter.drawLine(QPointF(x, body.top() + 1), QPointF(x, body.bottom() - 1))
        ink = QColor(t.text_on_accent if chosen else t.text_muted)
        size = round(14 * f)
        pixmap = qtawesome.icon(self._icon_name, color=ink).pixmap(size, size)
        painter.drawPixmap(round(body.left() + (stub_width - size) / 2), round(body.center().y() - size / 2), pixmap)
        painter.setPen(QColor(t.accent_text if chosen else (t.text_secondary if self.isEnabled() else t.disabled)))
        painter.setFont(self._font())
        painter.drawText(QRectF(x + 10 * f, body.top(), body.right() - x - 12 * f, body.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class HelperLine(QWidget):
    """兔白助手 and the Ctrl+V tip as one quiet line under the recent parses
    (draft A 售票窗口). Same ``refresh``/``manage`` as the earlier strip."""

    manage = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(6)
        row.addStretch(1)
        self.icon = QLabel()
        from .ui_zoom import set_size
        set_size(self.icon, fixed_w=20, fixed_h=20)
        row.addWidget(self.icon)
        self.state = named_label("", "linkHint", wrap=True)
        row.addWidget(self.state)
        from .link_download_widgets import button
        self.button = button(tr("安装"), "linkLink")
        self.button.clicked.connect(self.manage.emit)
        row.addWidget(self.button)
        row.addWidget(named_label("·", "linkHint"))
        row.addWidget(named_label(tr("在字幕工作台按 Ctrl+V 也能下载"), "linkHint", wrap=True))
        row.addStretch(1)

    def refresh(self, root, ready: list[str]):
        from PySide6.QtGui import QPixmap
        image = QPixmap(str(root / "assets/browser-helper/icon.png"))
        if not image.isNull():
            size = self.icon.width()
            self.icon.setPixmap(image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        if ready:
            self.state.setText(tr("兔白助手已在 {browsers} 设定", browsers="、".join(ready)))
            self.button.setText(tr("管理"))
        else:
            self.state.setText(tr("兔白助手还没装进浏览器"))
            self.button.setText(tr("安装"))
