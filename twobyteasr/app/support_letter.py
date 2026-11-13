# SPDX-License-Identifier: GPL-3.0-only
"""The letter-style 「支持我！」 window.

2026-11-13 (user picked draft B of three, "more cute and colourful"): a little
note from the bunny. Two strips of washi tape over the top edge, a round
bunny sticker, a title with a hand-drawn wavy underline, the voluntary
reminder as a highlighter stroke, the letter written on ruled lines and the
two links as perforated stamps. Everything is painted from the active theme:
light themes get warm paper, dark themes a dimmed sheet with the same shapes.
Sizes are logical px; the interface zoom scales fonts and layouts, painting
uses ``px``.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..design.typography import TITLE_FONT_STACK
from .rounded_window import SHADOW
from .ui_zoom import px, set_sheet

WIDTH = 600
RADIUS = 26


def _theme():
    from ..design.theme_manager import theme_definition, theme_key
    return theme_definition(theme_key())


def letter_colors(t=None) -> dict:
    from ..design.ui_theme import blend_hex
    t = t or _theme()
    if t.is_light:
        paper = blend_hex(t.surface_elevated, '#fffef9', 0.5)
        return {
            'paper': paper, 'rule': blend_hex(paper, t.border_strong, 0.4), 'ink': t.text_secondary,
            'title': t.text, 'muted': t.text_muted, 'highlight': '#fff0a0',
            'highlight_ink': blend_hex(t.text, '#4a3a14', 0.5),
            'tape_a': ('#ffc9d6', '#ffe2e9'), 'tape_b': ('#c4e3ff', '#e2f1ff'),
            'squiggle': '#f08aa8', 'sign': '#b25c7a', 'sticker': '#efe6ff', 'sticker_ring': '#ffffff',
            'sticker_shadow': QColor(90, 60, 130, 60), 'stamp_shadow': QColor(40, 26, 14, 46),
            'paypal': '#2f66d1', 'afdian': '#8752d2', 'stamp_ink': '#ffffff', 'focus': t.focus,
        }
    # 2026-11-13 (user, dark sheet): the words were not white enough, the
    # yellow highlighter clashed (pink now) and the tape needed dark-friendly tones.
    paper = t.surface_elevated
    bright = blend_hex(t.text, '#ffffff', 0.6)
    return {
        'paper': paper, 'rule': blend_hex(paper, t.text, 0.18), 'ink': blend_hex(t.text, '#ffffff', 0.35),
        'title': bright, 'muted': blend_hex(t.text_secondary, '#ffffff', 0.25),
        'highlight': blend_hex(paper, '#ff6fa8', 0.52), 'highlight_ink': '#ffffff',
        'tape_a': ('#c7a2ff', '#a983e8'), 'tape_b': ('#7fdcc4', '#5cbfa8'),
        'squiggle': '#f08aa8', 'sign': '#f0a3c0', 'sticker': blend_hex(paper, '#b89cff', 0.35),
        'sticker_ring': blend_hex(paper, '#ffffff', 0.85), 'sticker_shadow': QColor(0, 0, 0, 90),
        'stamp_shadow': QColor(0, 0, 0, 110), 'paypal': '#3d74dd', 'afdian': '#9563dd',
        'stamp_ink': '#ffffff', 'focus': t.focus,
    }


def letter_qss(t=None) -> str:
    c = letter_colors(t)
    t = t or _theme()
    return f"""
QWidget#supportLetter {{ background: {c['paper']}; color: {c['ink']}; }}
QWidget#supportLetterHeader {{ background: transparent; }}
QLabel#supportLetterTitle {{ font-family: {TITLE_FONT_STACK}; font-size: 26px; font-weight: 900;
    color: {c['title']}; background: transparent; }}
QLabel#supportLetterSubtitle {{ font-size: 12.5px; color: {c['muted']}; background: transparent; }}
QLabel#supportEmphasis {{ font-size: 14px; font-weight: 700; color: {c['highlight_ink']}; background: transparent; }}
QLabel#supportLetterLine {{ font-size: 14.5px; color: {c['ink']}; background: transparent; }}
QLabel#supportLetterSign {{ font-size: 14px; font-weight: 700; color: {c['sign']}; background: transparent; }}
QPushButton#supportStamp {{ font-size: 17px; font-weight: 800; background: transparent; border: 0;
    min-height: 100px; max-height: 100px; padding: 0; }}
