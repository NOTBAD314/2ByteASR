"""Little things flying about on 兔白's clear layer while she plays with the page (2026-11-26).

User (2026-11-26): before she does something with a button it must be plain that she took it —
the term library's book flies out of its button into her paws and back again — and her hits must
land (sparks where the wrench strikes the gear). These are drawn on the puck's clear layer
(``bunny_puck._Carrier``), whose click mask grows to hold them while they last.

``FxOverlay`` is stepped by the caller's clock (``step(now)``), like ``design.bunny_button_fx``,
so a review can render exact frames. Window coordinates throughout (the layer lies on the window).
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

GOLD, WHITE, DUST, PINK = '#ffc531', '#ffffff', '#cdbfae', '#ff8fb1'


def _color(name, alpha=1.0):
    color = QColor(name)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


def _ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


class _Fly:
    __slots__ = ('pixmap', 'a', 'b', 't0', 'seconds', 'lift', 'grow', 'spin', 'done', 'fired')

    def __init__(self, pixmap, a, b, t0, seconds, lift, grow, spin, done):
        self.pixmap, self.a, self.b, self.t0, self.seconds = pixmap, QPointF(a), QPointF(b), t0, seconds
        self.lift, self.grow, self.spin, self.done, self.fired = lift, grow, spin, done, False

    def where(self, now):
        k = max(0.0, min(1.0, (now - self.t0) / self.seconds))
        e = _ease(k)
        x = self.a.x() + (self.b.x() - self.a.x()) * e
        y = self.a.y() + (self.b.y() - self.a.y()) * e - self.lift * math.sin(math.pi * k)
        scale = 1 + (self.grow - 1) * math.sin(math.pi * k * .5)
        return k, QPointF(x, y), scale, self.spin * e


class _Burst:
    __slots__ = ('kind', 'at', 't0', 'seconds', 'direction', 'seed', 'size')

    def __init__(self, kind, at, t0, seconds, direction, size):
        self.kind, self.at, self.t0, self.seconds = kind, QPointF(at), t0, seconds
        self.direction, self.size, self.seed = direction, size, random.random() * 1000


class FxOverlay(QWidget):
    def __init__(self, carrier):
        super().__init__(carrier)
        self.setObjectName('bunnyFxOverlay')
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._flies: list[_Fly] = []
        self._bursts: list[_Burst] = []
        self.now = 0.0
        self.hide()

    # ------------------------------------------------------------ what flies
    def fly(self, pixmap, a: QPointF, b: QPointF, now: float, seconds: float, lift: float = 50.0,
            grow: float = 1.6, spin: float = 0.0, done=None):
        """``pixmap`` (e.g. a button's icon) flies from ``a`` to ``b`` in an arc; ``done`` runs on arrival."""
        self._flies.append(_Fly(pixmap, a, b, now, max(.05, seconds), lift, grow, spin, done))
        self._sound('pop')
        self._show()

    # 2026-11-27: what each effect sounds like (bunny_sfx); spark and tap come with their own hit sound.
    BURST_SOUNDS = {'sparkle': 'sparkle', 'dust': 'puff', 'hearts': 'pat', 'notes': 'sparkle'}

    def _sound(self, name):
        sound = getattr(self, 'sound', None)
        if callable(sound) and name:
            try:
                sound(name)
            except Exception:  # noqa: BLE001
                pass

    def burst(self, kind: str, at: QPointF, now: float, seconds: float = .6, direction: float = 0.0,
              size: float = 1.0):
        """'spark' (a hit), 'sparkle' (shiny), 'dust' (blown off), 'tap' (a knock), 'hearts', 'notes'."""
        self._bursts.append(_Burst(kind, at, now, max(.05, seconds), direction, size))
        self._sound(self.BURST_SOUNDS.get(kind))
        self._show()

    def _show(self):
        parent = self.parentWidget()
        if parent is not None and self.geometry() != parent.rect():
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        bubble = getattr(parent, 'bubble', None)
        if bubble is not None and bubble.isVisible():
            bubble.raise_()

    def busy(self) -> bool:
        return bool(self._flies or self._bursts)

    def clear(self):
        self._flies.clear()
        self._bursts.clear()
        self.hide()

    def bounds(self) -> QRect:
        """Where anything is drawn now (window coordinates), for the layer's mask."""
        rect = QRectF()
        for fly in self._flies:
            _k, at, scale, _turn = fly.where(self.now)
            r = max(fly.pixmap.width(), fly.pixmap.height()) / max(1.0, fly.pixmap.devicePixelRatio()) * scale
            rect = rect.united(QRectF(at.x() - r, at.y() - r, 2 * r, 2 * r))
            rect = rect.united(QRectF(fly.a.x() - 4, fly.a.y() - fly.lift - r, 8, 8))
            rect = rect.united(QRectF(fly.b.x() - r, fly.b.y() - r, 2 * r, 2 * r))
        for burst in self._bursts:
            r = 70 * burst.size
            rect = rect.united(QRectF(burst.at.x() - r, burst.at.y() - r, 2 * r, 2 * r))
        return rect.toAlignedRect().adjusted(-6, -6, 6, 6) if not rect.isNull() else QRect()

    def step(self, now: float):
        self.now = now
        arrived = [fly for fly in self._flies if now - fly.t0 >= fly.seconds]
        self._flies = [fly for fly in self._flies if fly not in arrived]
        self._bursts = [burst for burst in self._bursts if now - burst.t0 < burst.seconds]
        for fly in arrived:
            if fly.done is not None and not fly.fired:
                fly.fired = True
                fly.done()
        if self.busy():
            self.update()
        elif self.isVisible():
            self.hide()

    # ------------------------------------------------------------ painting
    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        now = self.now
        for burst in self._bursts:
            k = (now - burst.t0) / burst.seconds
            getattr(self, '_draw_' + burst.kind, self._draw_sparkle)(painter, burst, max(0.0, min(1.0, k)))
        for fly in self._flies:
            k, at, scale, turn = fly.where(now)
            ratio = max(1.0, fly.pixmap.devicePixelRatio())
            w, h = fly.pixmap.width() / ratio * scale, fly.pixmap.height() / ratio * scale
            painter.save()
            painter.translate(at)
            painter.rotate(turn)
            # A soft glow under it so it reads as picked up, not as a stray icon.
            glow = _color(WHITE, .35 * math.sin(math.pi * k))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(0, 0), w * .62, h * .62)
            painter.drawPixmap(QRectF(-w / 2, -h / 2, w, h), fly.pixmap, QRectF(fly.pixmap.rect()))
            painter.restore()
        painter.end()

    def _draw_spark(self, painter, burst, k):
        cx, cy = burst.at.x(), burst.at.y()
        alpha = 1 - k
        for i in range(9):
            a = burst.direction + i * 2 * math.pi / 9 + math.sin(burst.seed + i) * .3
            inner, outer = (6 + 26 * k) * burst.size, (14 + 46 * k) * burst.size
            painter.setPen(QPen(_color(GOLD, alpha), (3.2 - 1.8 * k) * burst.size))
            painter.drawLine(QPointF(cx + math.cos(a) * inner, cy + math.sin(a) * inner),
                             QPointF(cx + math.cos(a) * outer, cy + math.sin(a) * outer))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color('#fff6c8', alpha))
        painter.drawEllipse(QPointF(cx, cy), (9 - 6 * k) * burst.size, (9 - 6 * k) * burst.size)

    def _draw_tap(self, painter, burst, k):
        cx, cy = burst.at.x(), burst.at.y()
        painter.setPen(QPen(_color(WHITE, (1 - k) * .9), 2.4))
        for i in (-1, 0, 1):
            a = burst.direction + i * .55
            r0, r1 = 8 + 10 * k, 16 + 12 * k
            painter.drawLine(QPointF(cx + math.cos(a) * r0, cy + math.sin(a) * r0),
                             QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1))

    @staticmethod
    def _star(cx, cy, r):
        path = QPainterPath(QPointF(cx, cy - r))
        for px, py in ((cx + r * .22, cy - r * .22), (cx + r, cy), (cx + r * .22, cy + r * .22), (cx, cy + r),
                       (cx - r * .22, cy + r * .22), (cx - r, cy), (cx - r * .22, cy - r * .22), (cx, cy - r)):
            path.lineTo(QPointF(px, py))
        return path

    def _draw_sparkle(self, painter, burst, k):
        rng = random.Random(burst.seed)
        for i in range(6):
            dx, dy = rng.uniform(-1, 1) * 46 * burst.size, rng.uniform(-1, 1) * 22 * burst.size
            delay = i * .08
            local = max(0.0, min(1.0, (k - delay) / .6))
            if not 0 < local < 1:
                continue
            r = 9 * burst.size * math.sin(math.pi * local)
            painter.setPen(QPen(_color(WHITE, .9), 1.4))
            painter.setBrush(_color(GOLD, 1.0))
            painter.drawPath(self._star(burst.at.x() + dx, burst.at.y() + dy, r))

    def _draw_dust(self, painter, burst, k):
        rng = random.Random(burst.seed)
        painter.setPen(Qt.PenStyle.NoPen)
        for _i in range(10):
            spread = burst.direction + rng.uniform(-.7, .7)
            speed = rng.uniform(30, 70) * burst.size
            x = burst.at.x() + math.cos(spread) * speed * k
            y = burst.at.y() + math.sin(spread) * speed * k - 10 * k
            r = (4 + 7 * k) * rng.uniform(.7, 1.2) * burst.size
            painter.setBrush(_color(DUST, .7 * (1 - k)))
            painter.drawEllipse(QPointF(x, y), r, r)

    def _draw_hearts(self, painter, burst, k):
        from ..design.bunny_moves import _heart_path
        rng = random.Random(burst.seed)
        for i in range(3):
            local = max(0.0, min(1.0, (k - i * .15) / .7))
            if local <= 0:
                continue
            x = burst.at.x() + rng.uniform(-24, 24)
            y = burst.at.y() - 40 * local
            painter.setPen(QPen(_color(WHITE, 1 - local), 1.4))
            painter.setBrush(_color(PINK, 1 - local))
            painter.drawPath(_heart_path(x, y, 8 * burst.size))


__all__ = ['FxOverlay']
