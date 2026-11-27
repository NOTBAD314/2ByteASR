"""Things 兔白 holds while she is busy with the software's own parts (2026-11-26).

User (2026-11-26): with her dialog box folded away she should really pick up a wrench and mend the
AI settings gear, and really read the term library's book (``app/bunny_errands.py``). These are
drawn in code on the rig's canvas (900 x 888), in her body's frame, so they turn, squash and mirror
with her: ``BunnyMascot.hold(name)`` / ``drop_prop()``.

* ``PROPS``: name -> ``Prop(paw, back, front)``. ``paw`` is the paw whose shift and turn the prop
  follows (``'right'``, ``'left'`` or ``''`` for her body); ``back(painter, t, s)`` is painted just
  before her paws (so the paws hold it), ``front`` after every layer (sparks over everything).
  ``t`` is seconds since she took it.
* ``paw_point`` maps a canvas point through a paw's (dx, dy, turn, grow), like ``_draw_paws``;
  ``wrench_jaw`` is where the wrench's head is when it comes down in the 'strike' move
  (``bunny_moves.STRIKE_PAW``), for placing her so it lands on a gear.
* A prop pops in when she takes it and shrinks away when she puts it back (``grow_about``).

Round 2 (user: the gear fix looked odd and never landed): the wrench is swung down onto the gear
instead of turned about her paw; its sparks are drawn where it lands (``app/bunny_overlay``).

Pure painting; no widgets.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

PAW_PIVOT = {'left': (425.0, 612.0), 'right': (492.0, 612.0)}
WRENCH_GRIP = (500.0, 618.0)         # in the right paw
WRENCH_JAW = (652.0, 566.0)          # the open end, before the paw's own turn
READ_PERIOD = 2.6                    # bunny_moves 'read' loop
CLOTH_AT = (538.0, 604.0)            # the polishing cloth in the right paw
STEEL, STEEL_DARK, STEEL_EDGE, GRIP = '#d6dee8', '#93a2b5', '#4d5768', '#ff8fb1'
COVER, COVER_EDGE, PAGE, PAGE_EDGE, INK, RIBBON = '#c75b7a', '#8e3a55', '#fffaf0', '#d9cbb4', '#b3a58f', '#ffc531'


def _color(name, alpha=1.0):
    from PySide6.QtGui import QColor
    color = QColor(name)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


def paw_point(point, side: str, paw) -> tuple[float, float]:
    """``point`` (canvas) carried by the ``side`` paw shifted, turned and grown about its pivot (dx, dy, turn, grow)."""
    dx, dy, turn, *rest = paw
    return _through(point, PAW_PIVOT[side], dx, dy, turn, rest[0] if rest else 1.0)


def _through(point, pivot, dx, dy, turn, grow):
    a = math.radians(turn)
    x, y = (point[0] - pivot[0]) * grow, (point[1] - pivot[1]) * grow
    return (pivot[0] + x * math.cos(a) - y * math.sin(a) + dx, pivot[1] + x * math.sin(a) + y * math.cos(a) + dy)


def wrench_jaw(paw=None) -> tuple[float, float]:
    """Where the wrench's open end is when the right paw is at ``paw`` (canvas units); by default
    the moment it comes down in the 'strike' move."""
    if paw is None:
        from .bunny_moves import STRIKE_PAW
        paw = STRIKE_PAW
    dx, dy, turn, *rest = paw
    return _through(WRENCH_JAW, PAW_PIVOT['right'], dx, dy, turn, rest[0] if rest else 1.0)


# ------------------------------------------------------------------ the wrench
def _wrench(painter, t, s):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QLinearGradient, QPainterPath, QPen
    gx, gy = WRENCH_GRIP
    jx, jy = WRENCH_JAW
    length = math.hypot(jx - gx, jy - gy)
    painter.save()
    painter.translate(gx * s, gy * s)
    painter.rotate(math.degrees(math.atan2(jy - gy, jx - gx)))
    painter.scale(s, s)
    edge = QPen(_color(STEEL_EDGE), 5)
    # The handle, steel with a light stripe, and a pink rubber grip where her paw holds it.
    steel = QLinearGradient(QPointF(0, -14), QPointF(0, 14))
    steel.setColorAt(0.0, _color(STEEL))
    steel.setColorAt(1.0, _color(STEEL_DARK))
    painter.setPen(edge)
    painter.setBrush(steel)
    painter.drawRoundedRect(QRectF(-26, -12, length + 6, 24), 12, 12)
    painter.setBrush(_color(GRIP))
    painter.drawRoundedRect(QRectF(-30, -15, 70, 30), 15, 15)
    painter.setPen(QPen(_color('#ffffff', .8), 4))
    for x in (-10, 6, 22):
        painter.drawLine(QPointF(x, -9), QPointF(x + 6, 9))
    # The open end: a round head with a mouth facing forward.
    head = QPainterPath()
    head.addEllipse(QPointF(length, 0), 34, 34)
    mouth = QPainterPath()
    mouth.addRoundedRect(QRectF(length + 2, -14, 50, 28), 6, 6)
    head = head.subtracted(mouth)
    painter.setPen(edge)
    painter.setBrush(steel)
    painter.drawPath(head)
    painter.setPen(QPen(_color('#ffffff', .85), 5))
    painter.drawArc(QRectF(length - 24, -24, 48, 48), 100 * 16, 70 * 16)
    painter.drawLine(QPointF(4, -5), QPointF(length - 40, -5))
    painter.restore()


# ------------------------------------------------------------------ the book
BOOK_TOP, BOOK_BOTTOM, BOOK_HALF, SPINE = 588.0, 676.0, 128.0, 458.0


def _page(left: bool, lift: float = 0.0):
    """One open page as a path (canvas units): the outer edge a little higher, sagging to the spine."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    side = -1 if left else 1
    outer = SPINE + side * BOOK_HALF
    path = QPainterPath(QPointF(SPINE, BOOK_TOP + 10 - lift))
    path.cubicTo(QPointF(SPINE + side * 40, BOOK_TOP - 4 - lift), QPointF(outer - side * 30, BOOK_TOP - 8 - lift),
                 QPointF(outer, BOOK_TOP - 2 - lift))
    path.lineTo(QPointF(outer, BOOK_BOTTOM - 10))
    path.cubicTo(QPointF(outer - side * 30, BOOK_BOTTOM - 16), QPointF(SPINE + side * 40, BOOK_BOTTOM - 10),
                 QPointF(SPINE, BOOK_BOTTOM))
    path.closeSubpath()
    return path