""" + ("" if t.is_light else f"""
QWidget#supportLetter QPushButton[buttonRole="ghost"], QWidget#supportLetter QPushButton[buttonRole="secondary"] {{
    color: {c['ink']}; }}
""")


class RoundCloseButton(QPushButton):
    """The round ×, painted: style sheet radii are not honoured for this
    button under the application's control styling (it drew a square)."""

    SIZE = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('supportLetterClose')
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)

    def paintEvent(self, event):
        colors = letter_colors()
        ink = QColor(colors['title'])
        fill = QColor(ink)
        fill.setAlpha(46 if self.isDown() else 34 if self.underMouse() else 18)
        side = min(self.width(), self.height())
        circle = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side).adjusted(1, 1, -1, -1)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(colors['focus']), 2) if self.hasFocus() else Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(circle)
        arm = side * 0.16
        center = circle.center()
        pen = QPen(ink, max(1.6, side / 17))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(center.x() - arm, center.y() - arm), QPointF(center.x() + arm, center.y() + arm))
        painter.drawLine(QPointF(center.x() - arm, center.y() + arm), QPointF(center.x() + arm, center.y() - arm))
        painter.end()


def wrapped_lines(text: str, font: QFont, width: float) -> list[str]:
    """``text`` broken into the lines it takes at ``width`` (CJK and words)."""
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    lines = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(1.0, float(width)))
        lines.append(text[line.textStart():line.textStart() + line.textLength()].rstrip())
    layout.endLayout()
    return lines or ['']


class _PaintedText(QLabel):
    """A wrapping label that paints its own lines (heightForWidth matches)."""

    PAD_X = 0
    PAD_Y = 0
    alignment_x = Qt.AlignmentFlag.AlignLeft

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setAlignment(self.alignment_x | Qt.AlignmentFlag.AlignTop)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def line_height(self) -> int:
        return self.fontMetrics().height()

    def lines(self, width=None) -> list[str]:
        width = self.width() if width is None else width
        return wrapped_lines(self.text(), self.font(), width - 2 * px(self.PAD_X))

    def heightForWidth(self, width):
        return len(self.lines(width)) * self.line_height() + 2 * px(self.PAD_Y)

    def sizeHint(self):
        width = max(self.width(), px(320))
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        return QSize(px(140), self.line_height() + 2 * px(self.PAD_Y))

    def setText(self, text):
        super().setText(text)
        self.updateGeometry()
        self.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.updateGeometry()

    def _line_x(self, text_width) -> float:
        if self.alignment_x == Qt.AlignmentFlag.AlignHCenter:
            return (self.width() - text_width) / 2
        if self.alignment_x == Qt.AlignmentFlag.AlignRight:
            return self.width() - px(self.PAD_X) - text_width
        return px(self.PAD_X)


class LetterLine(_PaintedText):
    """A paragraph of the letter, each line sitting on a ruled line."""

    PAD_X = 4

    def __init__(self, parent=None, *, align=Qt.AlignmentFlag.AlignLeft, sign=False):
        self.alignment_x = align
        self.sign = sign
        super().__init__(parent)
        self.setObjectName('supportLetterSign' if sign else 'supportLetterLine')

    def _heart_room(self) -> int:
        return round(self.fontMetrics().ascent() * 0.95) if self.sign else 0

    def lines(self, width=None) -> list[str]:
        width = self.width() if width is None else width
        return wrapped_lines(self.text(), self.font(), width - 2 * px(self.PAD_X) - self._heart_room())

    def line_height(self) -> int:
        return self.fontMetrics().height() + px(14)

    def paintEvent(self, event):
        colors = letter_colors()
        metrics = self.fontMetrics()
        step = self.line_height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        rule = QPen(QColor(colors['rule']), 1)
        ink = self.palette().color(self.foregroundRole())
        for index, text in enumerate(self.lines()):
            bottom = (index + 1) * step - 0.5
            painter.setPen(rule)
            painter.drawLine(QPointF(0, bottom), QPointF(self.width(), bottom))
            painter.setPen(ink)
            baseline = bottom - px(7) - metrics.descent()
            advance = metrics.horizontalAdvance(text)
            left = self._line_x(advance + self._heart_room())
            painter.drawText(QPointF(left, baseline), text)
        if self.sign:
            side = self._heart_room() * 0.72
            x = left + advance + self._heart_room() - side
            draw_heart(painter, QRectF(x, baseline - metrics.ascent() * 0.72, side, side), ink)
        painter.end()


