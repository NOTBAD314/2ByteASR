"""The header's brand as a subtitle bubble: 兔白 peeks over the left end of it (2026-11-26).

User (2026-11-26), from the brand drafts (``tmp/brand-icon-drafts-20261126``): the keychain's
little full-body 兔白 was far too small to see. Round 1 picked B — the original head icon (with
her ears) peeking over the left end of the name tag, no paws; round 2 picked E for the tag — a
rounded speech bubble with 「兔白字幕」, a slowly blinking text caret after it, a small CC chip
before 2ByteASR, three dots in the lower right. 「问问兔白」 on the right keeps her keychain look.

The three widgets the rest of the app knows keep their names and roles: ``header_mascot`` (her
head; a QLabel whose pixmap is no larger than itself), ``header_subtitle`` (「兔白字幕」) and
``brand`` (2ByteASR). The launch picture lands its wordmark halves on the last two, so they stay
plain labels exactly as wide as their text; the bubble, caret, chip and dots are around them.

Hovered, she peeks up a few pixels and settles (``motion_tokens.BRAND_PEEK``). Not a button
or text: an arrow cursor, no click reaction, nothing selectable (2026-11-27).

2026-11-26 (user, later): 「兔白字幕」 sat higher than her head and looked odd; it should come down
level with the icon. The small CC 2ByteASR line now rides on the bubble's top edge as a name plate
(like the 「兔白」 tag on her chat box), so the title has the bubble to itself and sits level with
her face and the header's buttons.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from .main_ui_branding import HeaderMascot, _brand_pixmap
from .main_ui_helpers import APP_ICON_SOURCE_PATH

HEAD_H = 84            # logical height of her head (ears included)
HEAD_W = 74
HEAD_CROP = (0.11, 0.05, 0.895, 0.955)   # the opaque part of 2byteasr-icon-transparent.png
BOX_H = 92             # the header is 104 high with 6 px margins
TAG_LEFT = 10          # the bubble starts here; she covers its left end
TAG_PAD_LEFT = 74      # so the bubble's words start just right of her face
TAG_PAD_RIGHT = 42     # room for the three dots after the caret
LEDGE = 4
RADIUS = 20
CARET_W, CARET_H = 3, 26
PLATE_H = 20           # the CC 2ByteASR name plate on the bubble's top edge
BUBBLE_TOP = 31        # the bubble's top edge (the plate is centred on it)
BUBBLE_BOTTOM = BOX_H - LEDGE - 2
TAG_TOP = BUBBLE_TOP - PLATE_H // 2      # the tag holds the plate and the bubble


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _alpha(color: str, alpha: float) -> QColor:
    result = QColor(color)
    result.setAlphaF(alpha)
    return result


class BrandHead(HeaderMascot):
    """Her head from the original app icon, ears and all."""

    def __init__(self, parent=None):
        super().__init__(parent, full_artwork=True, logical_size=HEAD_H)
        self.setFixedSize(HEAD_W, HEAD_H)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _refresh_pixmap(self) -> None:
        screen = self.screen()
        ratio = max(1.0, float(screen.devicePixelRatio()) if screen else 1.0)
        if abs(ratio - self._rendered_dpr) < 0.001:
            return
        self._rendered_dpr = ratio
        if APP_ICON_SOURCE_PATH.is_file():
            self.setPixmap(_brand_pixmap(APP_ICON_SOURCE_PATH, HEAD_H, focus_crop=HEAD_CROP))
        else:
            HeaderMascot._refresh_pixmap(self)


class Caret(QWidget):
    """The text caret after 「兔白字幕」, blinking slowly."""

    def __init__(self, parent=None):
        from ..design.motion_tokens import BRAND_CARET_MS
        super().__init__(parent)
        self.setFixedSize(CARET_W + 3, CARET_H)
        self.on = True
        self.timer = QTimer(self)
        self.timer.setInterval(BRAND_CARET_MS)
        self.timer.timeout.connect(self._blink)

    def showEvent(self, event):  # noqa: N802 - Qt override
        from ..design.ui_motion import reduced_motion
        if not reduced_motion():
            self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):  # noqa: N802 - Qt override
        self.timer.stop()
        self.on = True
        super().hideEvent(event)

    def _blink(self):
        self.on = not self.on
        self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        if not self.on:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_theme().accent))
        painter.drawRoundedRect(QRectF(3, 0, CARET_W, CARET_H), 1.5, 1.5)
        painter.end()


class BrandPlate(QWidget):
    """The small CC 2ByteASR name plate riding on the bubble's top edge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('brandPlate')

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(t.accent), 1.5))
        painter.setBrush(QColor(t.surface_elevated))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.end()