def _book(painter, t, s):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainterPath, QPen
    painter.save()
    painter.scale(s, s)
    # The cover peeking out around the pages, and the ribbon hanging from the spine.
    cover = QPainterPath()
    cover.addRoundedRect(QRectF(SPINE - BOOK_HALF - 10, BOOK_TOP - 14, 2 * BOOK_HALF + 20, BOOK_BOTTOM - BOOK_TOP + 26), 16, 16)
    painter.setPen(QPen(_color(COVER_EDGE), 5))
    painter.setBrush(_color(COVER))
    painter.drawPath(cover)
    painter.setPen(QPen(_color('#ffffff', .9), 3))
    painter.setBrush(_color(RIBBON))
    ribbon = QPainterPath(QPointF(SPINE + 8, BOOK_BOTTOM - 4))
    ribbon.lineTo(QPointF(SPINE + 22, BOOK_BOTTOM + 40))
    ribbon.lineTo(QPointF(SPINE + 14, BOOK_BOTTOM + 34))
    ribbon.lineTo(QPointF(SPINE + 6, BOOK_BOTTOM + 44))
    ribbon.closeSubpath()
    painter.drawPath(ribbon)
    for left in (True, False):
        painter.setPen(QPen(_color(PAGE_EDGE), 3))
        painter.setBrush(_color(PAGE))
        painter.drawPath(_page(left))
        # A few lines of words on each page; the first a little bolder, like a term and its note.
        side = -1 if left else 1
        for row in range(5):
            y = BOOK_TOP + 18 + row * 13
            near, far = SPINE + side * 18, SPINE + side * (BOOK_HALF - 16 - (24 if row % 3 == 2 else 0))
            painter.setPen(QPen(_color('#c75b7a' if row == 0 else INK, .85), 5 if row == 0 else 3.4))
            painter.drawLine(QPointF(min(near, far), y), QPointF(max(near, far), y))
    painter.setPen(QPen(_color(PAGE_EDGE), 4))
    painter.drawLine(QPointF(SPINE, BOOK_TOP + 8), QPointF(SPINE, BOOK_BOTTOM))
    painter.restore()