def draw_heart(painter: QPainter, rect: QRectF, color: QColor):
    w, h = rect.width(), rect.height()
    x, y = rect.left(), rect.top()
    heart = QPainterPath()
    heart.moveTo(x + w / 2, y + h)
    heart.cubicTo(x - w * 0.15, y + h * 0.55, x + w * 0.05, y - h * 0.1, x + w / 2, y + h * 0.25)
    heart.cubicTo(x + w * 0.95, y - h * 0.1, x + w * 1.15, y + h * 0.55, x + w / 2, y + h)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(heart)
    painter.restore()


class HighlightNote(_PaintedText):
    """The voluntary reminder, as if run over with a yellow highlighter."""

    PAD_X = 18
    PAD_Y = 6
    alignment_x = Qt.AlignmentFlag.AlignHCenter

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('supportEmphasis')

    def line_height(self) -> int:
        return self.fontMetrics().height() + px(10)

    def paintEvent(self, event):
        colors = letter_colors()
        metrics = self.fontMetrics()
        step = self.line_height()
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-0.8)
        painter.translate(-self.width() / 2, -self.height() / 2)
        painter.setFont(self.font())
        ink = self.palette().color(self.foregroundRole())
        for index, text in enumerate(self.lines()):
            top = px(self.PAD_Y) + index * step
            width = metrics.horizontalAdvance(text)
            left = self._line_x(width)
            band = QRectF(left - px(12), top + step * 0.2, width + px(24), step * 0.72)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors['highlight']))
            painter.drawRoundedRect(band, px(4), px(4))
            painter.setPen(ink)
            baseline = top + (step + metrics.ascent() - metrics.descent()) / 2
            painter.drawText(QPointF(left, baseline), text)
        painter.end()


class SquiggleTitle(_PaintedText):
    """The title, underlined with a pink hand-drawn wave."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('supportLetterTitle')

    def line_height(self) -> int:
        return self.fontMetrics().height() + px(10)

    def paintEvent(self, event):
        colors = letter_colors()
        metrics = self.fontMetrics()
        step = self.line_height()
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        ink = self.palette().color(self.foregroundRole())
        for index, text in enumerate(self.lines()):
            baseline = index * step + metrics.ascent()
            width = metrics.horizontalAdvance(text)
            painter.setPen(ink)
            painter.drawText(QPointF(0, baseline), text)
            wave = QPainterPath()
            y = baseline + metrics.descent() + px(3)
            amplitude, period = px(3), px(18)
            x = -px(3)
            wave.moveTo(x, y)
            up = True
            while x < width + px(3):
                wave.quadTo(x + period / 4, y + (-amplitude if up else amplitude), x + period / 2, y)
                x += period / 2
                up = not up
            pen = QPen(QColor(colors['squiggle']), max(2.0, px(3.2)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(wave)
        painter.end()


class BunnySticker(QWidget):
    """The bunny's face as a round sticker, tilted; it perks up when happy."""

    SIZE = 78
    REST, HAPPY = -8.0, 6.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('supportLetterSticker')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(self.SIZE + 14, self.SIZE + 14)
        self._tilt = self.REST
        self._face = None
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(300)
        self._animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self._animation.valueChanged.connect(self._set_tilt)

    def _set_tilt(self, value):
        self._tilt = float(value)
        self.update()

    def set_happy(self, happy: bool):
        target = self.HAPPY if happy else self.REST
        self._animation.stop()
        self._animation.setStartValue(self._tilt)
        self._animation.setEndValue(target)
        self._animation.start()

    def enterEvent(self, event):
        self.set_happy(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_happy(False)
        super().leaveEvent(event)

    def _face_pixmap(self, side):
        ratio = self.devicePixelRatioF() or 1.0
        key = (side, ratio)
        if self._face is None or self._face[0] != key:
            from ..design.bunny_mascot import bunny_face_pixmap
            self._face = (key, bunny_face_pixmap(side, ratio))
        return self._face[1]

    def paintEvent(self, event):
        colors = letter_colors()
        side = min(self.width(), self.height()) - px(14)
        progress = (self._tilt - self.REST) / (self.HAPPY - self.REST)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._tilt)
        scale = 1 + 0.06 * max(0.0, progress)
        painter.scale(scale, scale)
        circle = QRectF(-side / 2, -side / 2, side, side)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colors['sticker_shadow'])
        painter.drawEllipse(circle.translated(0, px(3)).adjusted(-1, -1, 1, 1))
        painter.setBrush(QColor(colors['sticker']))
        painter.drawEllipse(circle)
        inset = px(4)
        face = circle.adjusted(inset, inset, -inset, -inset)
        painter.drawPixmap(face.toRect(), self._face_pixmap(int(face.width())))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(colors['sticker_ring']), px(4)))
        painter.drawEllipse(circle.adjusted(px(2), px(2), -px(2), -px(2)))
        painter.end()


