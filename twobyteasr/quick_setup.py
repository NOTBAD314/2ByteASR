"""First-run chooser: how should 兔白 turn speech into subtitles? (2026-10-14).

A new user sees two or three big rounded cards. Each has its own colour, the
models it uses, three short tags, one line, and a small animation that shows
what it actually does: the local plan cycles through speaker separation, the
three-way review (MOSS / FireRed / Qwen3, the consensus is kept) and
character-level timing; the cloud plan is quick (yellow); the light plan is
calm and slow (blue). Nothing downloads until the main button is pressed.
"自己选择模型…" hands over to the detailed ``GuidedSetupDialog``.
"""
from __future__ import annotations

import math
import sys
import threading
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .i18n import bind_text, current_language, save_language, tr
from .main_ui_dialogs import SpringDialog

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
    'cloud': QuickPlan('cloud', '云端识别', ('快速', '准确', '按量付费'), '不用显卡和下载，在服务商那里识别',
                       ('api', 'off', 'off'), 'cloud', ('MOSI', '百炼', 'Qwen Cloud')),
    'light': QuickPlan('light', '轻量本机', ('免费', '不用显卡', '体积小'), '用 CPU 识别，较慢，不分说话人',
                       ('sensevoice', 'off', 'off'), 'light', ('SenseVoice',)),
}

# Captions of the demonstrations (what the picture is showing right now).
LOCAL_DEMOS = ('分说话人', '三路审核', '字级时间')
REVIEW_ROWS = (('MOSS', '今天来玩新版本', -1), ('FireRed', '今天来玩新版本', -1), ('Qwen3', '今天来完新版本', 3))
WORD_SAMPLE = '今天我们来玩'


