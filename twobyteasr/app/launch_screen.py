"""The launch screen: B2 「音波時間軸」, picked by the user on 2026-11-23.

User (2026-11-23): the launch screen still did not look good; Home's skeleton with a glow (draft A
of 2026-11-20) was "too plain and crude", the wordmark draft B looked better. From three B drafts
(``tmp/launch-drafts-20261123``) they chose B2: the wordmark 「2ByteASR 兔白字幕」 in the middle,
under it a rounded timeline card - an audio waveform that lights up and grows where the playhead
has passed, the playhead moving on with the start's stages, and a small subtitle cue dropping onto
the timeline as each stage completes. At the end the wordmark flies to Home's title in the header
(``launch_picture``), so the start and Home read as one picture.

Everything is a function of the time since the start (``LaunchScreen.draw(painter, t)``), so the
in-process thread, the helper process (``launch_motion``) and the still picture agree. Text is
drawn from pictures made once in the main process (``Sprites``): the helper process has no
QGuiApplication and so no fonts. Durations and curves come from ``design/motion_tokens.py``; the
waveform's shape is fixed (seeded), so every start looks the same.

No application imports at module level: it runs before the heavy imports.
"""
from __future__ import annotations

import bisect
import json
import math
import os

# Layout in logical px at "unit" 1 (scaled with the window, see ``unit_for``), from the draft.
WORDMARK_EN_PX = 48
WORDMARK_ZH_PX = 42
WORDMARK_GAP = 14
# 2026-11-23 (user: the launch screen sat too high and was too small in a big window): the whole
# group - wordmark, card and status line - is centred vertically (a little above the middle,
# where the eye expects it), and grows with the window up to UNIT_MAX.
GROUP_CENTRE_SHARE = 0.47              # the space above the group, as a share of all free space
UNIT_MAX = 1.6
UNIT_GROWTH = 0.4                      # how much of the window's growth past the draft it follows
STATUS_HEIGHT = 30                     # the stage text and percentage under the card
CARD_WIDTH, CARD_HEIGHT = 460, 124
CARD_GAP = 46                          # from the wordmark's bottom to the card
CARD_RADIUS = 18
INNER_X = 16                           # the waveform's inset in the card
LANE_TOP, LANE_HEIGHT = 12, 26         # the cue lane at the card's top
WAVE_TOP, WAVE_HEIGHT = 48, 52
BAR_WIDTH = 4
TICK_EVERY = 36
TEXT_GAP = 14                          # under the card: the stage and the percentage
SMALL_TEXT_PX = 13
CUE_TEXT_PX = 12
CUE_RADIUS = 8
HEAD_RADIUS = 6
WAVE_BARS = 60
IDLE_HEIGHT, IDLE_SWAY = 0.22, 0.06    # bars the playhead has not reached breathe softly ...
IDLE_ALPHA = 0.55                      # ... in the strong border colour, half seen
SWAY_PERIOD_S = 2.6
CARD_DELAY_MS = 140                    # the card comes in a little after the wordmark
TABLE_STEP_S = 0.01                    # the progress table used to find when a bar was passed

STAGE_TEXT = {
    'zh': ('正在读取设置', '正在载入界面', '正在建立首页', '准备好了'),
    'zh-Hant': ('正在讀取設定', '正在載入介面', '正在建立首頁', '準備好了'),
    'ja': ('設定を読み込み中', '画面を準備中', 'ホームを作成中', '準備できました'),
    'en': ('Reading settings', 'Loading the interface', 'Building Home', 'Ready'),
}
CUE_TEXT = {
    'zh': ('设置 ✓', '界面 ✓', '首页 ✓'),
    'zh-Hant': ('設定 ✓', '介面 ✓', '首頁 ✓'),
    'ja': ('設定 ✓', '画面 ✓', 'ホーム ✓'),
    'en': ('Settings ✓', 'Interface ✓', 'Home ✓'),
}
WORDMARK = ('2ByteASR', '兔白字幕')


