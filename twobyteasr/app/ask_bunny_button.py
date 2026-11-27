"""「问问兔白」 as its own header button, left of 设置 (2026-11-14).

User (2026-11-14): 「问问兔白」 moves out of the 说明 menu into its own button
beside 设置, in an eye-catching colour; they picked draft A — a terracotta pill
with 兔白's face that softly "breathes" (a halo grows and fades every 2.6 s).
The colour is fixed, not the theme accent, so it stands out in every theme.
Compact headers show the face alone.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy

BREATH_MS = 2600
BREATH_FRAME_MS = 40
# 兔白's heights to prepare ahead: the chat card (BunnyChat.MASCOT_HEIGHT), the save question and
# the recovery question. Plain numbers so this button never imports the big chat module.
PREWARM_HEIGHTS = (150, 66, 70)

FILL = '#c4532c'
FILL_HOVER = '#d0603a'
FILL_PRESSED = '#a8441f'
LIP = '#8f3a1d'
RING = '#ffd9c7'
HALO = 7          # px the halo grows past the pill
FACE = 30


class AskBunnyButton(QPushButton):
    def __init__(self, text: str = '', parent=None):
        super().__init__(text, parent)
        self.setObjectName('askBunnyButton')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._phase = 0.
        # 2026-11-18 (user: the app should feel smooth everywhere): the halo used to run on a
        # looping QVariantAnimation — a repaint of this header button (and what is behind it) at
        # the animation clock's ~60 fps for as long as the app was open, even in the background.
        # A slow 2.6 s glow reads the same at 25 fps, and it rests while the window is not active.
        self._breath = QTimer(self)
        self._breath.setInterval(BREATH_FRAME_MS)
        self._breath.timeout.connect(self._breathe)
        self._breath_clock = QElapsedTimer()
        self._curve = QEasingCurve(QEasingCurve.Type.OutCubic)

    def _breathe(self) -> None:
        window = self.window()
        if window is not None and not window.isActiveWindow():
            if self._phase:
                self._phase = 0.
                self.update()
            return
        self._phase = self._curve.valueForProgress((self._breath_clock.elapsed() % BREATH_MS) / BREATH_MS)
        self.update()

    def _font(self) -> QFont:
        from ..design.typography import playful_font
        font = playful_font(self.font())     # 2026-11-26 (user): one of the few 猫啃什锦黑 places
        font.setPixelSize(15)
        font.setBold(True)
        return font

    def sizeHint(self):  # noqa: N802 - Qt override
        text = self.text()
        width = 5 + FACE + 5 if not text else 5 + FACE + 8 + QFontMetrics(self._font()).horizontalAdvance(text) + 16
        return QSize(width + 2 * HALO, 36 + 2 * HALO)

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        return self.sizeHint()

    def setText(self, text):  # noqa: N802 - Qt override
        super().setText(text)
        self.updateGeometry()
        self.update()

    def showEvent(self, event):  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self._breath_clock.isValid():
            self._breath_clock.start()
        self._breath.start()
        # 兔白's pictures for the chat card and the save question, prepared while nothing happens,
        # so neither opens on a stand-in picture that is swapped a moment later (2026-11-18).
        QTimer.singleShot(1200, self._prewarm_bunny)
        # Her word list for line breaks (jieba, ~0.6 s of loading) on a background thread, a little
        # later so it does not compete with the window's own first seconds.
        QTimer.singleShot(4000, self._prewarm_words)

    @staticmethod
    def _prewarm_words() -> None:
        try:
            from .tour_mascot import warm_words
            warm_words()
        except Exception:  # noqa: BLE001 - only a head start
            pass

    def _prewarm_bunny(self) -> None:
        try:
            from . import ui_zoom
            from ..design.mascot_assets import prewarm
            prewarm(tuple(ui_zoom.px(height) for height in PREWARM_HEIGHTS), self.devicePixelRatioF() or 1.0)
        except Exception:  # noqa: BLE001 - only a head start; the bunny prepares herself anyway
            pass

    def hideEvent(self, event):  # noqa: N802 - Qt override
        self._breath.stop()
        super().hideEvent(event)

    def enterEvent(self, event):  # noqa: N802 - Qt override
        self.update(); super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        self.update(); super().leaveEvent(event)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        from ..design.bunny_mascot import bunny_face_pixmap
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pill = QRectF(self.rect()).adjusted(HALO, HALO - 2, -HALO, -HALO - 2)
        down = self.isDown()
        lift = 1. if down else -1. if self.underMouse() else 0.
        radius = pill.height() / 2
        # Breathing halo.
        spread = HALO * self._phase
        halo = QColor(FILL)
        halo.setAlphaF(.45 * (1. - self._phase))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawRoundedRect(pill.adjusted(-spread, -spread, spread, spread), radius + spread, radius + spread)
        # 3 px lip under the pill, the pill on it.
        if not down:
            painter.setBrush(QColor(LIP))
            painter.drawRoundedRect(pill.translated(0, 3), radius, radius)
        body = pill.translated(0, lift + (2 if down else 0))
        painter.setBrush(QColor(FILL_PRESSED if down else FILL_HOVER if self.underMouse() else FILL))
        painter.drawRoundedRect(body, radius, radius)
        if self.hasFocus():
            painter.setPen(QPen(QColor('#ffffff'), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(body.adjusted(2, 2, -2, -2), radius - 2, radius - 2)
        # 兔白's face in a light ring.
        face = QRectF(body.left() + 5, body.center().y() - FACE / 2, FACE, FACE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(RING))
        painter.drawEllipse(face.adjusted(-2, -2, 2, 2))
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(face)
        clip = QPainterPath()
        clip.addEllipse(face)
        painter.save()
        painter.setClipPath(clip)
        pixmap = bunny_face_pixmap(FACE, self.devicePixelRatioF())
        painter.drawPixmap(face.topLeft().toPoint(), pixmap)
        painter.restore()
        if self.text():
            painter.setFont(self._font())
            painter.setPen(QColor('#ffffff'))
            painter.drawText(QRectF(face.right() + 8, body.top(), body.right() - face.right() - 8, body.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()