def _book_flip(painter, t, s):
    """Now and then a page lifts off the right side and turns over to the left."""
    from PySide6.QtGui import QPen, QTransform
    k = (t % READ_PERIOD) / READ_PERIOD
    if not .62 < k < .92:
        return
    f = (k - .62) / .30                          # 0..1 across the turn
    squeeze = math.cos(f * math.pi)              # 1 -> -1: the page's width seen from the front
    lift = math.sin(f * math.pi) * 26
    painter.save()
    painter.scale(s, s)
    page = _page(False, lift)
    flip = QTransform().translate(SPINE, 0).scale(squeeze if abs(squeeze) > .04 else .04, 1).translate(-SPINE, 0)
    painter.setPen(QPen(_color(PAGE_EDGE), 3))
    painter.setBrush(_color('#fffdf7' if squeeze > 0 else '#f3ead9'))
    painter.drawPath(flip.map(page))
    painter.restore()


# ------------------------------------------------------------------ the cloth
def _cloth(painter, t, s):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPen
    cx, cy = CLOTH_AT
    flap = 6 * math.sin(t * 2 * math.pi * 1.6)
    painter.save()
    painter.scale(s, s)
    path = QPainterPath(QPointF(cx - 34, cy - 30))
    path.cubicTo(QPointF(cx - 6, cy - 44), QPointF(cx + 26, cy - 34), QPointF(cx + 40, cy - 22 + flap))
    path.cubicTo(QPointF(cx + 46, cy + 4), QPointF(cx + 30, cy + 30), QPointF(cx + 6, cy + 34))
    path.cubicTo(QPointF(cx - 22, cy + 38), QPointF(cx - 44, cy + 14), QPointF(cx - 40, cy - 6))
    path.closeSubpath()
    painter.setPen(QPen(_color('#c75b7a'), 5))
    painter.setBrush(_color('#ffb3cf'))
    painter.drawPath(path)
    pen = QPen(_color('#ffffff', .9), 3.4)
    pen.setDashPattern([2.2, 2.4])
    painter.setPen(pen)
    painter.drawLine(QPointF(cx - 26, cy - 18), QPointF(cx + 26, cy + 18))
    painter.drawLine(QPointF(cx - 18, cy + 14), QPointF(cx + 22, cy - 16))
    painter.restore()


@dataclass(frozen=True)
class Prop:
    paw: str
    back: Callable
    front: Callable | None = None
    title: str = ''
    grow_about: tuple = (458.0, 612.0)        # it pops in and shrinks away about this canvas point


PROPS = {
    'wrench': Prop('right', _wrench, None, '小扳手', WRENCH_GRIP),
    'book': Prop('', _book, _book_flip, '术语库的书', (SPINE, (BOOK_TOP + BOOK_BOTTOM) / 2)),
    'cloth': Prop('right', _cloth, None, '擦东西的布', CLOTH_AT),
}


__all__ = ['PROPS', 'Prop', 'paw_point', 'wrench_jaw']