def language_key(language) -> str:
    text = str(language or 'zh')
    if text.startswith('zh'):
        return 'zh-Hant' if ('Hant' in text or text.endswith(('TW', 'HK', 'MO'))) else 'zh'
    return text if text in STAGE_TEXT else 'en'


def palette(theme_key) -> dict:
    """The theme's colours the launch screen uses (names as ``ThemeDefinition``)."""
    try:
        from ..design.ui_theme import DEFAULT_THEME_KEY, THEMES
        theme = THEMES.get(str(theme_key or '')) or THEMES[DEFAULT_THEME_KEY]
        return dict(background=theme.app_background, card=theme.surface_elevated, border=theme.border,
                    idle=theme.border_strong, text=theme.text, muted=theme.text_muted, accent=theme.accent, accent_soft=theme.accent_soft)
    except Exception:  # noqa: BLE001
        return dict(background='#19151c', card='#2f2935', border='#342d3a', idle='#574c60', text='#f4eee9', muted='#a69ba6',
                    accent='#b34470', accent_soft='#3a2231')


def waveform() -> list:
    """Speech-like bar heights (0..1), the same at every start."""
    seed, heights = 7, []
    for index in range(WAVE_BARS):
        seed = (seed * 9301 + 49297) % 233280
        envelope = 0.35 + 0.65 * abs(math.sin(index / 6.5) * math.sin(index / 2.9 + 1))
        heights.append(0.18 + 0.82 * envelope * (0.55 + 0.45 * seed / 233280))
    return heights


def _settle(spring, ms: float) -> float:
    """A critically damped spring from 0 to 1, ``ms`` after it started."""
    if ms <= 0:
        return 0.0
    omega = 2 * math.pi / spring.response
    t = ms / 1000
    return 1.0 - (1.0 + omega * t) * math.exp(-omega * t)


