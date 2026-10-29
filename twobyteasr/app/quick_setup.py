"""First-run chooser: how should 兔白 turn speech into subtitles? (2026-10-14).

A new user sees two or three big rounded cards. Each has its own colour, the
models it uses, three short tags, one line, and a small animation that shows
what it actually does: the local plan cycles through speaker separation, the
three-way review (MOSS / FireRed / Qwen3, the consensus is kept) and
character-level timing; the cloud plan is quick (yellow); the light plan is
calm and slow (blue). Nothing downloads until the main button is pressed.
"自己选择模型…" hands over to the detailed ``GuidedSetupDialog``.

2026-10-21 (user): many people's computers are not strong, and MOSS Pro gives
free credit on sign-up and every daily check-in, so the cloud card comes first,
is chosen by default and says 推荐. It is MOSS Pro (cloud text and speakers) +
FireRedASR2 (subtitle times on this computer); FireRed needs an NVIDIA card
with 4 GB, so without one the times come from Qwen3 对齐 on the CPU (the card
says so). "完成后带我走一遍新手教学" is ticked by default (``tour``).

2026-10-24 (user): the plan is the tutorial's first step, and with it the
language the videos mainly speak, which decides the subtitle-time model:
FireRedASR2 for Chinese, Qwen3 对齐 (Qwen3-ForcedAligner) for Japanese, English,
Korean and the rest (FireRed only does Chinese; recognition reroutes it anyway,
see ``recognition_choices.language_timeline``). The cards, their downloads and
the saved roles follow the language picked in the row above them (``spoken``).
"""
from __future__ import annotations

import math
import sys
import threading
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..i18n import LANGUAGE_NATIVE_NAMES, bind_text, current_language, save_language, tr
from ..design.main_ui_dialogs import SpringDialog

# Fixed identity colours: each way of working keeps its colour in every theme.
PLAN_COLORS = {'local': '#3FBF8F', 'cloud': '#F2B33D', 'light': '#5B9DF0', 'apple': '#A98BF2'}
SPEAKER_B = '#E77FA8'
WRONG = '#F3866B'


@dataclass(frozen=True)
class QuickPlan:
    key: str
    title: str
    tags: tuple[str, str, str]
    line: str
    backends: tuple[str, str, str]
    scene: str
    models: tuple[str, ...] = ()


PLANS = {
    'local': QuickPlan('local', '本机识别', ('安全', '准确', '免费'), '在这台电脑上识别，影音不离开电脑',
                       ('moss', 'local', 'local'), 'local', ('MOSS', 'FireRed', 'Qwen3')),
    'apple': QuickPlan('apple', 'Mac 本机识别', ('安全', '免费', 'Apple 芯片'), '在 Mac 上识别，影音不离开电脑',
                       ('mlx_qwen3_asr', 'mlx_qwen_aligner', 'off'), 'apple', ('Qwen3-ASR', 'Qwen3 对齐')),
    'cloud': QuickPlan('cloud', '云端识别', ('不挑电脑', '送免费额度', '准确'),
                       'MOSS Pro 在云端把说话变成文字，FireRedASR2 在本机对准字幕时间',
                       ('api', 'local', 'off'), 'cloud', ('MOSS Pro', 'FireRedASR2')),
    'light': QuickPlan('light', '轻量本机', ('免费', '不用显卡', '体积小'), '用 CPU 识别，较慢，不分说话人',
                       ('sensevoice', 'off', 'off'), 'light', ('SenseVoice',)),
}

# The cloud plan's service (its key is set up in the tutorial) and its timeline
# without a usable NVIDIA card (FireRed AED needs one with 4 GB on Windows).
CLOUD_PRESET = 'mosi_moss_pro'
CLOUD_CPU_TIMELINE = ('qwen_aligner', 'Qwen3 对齐')
RECOMMENDED = 'cloud'

# 2026-10-22 (user): the tutorial asks for the plan right after the video and says what
# each one is good for and what to watch out for. ``{size}``: the plan's download in GB.
POINTS = {
    'cloud': (('电脑配置一般也能用', '速度快', '注册、每天签到都送免费额度'),
              ('音频要上传到 MOSS Pro', '要注册并填 API Key', '免费额度用完要付费')),
    'local': (('免费，不限时长', '影音不离开这台电脑', '三个模型互相核对，更准'),
              ('需要 NVIDIA 显卡', '第一次要下载模型（约 {size} GB）', '速度看电脑配置')),
    'apple': (('免费，不限时长', '影音不离开这台电脑', '用 Apple 芯片加速'),
              ('第一次要下载模型（约 {size} GB）', '速度看电脑配置')),
}

# 2026-10-24: without FireRed (any language but Chinese) two recognizers check each other.
FOREIGN_LOCAL_GOOD = ('免费，不限时长', '影音不离开这台电脑', '两个模型互相核对，更准')

# The language row (2026-10-24): the common ones as buttons, the rest in a dropdown.
SPOKEN_CHOICES = (('zh', '简体中文'), ('zh-Hant', '繁体中文'), ('ja', '日语'), ('en', '英语'), ('ko', '韩语'))
OTHER_SPOKEN = (('es', '西班牙语'), ('de', '德语'), ('fr', '法语'), ('pt', '葡萄牙语'), ('it', '意大利语'),
                ('ru', '俄语'))
SPOKEN_NAMES = dict(SPOKEN_CHOICES + OTHER_SPOKEN)


def is_chinese(language: str) -> bool:
    return str(language or '') in ('zh', 'zh-Hant')


def default_spoken(saved: str = '', interface: str = '') -> str:
    """The language row's first choice: the home page's language, else the interface's (else Chinese)."""
    for value in (saved, interface):
        if str(value or '') in SPOKEN_NAMES:
            return str(value)
    return 'zh'


def plan_backends(key: str, language: str, cloud_timeline_backend: str = '') -> tuple[str, str, str]:
    """(primary, timeline, review) of a plan for the language the videos speak (2026-10-24).

    The cloud plan's timeline is what this computer can run (``cloud_timeline``).
    FireRedASR2 times Chinese only: any other language uses Qwen3 对齐, as the
    recognition plans 日语 / 外语 do.
    """
    primary, timeline, review = PLANS[key].backends
    if key == 'cloud' and cloud_timeline_backend:
        timeline = cloud_timeline_backend
    if timeline == 'local' and not is_chinese(language):
        timeline = 'qwen_aligner'
    return primary, timeline, review