def _perforated(rect: QRectF, radius: float, step: float) -> QPainterPath:
    body = QPainterPath()
    body.addRect(rect)
    holes = QPainterPath()
    across = max(2, round(rect.width() / step))
    down = max(2, round(rect.height() / step))
    for index in range(across + 1):
        x = rect.left() + index * rect.width() / across
        holes.addEllipse(QPointF(x, rect.top()), radius, radius)
        holes.addEllipse(QPointF(x, rect.bottom()), radius, radius)
    for index in range(1, down):
        y = rect.top() + index * rect.height() / down
        holes.addEllipse(QPointF(rect.left(), y), radius, radius)
        holes.addEllipse(QPointF(rect.right(), y), radius, radius)
    return body.subtracted(holes)


class StampButton(QPushButton):
    """A link painted as a perforated postage stamp; straightens on hover."""

    def __init__(self, color_key: str, rest_angle: float, parent=None):
        super().__init__(parent)
        self.setObjectName('supportStamp')
        self.color_key = color_key
        self.rest_angle = rest_angle
        self._caption = ''
        self._hover = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._set_hover)
        self.pressed.connect(self.update)
        self.released.connect(self.update)

    def caption(self) -> str:
        # Language switches re-apply only Qt's own text properties, so a bound
        # caption is translated whenever it is read (and painted).
        binding = getattr(self, '_i18n_bindings', {}).get('caption')
        if binding is None:
            return self._caption
        from ..i18n import current_language, render_arguments, translate
        source, arguments = binding
        value = translate(source, current_language())
        return value.format(**render_arguments(arguments)) if arguments else value

    def setCaption(self, text: str):
        self._caption = str(text)
        self.update()

    def sizeHint(self):
        return QSize(px(200), px(100))

    def minimumSizeHint(self):
        return QSize(px(150), px(100))

    def _set_hover(self, value):
        self._hover = float(value)
        self.update()

    def _animate(self, target):
        self._animation.stop()
        self._animation.setStartValue(self._hover)
        self._animation.setEndValue(target)
        self._animation.start()

    def enterEvent(self, event):
        self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        colors = letter_colors()
        hover = self._hover
        down = self.isDown()
        angle = self.rest_angle * (1 - hover)
        lift = 0 if down else -px(3) * hover
        scale = 0.97 if down else 1 + 0.03 * hover
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                               | QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(self.width() / 2, self.height() / 2 + lift)
        painter.rotate(angle)
        painter.scale(scale, scale)
        margin = px(10)
        rect = QRectF(-self.width() / 2 + margin, -self.height() / 2 + margin,
                      self.width() - 2 * margin, self.height() - 2 * margin)
        shape = _perforated(rect, px(4), px(12))
        painter.fillPath(shape.translated(0, px(2)), colors['stamp_shadow'])
        painter.fillPath(shape, QColor(colors[self.color_key]))
        ink = QColor(colors['stamp_ink'])
        dashed = QColor(ink)
        dashed.setAlpha(180)
        pen = QPen(dashed, max(1.5, px(2)), Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inner = rect.adjusted(px(9), px(9), -px(9), -px(9))
        painter.drawRoundedRect(inner, px(3), px(3))
        if self.hasFocus() and self.focusPolicy() != Qt.FocusPolicy.NoFocus:
            painter.setPen(QPen(QColor(colors['focus']), max(2.0, px(2))))
            painter.drawRoundedRect(rect.adjusted(-px(6), -px(6), px(6), px(6)), px(6), px(6))
        name_font = self.font()
        caption_font = QFont(name_font)
        caption_font.setWeight(QFont.Weight.Normal)
        if name_font.pixelSize() > 0:
            caption_font.setPixelSize(max(9, round(name_font.pixelSize() * 0.7)))
        else:
            caption_font.setPointSizeF(max(7.0, name_font.pointSizeF() * 0.7))
        from PySide6.QtGui import QFontMetricsF
        name_metrics, caption_metrics = QFontMetricsF(name_font), QFontMetricsF(caption_font)
        icon_side = round(name_metrics.ascent() * 0.8)
        gap = px(7)
        name_width = name_metrics.horizontalAdvance(self.text())
        caption = self.caption()
        total = name_metrics.height() + (caption_metrics.height() + px(2) if caption else 0)
        top = -total / 2
        row_width = icon_side + gap + name_width
        left = -row_width / 2
        from ..design.themed_icons import cached_icon_pixmap
        ratio = self.devicePixelRatioF() or 1.0
        icon = cached_icon_pixmap('fa5s.external-link-alt', colors['stamp_ink'], QSize(icon_side, icon_side),
                                  device_pixel_ratio=ratio)
        icon_top = top + (name_metrics.height() - icon_side) / 2
        painter.drawPixmap(QRectF(left, icon_top, icon_side, icon_side).toRect(), icon)
        painter.setPen(ink)
        painter.setFont(name_font)
        painter.drawText(QPointF(left + icon_side + gap, top + name_metrics.ascent()), self.text())
        if caption:
            soft = QColor(ink)
            soft.setAlpha(225)
            painter.setPen(soft)
            painter.setFont(caption_font)
            caption_top = top + name_metrics.height() + px(2)
            caption_width = caption_metrics.horizontalAdvance(caption)
            painter.drawText(QPointF(-caption_width / 2, caption_top + caption_metrics.ascent()), caption)
        painter.end()


def _draw_tape(painter: QPainter, center: QPointF, angle: float, colors: tuple[str, str]):
    width, height = px(112), px(28)
    painter.save()
    painter.translate(center)
    painter.rotate(angle)
    rect = QRectF(-width / 2, -height / 2, width, height)
    # Torn short ends: a small zigzag on the left and the right.
    teeth = 5
    shape = QPainterPath()
    shape.moveTo(rect.topLeft())
    shape.lineTo(rect.topRight())
    for index in range(1, teeth + 1):
        y = rect.top() + index * height / teeth
        shape.lineTo(rect.right() - (px(3) if index % 2 else 0), y)
    shape.lineTo(rect.bottomLeft())
    for index in range(teeth - 1, -1, -1):
        y = rect.top() + index * height / teeth
        shape.lineTo(rect.left() + (px(3) if index % 2 else 0), y)
    shape.closeSubpath()
    painter.setOpacity(0.92)
    painter.setClipPath(shape)
    painter.fillRect(rect, QColor(colors[1]))
    stripe = px(8)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colors[0]))
    x = rect.left() - height
    while x < rect.right():
        band = QPainterPath()
        band.moveTo(x, rect.bottom())
        band.lineTo(x + stripe, rect.bottom())
        band.lineTo(x + stripe + height, rect.top())
        band.lineTo(x + height, rect.top())
        band.closeSubpath()
        painter.drawPath(band)
        x += 2 * stripe
    painter.restore()