class BrandBubble(QWidget):
    """Her head and the subtitle bubble; the labels in it are the window's ``header_subtitle`` and ``brand``."""

    def __init__(self, title: QLabel, brand: QLabel, parent=None):
        from ..design.motion_tokens import BRAND_PEEK, easing_curve
        super().__init__(parent)
        self.setObjectName('brandBubble')
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.title = title
        self.brand = brand
        self.tag = QWidget(self)
        self.tag.setObjectName('brandTag')
        self.caret = Caret(self.tag)
        self.plate = BrandPlate(self.tag)
        self.cc = QLabel('CC', self.plate)
        self.cc.setObjectName('brandBubbleCC')
        self.cc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setParent(self.tag)
        brand.setParent(self.plate)
        for label in (title, brand):
            label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.charm = BrandHead(self)          # ``header_mascot``; drawn over the bubble's left end
        self._peek = 0.0
        self.peek = QVariantAnimation(self)
        self.peek.setDuration(BRAND_PEEK.ms)
        self.peek.setEasingCurve(easing_curve(BRAND_PEEK))
        self.peek.valueChanged.connect(self._peek_step)
        self.setFixedHeight(BOX_H)
        self.setMouseTracking(True)
        # 2026-11-27 (user: the title at the top left should not look selectable): a plain arrow,
        # no click bounce, and the words never take the mouse (no text cursor, nothing to select).
        self.setCursor(Qt.CursorShape.ArrowCursor)
        for label in (title, brand, self.cc):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # The interface zoom re-sizes the CC chip and the labels after they were placed
            # (at 120% the plate stayed laid out for the 100% chip until the next page switch).
            label.installEventFilter(self)
        self._placing = False
        self._style_chip()
        self._place()

    # ------------------------------------------------------------ layout
    def _sizes(self):
        """(title row width, plate width) from the labels' own sizes."""
        title = self.title.sizeHint()
        row = title.width() + 1 + self.caret.width()
        self.cc.adjustSize()
        plate = 7 + self.cc.width() + 6 + self.brand.sizeHint().width() + 9
        return row, plate

    def _tag_width(self) -> int:
        row, plate = self._sizes()
        return max(TAG_PAD_LEFT + row + TAG_PAD_RIGHT, TAG_PAD_LEFT - 2 + plate + 26)

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(TAG_LEFT + self._tag_width(), BOX_H)

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        return self.sizeHint()

    def bubble_rect(self) -> QRectF:
        """The drawn bubble in this widget's coordinates (the tag also holds the plate above it)."""
        tag = self.tag.geometry()
        return QRectF(tag.left(), BUBBLE_TOP, tag.width(), BUBBLE_BOTTOM - BUBBLE_TOP)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if (event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange, QEvent.Type.Resize)
                and not self._placing):
            self.updateGeometry()
            self._place()
        return False

    def _place(self):
        self._placing = True
        try:
            self._place_now()
        finally:
            self._placing = False

    def _place_now(self):
        width = self._tag_width()
        self.tag.setGeometry(TAG_LEFT, TAG_TOP, width, BUBBLE_BOTTOM - TAG_TOP)
        row, plate = self._sizes()
        bubble_top = BUBBLE_TOP - TAG_TOP
        # The title (and its caret) centred in the bubble below the plate's lower half: level with her face.
        title = self.title.sizeHint()
        inner_top = bubble_top + PLATE_H // 2
        inner_h = (BUBBLE_BOTTOM - TAG_TOP) - inner_top
        left = TAG_PAD_LEFT + max(0, (width - TAG_PAD_LEFT - TAG_PAD_RIGHT - row) // 2)
        top = inner_top + (inner_h - title.height()) // 2 - 1
        self.title.setGeometry(left, top, title.width(), title.height())
        self.caret.move(left + title.width() + 1, top + (title.height() - self.caret.height()) // 2)
        # The plate: its left end under the title's first character, centred on the bubble's top edge.
        self.plate.setGeometry(left - 4, bubble_top - PLATE_H // 2, plate, PLATE_H)
        brand = self.brand.sizeHint()
        self.cc.move(7, (PLATE_H - self.cc.height()) // 2)
        self.brand.setGeometry(7 + self.cc.width() + 6, (PLATE_H - brand.height()) // 2, brand.width(), brand.height())
        self._place_head()
        self.charm.raise_()

    def _place_head(self):
        from ..design.motion_tokens import BRAND_PEEK_PX
        self.charm.move(0, BOX_H - 2 - HEAD_H + 2 - round(self._peek * BRAND_PEEK_PX))

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        self._place()
        super().resizeEvent(event)

    def showEvent(self, event):  # noqa: N802 - Qt override
        self.updateGeometry()
        self._place()
        super().showEvent(event)

    # ------------------------------------------------------------ peeking
    def _peek_to(self, value: float):
        from ..design.ui_motion import reduced_motion
        self.peek.stop()
        if reduced_motion():
            self._peek_step(value)
            return
        self.peek.setStartValue(self._peek)
        self.peek.setEndValue(float(value))
        self.peek.start()

    def _peek_step(self, value):
        self._peek = float(value)
        self._place_head()
        self.update()

    def enterEvent(self, event):  # noqa: N802 - Qt override
        self._peek_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._peek_to(0.0)
        super().leaveEvent(event)

    # ------------------------------------------------------------ look
    def _style_chip(self):
        from ..design.typography import TITLE_FONT_STACK
        t = _theme()
        self.cc.setStyleSheet(
            f'QLabel#brandBubbleCC {{ background: {t.accent}; color: {t.text_on_accent or "#ffffff"};'
            f' font-family: {TITLE_FONT_STACK}; font-size: 9px; font-weight: 800; border-radius: 5px;'
            f' padding: 0 5px; min-height: 14px; max-height: 14px; letter-spacing: 0.5px; }}')

    def changeEvent(self, event):  # noqa: N802 - Qt override
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self._style_chip()
            self.update()
        super().changeEvent(event)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bubble = self.bubble_rect().adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_alpha(t.accent, 0.22))
        painter.drawRoundedRect(bubble.translated(0, LEDGE), RADIUS, RADIUS)
        painter.setBrush(QColor(t.surface_elevated))
        painter.setPen(QPen(QColor(t.accent), 2))
        painter.drawRoundedRect(bubble, RADIUS, RADIUS)
        # Three dots in the lower right, as if she were still typing; they lift a little with her peek.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_alpha(t.accent, 0.45))
        for index in range(3):
            lift = self._peek * (3.0 - index * 0.6)
            centre = QPoint(round(bubble.right() - 30 + index * 8), round(bubble.bottom() - 15 - lift))
            painter.drawEllipse(centre, 2.5, 2.5)
        painter.end()


__all__ = ['BrandBubble', 'BrandHead', 'BrandPlate', 'Caret']