# ---------------------------------------------------------------------------- text as pictures
class Sprites:
    """Every text the screen shows, drawn once into one picture (``atlas``) at the screen's scale.

    ``items``: name -> (x, y, width, height) in the atlas's device pixels, plus the logical
    advance used to place glyphs one after another."""

    def __init__(self, atlas, items: dict, scale: float):
        self.atlas = atlas
        self.items = items
        self.scale = float(scale) or 1.0

    @classmethod
    def build(cls, colors: dict, language, scale: float, font_family: str | None = None):
        """Main process, with a QGuiApplication (fonts)."""
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
        key = language_key(language)
        family = font_family or _loading_family()
        entries = []                                           # (name, text, px, colour, bold)
        for index, char in enumerate(WORDMARK[0]):
            entries.append((f'en{index}', char, WORDMARK_EN_PX, colors['text'], True))
        for index, char in enumerate(WORDMARK[1]):
            entries.append((f'zh{index}', char, WORDMARK_ZH_PX, colors['accent'], True))
        for index, text in enumerate(STAGE_TEXT[key]):
            entries.append((f'stage{index}', text + ('…' if index < 3 else ''), SMALL_TEXT_PX, colors['muted'], False))
        for index, text in enumerate(CUE_TEXT[key]):
            entries.append((f'cue{index}', text, CUE_TEXT_PX, colors['accent'], False))
        for char in '0123456789%':
            entries.append((f'digit{char}', char, SMALL_TEXT_PX, colors['muted'], False))
        prepared, y, widest = [], 0, 1
        for name, text, px, colour, bold in entries:
            font = QFont(family) if family else QFont()
            font.setPixelSize(px)
            font.setBold(bold)
            metrics = QFontMetricsF(font)
            advance = metrics.horizontalAdvance(text)
            pad = 2.0
            width, height = advance + 2 * pad, metrics.height()
            w, h = math.ceil(width * scale) + 1, math.ceil(height * scale) + 1
            prepared.append((name, text, font, colour, pad, metrics.ascent(), advance, width, height, y, w, h))
            y += h + 8                                  # apart, so scaled copies never pick up a neighbour
            widest = max(widest, w)
        atlas = QImage(widest, max(1, y), QImage.Format.Format_ARGB32_Premultiplied)
        atlas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(atlas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        items = {}
        for name, text, font, colour, pad, ascent, advance, width, height, top, w, h in prepared:
            painter.save()
            painter.translate(0, top)
            painter.scale(scale, scale)
            painter.setFont(font)
            painter.setPen(QColor(colour))
            painter.drawText(QPointF(pad, ascent), text)
            painter.restore()
            items[name] = (0, top, w, h, advance, pad, width, height, ascent)
        painter.end()
        return cls(atlas, items, scale)

    def save(self, folder: str) -> str:
        path = os.path.join(folder, 'sprites.png')
        self.atlas.save(path, 'PNG')
        with open(os.path.join(folder, 'sprites.json'), 'w', encoding='utf-8') as handle:
            json.dump(dict(items=self.items, scale=self.scale), handle)
        return path

    @classmethod
    def load(cls, folder: str):
        from PySide6.QtGui import QImage
        atlas = QImage(os.path.join(folder, 'sprites.png')).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        with open(os.path.join(folder, 'sprites.json'), encoding='utf-8') as handle:
            data = json.load(handle)
        return cls(atlas, {name: tuple(value) for name, value in data['items'].items()}, data['scale'])

    def size(self, name: str):
        """(advance, logical width, logical height, pad) of ``name``."""
        advance, pad, width, height = self.items[name][4:8]
        return advance, width, height, pad

    def ascent(self, name: str) -> float:
        return self.items[name][8]

    def draw(self, painter, name: str, x: float, y: float, scale: float = 1.0) -> None:
        """``name`` with its text's left edge at ``x`` and its top at ``y`` (logical)."""
        from PySide6.QtCore import QRectF
        sx, sy, w, h, _advance, pad = self.items[name][:6]
        target = QRectF(x - pad * scale, y, w / self.scale * scale, h / self.scale * scale)
        painter.drawImage(target, self.atlas, QRectF(sx, sy, w, h))


def unit_for(width: float, height: float) -> float:
    """The layout's scale for a window of ``width`` x ``height`` logical px: shrinks with small
    windows as the draft did, and grows gently with big ones (a 1320 x 880 window: 1.35)."""
    base = min(float(width) / 620, float(height) / 470)
    if base <= 1.0:
        return max(0.5, base)
    return min(UNIT_MAX, 1.0 + (base - 1.0) * UNIT_GROWTH)


def _loading_family():
    try:
        from ..design.loading_font import loading_font
        return loading_font().family()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------- the screen
class LaunchScreen:
    """B2 laid out for a window of ``width`` x ``height`` logical px."""

    def __init__(self, width: float, height: float, colors: dict, sprites: Sprites, language=None,
                 expected_s: float | None = None):
        from PySide6.QtGui import QColor
        from ..design import motion_tokens as tokens
        from .launch_motion import EXPECTED_S, STAGE_AT, progress_at
        self.width, self.height = float(width), float(height)
        self.sprites = sprites
        self.colors = {name: QColor(value) for name, value in colors.items()}
        self.expected_s = float(expected_s or EXPECTED_S)
        self.stage_at = [share * self.expected_s for share in STAGE_AT]
        self.unit = unit_for(self.width, self.height)
        self.page_in = tokens.easing_curve(tokens.PAGE_IN)
        self.page_in_ms = tokens.PAGE_IN.ms
        self.shift = tokens.PAGE_SHIFT_PX
        self.stagger = tokens.STAGGER_MS
        self.small = tokens.SMALL
        self.heights = waveform()
        u = self.unit
        # The wordmark, centred: one glyph after another.
        glyphs, x, spans = [], 0.0, {}
        for prefix, text in (('en', WORDMARK[0]), ('zh', WORDMARK[1])):
            if prefix == 'zh':
                x += WORDMARK_GAP * u
            begin = x
            for index in range(len(text)):
                name = f'{prefix}{index}'
                advance, _w, height, _pad = sprites.size(name)
                glyphs.append([name, x, height, sprites.ascent(name)])
                x += advance * u
            spans[prefix] = (begin, x - begin)
        self.wordmark_width = x
        rise = max(ascent for *_rest, ascent in glyphs) * u                    # above the baseline
        drop = max(height - ascent for _n, _x, height, ascent in glyphs) * u   # below it
        tallest = rise + drop
        left = (self.width - x) / 2
        group = tallest + (CARD_GAP + CARD_HEIGHT + TEXT_GAP + STATUS_HEIGHT) * u
        top = max(0.0, (self.height - group) * GROUP_CENTRE_SHARE)
        # The two sizes share one baseline, as the draft's line of text does.
        self.glyphs = [(name, left + gx, top + rise - ascent * u) for name, gx, _height, ascent in glyphs]
        self.wordmark_rect = (left, top, x, tallest)
        # Each half of the wordmark (``en`` 2ByteASR, ``zh`` 兔白字幕): (left, width), logical.
        self.spans = {prefix: (left + begin, width) for prefix, (begin, width) in spans.items()}
        # The timeline card.
        cw, ch = CARD_WIDTH * u, CARD_HEIGHT * u
        self.card = (self.width / 2 - cw / 2, top + tallest + CARD_GAP * u, cw, ch)
        cx, cy, _cw, _ch = self.card
        self.inner_x, self.inner_w = cx + INNER_X * u, cw - 2 * INNER_X * u
        self.bar_step = self.inner_w / WAVE_BARS
        self.text_y = cy + ch + TEXT_GAP * u
        # When the playhead passes each bar, from a table of the progress (both drawers agree).
        steps = int(30 / TABLE_STEP_S)
        self._table = [progress_at(i * TABLE_STEP_S, self.expected_s) for i in range(steps)]
        self.passed_at = []
        for index in range(WAVE_BARS):
            share = (index + 0.5) / WAVE_BARS
            at = bisect.bisect_left(self._table, share)
            self.passed_at.append(at * TABLE_STEP_S if at < steps else math.inf)
        # A cue for every completed stage, where the playhead was then, never over the one before.
        self.cues, right = [], 0.0
        for index in range(3):
            at = self.stage_at[index + 1]
            advance, _w, height, pad = sprites.size(f'cue{index}')
            width = max(56 * u, advance * u + 20 * u)
            middle = self.inner_x + progress_at(at, self.expected_s) * self.inner_w
            x = max(self.inner_x, min(self.inner_x + self.inner_w - width, middle - width / 2))
            x = max(x, right + 6 * u)
            x = min(x, self.inner_x + self.inner_w - width)
            self.cues.append((f'cue{index}', at, x, width))
            right = x + width

    # ------------------------------------------------------------ timing
    def progress(self, t: float) -> float:
        from .launch_motion import progress_at
        return progress_at(t, self.expected_s)

    def stage(self, t: float) -> int:
        return max(0, bisect.bisect_right(self.stage_at, t) - 1)

    def _rise(self, ms: float) -> float:
        return self.page_in.valueForProgress(max(0.0, min(1.0, ms / self.page_in_ms)))

    def area(self):
        """The logical rect every frame may change (the wordmark down to the percentage)."""
        from PySide6.QtCore import QRectF
        left, top, _w, _h = self.wordmark_rect
        cx, _cy, cw, _ch = self.card
        x0 = min(left, cx) - 12
        x1 = max(left + self.wordmark_width, cx + cw) + 12
        y1 = self.text_y + STATUS_HEIGHT * self.unit
        return QRectF(x0, top - self.shift - 4, x1 - x0, y1 - top + self.shift + 8).intersected(
            QRectF(0, 0, self.width, self.height))

    # ------------------------------------------------------------ drawing
    def draw(self, painter, t: float, *, wordmark: bool = True, fade: float = 1.0) -> None:
        """The screen at ``t`` s over an already painted background. ``wordmark=False`` leaves the
        wordmark out (it is flying to Home's title); ``fade`` scales everything else's opacity."""
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QColor, QPainter, QPen
        u, ms = self.unit, t * 1000
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if wordmark:
            for index, (name, x, y) in enumerate(self.glyphs):
                k = self._rise(ms - index * self.stagger)
                if k <= 0:
                    continue
                painter.setOpacity(k)
                self.sprites.draw(painter, name, x, y + (1 - k) * self.shift, u)
        k = self._rise(ms - CARD_DELAY_MS)
        if k > 0 and fade > 0:
            painter.setOpacity(k * fade)
            dy = (1 - k) * self.shift
            cx, cy, cw, ch = self.card
            cy += dy
            painter.setPen(QPen(self.colors['border'], 1.0))
            painter.setBrush(self.colors['card'])
            painter.drawRoundedRect(QRectF(cx + 0.5, cy + 0.5, cw - 1, ch - 1), CARD_RADIUS * u, CARD_RADIUS * u)
            # The ruler along the bottom.
            painter.setPen(QPen(self.colors['border'], 1.0))
            tick = self.inner_x
            while tick <= self.inner_x + self.inner_w + 0.5:
                painter.drawLine(QPointF(tick, cy + ch - 17 * u), QPointF(tick, cy + ch - 9 * u))
                tick += TICK_EVERY * u
            # The waveform: lit and grown where the playhead has passed, breathing ahead of it.
            painter.setPen(Qt.PenStyle.NoPen)
            middle = cy + (WAVE_TOP + WAVE_HEIGHT / 2) * u
            accent = self.colors['accent']
            idle = QColor(self.colors.get('idle', self.colors['border']))
            idle.setAlphaF(IDLE_ALPHA)
            for index, full in enumerate(self.heights):
                sway = IDLE_HEIGHT + IDLE_SWAY * math.sin(2 * math.pi * t / SWAY_PERIOD_S + index * 0.7)
                since = (t - self.passed_at[index]) * 1000
                if since >= 0:
                    share = sway + (full - sway) * _settle(self.small, since)
                    painter.setBrush(accent)
                else:
                    share = sway
                    painter.setBrush(idle)
                h = max(BAR_WIDTH * u, share * WAVE_HEIGHT * u)
                x = self.inner_x + index * self.bar_step + (self.bar_step - BAR_WIDTH * u) / 2
                painter.drawRoundedRect(QRectF(x, middle - h / 2, BAR_WIDTH * u, h), BAR_WIDTH * u / 2, BAR_WIDTH * u / 2)
            # Cues drop onto the lane as the stages complete.
            soft = QColor(self.colors['accent_soft'])
            edge = QColor(self.colors['accent'])
            edge.setAlphaF(0.35)
            for name, at, x, width in self.cues:
                kc = self._rise(ms - at * 1000)
                if kc <= 0:
                    continue
                painter.setOpacity(k * fade * kc)
                top = cy + LANE_TOP * u - (1 - kc) * 10 * u
                painter.setPen(QPen(edge, 1.0))
                painter.setBrush(soft)
                painter.drawRoundedRect(QRectF(x + 0.5, top + 0.5, width - 1, LANE_HEIGHT * u - 1), CUE_RADIUS * u, CUE_RADIUS * u)
                advance, _w, height, _pad = self.sprites.size(name)
                self.sprites.draw(painter, name, x + (width - advance * u) / 2, top + (LANE_HEIGHT * u - height * u) / 2, u)
            # The playhead.
            painter.setOpacity(k * fade)
            head = self.inner_x + self.progress(t) * self.inner_w
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(QRectF(head - 1, cy + 8 * u, 2, ch - 16 * u), 1, 1)
            halo = QColor(accent)
            halo.setAlphaF(0.22)
            painter.setBrush(halo)
            painter.drawEllipse(QPointF(head, cy + 9 * u), (HEAD_RADIUS + 4) * u, (HEAD_RADIUS + 4) * u)
            painter.setBrush(accent)
            painter.drawEllipse(QPointF(head, cy + 9 * u), HEAD_RADIUS * u, HEAD_RADIUS * u)
            # The stage and the percentage under the card.
            self._draw_status(painter, t, self.text_y + dy)
        painter.restore()

    def _draw_status(self, painter, t: float, y: float) -> None:
        u = self.unit
        stage = f'stage{self.stage(t)}'
        digits = [f'digit{char}' for char in f'{round(self.progress(t) * 100)}%']
        widths = [self.sprites.size(stage)[0] * u] + [self.sprites.size(name)[0] * u for name in digits]
        gap = 12 * u
        total = sum(widths) + gap
        x = (self.width - total) / 2
        self.sprites.draw(painter, stage, x, y, u)
        x += widths[0] + gap
        for name, width in zip(digits, widths[1:]):
            self.sprites.draw(painter, name, x, y, u)
            x += width

    def landing_ms(self) -> int:
        from ..design import motion_tokens as tokens
        return tokens.PAGE_IN.ms

    def draw_landing(self, painter, ms: float, picture, at, targets: dict, t: float) -> None:
        """The end (2026-11-23): Home (``picture``, the real window as it has just painted, its top
        left at ``at``) comes in under the screen while the timeline fades (LAUNCH_HANDOFF), and
        each half of the wordmark flies onto its own label in Home's header (``targets``: 'en' /
        'zh' -> (x, y, width, height), logical; PAGE_IN), giving way to the real labels in the
        last PAGE_CROSSFADE. The last frame is Home's picture alone."""
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QPainter
        from ..design import motion_tokens as tokens
        fly = self.page_in.valueForProgress(max(0.0, min(1.0, ms / tokens.PAGE_IN.ms)))
        handoff = tokens.easing_curve(tokens.LAUNCH_HANDOFF)
        fade = handoff.valueForProgress(max(0.0, min(1.0, ms / tokens.LAUNCH_HANDOFF.ms)))
        settle = max(0.0, min(1.0, (ms - (tokens.PAGE_IN.ms - tokens.PAGE_CROSSFADE.ms)) / tokens.PAGE_CROSSFADE.ms))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(QRectF(0, 0, self.width, self.height), self.colors['background'])
        if fade < 1.0:
            self.draw(painter, t, wordmark=False, fade=1.0 - fade)
        if picture is not None and fade > 0.0:
            painter.setOpacity(fade)
            painter.drawImage(QPointF(*at), picture)
            painter.setOpacity(1.0)
        if settle < 1.0:
            _left, top, _w, height = self.wordmark_rect
            for prefix, (left, width) in self.spans.items():
                target = targets.get(prefix)
                if not target:
                    continue
                tx, ty, tw, th = target
                scale = tw / max(1.0, width)
                end = (tx - left, ty + th / 2 - height * scale / 2 - top)
                current = 1.0 + (scale - 1.0) * fly
                painter.setOpacity(1.0 - settle)
                for name, x, y in self.glyphs:
                    if not name.startswith(prefix):
                        continue
                    self.sprites.draw(painter, name, left + end[0] * fly + (x - left) * current,
                                      top + end[1] * fly + (y - top) * current, self.unit * current)
        painter.restore()

    def draw_wordmark(self, painter, *, offset=(0.0, 0.0), scale: float = 1.0, opacity: float = 1.0) -> None:
        """The wordmark at rest, moved by ``offset`` and scaled about its top left (the flight)."""
        if opacity <= 0:
            return
        left, top, _w, _h = self.wordmark_rect
        painter.save()
        painter.setOpacity(opacity)
        for name, x, y in self.glyphs:
            self.sprites.draw(painter, name, left + offset[0] + (x - left) * scale,
                              top + offset[1] + (y - top) * scale, self.unit * scale)
        painter.restore()


__all__ = ['LaunchScreen', 'Sprites', 'language_key', 'palette', 'waveform']