def plans_for_this_computer(platform: str | None = None, apple_silicon: bool | None = None) -> list[str]:
    """Cards this computer can use: no CUDA card on a Mac, no local card on an Intel Mac."""
    platform = platform or sys.platform
    if platform == 'darwin':
        if apple_silicon is None:
            from .mlx_backend import platform_supported
            apple_silicon = platform_supported()
        return ['apple', 'cloud', 'light'] if apple_silicon else ['cloud']
    return ['local', 'cloud', 'light']


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

    DURATIONS = {'local': 9600, 'cloud': 1500, 'light': 5600, 'apple': 3400}
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
        from .ui_motion import reduced_motion
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
        return {'cloud': '上传 → 很快返回', 'light': '本机 CPU，慢慢来', 'apple': '字级时间'}.get(self.scene, '')

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
            self._caption(painter, '上传 → 很快返回', width)
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
        self.title = QLabel()
        bind_text(self.title, plan.title)
        self.title.setObjectName('quickPlanTitle')
        title_row.addWidget(self.title, 1)
        self.check = QLabel('✓')
        self.check.setObjectName('quickPlanCheck')
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check.setFixedSize(22, 22)
        self.check.hide()
        title_row.addWidget(self.check)
        layout.addLayout(title_row)
        if plan.models:
            models = QLabel(' · '.join(plan.models))
            models.setObjectName('quickPlanModels')
            layout.addWidget(models)
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
        f"QLabel#quickPlanModels {{ color: {theme.text_secondary}; font-size: 12px; font-weight: 600; }}",
        f"QLabel#quickPlanStatus {{ color: {theme.text_muted}; font-size: 12px; }}",
        f"QLabel#quickPlanStatus[tone=\"good\"] {{ color: {theme.success}; }}",
        f"QLabel#quickPlanStatus[tone=\"bad\"] {{ color: {theme.danger}; }}",
        f"QPushButton#quickSetupLink {{ background: transparent; border: 0; color: {theme.text_muted}; padding: 6px 2px; }}",
        f"QPushButton#quickSetupLink:hover {{ color: {theme.accent}; }}",
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
        from .hardware import detect_cuda_runtime
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

    def __init__(self, parent=None, *, plan_keys: list[str] | None = None, size_of=None):
        super().__init__(parent)
        from .design.presentation import button_role
        from .main_ui_popup import FramelessPopupCombo
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        self.setObjectName('quickSetup')
        bind_text(self, '选择识别方式 - 2ByteASR', property='windowTitle')
        self.choice: str | None = None
        self.backends: tuple[str, str, str] | None = None
        self._size_of = size_of or (lambda backends: 0.0)
        self._cuda = None
        theme = theme_definition(theme_key())
        self.setStyleSheet(card_qss(theme))
        self.setMinimumWidth(760)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 26)
        outer.setSpacing(18)
        header = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(6)
        title = QLabel()
        bind_text(title, '选一种方式开始')
        title.setObjectName('quickSetupTitle')
        words.addWidget(title)
        subtitle = QLabel()
        bind_text(subtitle, '选好就能用；之后随时可以在模型工坊更换')
        subtitle.setObjectName('quickSetupSubtitle')
        words.addWidget(subtitle)
        header.addLayout(words, 1)
        self.lang_combo = FramelessPopupCombo()
        for label, code in (('简体中文', 'zh'), ('繁體中文', 'zh-Hant'), ('English', 'en'), ('日本語', 'ja')):
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(current_language())))
        self.lang_combo.currentIndexChanged.connect(lambda index: save_language(self.lang_combo.itemData(index) or 'zh'))
        header.addWidget(self.lang_combo, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)
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
        outer.addLayout(row)
        outer.addStretch(1)
        footer = QHBoxLayout()
        custom = QPushButton()
        bind_text(custom, '自己选择模型…')
        custom.setObjectName('quickSetupLink')
        custom.setCursor(Qt.CursorShape.PointingHandCursor)
        custom.clicked.connect(self._choose_custom)
        footer.addWidget(custom)
        footer.addStretch(1)
        self.later_button = button_role(QPushButton(), 'secondary')
        bind_text(self.later_button, '稍后再说')
        self.later_button.clicked.connect(self.reject)
        footer.addWidget(self.later_button)
        self.go_button = button_role(QPushButton(), 'primary', size='large')
        self.go_button.setObjectName('quickSetupGo')
        self.go_button.setMinimumWidth(220)
        self.go_button.clicked.connect(self._go)
        footer.addWidget(self.go_button)
        outer.addLayout(footer)
        for key, card in self.cards.items():
            backends = PLANS[key].backends
            size = self._size_of(backends)
            card.set_status(tr('需要 API Key · 会上传音频') if key == 'cloud' else tr('下载约 {size:.1f} GB', size=size))
        self.cuda_ready.connect(self._cuda_checked)
        if 'local' in self.cards:
            self.cards['local'].set_status(tr('正在检查显卡…') + '  ·  ' +
                                           tr('下载约 {size:.1f} GB', size=self._size_of(PLANS['local'].backends)))
            relay = _CudaRelay(self)   # dies with the dialog; a late result is simply dropped
            relay.finished.connect(self._cuda_checked)
            threading.Thread(target=_probe_cuda, args=(relay,), name='quick-setup-cuda', daemon=True).start()
        first = 'local' if 'local' in self.cards else next(iter(self.cards))
        self.select('apple' if 'apple' in self.cards else first)
        self.resize(940, self.sizeHint().height())

    # ------------------------------------------------------------- choice
    def select(self, key: str) -> None:
        if key not in self.cards or not self.cards[key].isEnabled():
            return
        self.choice = key
        for name, card in self.cards.items():
            card.set_selected(name == key)
        if key == 'cloud':
            bind_text(self.go_button, '去设置 API Key')
        else:
            bind_text(self.go_button, '下载并开始（约 {size:.1f} GB）', size=self._size_of(PLANS[key].backends))

    def _cuda_checked(self, status) -> None:
        self._cuda = status
        card = self.cards.get('local')
        if card is None:
            return
        size = tr('下载约 {size:.1f} GB', size=self._size_of(PLANS['local'].backends))
        gpu = str(getattr(status, 'gpu_name', '') or '')
        usable = status is not None and (getattr(status, 'ready', False)
                                         or (getattr(status, 'code', '') == 'torch_missing' and gpu))
        if usable:
            card.set_status('✓ ' + gpu + '  ·  ' + size, 'good')
            return
        card.set_status(tr('这台电脑没有可用的 NVIDIA 显卡'), 'bad')
        card.setEnabled(False)
        card.setCursor(Qt.CursorShape.ArrowCursor)
        if self.choice == 'local':
            self.select('light' if 'light' in self.cards else 'cloud')

    def _go(self) -> None:
        if self.choice is None:
            return
        self.backends = PLANS[self.choice].backends
        self.accept()

    def _choose_custom(self) -> None:
        self.choice = 'custom'
        self.backends = None
        self.accept()