def plan_points(key: str, language: str):
    """The comparison's (good, care) lines for a plan and language."""
    good, care = POINTS[key]
    if key == 'local' and not is_chinese(language):
        good = FOREIGN_LOCAL_GOOD
    return good, care


def plan_models(key: str, timeline: str) -> tuple[str, ...]:
    """The model names a card shows for its (language-dependent) timeline."""
    if key == 'cloud':
        return {'local': PLANS['cloud'].models, 'off': ('MOSS Pro',)}.get(timeline, ('MOSS Pro', 'Qwen3 对齐'))
    if key == 'local' and timeline != 'local':
        return ('MOSS', 'Qwen3', 'Qwen3 对齐')
    return PLANS[key].models


def language_advice(language: str) -> str:
    """One line under the language row: which model times the subtitles, and why (translated, **marked**)."""
    name = tr(SPOKEN_NAMES.get(language, '简体中文'))
    if is_chinese(language):
        return tr('{value0}：字幕时间用 **FireRedASR2**，每个字的时间最准（要 NVIDIA 显卡，没有就用 Qwen3 对齐）',
                  value0=name)
    return tr('{value0}：字幕时间用 **Qwen3 对齐**，每个字词都对得准，不用显卡也能跑（FireRedASR2 只对中文）',
              value0=name)


# Captions of the demonstrations (what the picture is showing right now).
LOCAL_DEMOS = ('分说话人', '三路审核', '字级时间')
REVIEW_ROWS = (('MOSS', '今天来玩新版本', -1), ('FireRed', '今天来玩新版本', -1), ('Qwen3', '今天来完新版本', 3))
WORD_SAMPLE = '今天我们来玩'


def plans_for_this_computer(platform: str | None = None, apple_silicon: bool | None = None) -> list[str]:
    """Cards this computer can use: no CUDA card on a Mac, no local card on an Intel Mac."""
    platform = platform or sys.platform
    if platform == 'darwin':
        if apple_silicon is None:
            from ..recognition.mlx_backend import platform_supported
            apple_silicon = platform_supported()
        return ['cloud', 'apple', 'light'] if apple_silicon else ['cloud']
    return ['cloud', 'local', 'light']


def cloud_timeline(inventory=None, platform: str | None = None, apple_silicon: bool | None = None) -> str:
    """The cloud plan's subtitle-time model on this computer (2026-10-21).

    FireRedASR2 (``local``) wherever it can run: an NVIDIA card with enough
    memory (``vram_check`` says ok, tight, or could not read the memory of a
    card it found). Without one, Qwen3 对齐 on the CPU; an Apple-chip Mac uses
    its MLX build, an Intel Mac has no local model at all.
    """
    platform = platform or sys.platform
    if platform == 'darwin':
        if apple_silicon is None:
            from ..recognition.mlx_backend import platform_supported
            apple_silicon = platform_supported()
        return 'mlx_qwen_aligner' if apple_silicon else 'off'
    from ..system import vram_check
    if inventory is None:
        inventory = vram_check.read_gpu_inventory()
    level = vram_check.assess(('firered_aed',), inventory).level
    return 'local' if level in {'ok', 'tight', 'unknown'} else CLOUD_CPU_TIMELINE[0]


def _mix(color: str, alpha: float) -> QColor:
    value = QColor(color)
    value.setAlphaF(max(0.0, min(1.0, alpha)))
    return value


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def scene_movie_path(scene: str, light_theme: bool, still: bool = False):
    """assets/onboarding/<scene>-<dark|light>.webp (or -still.png), made from source/scenes.html."""
    from .main_ui_helpers import APP_ROOT
    name = f"{scene}-{'light' if light_theme else 'dark'}" + ('-still.png' if still else '.webp')
    path = APP_ROOT / 'assets' / 'onboarding' / name
    return path if path.is_file() else None