class LetterCard(QWidget):
    """The sheet of paper: tape, header (sticker, title, ×), body, footer."""

    def __init__(self, parent=None, *, close_callback=None):
        super().__init__(parent)
        self.setObjectName('supportLetter')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 30, 34, 18)
        layout.setSpacing(0)

        self.header = QWidget(self)
        self.header.setObjectName('supportLetterHeader')
        row = QHBoxLayout(self.header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.sticker = BunnySticker(self.header)
        row.addWidget(self.sticker, 0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(4)
        words.addStretch(1)
        self.title = SquiggleTitle(self.header)
        self.subtitle = QLabel(self.header)
        self.subtitle.setObjectName('supportLetterSubtitle')
        self.subtitle.setWordWrap(True)
        words.addWidget(self.title)
        words.addWidget(self.subtitle)
        words.addStretch(1)
        row.addLayout(words, 1)
        self.close_button = RoundCloseButton(self.header)
        from ..i18n import bind_text
        bind_text(self.close_button, '关闭', property='toolTip')
        bind_text(self.close_button, '关闭', property='accessibleName')
        if close_callback is not None:
            self.close_button.clicked.connect(close_callback)
        row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.header)
        layout.addSpacing(18)

        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        layout.addLayout(self.body_layout)
        layout.addSpacing(16)

        self.footer_layout = QHBoxLayout()
        self.footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_layout.setSpacing(12)
        layout.addLayout(self.footer_layout)
        self.refresh_theme()

    def refresh_theme(self):
        set_sheet(self, letter_qss())
        self.update()

    def paintEvent(self, event):
        colors = letter_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(colors['paper']))
        _draw_tape(painter, QPointF(px(92), px(6)), -6, colors['tape_a'])
        _draw_tape(painter, QPointF(self.width() - px(150), px(6)), 5, colors['tape_b'])
        painter.end()


