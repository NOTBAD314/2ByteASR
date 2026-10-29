"""Tutorial gestures drawn in the app's own look (2026-10-21).

User, after the first cloud-first round: the animations "do not fit the
software". They were pre-rendered WebP files in fixed pink, green, red and
yellow with emoji, while the app has fifteen themes and a quiet, flat look.
These scenes draw small copies of the app's own parts - a role card, the
Studio timeline with its cue blocks and playhead, a subtitle row, a dropdown,
a button - with the current theme's colours and the app's Font Awesome icons.
They match every theme, stay sharp at any scale, and their few interface words
follow the interface language (sample subtitles are content and stay as they
are).

``SCENES[name]`` is ``Scene(duration_ms, still, draw)``; ``draw(Draw, t)`` paints
the moment ``t`` (ms) on a 440 x 187 canvas that ``home_tour.TourAnim`` scales
to its own size. ``still`` is the moment shown when reduced motion is asked
for. Motion stays calm: short slides with an ease-out, no bouncing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF

from ..i18n import tr

WIDTH, HEIGHT = 440.0, 187.0


# ---------------------------------------------------------------- timing
def ease(v: float) -> float:
    """Cubic ease-out (the app's standard motion)."""
    v = max(0.0, min(1.0, v))
    return 1 - (1 - v) ** 3


def span(t: float, start: float, end: float) -> float:
    """0 before ``start``, 1 after ``end``, eased in between."""
    if end <= start:
        return 1.0 if t >= end else 0.0
    return ease((t - start) / (end - start))


def track(t: float, keys) -> float | tuple:
    """Value at ``t`` for keyframes ``[(ms, value), ...]`` (numbers or tuples), eased between them."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (a, va), (b, vb) in zip(keys, keys[1:]):
        if t <= b:
            v = span(t, a, b)
            if isinstance(va, tuple):
                return tuple(x + (y - x) * v for x, y in zip(va, vb))
            return va + (vb - va) * v
    return keys[-1][1]


def shown(t: float, start: float, end: float | None = None, fade: float = 220) -> float:
    """Opacity: fades in at ``start``, out at ``end``."""
    value = span(t, start, start + fade)
    if end is not None:
        value *= 1 - span(t, end, end + fade)
    return value


# ---------------------------------------------------------------- the theme's colours
class Look:
    """The theme tokens the scenes use (the same names the app's style sheets use)."""

    def __init__(self, theme):
        self.light = bool(theme.is_light)
        self.text = QColor(theme.text)
        self.secondary = QColor(theme.text_secondary)
        self.muted = QColor(theme.text_muted)
        self.surface = QColor(theme.surface)
        self.elevated = QColor(theme.surface_elevated)
        self.input = QColor(theme.input_surface)
        self.border = QColor(theme.border)
        self.accent = QColor(theme.accent)
        self.accent_tint = QColor(theme.accent_tint)
        self.on_accent = QColor(theme.text_on_accent)
        self.success = QColor(theme.success)
        self.success_soft = QColor(theme.success_soft)
        self.warning = QColor(theme.warning)
        self.warning_soft = QColor(theme.warning_soft)
        self.danger = QColor(theme.danger)
        self.media = QColor(theme.media)
        self.media_accent = QColor(theme.media_accent)
        self.timeline = QColor(theme.timeline_background)
        self.grid = QColor(theme.timeline_grid)
        self.playhead = QColor(theme.timeline_playhead)
        roles = dict(theme.role_colors or {})
        self.role = {key: QColor(roles.get(key, theme.accent)) for key in ('primary', 'timeline', 'review')}
        # The demo area: a little inset from the bubble, like the app's inner panels.
        stage = QColor(theme.surface_elevated)
        back = QColor(theme.app_background)
        self.stage = QColor(*(round(a + (b - a) * 0.45) for a, b in zip(stage.getRgb()[:3], back.getRgb()[:3])))


def faded(color: QColor, alpha: float) -> QColor:
    value = QColor(color)
    value.setAlphaF(max(0.0, min(1.0, color.alphaF() * alpha)))
    return value


def mix(a: QColor, b: QColor, v: float) -> QColor:
    v = max(0.0, min(1.0, v))
    return QColor(*(round(x + (y - x) * v) for x, y in zip(a.getRgb(), b.getRgb())))


# ---------------------------------------------------------------- drawing helpers
class Draw:
    """A painter, the theme and the app font, with the few shapes the scenes are made of."""

    _icons: dict = {}

    def __init__(self, painter: QPainter, look: Look, font: QFont, ratio: float = 2.0):
        self.p, self.look, self.font, self.ratio = painter, look, QFont(font), ratio

    # -- shapes
    def box(self, x, y, w, h, fill=None, border=None, radius=10.0, alpha=1.0, width=1.0, dash=False):
        if alpha <= 0.003:
            return
        p = self.p
        if border is not None:
            pen = QPen(faded(border, alpha), width)
            if dash:
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setDashPattern([4, 3])
            p.setPen(pen)
        else:
            p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(faded(fill, alpha) if fill is not None else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    def stage(self):
        self.box(0.5, 0.5, WIDTH - 1, HEIGHT - 1, self.look.stage, faded(self.look.border, 0.7), radius=14)

    def card(self, x, y, w, h, alpha=1.0, highlight=0.0, radius=10.0):
        """An app card: surface, hairline border; ``highlight`` turns the border into the accent outline."""
        look = self.look
        self.box(x, y, w, h, look.surface, mix(look.border, look.accent, highlight), radius, alpha,
                 1.0 + 1.0 * highlight)

    def text(self, x, y, value, size=13, weight=QFont.Weight.Medium, color=None, alpha=1.0, align='left',
             width=0.0, ui=False):
        """``y`` is the text's vertical centre. ``ui``: an interface word (translated)."""
        if alpha <= 0.003 or not value:
            return 0.0
        value = str(tr(value)) if ui else str(value)
        font = QFont(self.font)
        font.setPixelSize(int(round(size)))
        font.setWeight(weight)
        p = self.p
        p.setFont(font)
        p.setPen(faded(color or self.look.text, alpha))
        advance = p.fontMetrics().horizontalAdvance(value)
        if width and advance > width:   # never spill out of its box: elide
            value = p.fontMetrics().elidedText(value, Qt.TextElideMode.ElideRight, int(width))
            advance = p.fontMetrics().horizontalAdvance(value)
        left = x - advance / 2 if align == 'center' else (x - advance if align == 'right' else x)
        p.drawText(QRectF(left, y - size, advance + 2, size * 2), Qt.AlignmentFlag.AlignVCenter, value)
        return advance

    def measure(self, value, size=13, weight=QFont.Weight.Medium, ui=False) -> float:
        font = QFont(self.font)
        font.setPixelSize(int(round(size)))
        font.setWeight(weight)
        self.p.setFont(font)
        return self.p.fontMetrics().horizontalAdvance(str(tr(value)) if ui else str(value))

    def icon(self, name, cx, cy, size, color, alpha=1.0):
        if alpha <= 0.003:
            return
        key = (name, color.name(QColor.NameFormat.HexArgb), int(size), self.ratio)
        pixmap = self._icons.get(key)
        if pixmap is None:
            try:
                import qtawesome as qta
                pixmap = qta.icon(name, color=color).pixmap(int(size * self.ratio), int(size * self.ratio))
                pixmap.setDevicePixelRatio(self.ratio)
            except Exception:  # noqa: BLE001 - a missing glyph leaves a gap, never a crash
                pixmap = False
            self._icons[key] = pixmap
        if not pixmap:
            return
        self.p.setOpacity(alpha)
        self.p.drawPixmap(QRectF(cx - size / 2, cy - size / 2, size, size), pixmap, QRectF(pixmap.rect()))
        self.p.setOpacity(1.0)

    def chip(self, x, cy, label, fill, color, alpha=1.0, size=11.5, icon='', ui=True, height=22.0):
        """A small rounded status chip like the home cards' (returns its width)."""
        pad = 9.0
        icon_w = size + 4 if icon else 0
        w = self.measure(label, size, QFont.Weight.DemiBold, ui) + 2 * pad + icon_w
        self.box(x, cy - height / 2, w, height, fill, None, height / 2, alpha)
        if icon:
            self.icon(icon, x + pad + size / 2 - 1, cy, size, color, alpha)
        self.text(x + pad + icon_w, cy, label, size, QFont.Weight.DemiBold, color, alpha, ui=ui)
        return w

    def check(self, cx, cy, alpha=1.0, r=9.0):
        """The success mark: a filled circle with a check."""
        if alpha <= 0.003:
            return
        scale = 0.85 + 0.15 * alpha
        self.box(cx - r * scale, cy - r * scale, 2 * r * scale, 2 * r * scale, self.look.success, None, r * scale, alpha)
        self.icon('fa5s.check', cx, cy, r * 1.05, self.look.surface, alpha)

    def button(self, x, y, w, h, label, primary=True, pressed=0.0, alpha=1.0, icon='', size=13.0):
        look = self.look
        if primary:
            fill = mix(look.accent, look.text if look.light else look.media, 0.18 * pressed)
            self.box(x, y + pressed, w, h, fill, None, 8, alpha)
            color = look.on_accent
        else:
            self.box(x, y + pressed, w, h, mix(look.surface, look.accent_tint, pressed), look.border, 8, alpha)
            color = look.text
        text_w = self.measure(label, size, QFont.Weight.DemiBold, True)
        icon_w = size + 6 if icon else 0
        left = x + (w - text_w - icon_w) / 2
        if icon:
            self.icon(icon, left + size / 2, y + h / 2 + pressed, size, color, alpha)
        self.text(left + icon_w, y + h / 2 + pressed, label, size, QFont.Weight.DemiBold, color, alpha, ui=True)

    def combo(self, x, y, w, h, value, alpha=1.0, open_=0.0, ui=True, highlight=0.0):
        look = self.look
        self.box(x, y, w, h, look.input, mix(look.border, look.accent, max(open_, highlight)), 8, alpha,
                 1.0 + max(open_, highlight) * 0.6)
        self.text(x + 12, y + h / 2, value, 12.5, QFont.Weight.Medium, look.text, alpha, width=w - 40, ui=ui)
        self.icon('fa5s.chevron-down', x + w - 16, y + h / 2, 10, look.muted, alpha)

    def caption(self, x, y, value, alpha=1.0):
        self.text(x, y, value, 11, QFont.Weight.DemiBold, self.look.muted, alpha, ui=True)

    def wave(self, x, y, w, h, color, loud=None, alpha=1.0, step=5.0, seed=0.0):
        """Waveform bars; ``loud`` = [(x0, x1), ...] where someone speaks (elsewhere a flat line)."""
        if alpha <= 0.003:
            return
        p = self.p
        p.setPen(Qt.PenStyle.NoPen)
        position = 0.0
        while position < w:
            speaking = loud is None or any(a <= position <= b for a, b in loud)
            level = (0.25 + 0.75 * abs(math.sin(position * 0.19 + seed) * 0.7 + math.sin(position * 0.053 + seed) * 0.3)
                     if speaking else 0.06)
            bar = max(2.0, h * level)
            p.setBrush(faded(color, alpha * (1.0 if speaking else 0.6)))
            p.drawRoundedRect(QRectF(x + position, y + (h - bar) / 2, 2.2, bar), 1.1, 1.1)
            position += step

    def cue(self, x, y, w, h, color, label='', alpha=1.0, selected=0.0):
        """A Studio cue block: tinted fill, hairline border, the speaker stripe on its left."""
        look = self.look
        fill = mix(look.timeline, color, 0.30 + 0.12 * selected)
        border = mix(look.timeline, color, 0.75)
        self.box(x, y, w, h, fill, mix(border, look.accent, selected), 5, alpha, 1.2 + selected)
        self.box(x + 1, y + 1, 3, h - 2, color, None, 1.5, alpha)
        if label:
            self.text(x + 10, y + h / 2, label, 11.5, QFont.Weight.DemiBold, look.text, alpha, width=w - 14)

    def cursor(self, x, y, pressed=0.0, alpha=1.0):
        """The pointer the tutorial moves (the app's text colour, outlined in its surface)."""
        if alpha <= 0.003:
            return
        p = self.p
        scale = 1.0 - 0.12 * pressed
        shape = QPolygonF([QPointF(x + dx * scale, y + dy * scale) for dx, dy in
                           ((0, 0), (0, 17), (4.6, 13), (7.6, 19.4), (10.4, 18.2), (7.4, 11.8), (13, 11.8))])
        p.setPen(QPen(faded(self.look.surface, alpha), 1.4))
        p.setBrush(faded(self.look.text, alpha))
        p.drawPolygon(shape)

    def ripple(self, x, y, t, at):
        """A click: a ring in the accent colour that widens and fades."""
        v = (t - at) / 480.0
        if not 0.0 <= v <= 1.0:
            return
        r = 6 + 16 * ease(v)
        p = self.p
        p.setPen(QPen(faded(self.look.accent, 1 - v), 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(x, y), r, r)

    def pointer(self, t, path, clicks=()):
        """Move the cursor along ``path`` = [(ms, x, y), ...] and click at ``clicks`` (ms)."""
        x, y = track(t, [(ms, (px, py)) for ms, px, py in path])
        pressed = max((1 - abs(t - at - 90) / 110 if abs(t - at - 90) < 110 else 0.0) for at in clicks) if clicks else 0.0
        for at in clicks:
            cx, cy = track(at, [(ms, (px, py)) for ms, px, py in path])
            self.ripple(cx + 2, cy + 2, t, at)
        self.cursor(x, y, pressed)

    def keycap(self, x, y, label, down=0.0, size=30.0):
        look = self.look
        self.box(x, y + 3, size, size, faded(look.border, 1.0), None, 7)
        self.box(x, y + 3 * down, size, size, mix(look.surface, look.accent, down), look.border, 7)
        self.text(x + size / 2, y + 3 * down + size / 2, label, 13, QFont.Weight.Bold,
                  mix(look.text, look.on_accent, down), align='center')

    def underline(self, x0, x1, y, color, alpha=1.0, wavy=True):
        if alpha <= 0.003:
            return
        path = QPainterPath(QPointF(x0, y))
        position = x0
        up = True
        while position < x1:
            position = min(x1, position + 3)
            path.lineTo(position, y + (-1.6 if up and wavy else 1.6 if wavy else 0))
            up = not up
        self.p.setPen(QPen(faded(color, alpha), 1.4))
        self.p.setBrush(Qt.BrushStyle.NoBrush)
        self.p.drawPath(path)


@dataclass(frozen=True)
class Scene:
    duration: int
    still: float
    draw: Callable[[Draw, float], None]


# ---------------------------------------------------------------- scenes
def drop(d: Draw, t: float) -> None:
    """① A video file goes onto the drop area and shows up as loaded."""
    look = d.look
    d.stage()
    over = span(t, 1050, 1300) * (1 - span(t, 2000, 2300))
    d.box(176, 30, 236, 126, faded(look.accent_tint, over), mix(look.border, look.accent, over), 12, width=1.4, dash=True)
    d.icon('fa5s.cloud-upload-alt', 294, 74, 26, mix(look.muted, look.accent, over), 1 - span(t, 1700, 1900))
    x, y = track(t, [(0, (44.0, 64.0)), (350, (44.0, 64.0)), (1500, (262.0, 64.0)), (3050, (262.0, 64.0)), (3150, (44.0, 64.0))])
    gone = span(t, 1500, 1750) * (1 - span(t, 3000, 3150))
    tile = 1 - gone
    d.card(x, y, 64 * (1 - 0.3 * gone), 54 * (1 - 0.3 * gone), alpha=tile)
    d.icon('fa5s.film', x + 32, y + 27, 22, look.accent, tile)
    loaded = shown(t, 1800, 2900)
    d.card(196, 76, 196, 38, alpha=loaded)
    d.check(214, 95, loaded, 8)
    d.icon('fa5s.film', 236, 95, 14, look.accent, loaded)
    d.text(250, 95, 'clip.mp4', 12, QFont.Weight.Medium, look.secondary, loaded)
    d.pointer(t, [(0, 70, 120), (350, 76, 92), (1500, 294, 92), (2200, 330, 140), (3000, 330, 140), (3150, 76, 92)])


def spoken(d: Draw, t: float) -> None:
    """② Pick the language the people in the video speak; the subtitles come out in it."""
    look = d.look
    d.stage()
    d.caption(30, 30, '视频里说的话')
    opened = span(t, 650, 800) * (1 - span(t, 1550, 1700))
    d.combo(30, 44, 200, 34, '日语' if t >= 1600 else '自动识别语言', open_=opened)
    menu = opened
    if menu > 0.01:
        d.box(30, 84 - 6 * (1 - menu), 200, 92, look.elevated, look.border, 8, menu)
        for row, label in enumerate(('简体中文', '日语', '英语')):
            hover = span(t, 1200, 1300) if row == 1 else 0.0
            d.box(36, 90 + row * 28 - 6 * (1 - menu), 188, 26, faded(look.accent_tint, hover), None, 6, menu)
            d.text(48, 103 + row * 28 - 6 * (1 - menu), label, 12.5, QFont.Weight.Medium, look.text, menu, ui=True)
    d.box(256, 34, 160, 118, look.media, None, 8)
    d.wave(276, 54, 120, 24, faded(look.muted, 0.8), alpha=0.5 + 0.5 * span(t, 2000, 2200))
    line = shown(t, 2200, 3550)
    d.text(336, 128 - 5 * (1 - line), 'こんにちは、みんな', 14, QFont.Weight.Bold, QColor('#ffffff'), line, align='center')
    d.pointer(t, [(0, 150, 160), (300, 150, 160), (580, 160, 62), (900, 160, 62), (1150, 120, 118), (1700, 120, 118),
                  (2400, 210, 166)], (650, 1300))


def moss_signup(d: Draw, t: float) -> None:
    """③ 主力转写 → MOSS Pro: sign up (free credit, again every day), the key goes into the card."""
    look = d.look
    d.stage()
    picked = span(t, 600, 760)
    done = span(t, 3450, 3650)
    d.card(22, 26, 184, 134, highlight=max(picked * (1 - done), 0.0) if t < 3450 else 0.0)
    if done:
        d.box(22, 26, 184, 134, None, look.success, 10, done, 1.6)
    d.text(38, 44, '主力转写', 11, QFont.Weight.Bold, look.role['primary'], ui=True)
    if t < 3450:
        d.chip(118, 44, '未配置', look.warning_soft, look.warning, height=20, size=10.5)
    else:
        d.chip(118, 44, '已配置', look.success_soft, look.success, done, height=20, size=10.5)
    d.box(38, 64, 38, 38, look.accent_tint, None, 9)
    d.icon('fa5s.wave-square', 57, 83, 18, look.role['primary'])
    d.text(86, 76, 'MOSS Pro', 16, QFont.Weight.Bold, look.text)
    d.text(86, 94, 'MOSI', 11, QFont.Weight.Medium, look.muted)
    d.wave(38, 120, 150, 22, faded(look.role['primary'], 0.7), step=5.5)
    site = shown(t, 900)
    sx = 228 + 10 * (1 - site)
    d.card(sx, 26, 190, 134, alpha=site)
    for i in range(3):
        d.box(sx + 12 + i * 10, 38, 6, 6, look.border, None, 3, site)
    d.box(sx + 46, 35, 132, 12, look.input, None, 6, site)
    gift = shown(t, 1300)
    d.icon('fa5s.gift', sx + 30, 76, 20, look.accent, site * gift)
    d.chip(sx + 48, 76, '+50', look.success_soft, look.success, site * gift, size=12, ui=False)
    daily = shown(t, 1700)
    d.icon('fa5s.calendar-check', sx + 120, 76, 20, look.accent, site * daily)
    d.check(sx + 150, 70, site * daily, 7)
    # The key: shown on the site, copied, carried into the card.
    key_in = shown(t, 2200, 3350, 200)
    kx, ky = track(t, [(0, (sx + 22, 116.0)), (2600, (sx + 22, 116.0)), (3300, (64.0, 122.0))])
    if key_in > 0.003:
        width = d.measure('sk-••••••', 12, QFont.Weight.DemiBold) + 40
        d.box(kx, ky - 13, width, 26, look.accent, None, 13, key_in)
        d.icon('fa5s.key', kx + 15, ky, 12, look.on_accent, key_in)
        d.text(kx + 28, ky, 'sk-••••••', 12, QFont.Weight.DemiBold, look.on_accent, key_in)
    d.check(196, 34, done, 9)
    d.pointer(t, [(0, 120, 176), (300, 120, 176), (520, 110, 100), (820, 110, 100), (1900, sx + 60, 150),
                  (2300, sx + 50, 120), (2600, sx + 50, 120), (3300, 94, 126), (4200, 200, 176)], (600, 2380))


def plan_ok(d: Draw, t: float) -> None:
    """③ (another plan) The three role cards already hold the recommended models."""
    look = d.look
    d.stage()
    for i, (role, label, icon) in enumerate((('primary', '主力转写', 'fa5s.wave-square'),
                                             ('timeline', '字幕时间轴', 'fa5s.clock'),
                                             ('review', '文字复核', 'fa5s.check-circle'))):
        x = 20 + i * 136
        d.card(x, 30, 124, 112, highlight=span(t, 500 + i * 450, 650 + i * 450) * (1 - span(t, 2600, 2800)))
        d.text(x + 12, 46, label, 11, QFont.Weight.Bold, look.role[role], width=100, ui=True)
        d.box(x + 12, 64, 36, 36, look.accent_tint, None, 9)
        d.icon(icon, x + 30, 82, 17, look.role[role])
        d.box(x + 12, 112, 92, 7, look.border, None, 3.5)
        d.box(x + 12, 124, 64, 7, look.border, None, 3.5)
        d.check(x + 112, 38, span(t, 650 + i * 450, 850 + i * 450))
    d.pointer(t, [(0, 70, 176), (500, 80, 150), (950, 216, 150), (1400, 352, 150), (2600, 220, 176)])


def timeline_mg(d: Draw, t: float) -> None:
    """④ Rough subtitle times (too early, too late) slide onto the voice; then each line shows exactly while it is said."""
    look = d.look
    d.stage()
    left, right = 18.0, 422.0
    d.box(left - 6, 14, right - left + 12, 112, look.timeline, None, 9)
    for i, label in enumerate(('00:01', '00:02', '00:03', '00:04')):
        x = left + 20 + i * 100
        d.box(x, 20, 1, 6, look.grid, None, 0)
        d.text(x + 4, 23, label, 9.5, QFont.Weight.Medium, look.muted)
    voice = ((48.0, 182.0), (232.0, 372.0))
    d.wave(left, 34, right - left, 36, look.muted, [(a - left, b - left) for a, b in voice], alpha=0.85)
    found = shown(t, 2150, 5500)
    for a, b in voice:
        d.box(a - 2, 32, b - a + 4, 40, faded(look.success, 0.14), None, 6, found)
        for x in (a, b):
            d.p.setPen(QPen(faded(look.success, found * 0.9), 1.2, Qt.PenStyle.DashLine))
            d.p.drawLine(QPointF(x, 30), QPointF(x, 118))
    speakers = (look.role['primary'], look.role['review'])
    rows = (('今天开新档', 22.0, voice[0], '-0.4s'), ('先打第一个 Boss', 262.0, voice[1], '+0.3s'))
    for i, (text, rough, (a, b), off) in enumerate(rows):
        x = track(t, [(0, rough), (1500 + i * 150, rough), (2200 + i * 150, a), (5500, a), (5750, rough)])
        d.cue(x, 84, b - a, 28, speakers[i], text)
        miss = 1 - span(t, 1400 + i * 150, 1650 + i * 150)
        miss = max(miss, span(t, 5550, 5750))
        d.text(x + (b - a) / 2, 122, off, 10.5, QFont.Weight.DemiBold, look.danger, miss, align='center')
        d.check(b - 4, 84, shown(t, 2300 + i * 150, 5500))
    t0, t1 = 2900.0, 5300.0
    head = shown(t, t0 - 150, t1, 150)
    hx = left + (right - left) * max(0.0, min(1.0, (t - t0) / (t1 - t0)))
    if head > 0.003:
        d.p.setPen(QPen(faded(look.playhead, head), 2))
        d.p.drawLine(QPointF(hx, 16), QPointF(hx, 124))
        d.box(hx - 5, 14, 10, 6, look.playhead, None, 2, head)
    d.box(130, 138, 180, 36, look.media, None, 8)
    for text, _rough, (a, b), _off in rows:
        inside = 1.0 if a <= hx <= b and t0 <= t <= t1 else 0.0
        if inside:
            d.text(220, 156, text, 14, QFont.Weight.Bold, QColor('#ffffff'), align='center')


def ai_polish(d: Draw, t: float) -> None:
    """⑤ AI makes the words read well: one long raw line with a wrong word → two clean lines, the word fixed."""
    look = d.look
    d.stage()
    raw = '今天我们来玩一下这个新版本然后呢先去打第一个'
    d.card(16, 14, 408, 40)
    d.text(28, 34, '00:03', 10.5, QFont.Weight.Medium, look.muted)
    w = d.text(70, 34, raw, 12.5, QFont.Weight.Medium, look.secondary, width=300)
    wrong = span(t, 800, 1000)
    d.text(70 + w, 34, '波斯', 12.5, QFont.Weight.Medium, mix(look.secondary, look.danger, wrong))
    d.underline(70 + w, 70 + w + d.measure('波斯', 12.5), 44, look.danger, wrong)
    sweep = span(t, 1300, 2150)
    if 0.0 < sweep < 1.0:
        x = 30 + 370 * sweep
        d.box(28, 18, x - 28, 32, faded(look.accent_tint, 0.8 * (1 - sweep * 0.3)), None, 6)
        d.icon('fa5s.magic', x, 34, 16, look.accent)
    d.icon('fa5s.chevron-down', 170, 66, 11, look.muted, shown(t, 2100, 5400))
    for i, (line, start) in enumerate((('今天来玩新版本，', 2300), ('先去打第一个 ', 2600))):
        a = shown(t, start, 5400)
        y = 78 + i * 44 + 6 * (1 - a)
        d.card(16, y, 300, 36, alpha=a)
        d.box(17, y + 1, 3, 34, look.success, None, 1.5, a)
        tw = d.text(30, y + 18, line, 14, QFont.Weight.Bold, look.text, a)
        if i == 1:
            d.text(30 + tw, y + 18, 'Boss', 14, QFont.Weight.Bold, look.success, a)
    for i, (icon, start) in enumerate((('fa5s.cut', 3000), ('fa5s.spell-check', 3400), ('fa5s.language', 3800))):
        a = shown(t, start, 5400)
        d.box(334, 78 + i * 31, 86, 27, look.accent_tint, None, 13.5, a)
        d.icon(icon, 377, 91.5 + i * 31, 16, look.accent, a)


def apikey(d: Draw, t: float) -> None:
    """⑥ The key is in; 测试连接 says whether it works."""
    look = d.look
    d.stage()
    d.card(16, 22, 408, 60)
    d.box(30, 36, 32, 32, look.accent_tint, None, 8)
    d.icon('fa5s.project-diagram', 46, 52, 15, look.accent)
    d.text(74, 44, 'AI 智能断句', 13, QFont.Weight.Bold, look.text, ui=True)
    d.text(74, 62, 'DeepSeek', 11, QFont.Weight.Medium, look.muted)
    pressed = 1 - abs(t - 1050) / 110 if abs(t - 1050) < 110 else 0.0
    d.button(298, 38, 112, 30, '测试连接', primary=False, pressed=pressed)
    d.box(16, 100, 250, 34, look.input, look.border, 8)
    d.icon('fa5s.key', 34, 117, 12, look.muted)
    typed = int(max(0.0, min(1.0, (t - 200) / 700)) * 10)
    d.text(48, 117, 'sk-' + '•' * typed, 12.5, QFont.Weight.Medium, look.text)
    spin = shown(t, 1150, 2050, 120)
    if spin > 0.003:
        d.p.setPen(QPen(faded(look.accent, spin), 2.2))
        d.p.setBrush(Qt.BrushStyle.NoBrush)
        d.p.drawArc(QRectF(284, 108, 18, 18), int((t * 0.6) % 360 * 16), 270 * 16)
    ok = shown(t, 2150)
    if ok > 0.003:
        d.chip(282, 117, '连接正常', look.success_soft, look.success, ok, icon='fa5s.check-circle')
    d.pointer(t, [(0, 200, 176), (400, 220, 160), (950, 352, 56), (1400, 352, 56), (2400, 380, 176)], (1000,))


def subtitle_lang(d: Draw, t: float) -> None:
    """⑦ 原文 + 翻译: the spoken line on top, its translation under it."""
    look = d.look
    d.stage()
    d.caption(20, 30, '字幕显示')
    d.combo(20, 42, 186, 32, '原文 + 翻译（双语）', highlight=span(t, 300, 500) * (1 - span(t, 1300, 1500)))
    d.caption(20, 96, '翻译成')
    d.combo(20, 108, 186, 32, '简体中文', ui=False, highlight=span(t, 1300, 1500) * (1 - span(t, 2300, 2500)))
    d.box(222, 22, 198, 142, look.media, None, 8)
    d.box(234, 34, 54, 6, faded(QColor('#ffffff'), 0.14), None, 3)
    original = shown(t, 500, 4150)
    d.text(321, 118 - 4 * (1 - original), '今日は新しいステージ', 13.5, QFont.Weight.Bold, QColor('#ffffff'), original,
           align='center')
    translated = shown(t, 1900, 4150)
    d.icon('fa5s.magic', 398, 140, 12, look.media_accent, shown(t, 1700, 2300))
    d.text(321, 140 - 4 * (1 - translated), '今天是新关卡', 13.5, QFont.Weight.Bold, look.media_accent, translated,
           align='center')


def glossary(d: Draw, t: float) -> None:
    """⑧ The game's name lets the glossary put names and terms right."""
    look = d.look
    d.stage()
    d.caption(20, 34, '游戏 / 内容名称')
    d.box(20, 46, 196, 34, look.input, mix(look.border, look.accent, span(t, 200, 400) * (1 - span(t, 1200, 1400))), 8)
    typed = '原神'[:int(max(0.0, min(1.0, (t - 400) / 500)) * 2 + 0.001)]
    d.text(32, 63, typed, 13, QFont.Weight.Medium, look.text)
    bx, by = track(t, [(0, (196.0, 63.0)), (1300, (196.0, 63.0)), (1900, (300.0, 110.0))])
    d.icon('fa5s.book', bx, by, 16, look.accent, shown(t, 1100, 1900, 160))
    d.card(236, 92, 184, 36)
    fixed = span(t, 1950, 2150)
    w = d.text(250, 110, '派', 13, QFont.Weight.Medium, look.text)
    d.text(250 + w, 110, '蒙' if fixed > 0.5 else '门', 13, QFont.Weight.Bold,
           look.success if fixed > 0.5 else look.danger)
    d.text(250 + w + d.measure('蒙', 13, QFont.Weight.Bold), 110, '又在旁边说个不停', 13, QFont.Weight.Medium,
           look.text, width=140)
    d.check(412, 92, shown(t, 2200))
    d.pointer(t, [(0, 120, 176), (300, 110, 70), (1300, 110, 70), (2400, 160, 176)], (300,))


def start(d: Draw, t: float) -> None:
    """⑨ 开始生成字幕: a short wait, then the subtitles are there."""
    look = d.look
    d.stage()
    pressed = 1 - abs(t - 760) / 110 if abs(t - 760) < 110 else 0.0
    d.button(110, 44, 220, 44, '开始生成字幕', primary=True, pressed=pressed, icon='fa5s.play-circle', size=14)
    bar = shown(t, 900, 2900)
    d.box(110, 108, 220, 6, look.border, None, 3, bar)
    d.box(110, 108, 220 * span(t, 950, 2250), 6, look.accent, None, 3, bar)
    done = shown(t, 2300, 2900)
    d.check(152, 140, done, 9)
    d.text(168, 140, '字幕已生成', 13, QFont.Weight.Bold, look.success, done, ui=True)
    d.pointer(t, [(0, 230, 176), (400, 236, 70), (1100, 236, 70), (1800, 330, 176)], (700,))


def export(d: Draw, t: float) -> None:
    """⑩ 导出字幕: pick a format, the file lands in a folder."""
    look = d.look
    d.stage()
    d.card(20, 30, 176, 112, highlight=span(t, 600, 760) * (1 - span(t, 1500, 1700)))
    d.box(36, 46, 36, 36, look.accent_tint, None, 9)
    d.icon('fa5s.file-export', 54, 64, 16, look.accent)
    d.text(36, 102, '导出字幕', 14, QFont.Weight.Bold, look.text, ui=True)
    d.text(36, 122, 'SRT · ASS · TXT', 11, QFont.Weight.Medium, look.muted)
    for i, label in enumerate(('SRT', 'ASS', 'TXT')):
        a = shown(t, 900 + i * 120)
        pick = span(t, 1300, 1450) if i == 0 else 0.0
        d.box(220 + i * 66, 36, 56, 28, mix(look.surface, look.accent_tint, pick), mix(look.border, look.accent, pick), 8, a)
        d.text(248 + i * 66, 50, label, 12, QFont.Weight.Bold, mix(look.text, look.accent, pick), a, align='center')
    fx, fy = track(t, [(0, (250.0, 100.0)), (1650, (250.0, 100.0)), (2350, (372.0, 118.0))])
    moving = shown(t, 1550, 2350, 160)
    d.icon('fa5s.file-alt', fx, fy, 20, look.accent, moving)
    d.icon('fa5s.folder-open', 380, 122, 30, look.secondary, shown(t, 1500))
    d.check(398, 104, shown(t, 2450))
    d.pointer(t, [(0, 120, 176), (400, 110, 90), (900, 110, 90), (1250, 248, 56), (1700, 248, 56), (2500, 300, 176)],
              (650, 1330))


def advanced(d: Draw, t: float) -> None:
    """The last basic step: what 进阶 teaches — fix a wrong word, pick the best of three (1/2/3), drag a line's end."""
    look = d.look
    d.stage()
    for i in range(3):
        on = 300 + i * 1700
        d.card(14 + i * 140, 18, 132, 150, highlight=span(t, on, on + 150) * (1 - span(t, on + 1500, on + 1650)))
    # 1: a wrong word put right
    d.card(26, 52, 108, 34)
    w = d.text(36, 69, '去', 13, QFont.Weight.Medium, look.text)
    fixed = span(t, 1100, 1300)
    d.text(36 + w, 69, '至冬' if fixed > 0.5 else '至东', 13, QFont.Weight.Bold, look.success if fixed > 0.5 else look.danger)
    if fixed < 0.5:
        d.underline(36 + w, 36 + w + d.measure('至东', 13, QFont.Weight.Bold), 79, look.danger)
    d.check(80, 124, shown(t, 1250, 5300), 10)
    # 2: three results, key 2 picks one
    for row, width in enumerate((92, 104, 80)):
        pick = span(t, 2650, 2800) if row == 1 else 0.0
        d.box(166, 40 + row * 18, width, 10, mix(look.border, look.success, pick), None, 5)
    for k in range(3):
        down = (1 - abs(t - 2700) / 160) if (k == 1 and abs(t - 2700) < 160) else 0.0
        d.keycap(166 + k * 36, 108, str(k + 1), down)
    # 3: drag the end of a line to set its time
    d.box(302, 56, 112, 44, look.timeline, None, 6)
    width = track(t, [(0, 50.0), (3900, 50.0), (4600, 88.0), (5250, 88.0), (5400, 50.0)])
    d.cue(310, 64, width, 28, look.role['primary'])
    d.p.setPen(QPen(faded(look.playhead, 0.9), 1.6))
    d.p.drawLine(QPointF(310 + width, 58), QPointF(310 + width, 98))
    d.pointer(t, [(0, 380, 176), (3500, 380, 176), (3850, 312 + 50, 80), (3900, 312 + 50, 80), (4600, 312 + 88, 80),
                  (5000, 312 + 88, 80), (5400, 380, 176)])


def key_what(d: Draw, t: float) -> None:
    """API Key 是什么: the service hands out a key; the app uses it to call that service's AI."""
    look = d.look
    d.stage()
    d.card(20, 30, 130, 120)
    d.box(36, 46, 36, 36, look.accent_tint, None, 9)
    d.icon('fa5s.robot', 54, 64, 17, look.accent)
    d.text(36, 102, 'DeepSeek', 13, QFont.Weight.Bold, look.text)
    d.box(36, 120, 86, 7, look.border, None, 3.5)
    arrived = span(t, 2050, 2250)
    d.card(290, 30, 130, 120, highlight=arrived)
    d.box(306, 46, 36, 36, look.accent_tint, None, 9)
    d.icon('fa5s.project-diagram', 324, 64, 15, look.accent)
    d.text(306, 102, 'AI 智能断句', 12.5, QFont.Weight.Bold, look.text, width=104, ui=True)
    for row, width in enumerate((92, 70)):
        d.box(306, 118 + row * 12, width, 6, mix(look.border, look.accent, arrived * 0.6), None, 3)
    d.check(412, 38, shown(t, 2500))
    x = track(t, [(0, 70.0), (1100, 70.0), (1950, 250.0)])
    key = shown(t, 400, 2050, 200)
    if key > 0.003:
        d.box(x, 76, 104, 28, look.accent, None, 14, key)
        d.icon('fa5s.key', x + 16, 90, 12, look.on_accent, key)
        d.text(x + 30, 90, 'sk-a8f3…', 12, QFont.Weight.DemiBold, look.on_accent, key)


def key_topup(d: Draw, t: float) -> None:
    """Most services need credit first: top up 10 yuan, then pay for what you use."""
    look = d.look
    d.stage()
    d.card(56, 20, 328, 70)
    d.icon('fa5s.coins', 92, 55, 24, look.warning)
    paid = span(t, 1450, 1650)
    d.text(122, 55, '¥10.00' if paid > 0.5 else '¥0.00', 24, QFont.Weight.Bold, mix(look.muted, look.success, paid))
    for i, (label, x) in enumerate((('¥10', 70), ('¥50', 160), ('¥100', 250))):
        pick = span(t, 1050, 1200) if i == 0 else 0.0
        dim = 1 - 0.45 * span(t, 1200, 1450) if i else 1.0
        d.box(x, 112, 80, 34, mix(look.surface, look.accent_tint, pick), mix(look.border, look.accent, pick), 8, dim)
        d.text(x + 40, 129, label, 14, QFont.Weight.Bold, mix(look.text, look.accent, pick), dim, align='center')
    for at, dx in ((2400, 0), (3000, 34)):
        v = (t - at) / 700
        if 0 <= v <= 1:
            d.text(300 + dx, 48 - 14 * v, '−0.02', 11, QFont.Weight.DemiBold, look.muted, 1 - v)
    d.pointer(t, [(0, 220, 176), (500, 220, 176), (900, 104, 126), (1600, 104, 126), (2200, 340, 176)], (1100,))


def key_get(d: Draw, t: float) -> None:
    """On the service's site: create a key and copy it; in the app: paste it, check it, 连接正常."""
    look = d.look
    d.stage()
    d.card(14, 16, 210, 152)
    for i in range(3):
        d.box(26 + i * 10, 28, 6, 6, look.border, None, 3)
    d.box(60, 25, 150, 12, look.input, None, 6)
    pressed = 1 - abs(t - 760) / 110 if abs(t - 760) < 110 else 0.0
    d.button(26, 48, 104, 30, '+ API Key', primary=True, pressed=pressed, size=12)
    row = shown(t, 950)
    d.box(26, 94, 186, 36, look.input, look.border, 8, row)
    d.text(38, 112, 'sk-7f2c••••', 12.5, QFont.Weight.Medium, look.text, row)
    copied = span(t, 1650, 1800)
    d.icon('fa5s.check' if copied > 0.5 else 'fa5s.copy', 196, 112, 13, look.success if copied > 0.5 else look.muted, row)
    d.icon('fa5s.arrow-right', 240, 92, 16, look.accent, shown(t, 1900))
    d.box(258, 52, 166, 36, look.input, mix(look.border, look.accent, span(t, 2250, 2400) * (1 - span(t, 3100, 3250))), 8)
    typed = int(max(0.0, min(1.0, (t - 2450) / 450)) * 8)
    d.text(270, 70, 'sk-' + '•' * typed, 12.5, QFont.Weight.Medium, look.text)
    tested = 1 - abs(t - 3300) / 110 if abs(t - 3300) < 110 else 0.0
    if t < 3400:
        d.button(258, 104, 166, 32, '测试连接', primary=False, pressed=tested)
    else:
        d.chip(274, 120, '连接正常', look.success_soft, look.success, shown(t, 3400), icon='fa5s.check-circle')
    d.pointer(t, [(0, 130, 176), (350, 130, 176), (650, 76, 62), (1100, 76, 62), (1500, 196, 114), (1900, 196, 114),
                  (2200, 330, 70), (2600, 330, 70), (3050, 340, 120), (3500, 340, 120), (4000, 240, 176)],
              (720, 1620, 2300, 3260))



# ---------------------------------------------------------------- 进阶 (proofreading and the workbench)
def gl_check(d: Draw, t: float) -> None:
    """① Tick the game's glossary (found on this computer, free)."""
    look = d.look
    d.stage()
    d.card(60, 18, 320, 150)
    d.text(76, 36, '词库', 12, QFont.Weight.Bold, look.secondary, ui=True)
    for row, name in enumerate(('原神', '崩坏：星穹铁道', '绝区零')):
        y = 52 + row * 36
        ticked = span(t, 1050, 1200) if row == 0 else 0.0
        d.box(72, y, 296, 30, faded(look.accent_tint, ticked * 0.7), None, 7)
        d.box(84, y + 7, 16, 16, mix(look.surface, look.accent, ticked), mix(look.border, look.accent, ticked), 4)
        d.icon('fa5s.check', 92, y + 15, 10, look.on_accent, ticked)
        d.icon('fa5s.book', 116, y + 15, 12, look.muted)
        d.text(130, y + 15, name, 12.5, QFont.Weight.Medium, look.text)
    d.icon('fa5s.laptop', 300, 36, 14, look.muted, shown(t, 1300))
    d.chip(316, 36, '¥0', look.success_soft, look.success, shown(t, 1300), size=10.5, height=20, ui=False)
    d.pointer(t, [(0, 230, 176), (400, 230, 176), (850, 92, 70), (1500, 92, 70), (2300, 230, 176)], (1000,))


def gl_ai(d: Draw, t: float) -> None:
    """② AI 校对 finds the wrong words the glossary does not know (offline in the tutorial)."""
    look = d.look
    d.stage()
    pressed = 1 - abs(t - 760) / 110 if abs(t - 760) < 110 else 0.0
    d.button(24, 24, 128, 34, 'AI 校对', primary=True, pressed=pressed, icon='fa5s.magic')
    busy = shown(t, 880, 1900, 120)
    if busy > 0.003:
        d.p.setPen(QPen(faded(look.accent, busy), 2.2))
        d.p.setBrush(Qt.BrushStyle.NoBrush)
        d.p.drawArc(QRectF(166, 32, 18, 18), int((t * 0.6) % 360 * 16), 270 * 16)
    for row, (before, word, after) in enumerate((('听说', '至东', '那边下雪了'), ('', '派门', '又在旁边说个不停'),
                                                  ('', '阿雷奇诺', '这次登场好帅'))):
        y = 72 + row * 34
        d.card(24, y, 392, 28)
        x = 36 + d.text(36, y + 14, before, 12.5, QFont.Weight.Medium, look.text)
        flagged = shown(t, 1950 + row * 250) if row < 2 else 0.0
        w = d.text(x, y + 14, word, 12.5, QFont.Weight.Bold, mix(look.text, look.danger, flagged))
        d.underline(x, x + w, y + 23, look.danger, flagged)
        d.text(x + w, y + 14, after, 12.5, QFont.Weight.Medium, look.text)
        d.icon('fa5s.magic', 400, y + 14, 12, look.accent, flagged)
    d.pointer(t, [(0, 200, 176), (400, 200, 176), (700, 90, 44), (1100, 90, 44), (2000, 260, 176)], (700,))


def gl_fix(d: Draw, t: float) -> None:
    """③ The red word is wrong: click the suggestion under it (至东 → 至冬); Ctrl+Z undoes it."""
    look = d.look
    d.stage()
    d.card(24, 26, 392, 46)
    fixed = span(t, 1500, 1700)
    x = 40 + d.text(40, 49, '听说', 15, QFont.Weight.Medium, look.text)
    word = '至冬' if fixed > 0.5 else '至东'
    w = d.text(x, 49, word, 15, QFont.Weight.Bold, look.success if fixed > 0.5 else look.danger)
    if fixed <= 0.5:
        d.underline(x, x + w, 61, look.danger)
    d.text(x + w, 49, '那边下了很大的雪', 15, QFont.Weight.Medium, look.text)
    offer = 1 - span(t, 1550, 1800)
    d.box(x - 6, 84, 96, 30, look.surface, look.accent, 8, offer, 1.4)
    d.icon('fa5s.magic', x + 8, 99, 11, look.accent, offer)
    d.text(x + 20, 99, '至冬', 13, QFont.Weight.Bold, look.accent, offer)
    d.check(x + w + 6, 30, shown(t, 1750, 3300))
    d.keycap(300, 124, 'Ctrl', 0.0, 40)
    d.keycap(346, 124, 'Z', 0.0, 30)
    d.pointer(t, [(0, 230, 176), (400, 230, 176), (1000, x + 30, 100), (1650, x + 30, 100), (2600, 230, 176)], (1300,))


def gl_back(d: Draw, t: float) -> None:
    """④ Done: back to the result."""
    look = d.look
    d.stage()
    slide = span(t, 1100, 1700)
    d.card(24 - 30 * slide, 22, 392, 142, alpha=1 - slide)
    pressed = 1 - abs(t - 860) / 110 if abs(t - 860) < 110 else 0.0
    d.button(40 - 30 * slide, 36, 132, 32, '返回结果', primary=False, pressed=pressed, icon='fa5s.arrow-left',
             alpha=1 - slide)
    for row in range(3):
        d.box(40 - 30 * slide, 84 + row * 24, 300 - row * 60, 10, look.border, None, 5, 1 - slide)
    back = span(t, 1500, 2000)
    d.card(24 + 30 * (1 - back), 22, 392, 142, alpha=back)
    d.check(48 + 30 * (1 - back), 52, back, 10)
    d.text(66 + 30 * (1 - back), 52, '字幕已生成', 15, QFont.Weight.Bold, look.text, back, ui=True)
    d.pointer(t, [(0, 200, 176), (400, 200, 176), (800, 100, 54), (1200, 100, 54), (2200, 250, 176)], (800,))


def studio_open(d: Draw, t: float) -> None:
    """The result page opens the workbench: edit line by line, review, timing, burn-in."""
    look = d.look
    d.stage()
    opened = span(t, 1100, 1700)
    pressed = 1 - abs(t - 800) / 110 if abs(t - 800) < 110 else 0.0
    d.card(110, 52 + pressed, 220, 70, alpha=1 - opened, highlight=span(t, 500, 650))
    d.box(126, 70 + pressed, 34, 34, look.accent_tint, None, 9, 1 - opened)
    d.icon('fa5s.closed-captioning', 143, 87 + pressed, 17, look.accent, 1 - opened)
    d.text(172, 87 + pressed, '打开字幕工作台', 14, QFont.Weight.Bold, look.text, 1 - opened, width=150, ui=True)
    if opened > 0.003:
        scale = 0.92 + 0.08 * opened
        x0, y0 = 220 - 200 * scale, 94 - 78 * scale
        d.box(x0, y0, 400 * scale, 156 * scale, look.surface, look.border, 10, opened)
        d.box(x0 + 10 * scale, y0 + 10 * scale, 180 * scale, 92 * scale, look.media, None, 6, opened)
        d.text(x0 + 100 * scale, y0 + 86 * scale, '派蒙又在旁边说个不停', 11 * scale, QFont.Weight.Bold,
               QColor('#ffffff'), opened, align='center')
        for row in range(4):
            d.box(x0 + 202 * scale, y0 + (14 + row * 22) * scale, (180 - row * 24) * scale, 12 * scale,
                  look.border, None, 5, opened)
        d.box(x0 + 10 * scale, y0 + 112 * scale, 380 * scale, 34 * scale, look.timeline, None, 6, opened)
        for i, (x, w) in enumerate(((20, 90), (128, 120), (270, 100))):
            d.cue(x0 + x * scale, y0 + 118 * scale, w * scale, 22 * scale,
                  (look.role['primary'], look.role['review'])[i % 2], alpha=opened)
    d.pointer(t, [(0, 230, 176), (400, 230, 176), (700, 200, 90), (1100, 200, 90), (2000, 300, 176)], (800,))


def _workbench_track(d: Draw, x0=20.0, y0=40.0, w=400.0):
    """A strip of the Studio timeline (the lane the edit / review / timing scenes work on)."""
    look = d.look
    d.box(x0, y0, w, 64, look.timeline, None, 8)
    d.wave(x0 + 8, y0 + 6, w - 16, 18, faded(look.muted, 0.8), step=5.5)


def edit(d: Draw, t: float) -> None:
    """Double-click a line to edit it, or press E for the line at the playhead."""
    look = d.look
    d.stage()
    _workbench_track(d)
    editing = span(t, 900, 1050) * (1 - span(t, 3300, 3450))
    d.cue(36, 72, 120, 26, look.role['primary'], '' if editing > 0.5 else '去至东', selected=span(t, 700, 850))
    d.cue(176, 72, 130, 26, look.role['review'], '这期纪行挺划算')
    if editing > 0.003:
        d.box(30, 112, 220, 40, look.input, look.accent, 8, editing, 1.6)
        typed = '去至冬吧'[:int(max(0.0, min(1.0, (t - 1300) / 900)) * 4 + 0.001)] if t > 1300 else '去至东'
        w = d.text(44, 132, typed, 14, QFont.Weight.Medium, look.text, editing)
        if int(t / 400) % 2 == 0:
            d.box(46 + w, 122, 2, 20, look.accent, None, 1, editing)
    d.text(300, 132, '或', 12, QFont.Weight.DemiBold, look.muted, align='center', ui=True)
    d.keycap(320, 117, 'E', 1.0 if 1 - abs(t - 4000) / 160 > 0 and abs(t - 4000) < 160 else 0.0)
    d.pointer(t, [(0, 200, 176), (400, 200, 176), (650, 96, 84), (1100, 96, 84), (1500, 220, 176), (3700, 336, 160),
                  (4300, 336, 160)], (700, 820))


def review(d: Draw, t: float) -> None:
    """R starts reviewing: three recognitions side by side, 1 / 2 / 3 picks one."""
    look = d.look
    d.stage()
    started = span(t, 700, 900)
    down_r = 1 - abs(t - 600) / 160 if abs(t - 600) < 160 else 0.0
    d.keycap(24, 24, 'R', down_r)
    d.text(64, 39, '审核', 13, QFont.Weight.Bold, look.text, ui=True)
    rows = (('MOSS', '我们一起去须迷'), ('FireRed', '我们一起去须弥'), ('Qwen3', '我们一起去须弥'))
    for row, (model, text) in enumerate(rows):
        y = 66 + row * 32
        a = shown(t, 900 + row * 150)
        picked = span(t, 2350, 2500) if row == 1 else 0.0
        d.box(24, y, 300, 26, mix(look.surface, look.accent_tint, picked), mix(look.border, look.accent, picked), 7,
              a * started)
        d.text(36, y + 13, model, 11, QFont.Weight.Bold, look.muted, a * started)
        d.text(104, y + 13, text, 12.5, QFont.Weight.Medium, look.text, a * started)
        if row == 0:
            d.underline(104 + d.measure('我们一起去须', 12.5), 104 + d.measure('我们一起去须迷', 12.5), y + 22,
                        look.danger, a * started)
        d.keycap(340, y - 2, str(row + 1), (1 - abs(t - 2300) / 160) if (row == 1 and abs(t - 2300) < 160) else 0.0,
                 28)
    d.check(316, 98, shown(t, 2500, 3600))


def speakers(d: Draw, t: float) -> None:
    """说话人管理: rename, recolour, merge duplicates."""
    look = d.look
    d.stage()
    d.card(40, 20, 360, 146)
    d.text(56, 38, '说话人管理', 13, QFont.Weight.Bold, look.text, ui=True)
    recolour = span(t, 2300, 2600)
    rows = (('S1', look.role['primary'], '主播' if t > 1700 else 'S1'), ('S2', mix(look.role['review'], look.success, recolour), 'S2'),
            ('S3', look.role['review'], 'S2'))
    merged = span(t, 3000, 3400)
    for row, (_key, color, name) in enumerate(rows):
        alpha = 1 - merged if row == 2 else 1.0
        y = 56 + row * 34 - (0 if row < 2 else 0)
        d.box(56, y, 328, 28, look.input, look.border, 7, alpha)
        d.box(68, y + 8, 12, 12, color, None, 6, alpha)
        d.text(92, y + 14, name, 12.5, QFont.Weight.Medium, look.text, alpha)
        if row == 0:
            d.box(92 + d.measure(name, 12.5) + 2, y + 6, 2, 16, look.accent, None, 1,
                  shown(t, 900, 1800) * (int(t / 400) % 2 == 0))
    d.icon('fa5s.compress-alt', 368, 128, 13, look.accent, shown(t, 2800, 3500))
    d.pointer(t, [(0, 220, 176), (400, 220, 176), (800, 160, 70), (1800, 160, 70), (2200, 74, 104), (2700, 74, 104),
                  (2900, 368, 128), (3500, 368, 128), (3900, 250, 176)], (850, 2350, 3000))


def replace(d: Draw, t: float) -> None:
    """Batch replace: every 派门 becomes 派蒙 — preview first, then replace."""
    look = d.look
    d.stage()
    d.caption(24, 26, '查找')
    d.box(24, 36, 150, 30, look.input, look.border, 8)
    d.text(36, 51, '派门'[:int(max(0.0, min(1.0, (t - 200) / 400)) * 2 + 0.001)], 13, QFont.Weight.Medium, look.text)
    d.caption(190, 26, '替换为')
    d.box(190, 36, 150, 30, look.input, look.border, 8)
    d.text(202, 51, '派蒙'[:int(max(0.0, min(1.0, (t - 800) / 400)) * 2 + 0.001)], 13, QFont.Weight.Medium, look.text)
    pressed = 1 - abs(t - 2500) / 110 if abs(t - 2500) < 110 else 0.0
    d.button(352, 36, 68, 30, '替换', primary=True, pressed=pressed, size=12)
    done = span(t, 2600, 2800)
    for row, rest in enumerate(('又在旁边说个不停', '一起去探险')):
        y = 82 + row * 36
        a = shown(t, 1300 + row * 150)
        d.card(24, y, 396, 30, alpha=a)
        word = '派蒙' if done > 0.5 else '派门'
        w = d.text(38, y + 15, word, 12.5, QFont.Weight.Bold, look.success if done > 0.5 else look.accent, a)
        if done <= 0.5:
            d.box(36, y + 6, w + 4, 18, faded(look.accent_tint, 0.8), None, 4, a)
            d.text(38, y + 15, word, 12.5, QFont.Weight.Bold, look.accent, a)
        d.text(38 + w, y + 15, rest, 12.5, QFont.Weight.Medium, look.text, a)
    d.pointer(t, [(0, 230, 176), (1600, 230, 176), (2300, 386, 52), (2700, 386, 52), (3300, 300, 176)], (2400,))


def qw(d: Draw, t: float) -> None:
    """Drag a line's edges to change its time; Q / W cut its start / end to the playhead."""
    look = d.look
    d.stage()
    _workbench_track(d, y0=26)
    head = 250.0
    d.p.setPen(QPen(look.playhead, 2))
    d.p.drawLine(QPointF(head, 20), QPointF(head, 98))
    d.box(head - 5, 18, 10, 6, look.playhead, None, 2)
    left = track(t, [(0, 70.0), (500, 70.0), (1200, 100.0), (3000, 100.0), (3100, 70.0)])
    right = track(t, [(0, 320.0), (1900, 320.0), (2050, head), (3000, head), (3100, 320.0)])
    d.cue(left, 60, right - left, 28, look.role['primary'], '今天开新档')
    d.keycap(150, 124, 'Q', 0.0)
    w_down = 1 - abs(t - 1950) / 160 if abs(t - 1950) < 160 else 0.0
    d.keycap(196, 124, 'W', w_down)
    d.pointer(t, [(0, 70, 150), (300, 72, 74), (500, 72, 74), (1200, 102, 74), (1500, 140, 170), (2600, 140, 170)])


def punct(d: Draw, t: float) -> None:
    """Punctuation: add it, drop it or keep the original — only how lines show and export."""
    look = d.look
    d.stage()
    modes = ('保留原文', '添加标点', '不加标点')
    pick = 1 if 1100 <= t < 2600 else (2 if t >= 2600 else 0)
    x = 40.0
    for i, mode in enumerate(modes):
        w = d.measure(mode, 12, QFont.Weight.DemiBold, True) + 24
        d.box(x, 30, w, 30, look.accent_tint if i == pick else look.surface, look.accent if i == pick else look.border,
              8)
        d.text(x + 12, 45, mode, 12, QFont.Weight.DemiBold, look.accent if i == pick else look.text, ui=True)
        x += w + 8
    lines = {0: '今天来玩新版本 先去打 Boss', 1: '今天来玩新版本，先去打 Boss。', 2: '今天来玩新版本 先去打 Boss'}
    d.box(40, 84, 360, 64, look.media, None, 8)
    d.text(220, 116, lines[pick], 15, QFont.Weight.Bold, QColor('#ffffff'), align='center')
    d.pointer(t, [(0, 200, 176), (700, 150, 46), (1300, 150, 46), (2200, 230, 46), (2900, 230, 46), (3400, 250, 176)],
              (1000, 2500))


def burn(d: Draw, t: float) -> None:
    """压制成片: the subtitles are burnt into the video."""
    look = d.look
    d.stage()
    d.box(60, 18, 200, 112, look.media, None, 8)
    d.text(160, 112, '今天开新档', 13, QFont.Weight.Bold, QColor('#ffffff'), align='center')
    d.icon('fa5s.fire-alt', 300, 60, 22, look.accent, shown(t, 400))
    bar = shown(t, 700, 3000)
    d.box(60, 146, 320, 8, look.border, None, 4, bar)
    d.box(60, 146, 320 * span(t, 800, 2400), 8, look.accent, None, 4, bar)
    d.icon('fa5s.film', 340, 76, 30, look.secondary, shown(t, 2400))
    d.check(358, 58, shown(t, 2500))


# ---------------------------------------------------------------- 2026-10-24: C / B / Shift+Q·W / T
# Key caps name the keys set in the shortcut settings (read when a step loads its scene).
_KEYS: dict[str, str] = {}


def refresh_keys() -> None:
    try:
        from ..studio.shortcut_registry import current_values, display
        values = current_values()
        _KEYS.clear()
        _KEYS.update({action: display(values.get(action, '')) for action in
                      ('razor_tool', 'merge_tool', 'merge_previous', 'merge_next', 'add_subtitle')})
    except Exception:  # noqa: BLE001 - the defaults below
        _KEYS.clear()


def key_name(action: str, default: str) -> str:
    return _KEYS.get(action) or default


def _keycap_width(d: Draw, label: str) -> float:
    return max(30.0, d.measure(label, 13, QFont.Weight.Bold) + 18)


def _wide_keycap(d: Draw, x, y, label, down=0.0) -> float:
    """A key cap as wide as its name (Shift+Q); returns its width."""
    look = d.look
    w = _keycap_width(d, label)
    d.box(x, y + 3, w, 30, faded(look.border, 1.0), None, 7)
    d.box(x, y + 3 * down, w, 30, mix(look.surface, look.accent, down), look.border, 7)
    d.text(x + w / 2, y + 3 * down + 15, label, 13, QFont.Weight.Bold, mix(look.text, look.on_accent, down),
           align='center')
    return w


def _press(t: float, at: float, length: float = 160) -> float:
    return 1 - abs(t - at) / length if abs(t - at) < length else 0.0


def razor(d: Draw, t: float) -> None:
    """C: the razor shows where it will cut and the words on each side; two clicks make three pieces."""
    look = d.look
    d.stage()
    _workbench_track(d, y0=26)
    color = look.role['review']
    x0, x1, y = 60.0, 380.0, 62.0
    cuts = [x for x, at in ((167.0, 1500), (274.0, 2700)) if t >= at]
    edges = [x0, *cuts, x1]
    labels = {2: ('这期纪行的奖励还挺划算',), 3: ('这期纪行', '的奖励还挺划算'),
              4: ('这期纪行', '的奖励', '还挺划算')}[len(edges)]
    for index, (a, b) in enumerate(zip(edges, edges[1:])):
        gap = 3.0 if index else 0.0
        d.cue(a + gap, y, b - a - gap, 28, color, labels[index])
    hover = track(t, [(0, 330.0), (500, 330.0), (1200, 167.0), (1900, 167.0), (2400, 274.0), (3600, 274.0)])
    if 400 <= t <= 3000 and not any(abs(hover - x) < 2 for x in cuts):
        d.p.setPen(QPen(look.accent, 1.6, Qt.PenStyle.DashLine))
        d.p.drawLine(QPointF(hover, 54), QPointF(hover, 98))
        d.icon('fa5s.cut', hover, 46, 12, look.accent)
    d.keycap(24, 126, key_name('razor_tool', 'C'), _press(t, 250))
    d.text(64, 141, '剃刀', 12.5, QFont.Weight.DemiBold, look.secondary, ui=True)
    d.check(400, 132, shown(t, 2900, 3800))
    d.pointer(t, [(0, 330, 150), (500, 330, 104), (1200, 167, 104), (1900, 167, 104), (2400, 274, 104),
                  (3600, 274, 104)], (1400, 2600))


def merge_tool(d: Draw, t: float) -> None:
    """B: press on a piece and drag toward its neighbour; the two become one."""
    look = d.look
    d.stage()
    _workbench_track(d, y0=26)
    color = look.role['review']
    joined = span(t, 1900, 2150)
    a_end = 167.0 + (274.0 - 167.0) * joined
    d.cue(60, 62, a_end - 60, 28, color, '这期纪行' if joined < 0.5 else '这期纪行的奖励',
          selected=span(t, 700, 850))
    if joined < 1.0:   # the piece being joined shrinks into its neighbour (no label: it would elide to "…")
        d.cue(170 + (a_end - 167), 62, max(4.0, 274 - (170 + (a_end - 167))), 28, color,
              '的奖励' if joined <= 0.0 else '', alpha=1 - joined)
    d.cue(277, 62, 103, 28, color, '还挺划算')
    drag = span(t, 900, 1800)
    if 900 <= t <= 2000:
        d.p.setPen(QPen(faded(look.accent, 0.9), 2.0))
        d.p.drawLine(QPointF(110, 76), QPointF(110 + 110 * drag, 76))
        d.icon('fa5s.arrow-right', 118 + 110 * drag, 76, 11, look.accent, shown(t, 900, 1900))
    d.keycap(24, 126, key_name('merge_tool', 'B'), _press(t, 300))
    d.text(64, 141, '合并工具', 12.5, QFont.Weight.DemiBold, look.secondary, ui=True)
    d.check(400, 132, shown(t, 2300, 3300))
    d.pointer(t, [(0, 300, 160), (600, 110, 80), (900, 110, 80), (1800, 220, 80), (2600, 220, 80), (3400, 300, 170)],
              (750,))


def ripple(d: Draw, t: float) -> None:
    """Shift+Q joins the selected piece to the one before it, Shift+W to the one after."""
    look = d.look
    d.stage()
    _workbench_track(d, y0=26)
    color = look.role['review']
    joined = span(t, 1300, 1550)
    edge = 274.0 + (380.0 - 274.0) * joined
    d.cue(60, 62, edge - 60, 28, color, '这期纪行的奖励' if joined < 0.5 else '这期纪行的奖励还挺划算',
          selected=joined)
    if joined < 1.0:
        d.cue(edge + 3, 62, max(4.0, 380 - edge - 3), 28, color, '还挺划算' if joined <= 0.0 else '',
              alpha=1 - joined, selected=1 - joined)
    x = 24.0
    x += _wide_keycap(d, x, 120, key_name('merge_previous', 'Shift+Q'), _press(t, 1150)) + 8
    d.text(x, 135, '和上一段', 12, QFont.Weight.DemiBold, look.secondary, ui=True)
    x = 232.0
    x += _wide_keycap(d, x, 120, key_name('merge_next', 'Shift+W'), 0.0) + 8
    d.text(x, 135, '和下一段', 12, QFont.Weight.DemiBold, look.secondary, ui=True)
    d.check(400, 160, shown(t, 1700, 2900))


def add_cue(d: Draw, t: float) -> None:
    """T: a new two-second line appears at the playhead, ready for typing."""
    look = d.look
    d.stage()
    _workbench_track(d, y0=26)
    head = 230.0
    d.cue(40, 62, 150, 28, look.role['primary'], '下次一起去探险')
    born = span(t, 900, 1150)
    if born > 0.003:
        d.cue(head, 62, 110 * born, 28, look.role['primary'], '', alpha=born, selected=1.0)
        typed = '好啊'[:int(max(0.0, min(1.0, (t - 1500) / 600)) * 2 + 0.001)] if t > 1500 else ''
        w = d.text(head + 10, 76, typed, 11.5, QFont.Weight.DemiBold, look.text, born)
        if int(t / 400) % 2 == 0 and t < 3000:
            d.box(head + 11 + w, 68, 2, 16, look.accent, None, 1, born)
    d.p.setPen(QPen(look.playhead, 2))
    d.p.drawLine(QPointF(head, 20), QPointF(head, 98))
    d.box(head - 5, 18, 10, 6, look.playhead, None, 2)
    d.keycap(24, 126, key_name('add_subtitle', 'T'), _press(t, 800))
    d.text(64, 141, '新建字幕', 12.5, QFont.Weight.DemiBold, look.secondary, ui=True)
    d.check(400, 132, shown(t, 2400, 3300))


def plan_compare(d: Draw, t: float) -> None:
    """② Two ways to turn speech into text: 云端 (any computer, uploads) or 本机 (free, needs a graphics card)."""
    look = d.look
    d.stage()
    picked = span(t, 1500, 1750)
    for index, (x, icon, title, good, care, role) in enumerate((
            (18, 'fa5s.cloud', '云端识别', '不挑电脑', '要上传', 'primary'),
            (226, 'fa5s.desktop', '本机识别', '免费', '要 N 卡', 'timeline'))):
        color = look.role[role]
        chosen = picked if index == 0 else 0.0
        d.card(x, 18, 196, 150, highlight=chosen, radius=12)
        d.box(x + 14, 32, 36, 36, faded(color, 0.18), None, 9)
        d.icon(icon, x + 32, 50, 17, color)
        d.text(x + 60, 50, title, 14, QFont.Weight.Bold, look.text, ui=True, width=120)
        good_in = shown(t, 300 + 250 * index)
        d.icon('fa5s.check', x + 22, 96, 11, look.success, good_in)
        d.text(x + 34, 96, good, 12, QFont.Weight.DemiBold, look.text, good_in, ui=True, width=150)
        care_in = shown(t, 700 + 250 * index)
        d.icon('fa5s.exclamation-circle', x + 22, 124, 11, look.warning, care_in)
        d.text(x + 34, 124, care, 12, QFont.Weight.DemiBold, look.secondary, care_in, ui=True, width=150)
        d.check(x + 178, 34, chosen if index == 0 else 0.0)
    d.pointer(t, [(0, 380, 176), (900, 300, 160), (1350, 120, 150), (2600, 120, 150), (3300, 400, 176)], (1400,))


def ai_lock(d: Draw, t: float) -> None:
    """⑤ AI 断句, 翻译字幕 and 术语库校对 stay locked until an API key is in and tested."""
    look = d.look
    d.stage()
    unlock = span(t, 1900, 2300)
    for index, (icon, label) in enumerate((('fa5s.cut', 'AI 断句'), ('fa5s.language', '翻译字幕'),
                                           ('fa5s.book-open', '术语库校对'))):
        y = 30 + index * 46
        lit = span(t, 2000 + index * 160, 2350 + index * 160)
        d.box(150, y, 270, 36, mix(look.input, look.surface, lit), mix(look.border, look.accent, lit * 0.6), 9)
        d.icon(icon, 170, y + 18, 14, mix(look.muted, look.accent, lit))
        d.text(188, y + 18, label, 13, QFont.Weight.DemiBold, mix(look.muted, look.text, lit), ui=True, width=170)
        d.icon('fa5s.lock', 398, y + 18, 12, look.muted, 1 - lit)
        d.check(398, y + 18, lit, 8.0)
    slide = track(t, [(0, 0.0), (500, 0.0), (1500, 1.0)])
    x = 18 + 92 * slide
    d.box(x, 74, 46, 38, look.accent_tint, mix(look.border, look.accent, slide), 10, 1.0 - 0.6 * unlock)
    d.icon('fa5s.key', x + 23, 93, 17, look.accent, 1.0 - 0.6 * unlock)
    d.text(41, 132, 'API Key', 11.5, QFont.Weight.Bold, look.muted, 1 - span(t, 500, 900), align='center')


SCENES: dict[str, Scene] = {
    'plan_compare': Scene(3600, 0.62, plan_compare),
    'ai_lock': Scene(4200, 0.8, ai_lock),
    'drop': Scene(3200, 0.66, drop),
    'spoken': Scene(3800, 0.75, spoken),
    'moss_signup': Scene(4800, 0.86, moss_signup),
    'plan_ok': Scene(3400, 0.7, plan_ok),
    'timeline_mg': Scene(5800, 0.6, timeline_mg),
    'ai_polish': Scene(5600, 0.8, ai_polish),
    'apikey': Scene(3400, 0.8, apikey),
    'subtitle_lang': Scene(4400, 0.7, subtitle_lang),
    'glossary': Scene(3600, 0.75, glossary),
    'start': Scene(3000, 0.85, start),
    'export': Scene(3200, 0.85, export),
    'advanced': Scene(5400, 0.62, advanced),
    'key_what': Scene(3800, 0.75, key_what),
    'key_topup': Scene(3800, 0.6, key_topup),
    'key_get': Scene(4400, 0.85, key_get),
    # 进阶
    'gl_check': Scene(3000, 0.7, gl_check),
    'gl_ai': Scene(3600, 0.8, gl_ai),
    'gl_fix': Scene(3400, 0.7, gl_fix),
    'gl_back': Scene(2800, 0.8, gl_back),
    'studio_open': Scene(3200, 0.75, studio_open),
    'edit': Scene(4600, 0.4, edit),
    'review': Scene(3800, 0.75, review),
    'speakers': Scene(4200, 0.6, speakers),
    'replace': Scene(3600, 0.85, replace),
    'qw': Scene(3200, 0.75, qw),
    'punct': Scene(3600, 0.55, punct),
    'burn': Scene(3400, 0.85, burn),
    'razor': Scene(4000, 0.8, razor),
    'merge_tool': Scene(3600, 0.75, merge_tool),
    'ripple': Scene(3200, 0.7, ripple),
    'add_cue': Scene(3600, 0.75, add_cue),
}


def paint_scene(painter: QPainter, scene: Scene, t: float, look: Look, font: QFont, width: float, height: float,
                ratio: float) -> None:
    """Draw ``scene`` at ``t`` into a ``width`` x ``height`` area, the 440 x 187 canvas scaled to fit and centred."""
    scale = min(width / WIDTH, height / HEIGHT)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.translate((width - WIDTH * scale) / 2, (height - HEIGHT * scale) / 2)
    painter.scale(scale, scale)
    scene.draw(Draw(painter, look, font, ratio * scale), t % scene.duration)
    painter.restore()