class PlanScene(QWidget):
    """A small motion graphic of what the plan really does.

    local: speakers in two colours → three models compared, the agreeing text
    kept → every character with its own time. cloud: up and back, fast.
    light: one character after another, slowly. apple: character timing.
    The designed animation is an animated WebP rendered from HTML
    (assets/onboarding/source/scenes.html); the caption is drawn here so it
    follows the interface language. Without the file the same story is drawn
    with QPainter. Plays only while its card is selected or hovered and never
    when reduced motion is asked for; otherwise a still frame is shown.
    """

    DURATIONS = {'local': 9600, 'cloud': 2400, 'light': 5600, 'apple': 3400}
    STILL = {'local': 0.30, 'cloud': 0.85, 'light': 0.7, 'apple': 0.75}

    def __init__(self, scene: str, color: str, parent=None):
        super().__init__(parent)
        self.scene, self.color = scene, color
        self.phase = self.STILL.get(scene, 0.7)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(124)
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(self.DURATIONS.get(scene, 3000))
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QEasingCurve.Type.Linear)
        self._animation.valueChanged.connect(self._advance)
        self._muted, self._surface, self._text = '#8a8494', '#252028', '#f4eef6'
        self._movie = None
        self._still = None
        self._load_movie(False)

    def _load_movie(self, light_theme: bool) -> None:
        from PySide6.QtGui import QMovie, QPixmap
        path = scene_movie_path(self.scene, light_theme)
        still = scene_movie_path(self.scene, light_theme, still=True)
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None
        self._still = QPixmap(str(still)) if still is not None else None
        if path is None or self._still is None or self._still.isNull():
            self._still = None
            return
        movie = QMovie(str(path), parent=self)
        if not movie.isValid():
            return
        movie.setCacheMode(QMovie.CacheMode.CacheNone)  # a few frames in memory, not the whole loop
        movie.frameChanged.connect(lambda _frame: self.update())
        self._movie = movie
        self._show_still()

    def _show_still(self) -> None:
        self._playing = False
        self.update()

    def set_palette(self, muted: str, surface: str, text: str = '#f4eef6') -> None:
        self._muted, self._surface, self._text = muted, surface, text
        self._load_movie(QColor(surface).lightnessF() > 0.6)
        self.update()

    def set_active(self, active: bool) -> None:
        from PySide6.QtGui import QMovie
        from ..design.ui_motion import reduced_motion
        play = active and not reduced_motion()
        if self._movie is not None:
            if play and self._movie.state() != QMovie.MovieState.Running:
                self._playing = True
                self._movie.start()
            elif not play:
                self._movie.stop()
                self._show_still()
            return
        if play:
            if self._animation.state() != QVariantAnimation.State.Running:
                self._animation.start()
        else:
            self._animation.stop()
            self.phase = self.STILL.get(self.scene, 0.7)
            self.update()

    def hideEvent(self, event):  # noqa: N802 - Qt override
        self._animation.stop()
        if self._movie is not None:
            self._movie.stop()
        super().hideEvent(event)

    def _movie_caption(self) -> str:
        if self.scene == 'local':
            if not getattr(self, '_playing', False):
                return LOCAL_DEMOS[0]
            count = max(1, self._movie.frameCount())
            return LOCAL_DEMOS[min(2, max(0, self._movie.currentFrameNumber()) * 3 // count)]
        return {'cloud': '云端听写 + 本机对时间', 'light': '本机 CPU，慢慢来', 'apple': '字级时间'}.get(self.scene, '')

    def _advance(self, value) -> None:
        self.phase = float(value)
        self.update()

    # ------------------------------------------------------------- drawing
    def paintEvent(self, _event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        width, height = float(self.width()), float(self.height())
        if self._movie is not None:
            frame = self._movie.currentPixmap() if getattr(self, '_playing', False) else self._still
            if frame is None or frame.isNull():
                frame = self._still
            if frame is not None and not frame.isNull():
                # The 2x frame, scaled to the card width (aspect kept), then the translated caption.
                scale = min(width / frame.width(), height / frame.height())
                w, h = frame.width() * scale, frame.height() * scale
                painter.drawPixmap(QRectF((width - w) / 2, (height - h) / 2, w, h), frame, QRectF(frame.rect()))
                self._caption(painter, self._movie_caption(), width)
                painter.end()
                return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_mix(self.color, 0.10))
        painter.drawRoundedRect(QRectF(0, 0, width, height), 16, 16)
        if self.scene == 'local':
            demo = min(2, int(self.phase * 3))
            local = (self.phase * 3) % 1.0
            self._caption(painter, LOCAL_DEMOS[demo], width)
            (self._speakers, self._review, self._words)[demo](painter, width, height, local)
        elif self.scene == 'cloud':
            self._caption(painter, '云端听写 + 本机对时间', width)
            self._cloud(painter, width, height, self.phase)
        elif self.scene == 'light':
            self._caption(painter, '本机 CPU，慢慢来', width)
            self._light(painter, width, height, self.phase)
        else:
            self._caption(painter, '字级时间', width)
            self._words(painter, width, height, self.phase)
        painter.end()

    def _font(self, painter, size, bold=False):
        font = QFont(self.font())
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)

    def _caption(self, painter, text, width):
        self._font(painter, 12, True)
        label = str(tr(text))
        metrics = painter.fontMetrics()
        rect = QRectF(10, 9, metrics.horizontalAdvance(label) + 18, 21)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_mix(self.color, 0.22))
        painter.drawRoundedRect(rect, 10.5, 10.5)
        painter.setPen(QColor(self.color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _bars(self, painter, x0, cy, count, colors, played, speed=1.5, gap=7.0, height=30.0):
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(count):
            level = 0.35 + 0.65 * abs(math.sin(2 * math.pi * self.phase * speed + index * 0.9))
            alpha = 1.0 if index < played else 0.35
            painter.setBrush(_mix(colors[index], alpha))
            bar = height * level
            painter.drawRoundedRect(QRectF(x0 + index * gap, cy - bar / 2, 4.5, bar), 2.2, 2.2)

    def _bubble(self, painter, x, y, width, badge, badge_color, text, alpha):
        if alpha <= 0:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_mix(self._surface, 0.95 * alpha))
        painter.drawRoundedRect(QRectF(x, y, width, 24), 12, 12)
        painter.setBrush(_mix(badge_color, alpha))
        painter.drawEllipse(QRectF(x + 4, y + 3, 18, 18))
        self._font(painter, 11, True)
        painter.setPen(_mix('#ffffff', alpha))
        painter.drawText(QRectF(x + 4, y + 3, 18, 18), Qt.AlignmentFlag.AlignCenter, badge)
        self._font(painter, 13)
        painter.setPen(_mix(self._text, alpha))
        painter.drawText(QRectF(x + 28, y, width - 32, 24), Qt.AlignmentFlag.AlignVCenter, text)

    def _speakers(self, painter, width, height, p):
        """Two voices, two colours: each line knows who spoke it."""
        colors = [self.color] * 5 + [SPEAKER_B] * 5
        self._bars(painter, 16, height * 0.62, 10, colors, played=int(p * 1.25 * 10))
        x = 104
        self._bubble(painter, x, 42, width - x - 12, 'A', self.color, '大家好，今天来玩', _clamp((p - 0.18) / 0.15))
        self._bubble(painter, x, 76, width - x - 12, 'B', SPEAKER_B, '欢迎回来！', _clamp((p - 0.55) / 0.15))

    def _review(self, painter, width, height, p):
        """Three models, one sentence: the agreeing text is kept, the odd one out is flagged."""
        decided = p > 0.55
        for index, (model, text, wrong_at) in enumerate(REVIEW_ROWS):
            alpha = _clamp((p - index * 0.13) / 0.13)
            if alpha <= 0:
                continue
            y = 38 + index * 27
            agree = wrong_at < 0
            painter.setPen(QPen(_mix(self.color if decided and agree else self._muted, 0.9 * alpha), 1.3))
            painter.setBrush(_mix(self.color if decided and agree else self._surface, 0.18 if decided and agree else 0.9))
            painter.drawRoundedRect(QRectF(12, y, width - 24, 22), 11, 11)
            self._font(painter, 11, True)
            painter.setPen(_mix(self._muted if not (decided and agree) else self.color, alpha))
            painter.drawText(QRectF(20, y, 62, 22), Qt.AlignmentFlag.AlignVCenter, model)
            self._font(painter, 13)
            x = 84.0
            for position, char in enumerate(text):
                flagged = decided and position == wrong_at
                painter.setPen(_mix(WRONG if flagged else self._text, alpha * (0.55 if decided and not agree and not flagged else 1)))
                painter.drawText(QPointF(x, y + 16), char)
                x += painter.fontMetrics().horizontalAdvance(char)
            if decided:
                mark = '✓' if agree else '✕'
                self._font(painter, 13, True)
                painter.setPen(_mix(self.color if agree else WRONG, _clamp((p - 0.55) / 0.1)))
                painter.drawText(QRectF(width - 40, y, 22, 22), Qt.AlignmentFlag.AlignCenter, mark)

    def _words(self, painter, width, height, p):
        """Every character has its own time: the playhead lights them one by one."""
        chars = WORD_SAMPLE
        left, right = 26.0, width - 26.0
        step = (right - left) / len(chars)
        ruler_y = height - 22
        painter.setPen(QPen(_mix(self._muted, 0.6), 1.2))
        painter.drawLine(QPointF(left - 8, ruler_y), QPointF(right + 8, ruler_y))
        head = left - 8 + (right - left + 16) * _clamp(p / 0.85)
        self._font(painter, 20, True)
        for index, char in enumerate(chars):
            cx = left + step * (index + 0.5)
            lit = head >= cx
            painter.setPen(QPen(_mix(self.color if lit else self._muted, 0.8), 1.2, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(cx, 70), QPointF(cx, ruler_y - 3))
            painter.setPen(QPen(_mix(self.color if lit else self._muted, 1.0), 2))
            painter.drawLine(QPointF(cx, ruler_y - 4), QPointF(cx, ruler_y + 4))
            painter.setPen(QColor(self.color) if lit else _mix(self._text, 0.45))
            painter.drawText(QRectF(cx - step / 2, 38, step, 30), Qt.AlignmentFlag.AlignCenter, char)
        painter.setPen(QPen(QColor(self.color), 2))
        painter.drawLine(QPointF(head, 36), QPointF(head, ruler_y + 6))

    def _cloud(self, painter, width, height, p):
        """Up to the provider and straight back: quick."""
        cy = height * 0.66
        self._bars(painter, 14, cy, 6, [self.color] * 6, played=6, speed=3.0, gap=7.0, height=26)
        cx, top = width * 0.5, 50.0
        cloud = QPainterPath()
        cloud.addRoundedRect(QRectF(cx - 24, top + 2, 52, 14), 7, 7)
        for dx, dy, radius in ((-14, 4, 11), (2, -4, 15), (18, 4, 11)):
            puff = QPainterPath()
            puff.addEllipse(QPointF(cx + dx, top + dy), radius, radius)
            cloud = cloud.united(puff)
        painter.setPen(QPen(QColor(self.color), 2))
        painter.setBrush(_mix(self.color, 0.25))
        painter.drawPath(cloud)
        start, end = QPointF(60, cy), QPointF(width * 0.68, cy)
        # Speed streaks: up into the cloud, then down to the subtitles.
        for lane in range(3):
            t = (p * 1.0 + lane * 0.12) % 1.0
            if t < 0.45:
                a, b = start, QPointF(cx - 30, top + 12)
                u = t / 0.45
            elif t < 0.9:
                a, b = QPointF(cx + 32, top + 12), end
                u = (t - 0.45) / 0.45
            else:
                continue
            head = QPointF(a.x() + (b.x() - a.x()) * u, a.y() + (b.y() - a.y()) * u)
            tail_u = max(0.0, u - 0.28)
            tail = QPointF(a.x() + (b.x() - a.x()) * tail_u, a.y() + (b.y() - a.y()) * tail_u)
            painter.setPen(QPen(_mix(self.color, 0.85), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(tail, head)
        # The subtitles snap in at once.
        shown = _clamp((p - 0.5) / 0.08)
        x0 = width * 0.68 + 6
        painter.setPen(Qt.PenStyle.NoPen)
        for index, scale in enumerate((1.0, 0.75, 0.55)):
            painter.setBrush(_mix(self.color, shown))
            painter.drawRoundedRect(QRectF(x0, cy - 18 + index * 14 - (1 - shown) * 6,
                                           (width - x0 - 14) * scale, 7), 3.5, 3.5)

    def _light(self, painter, width, height, p):
        """On this computer's CPU, one character after another, calmly."""
        cy = height * 0.64
        self._bars(painter, 14, cy, 5, [self.color] * 5, played=5, speed=0.6, gap=7.0, height=24)
        chip = QRectF(62, cy - 18, 36, 36)
        breath = 0.18 + 0.14 * (0.5 + 0.5 * math.sin(2 * math.pi * p))
        painter.setPen(QPen(QColor(self.color), 2))
        painter.setBrush(_mix(self.color, breath))
        painter.drawRoundedRect(chip, 8, 8)
        for offset in (-8, 0, 8):
            painter.drawLine(QPointF(80 + offset, cy - 22), QPointF(80 + offset, cy - 18))
            painter.drawLine(QPointF(80 + offset, cy + 18), QPointF(80 + offset, cy + 22))
        self._font(painter, 18, True)
        text = '我们去看看吧'
        x = 112.0
        for index, char in enumerate(text):
            alpha = _clamp((p * len(text) * 1.15 - index) / 1.0)
            painter.setPen(_mix(self.color, alpha))
            painter.drawText(QPointF(x, cy + 7), char)
            x += painter.fontMetrics().horizontalAdvance(char)


class PlanCard(QFrame):
    """One way of working: picture, name, three tags, one line, one status."""

    clicked = Signal(str)

    def __init__(self, plan: QuickPlan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.color = PLAN_COLORS[plan.scene]
        self.setObjectName('quickPlanCard')
        self.setProperty('selected', False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 16)
        layout.setSpacing(10)
        self.scene = PlanScene(plan.scene, self.color, self)
        layout.addWidget(self.scene)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLabel()
        bind_text(self.title, plan.title)
        self.title.setObjectName('quickPlanTitle')
        title_row.addWidget(self.title)
        self.badge = None
        if plan.key == RECOMMENDED:
            self.badge = QLabel()
            bind_text(self.badge, '推荐')
            self.badge.setObjectName('quickPlanBadge')
            title_row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        self.check = QLabel('✓')
        self.check.setObjectName('quickPlanCheck')
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check.setFixedSize(22, 22)
        self.check.hide()
        title_row.addWidget(self.check)
        layout.addLayout(title_row)
        self.models = None
        if plan.models:
            self.models = QLabel(' · '.join(plan.models))
            self.models.setObjectName('quickPlanModels')
            layout.addWidget(self.models)
        tags = QHBoxLayout()
        tags.setSpacing(6)
        for word in plan.tags:
            tag = QLabel()
            bind_text(tag, word)
            tag.setObjectName('quickPlanTag')
            tags.addWidget(tag)
        tags.addStretch(1)
        layout.addLayout(tags)
        self.line = QLabel()
        bind_text(self.line, plan.line)
        self.line.setObjectName('quickPlanLine')
        self.line.setWordWrap(True)
        layout.addWidget(self.line)
        self.status = QLabel()
        self.status.setObjectName('quickPlanStatus')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.points = []

    def add_points(self, good, care, size: float = 0.0) -> None:
        """What the plan is good for (✓) and what to watch out for (!), one short line each (2026-10-22)."""
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        import html
        theme = theme_definition(theme_key())
        layout = self.layout()
        for label in self.points:   # 2026-10-24: called again when the language (and the download) changes
            layout.removeWidget(label)
            label.hide()
            label.deleteLater()
        self.points = []
        for lines, mark, color in ((good, '✓', theme.success), (care, '!', theme.warning)):
            for line in lines:
                words = str(tr(line)).replace('{size}', f'{size:.1f}')
                label = QLabel(f'<span style="color:{color}; font-weight:800;">{mark}</span>&nbsp;&nbsp;'
                               + html.escape(words))
                label.setObjectName('quickPlanPoint')
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setWordWrap(True)
                layout.insertWidget(layout.indexOf(self.status), label)
                self.points.append(label)

    def set_selected(self, selected: bool) -> None:
        self.setProperty('selected', bool(selected))
        self.check.setVisible(bool(selected))
        self.scene.set_active(bool(selected) or self.underMouse())
        self.style().unpolish(self)
        self.style().polish(self)

    def set_status(self, text: str, tone: str = 'muted') -> None:
        self.status.setText(text)
        self.status.setProperty('tone', tone)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.plan.key)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.isEnabled():
            self.clicked.emit(self.plan.key)
            return
        super().keyPressEvent(event)

    def enterEvent(self, event):  # noqa: N802 - Qt override
        self.scene.set_active(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        self.scene.set_active(bool(self.property('selected')))
        super().leaveEvent(event)


def card_qss(theme) -> str:
    css = [
        f"QDialog#quickSetup {{ background: {theme.app_background}; }}",
        f"QLabel#quickSetupTitle {{ color: {theme.text}; font-size: 24px; font-weight: 800; }}",
        f"QLabel#quickSetupSubtitle {{ color: {theme.text_muted}; font-size: 14px; }}",
        f"QLabel#quickPlanTitle {{ color: {theme.text}; font-size: 17px; font-weight: 700; }}",
        f"QLabel#quickPlanLine {{ color: {theme.text_secondary}; font-size: 13px; }}",
        f"QLabel#quickPlanPoint {{ color: {theme.text}; font-size: 13px; }}",
        f"QLabel#quickPlanModels {{ color: {theme.text_secondary}; font-size: 12px; font-weight: 600; }}",
        f"QLabel#quickPlanBadge {{ background: {theme.accent}; color: {theme.text_on_accent}; border-radius: 9px;"
        f" padding: 2px 9px; font-size: 12px; font-weight: 800; }}",
        f"QCheckBox#quickSetupTour {{ color: {theme.text_secondary}; font-size: 13px; spacing: 8px; }}",
        f"QLabel#quickPlanStatus {{ color: {theme.text_muted}; font-size: 12px; }}",
        f"QLabel#quickPlanStatus[tone=\"good\"] {{ color: {theme.success}; }}",
        f"QLabel#quickPlanStatus[tone=\"bad\"] {{ color: {theme.danger}; }}",
        f"QLabel#quickPlanStatus[tone=\"warn\"] {{ color: {theme.warning}; }}",
        f"QPushButton#quickSetupLink {{ background: transparent; border: 0; color: {theme.text_muted}; padding: 6px 2px; }}",
        f"QPushButton#quickSetupLink:hover {{ color: {theme.accent}; }}",
        # 2026-10-24: the language row, as tall as the 其他语言 dropdown beside it (the app sheet's
        # button min-height made the buttons a third taller); radius under half the ~31 px height.
        f"QLabel#quickLanguageLabel {{ color: {theme.text}; font-size: 14px; font-weight: 700; }}",
        f"QPushButton#quickLanguage {{ background: {theme.surface}; color: {theme.text}; border: 1.5px solid {theme.border};"
        f" border-radius: 12px; padding: 4px 14px; min-height: 20px; font-size: 13px; font-weight: 600; }}",
        f"QPushButton#quickLanguage:hover {{ border-color: {theme.accent}; }}",
        f"QPushButton#quickLanguage:checked {{ background: {theme.accent_tint}; color: {theme.accent};"
        f" border: 2px solid {theme.accent}; font-weight: 700; }}",
        f"QLabel#quickLanguageAdvice {{ color: {theme.text_secondary}; font-size: 13px; }}",
    ]
    for key, color in PLAN_COLORS.items():
        tint = _mix(color, 0.16).name(QColor.NameFormat.HexArgb)
        soft = _mix(color, 0.08).name(QColor.NameFormat.HexArgb)
        selector = f'QFrame#quickPlanCard[plan="{key}"]'
        css += [
            f"{selector} {{ background: {theme.surface}; border: 1.5px solid {theme.border}; border-radius: 18px; }}",
            f"{selector}:hover {{ border-color: {color}; }}",
            f"{selector}[selected=\"true\"] {{ background: {soft}; border: 2px solid {color}; }}",
            f"{selector}:focus {{ border-color: {color}; }}",
            f"{selector}:disabled {{ background: {theme.panel}; }}",
            f"{selector} QLabel#quickPlanTag {{ background: {tint}; color: {color}; border-radius: 9px;"
            f" padding: 2px 9px; font-size: 12px; font-weight: 600; }}",
            f"{selector} QLabel#quickPlanCheck {{ background: {color}; color: #ffffff; border-radius: 11px;"
            f" font-weight: 800; }}",
        ]
    return '\n'.join(css)


def _probe_cuda(relay: '_CudaRelay') -> None:
    try:
        from ..system.hardware import detect_cuda_runtime
        status = detect_cuda_runtime()
    except Exception:  # noqa: BLE001 - shown as "could not check"
        status = None
    try:
        relay.finished.emit(status)
    except RuntimeError:
        pass  # dialog already closed


class _CudaRelay(QObject):
    """Carries the background CUDA check to the GUI thread (the thread never holds the dialog)."""

    finished = Signal(object)


class QuickSetupDialog(SpringDialog):
    """Pick one way of working. ``choice`` is the plan key, 'custom', or None."""

    cuda_ready = Signal(object)

    def __init__(self, parent=None, *, plan_keys: list[str] | None = None, size_of=None, compare: bool = False,
                 current: str = '', spoken: str = ''):
        super().__init__(parent)
        # 2026-10-22: ``compare`` is the tutorial's plan step: cloud and local side by side with
        # what each is good for, the saved plan (``current``) chosen; no tutorial box, no language.
        self.compare = bool(compare)
        if self.compare and plan_keys is None:
            plan_keys = [key for key in plans_for_this_computer() if key != 'light']
        from ..design.presentation import button_role
        from ..design.main_ui_popup import FramelessPopupCombo
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        self.setObjectName('quickSetup')
        bind_text(self, '选择识别方式 - 2ByteASR', property='windowTitle')
        self.choice: str | None = None
        self.backends: tuple[str, str, str] | None = None
        # Cloud service the API guide should open on ('' = the saved one).
        self.api_preset = ''
        self.tour = True                  # start the tutorial once the window is back on the home page
        self._size_of = size_of or (lambda backends: 0.0)
        self._cuda = None
        self._cuda_answered = False                        # the background graphics card check has answered
        self._cloud_timeline = PLANS['cloud'].backends[1]   # until the graphics card check says otherwise
        # 2026-10-24: the language the videos mainly speak (the row above the cards).
        self.spoken = default_spoken(spoken, current_language())
        theme = theme_definition(theme_key())
        self._theme = theme
        self.setStyleSheet(card_qss(theme))
        self.setMinimumWidth(760)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 26)
        outer.setSpacing(18)
        header = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(6)
        title = QLabel()
        bind_text(title, '识别方案：用云端还是本机？' if self.compare else '选一种方式开始')
        title.setObjectName('quickSetupTitle')
        words.addWidget(title)
        subtitle = QLabel()
        bind_text(subtitle, '两种都能做字幕。看看好处和要注意的，选一个；以后在模型工坊随时能换' if self.compare
                  else '选好就能用；之后随时可以在模型工坊更换')
        subtitle.setWordWrap(True)
        subtitle.setObjectName('quickSetupSubtitle')
        words.addWidget(subtitle)
        header.addLayout(words, 1)
        self.lang_combo = FramelessPopupCombo()
        for code, label in LANGUAGE_NATIVE_NAMES.items():
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(current_language())))
        self.lang_combo.currentIndexChanged.connect(lambda index: save_language(self.lang_combo.itemData(index) or 'zh'))
        header.addWidget(self.lang_combo, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)
        outer.addLayout(self._build_spoken_row())
        self.spoken_advice = QLabel()
        self.spoken_advice.setObjectName('quickLanguageAdvice')
        self.spoken_advice.setTextFormat(Qt.TextFormat.RichText)
        self.spoken_advice.setWordWrap(True)
        outer.addWidget(self.spoken_advice)
        row = QHBoxLayout()
        row.setSpacing(14)
        self.cards: dict[str, PlanCard] = {}
        for key in plan_keys or plans_for_this_computer():
            card = PlanCard(PLANS[key], self)
            card.setProperty('plan', key)
            card.scene.set_palette(theme.text_muted, theme.surface, theme.text)
            card.clicked.connect(self.select)
            row.addWidget(card, 1, Qt.AlignmentFlag.AlignTop)
            self.cards[key] = card
            if self.compare and key in POINTS:
                card.add_points(*plan_points(key, self.spoken), size=self._size_of(self.plan_backends(key)))
        outer.addLayout(row)
        source_row = QHBoxLayout()
        source_label = QLabel()
        bind_text(source_label, '模型下载来源')
        source_row.addWidget(source_label)
        self.source_combo = FramelessPopupCombo()
        self.source_combo.setObjectName('quickSetupSource')
        from ..download_sources import user_facing_source_choices
        for item in user_facing_source_choices():
            self.source_combo.addItem(item['label'], item['mode'])
        source_row.addWidget(self.source_combo)
        source_row.addStretch(1)
        outer.addLayout(source_row)
        self.runtime_note = QLabel()
        self.runtime_note.setWordWrap(True)
        bind_text(self.runtime_note, '模型容量不含 Python 和依赖套件，首次使用会自动准备；无需安装系统 Python。')
        bind_text(self.source_combo, '选择 ModelScope 时，模型使用 ModelScope，Python 和依赖套件另按固定清单优先使用国内镜像。', property='toolTip')
        outer.addWidget(self.runtime_note)
        outer.addStretch(1)
        from PySide6.QtWidgets import QCheckBox
        self.tour_check = QCheckBox()
        bind_text(self.tour_check, '选好后带我走一遍新手教学（推荐，约 6 分钟）')
        self.tour_check.setObjectName('quickSetupTour')
        self.tour_check.setChecked(True)
        self.tour_check.setCursor(Qt.CursorShape.PointingHandCursor)
        outer.addWidget(self.tour_check)
        if self.compare:   # inside the tutorial: no second tutorial, no language switch
            self.tour_check.setChecked(False)
            self.tour_check.hide()
            self.lang_combo.hide()
        footer = QHBoxLayout()
        custom = QPushButton()
        bind_text(custom, '自己选择模型…')
        custom.setObjectName('quickSetupLink')
        custom.setCursor(Qt.CursorShape.PointingHandCursor)
        custom.clicked.connect(self._choose_custom)
        footer.addWidget(custom)
        custom.setVisible(not self.compare)
        # 2026-10-15: many people have never heard of an API key (or that it needs credit).
        key_help = QPushButton()
        bind_text(key_help, 'API Key 是什么？')
        key_help.setObjectName('quickSetupLink')
        key_help.setCursor(Qt.CursorShape.PointingHandCursor)
        key_help.clicked.connect(self._explain_api_key)
        footer.addWidget(key_help)
        footer.addStretch(1)
        self.later_button = button_role(QPushButton(), 'secondary')
        bind_text(self.later_button, '先不换' if self.compare else '稍后再说')
        self.later_button.clicked.connect(self.reject)
        footer.addWidget(self.later_button)
        self.go_button = button_role(QPushButton(), 'primary', size='large')
        self.go_button.setObjectName('quickSetupGo')
        self.go_button.setMinimumWidth(220)
        self.go_button.clicked.connect(self._go)
        footer.addWidget(self.go_button)
        outer.addLayout(footer)
        for key, card in self.cards.items():
            if key != 'cloud':
                card.set_status(tr('下载约 {size:.1f} GB', size=self._size_of(self.plan_backends(key))))
        self.cuda_ready.connect(self._cuda_checked)
        if 'cloud' in self.cards:
            self._show_cloud_timeline(cloud_timeline() if sys.platform == 'darwin' else self._cloud_timeline)
        if 'local' in self.cards or ('cloud' in self.cards and sys.platform != 'darwin'):
            self._show_local_status()   # 正在检查显卡… until the check answers
            relay = _CudaRelay(self)   # dies with the dialog; a late result is simply dropped
            relay.finished.connect(self._cuda_checked)
            threading.Thread(target=_probe_cuda, args=(relay,), name='quick-setup-cuda', daemon=True).start()
        start = current if self.compare and current in self.cards else RECOMMENDED
        self.select(start if start in self.cards else next(iter(self.cards)))
        self.set_spoken(self.spoken)
        self.lang_combo.currentIndexChanged.connect(lambda _index: QTimer.singleShot(0, self._show_spoken))
        self.resize(940, self.sizeHint().height())

    # ------------------------------------------------------------- language
    def _build_spoken_row(self) -> QHBoxLayout:
        """视频里主要说什么话？ The common languages as buttons, the others in a dropdown (2026-10-24)."""
        from ..design.main_ui_popup import FramelessPopupCombo
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel()
        bind_text(label, '视频里主要说什么话？')
        label.setObjectName('quickLanguageLabel')
        row.addWidget(label)
        row.addSpacing(4)
        self.spoken_buttons: dict[str, QPushButton] = {}
        for code, name in SPOKEN_CHOICES:
            button = QPushButton()
            bind_text(button, name)
            button.setObjectName('quickLanguage')
            button.setProperty('language', code)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=code: self.set_spoken(value))
            row.addWidget(button)
            self.spoken_buttons[code] = button
        self.spoken_other = FramelessPopupCombo()
        self.spoken_other.setObjectName('quickLanguageOther')
        self.spoken_other.addItem(tr('其他语言'), '')
        for code, name in OTHER_SPOKEN:
            self.spoken_other.addItem(tr(name), code)
        self.spoken_other.currentIndexChanged.connect(self._other_spoken_picked)
        row.addWidget(self.spoken_other)
        row.addStretch(1)
        return row

    def _other_spoken_picked(self, index: int) -> None:
        code = self.spoken_other.itemData(index)
        if code:
            self.set_spoken(str(code))
        else:   # back on 其他语言: keep the language until a button is pressed
            self.set_spoken(self.spoken)

    def set_spoken(self, code: str) -> None:
        """The videos mainly speak ``code``: the cards show its models, downloads and timeline."""
        if code not in SPOKEN_NAMES:
            return
        self.spoken = code
        for value, button in self.spoken_buttons.items():
            button.setChecked(value == code)
        blocked = self.spoken_other.blockSignals(True)
        self.spoken_other.setCurrentIndex(0 if code in self.spoken_buttons else max(0, self.spoken_other.findData(code)))
        self.spoken_other.blockSignals(blocked)
        self._show_spoken()

    def _show_spoken(self) -> None:
        from .onboarding import emphasis_html
        self.spoken_advice.setText(emphasis_html(str(language_advice(self.spoken)), self._theme.accent))
        if 'cloud' in self.cards:
            self._show_cloud_timeline(self._cloud_timeline)
        card = self.cards.get('local')
        if card is not None:
            if card.models is not None:
                card.models.setText(' · '.join(str(tr(name)) for name in
                                               plan_models('local', self.plan_backends('local')[1])))
            if self.compare:
                card.add_points(*plan_points('local', self.spoken), size=self._size_of(self.plan_backends('local')))
            self._show_local_status()
        if self.choice is not None:
            self.select(self.choice)   # the main button names this language's download

    def plan_backends(self, key: str) -> tuple[str, str, str]:
        """(primary, timeline, review) of ``key`` on this computer for the chosen language."""
        return plan_backends(key, self.spoken, self._cloud_timeline)

    # ------------------------------------------------------------- choice
    def select(self, key: str) -> None:
        if key not in self.cards or not self.cards[key].isEnabled():
            return
        self.choice = key
        # 2026-10-21: 云端识别 downloads its timeline model too, so the source applies to it as well.
        downloads = key != 'cloud' or self._cloud_timeline != 'off'
        self.source_combo.setEnabled(downloads)
        self.runtime_note.setVisible(downloads)
        for name, card in self.cards.items():
            card.set_selected(name == key)
        if self.compare:
            bind_text(self.go_button, '用这个方案')
        elif key == 'cloud':
            bind_text(self.go_button, '选好了，开始')
        else:
            bind_text(self.go_button, '准备并开始（模型约 {size:.1f} GB）', size=self._size_of(self.plan_backends(key)))

    def cloud_backends(self) -> tuple[str, str, str]:
        return self.plan_backends('cloud')

    def _show_cloud_timeline(self, timeline: str) -> None:
        """FireRedASR2 where it can run, else what replaces it, said on the card (2026-10-21).

        ``timeline`` is what this computer can run; 2026-10-24: a language other
        than Chinese uses Qwen3 对齐 even where FireRedASR2 could run."""
        self._cloud_timeline = timeline
        card = self.cards.get('cloud')
        if card is None:
            return
        shown = self.cloud_backends()[1]
        models = plan_models('cloud', shown)
        if shown == 'local':
            line = PLANS['cloud'].line
        elif shown == 'off':
            line = 'MOSS Pro 在云端把说话变成文字，还分出谁在说'
        else:
            line = ('MOSS Pro 在云端把说话变成文字，Qwen3 对齐在本机对准时间（不用 NVIDIA 显卡）'
                    if sys.platform != 'darwin' and timeline != 'local'
                    else 'MOSS Pro 在云端把说话变成文字，Qwen3 对齐在本机对准时间')
        if card.models is not None:
            card.models.setText(' · '.join(str(tr(name)) for name in models))
        bind_text(card.line, line)
        # 2026-10-22: in the comparison the card's points already say it; only the download is left.
        status = '' if self.compare else str(tr('注册、每天签到都送免费额度 · 会上传音频'))
        size = self._size_of(self.cloud_backends())
        if size:
            download = str(tr('本机时间轴模型约 {size:.1f} GB，稍后自动下载', size=size))
            status = status + '\n' + download if status else download
        card.set_status(status, 'good')

    def _cuda_checked(self, status) -> None:
        self._cuda = status
        if 'cloud' in self.cards and sys.platform != 'darwin':
            from ..system.vram_check import inventory_from_cuda_status
            try:
                self._show_cloud_timeline(cloud_timeline(inventory_from_cuda_status(status)))
            except Exception:  # noqa: BLE001 - keep FireRedASR2; the workshop checks again before downloading
                pass
        self._cuda_answered = True
        card = self.cards.get('local')
        if card is None:
            return
        if self._show_local_status():
            return
        card.setEnabled(False)
        card.setCursor(Qt.CursorShape.ArrowCursor)
        if self.choice == 'local':
            self.select('light' if 'light' in self.cards else 'cloud')

    def _show_local_status(self) -> bool:
        """The local card's graphics card and download line (False: no usable NVIDIA card).

        2026-10-24: shown again when the language changes, since the download does."""
        card = self.cards.get('local')
        if card is None:
            return False
        size = tr('下载约 {size:.1f} GB', size=self._size_of(self.plan_backends('local')))
        if not self._cuda_answered:
            card.set_status(tr('正在检查显卡…') + '  ·  ' + size)
            return True
        status = self._cuda
        gpu = str(getattr(status, 'gpu_name', '') or '')
        usable = status is not None and (getattr(status, 'ready', False)
                                         or (getattr(status, 'code', '') == 'torch_missing' and gpu))
        if not usable:
            card.set_status(tr('这台电脑没有可用的 NVIDIA 显卡'), 'bad')
            return False
        try:
            _keys, vram = self._local_vram()
        except Exception:  # noqa: BLE001 - the plain NVIDIA line is still right
            vram = None
        from ..system.vram_check import card_summary
        note = card_summary(vram) if vram is not None else ''
        if note:
            # 2026-10-15: an NVIDIA card with too little memory (RTX 2060 6 GB report).
            card.set_status(note + '  ·  ' + size, 'warn')
        else:
            card.set_status('✓ ' + gpu + '  ·  ' + size, 'good')
        return True

    def _go(self) -> None:
        if self.choice is None:
            return
        if self.choice == 'local':
            answer = self._local_vram_answer()
            if answer == 'cancel':
                return
            if answer == 'online' and 'cloud' in self.cards:
                self.select('cloud')
        if self.choice == 'cloud':
            if self._cuda is None and sys.platform != 'darwin':
                try:   # the background check is still running: nvidia-smi alone (under a second)
                    self._show_cloud_timeline(cloud_timeline())
                except Exception:  # noqa: BLE001
                    pass
            self.api_preset = CLOUD_PRESET
            self.backends = self.cloud_backends()
        else:
            self.backends = self.plan_backends(self.choice)
        self.tour = self.tour_check.isChecked()
        self.accept()

    # ------------------------------------------------------ graphics memory
    def _local_vram(self):
        """The 本机识别 download keys and how they fit this graphics card (2026-10-15)."""
        from ..system import vram_check
        from .guided_setup_dialog import GuidedSetupDialog
        keys = GuidedSetupDialog.download_keys_for(*self.plan_backends('local'))
        # The background CUDA check when it has finished, else nvidia-smi alone (under a second).
        inventory = (vram_check.inventory_from_cuda_status(self._cuda) if self._cuda is not None
                     else vram_check.read_gpu_inventory())
        return keys, vram_check.assess(keys, inventory)

    def _local_vram_answer(self) -> str:
        """'go', 'online' (改用 MOSS Pro 云端) or 'cancel'. Only a reminder: 仍然选择本机识别 goes on."""
        from ..system import vram_check
        try:
            keys, assessment = self._local_vram()
        except Exception:  # noqa: BLE001 - a failed check never blocks the choice
            return 'go'
        if (assessment.level not in {'insufficient', 'tight', 'unknown', 'no_nvidia'}
                or vram_check.acknowledged(keys)):
            return 'go'
        answer = self._ask_vram(assessment)
        if answer == 'keep':
            vram_check.acknowledge(keys)   # the workshop does not ask again
            return 'go'
        return answer

    def _ask_vram(self, assessment) -> str:
        """'online', 'keep' or 'cancel'."""
        from PySide6.QtWidgets import QMessageBox
        from ..system.vram_check import warning_text
        title, body = warning_text(assessment)
        box = QMessageBox(QMessageBox.Icon.Warning, title, body, QMessageBox.StandardButton.NoButton, self)
        box.setObjectName('vramReminder')
        online = box.addButton(tr('改用 MOSS Pro 云端'), QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton(tr('仍然选择本机识别'), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr('返回'), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(online)
        box.exec()
        return {id(online): 'online', id(keep): 'keep'}.get(id(box.clickedButton()), 'cancel')

    def _explain_api_key(self) -> None:
        from .api_key_explainer import open_api_key_explainer
        open_api_key_explainer(self, offer_setup=False)

    def _choose_custom(self) -> None:
        self.choice = 'custom'
        self.backends = None
        self.tour = self.tour_check.isChecked()
        self.accept()