class LetterDialog(QDialog):
    """A frameless, rounded window holding one LetterCard."""

    def __init__(self, parent, title: str, subtitle: str):
        super().__init__(parent)
        from ..i18n import bind_text
        from ..design.studio_theme import apply_secondary_surface_theme
        from .rounded_window import RoundedWindow
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        bind_text(self, title, property='windowTitle')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.surface = LetterCard(self, close_callback=self.reject)
        bind_text(self.surface.title, title)
        bind_text(self.surface.subtitle, subtitle)
        outer.addWidget(self.surface)
        self.setMinimumWidth(480 + 2 * SHADOW)
        self.resize(WIDTH + 2 * SHADOW, 460)
        apply_secondary_surface_theme(self)
        self.chrome = RoundedWindow(self, self.surface, title_areas=[self.surface.header], radius=RADIUS,
                                    maximizable=False)
        self._fitting = False
        self._fit_pending = False

    def refresh_theme_palette(self):
        self.surface.refresh_theme()
        for child in self.findChildren(QWidget):
            child.update()

    def fit_height(self):
        """Exactly as tall as the letter at the current width (no scrolling, no gap)."""
        if self._fitting:
            return
        self._fitting = True
        try:
            margin = self.chrome.margin()
            layout = self.surface.layout()
            # Painted lines measure from the styled (and zoomed) font: drop the
            # layout's cached heights before asking again.
            for label in self.surface.findChildren(_PaintedText):
                label.updateGeometry()
            layout.invalidate()
            inner = layout.totalHeightForWidth(self.width() - 2 * margin)
            height = max(inner, layout.totalMinimumSize().height()) + 2 * margin
            if height != self.height():
                self.resize(self.width(), height)
        finally:
            self._fitting = False

    def _fit_soon(self):
        if not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self._fit_later)

    def _fit_later(self):
        self._fit_pending = False
        self.fit_height()

    def showEvent(self, event):
        self.surface.ensurePolished()
        for child in self.surface.findChildren(QWidget):
            child.ensurePolished()
        self.fit_height()
        super().showEvent(event)
        self._fit_soon()

    def event(self, event):
        handled = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and self.isVisible():
            self._fit_soon()
        return handled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self._fit_soon()
