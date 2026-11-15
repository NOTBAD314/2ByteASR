"""Studio master bus controls and cancellable read-only loudness analysis.

2026-11-14 (user): 「工程音量 / 响度」 was impossible to understand. Of three drafts
they picked A, three steps: ① how loud the whole mix is now (measured on open,
shown on a ruler with the target band), ② where it is going (a destination
brings its suggested loudness, or type one), ③ one button that sets the master
gain, saying the result and whether the peak is safe. Manual gain folds away
under 「自己微调总增益」; the listening volume sits apart at the bottom in a
cool colour, because it never changes the export. The measuring, preview,
undo and cache logic is unchanged.
"""
import copy
import math
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QRectF, QPointF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QProgressBar, QSlider, QAbstractButton,
                               QWidget, QGridLayout, QToolButton, QScrollArea, QSizePolicy, QFrame)
from ..design.main_ui_dialogs import SpringDialog, DialogSurface
from ..design.studio_theme import apply_secondary_surface_theme
from ..i18n import bind_text, tr
from . import gain_scale as scale
from .gain_fader import GainFader, _theme
from ..playback.project_loudness import (baseline_identity, freeze_baseline, analyze_baseline,
    project_gain_db, project_gain_command, match_gain)

TARGET_KEY = 'loudness_target'
DESTINATION_KEY = 'loudness_destination'
# (key, icon, name, suggested integrated loudness)
DESTINATIONS = (
    ('short', 'fa5s.mobile-alt', '短视频', -14.),
    ('video', 'fa5s.desktop', '视频网站', -14.),
    ('podcast', 'fa5s.microphone', '播客 / 有声', -16.),
    ('broadcast', 'fa5s.tv', '电视广播', -23.),
)


class LoudnessWorker(QThread):
    measured = Signal(object)
    failed = Signal(str)
    progress = Signal(float)

    def __init__(self, project):
        super().__init__()
        self.project = copy.deepcopy(project)

    def run(self):
        try:
            from ..system.platform_media import ffmpeg_tool
            ffmpeg = ffmpeg_tool()
            key, baseline = freeze_baseline(self.project, ffmpeg)
            result = analyze_baseline(ffmpeg, baseline, cancelled=self.isInterruptionRequested, progress=self.progress.emit)
            self.measured.emit(dict(result, baseline_key=key))
        except InterruptedError: self.failed.emit('已取消分析，声音未改变')
        except Exception as exc: self.failed.emit(str(exc))


def loudness_target(project) -> float:
    try:
        value = float(project.studio_state.get(TARGET_KEY, -14.))
    except (TypeError, ValueError, AttributeError):
        return -14.
    return max(-60., min(-5., value)) if math.isfinite(value) else -14.


def loudness_status(loudness: float, target: float) -> tuple[str, str]:
    """(role, words): within 1 LU is 刚好, else 偏大声 / 偏小声."""
    delta = loudness - target
    if abs(delta) <= 1.:
        return 'success', '刚好'
    return ('warning', '偏大声') if delta > 0 else ('focus', '偏小声')


def loudness_readout(page):
    """(predicted LUFS, predicted true peak, target) from a still-valid analysis, else None."""
    project = getattr(page, 'project', None)
    cache = getattr(page, '_loudness_cache', None)
    if project is None or not cache:
        return None
    result = cache.get(baseline_identity(project))
    if not result:
        return None
    preview = getattr(page, '_project_gain_preview', None)
    gain = project_gain_db(project) if preview is None else float(preview)
    return result['integrated'] + gain, result['true_peak'] + gain, loudness_target(project)


def show_project_loudness(page):
    if page.project is None: return
    existing = getattr(page, '_project_loudness_panel', None)
    if existing is not None and existing.isVisible():
        existing.raise_(); existing.activateWindow(); return
    dialog = ProjectLoudnessPanel(page)
    page._project_loudness_panel = dialog
    dialog.open()


def _lufs(value: float) -> str:
    return f'{value:.1f}'.replace('-', '−')


def _role_color(theme, role: str) -> str:
    return {'success': theme.success, 'warning': theme.warning, 'focus': theme.focus,
            'danger': theme.danger}.get(role, theme.accent)


class _Pill(QLabel):
    """A rounded badge in a theme role colour (text in the role, background a soft tint)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._role = 'accent'
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContentsMargins(10, 2, 10, 2)

    def set_role(self, role: str) -> None:
        self._role = role
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt override
        from ..design.ui_theme import blend_hex
        theme = _theme()
        color = _role_color(theme, self._role)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(blend_hex(theme.surface_elevated, color, .16)))
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setPen(QColor(color))
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.text())
        painter.end()

    def sizeHint(self):  # noqa: N802 - Qt override
        hint = super().sizeHint()
        return QSize(hint.width() + 4, max(24, hint.height()))


class _StepNumber(QWidget):
    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self.number, self.done = number, False
        self.setFixedSize(28, 28)

    def set_done(self, done: bool) -> None:
        if done != self.done:
            self.done = done
            self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.success if self.done else theme.accent))
        painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        font = QFont(self.font())
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.text_on_accent))
        painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, '✓' if self.done else str(self.number))
        painter.end()


class _LoudnessRuler(QWidget):
    """−30…−6 LUFS: quiet (cool) to loud (warm), the target band in green,
    a hollow dot where the mix was and a filled dot where it will be."""

    LOW, HIGH = -30., -6.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target, self.original, self.now = -14., None, None
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, target: float, original, now) -> None:
        self.target, self.original, self.now = target, original, now
        self.update()

    def _x(self, value: float) -> float:
        left, right = 14., self.width() - 14.
        return left + (right - left) * max(0., min(1., (value - self.LOW) / (self.HIGH - self.LOW)))

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        from PySide6.QtGui import QLinearGradient
        from ..design.ui_theme import blend_hex
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = 22.
        band = QRectF(self._x(self.LOW), y - 7, self._x(self.HIGH) - self._x(self.LOW), 14)
        gradient = QLinearGradient(band.topLeft(), band.topRight())
        gradient.setColorAt(0, QColor(blend_hex(theme.input_surface, theme.focus, .22)))
        gradient.setColorAt(.45, QColor(theme.input_surface))
        gradient.setColorAt(.6, QColor(theme.input_surface))
        gradient.setColorAt(1, QColor(blend_hex(theme.input_surface, theme.danger, .2)))
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(gradient)
        painter.drawRoundedRect(band, 7, 7)
        ok = QRectF(self._x(self.target - 1), y - 9, self._x(self.target + 1) - self._x(self.target - 1), 18)
        painter.setPen(QPen(QColor(theme.success), 2))
        painter.setBrush(QColor(blend_hex(theme.surface_elevated, theme.success, .18)))
        painter.drawRoundedRect(ok, 9, 9)
        small = QFont(self.font())
        small.setPixelSize(11)
        painter.setFont(small)
        painter.setPen(QColor(theme.success))
        painter.drawText(QRectF(ok.center().x() - 40, 0, 80, 12), Qt.AlignmentFlag.AlignCenter, str(tr('目标')))
        painter.setPen(QColor(theme.focus))
        painter.drawText(QRectF(band.left(), 0, 60, 12), Qt.AlignmentFlag.AlignLeft, str(tr('小声')))
        painter.setPen(QColor(theme.danger))
        painter.drawText(QRectF(band.right() - 60, 0, 60, 12), Qt.AlignmentFlag.AlignRight, str(tr('大声')))
        painter.setPen(QColor(theme.text_muted))
        for value in (-30, -24, -18, -14, -10, -6):
            x = self._x(value)
            painter.drawText(QRectF(x - 20, y + 12, 40, 14), Qt.AlignmentFlag.AlignCenter, f'{value:g}'.replace('-', '−'))
        if self.original is not None and self.now is not None and abs(self.original - self.now) > .05:
            painter.setPen(QPen(QColor(theme.border_strong), 3))
            painter.setBrush(QColor(theme.surface_elevated))
            painter.drawEllipse(QPointF(self._x(self.original), y), 7, 7)
        if self.now is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 40))
            painter.drawEllipse(QPointF(self._x(self.now), y + 2), 12, 12)
            painter.setPen(QPen(QColor(theme.surface_elevated), 3))
            painter.setBrush(QColor(theme.accent))
            painter.drawEllipse(QPointF(self._x(self.now), y), 11, 11)
        painter.end()


class _DestinationCard(QAbstractButton):
    """A destination: icon, name and its suggested loudness. Checkable, painted round
    (not a QPushButton, so the app's push-button height rules leave it alone)."""

    def __init__(self, key, icon, name, target, parent=None):
        super().__init__(parent)
        self.key, self.icon_name, self.name, self.target = key, icon, name, target
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(104, 78)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setObjectName('loudnessDestination')
        self.setAccessibleName(f'{tr(name)} {_lufs(target)} LUFS')
        self.setToolTip(str(tr('建议 {value} LUFS', value=_lufs(target))))

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(120, 78)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        from ..design.themed_icons import themed_icon
        from ..design.ui_theme import blend_hex
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        hovered = self.underMouse()
        painter.setPen(QPen(QColor(theme.accent if self.isChecked() or hovered else theme.border), 1.6))
        painter.setBrush(QColor(theme.accent_soft if self.isChecked() else theme.surface_elevated))
        painter.drawRoundedRect(card, 14, 14)
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.focus), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(card.adjusted(2, 2, -2, -2), 12, 12)
        chip = QRectF(card.center().x() - 15, card.top() + 8, 30, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(blend_hex(theme.input_surface, theme.accent, .1)))
        painter.drawRoundedRect(chip, 10, 10)
        icon = themed_icon(self.icon_name, 'accent')
        icon.paint(painter, chip.adjusted(7, 7, -7, -7).toRect())
        name = QFont(self.font())
        name.setPixelSize(13)
        name.setBold(True)
        painter.setFont(name)
        painter.setPen(QColor(theme.text))
        painter.drawText(QRectF(card.left(), chip.bottom() + 2, card.width(), 18), Qt.AlignmentFlag.AlignCenter, str(tr(self.name)))
        value = QFont(self.font())
        value.setPixelSize(11)
        painter.setFont(value)
        painter.setPen(QColor(theme.accent_text if self.isChecked() else theme.text_muted))
        painter.drawText(QRectF(card.left(), chip.bottom() + 19, card.width(), 16), Qt.AlignmentFlag.AlignCenter,
                         f'{_lufs(self.target)} LUFS')
        painter.end()

    def enterEvent(self, event):  # noqa: N802 - Qt override
        self.update(); super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        self.update(); super().leaveEvent(event)


class _MonitorCard(QFrame):
    """The listening volume, apart and in a cool colour: it never reaches the export."""

    def paintEvent(self, event):  # noqa: N802 - Qt override
        from ..design.ui_theme import blend_hex
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        pen = QPen(QColor(theme.focus), 1.3, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(QColor(blend_hex(theme.surface_elevated, theme.focus, .1)))
        painter.drawRoundedRect(rect, 14, 14)
        painter.end()


class ProjectLoudnessPanel(SpringDialog):
    def __init__(self, page):
        super().__init__(page, backdrop=False)
        from ..design.presentation import button_role
        from ..design.themed_icons import install_themed_icon
        self.page, self.project = page, page.project
        self.closed, self.worker, self.result = False, None, None
        self.flash = None
        self.identity = baseline_identity(self.project)
        self.setObjectName('projectLoudnessPanel'); bind_text(self, '工程音量 / 响度', property='windowTitle')
        self.resize(660, 690); apply_secondary_surface_theme(self)
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        surface = DialogSurface(self, title=str(tr('工程音量 / 响度')), close_callback=self.reject); layout.addWidget(surface)
        content = QWidget()
        body = QVBoxLayout(content); body.setContentsMargins(0, 0, 4, 0); body.setSpacing(14)
        scroll = QScrollArea(); scroll.setWidget(content); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False); content.setAutoFillBackground(False)
        surface.body_layout.addWidget(scroll, 1)

        def step(number, title, hint=''):
            row = QHBoxLayout(); row.setSpacing(12)
            badge = _StepNumber(number); row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            column = QVBoxLayout(); column.setSpacing(8); row.addLayout(column, 1)
            head = QHBoxLayout(); head.setSpacing(8)
            label = QLabel(); label.setObjectName('loudnessStepTitle'); bind_text(label, title)
            font = label.font(); font.setBold(True); font.setPixelSize(15); label.setFont(font)
            head.addWidget(label)
            if hint:
                note = QLabel(); note.setObjectName('settingsDescription'); bind_text(note, hint); head.addWidget(note)
            head.addStretch(1); column.addLayout(head)
            body.addLayout(row)
            return badge, column

        # ① how loud now
        self.step1, column = step(1, '现在整部片多大声')
        line = QHBoxLayout(); line.setSpacing(8)
        self.loud_badge = _Pill(); self.loud_badge.setObjectName('loudnessNow')
        bold = self.loud_badge.font(); bold.setBold(True); bold.setPixelSize(14); self.loud_badge.setFont(bold)
        line.addWidget(self.loud_badge)
        self.peak_label = QLabel(); self.peak_label.setObjectName('settingsDescription'); line.addWidget(self.peak_label)
        self.peak_badge = _Pill(); line.addWidget(self.peak_badge)
        line.addStretch(1)
        self.analyze = QPushButton(); self.analyze.setObjectName('analyzeLoudness'); bind_text(self.analyze, '重新测量')
        button_role(self.analyze, 'ghost', size='compact'); install_themed_icon(self.analyze, 'fa5s.redo-alt', 'secondary')
        self.analyze.clicked.connect(self.start); line.addWidget(self.analyze)
        self.cancel = QPushButton(); bind_text(self.cancel, '取消测量'); button_role(self.cancel, 'ghost', size='compact')
        self.cancel.clicked.connect(self.cancel_analysis); line.addWidget(self.cancel)
        column.addLayout(line)
        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0,1000); self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10); column.addWidget(self.progress_bar)
        self.ruler = _LoudnessRuler(); column.addWidget(self.ruler)
        self.status = QLabel(); self.status.setObjectName('loudnessStatus'); self.status.setWordWrap(True)
        self.status.setProperty('role', 'description'); column.addWidget(self.status)

        # ② where it goes
        self.step2, column = step(2, '要发到哪里？', '会带出建议的响度')
        grid = QGridLayout(); grid.setSpacing(8)
        self.destinations = []
        for index, (key, icon, name, target) in enumerate(DESTINATIONS):
            card = _DestinationCard(key, icon, name, target)
            card.clicked.connect(lambda _checked=False, card=card: self.choose_destination(card))
            grid.addWidget(card, 0, index); self.destinations.append(card)
        column.addLayout(grid)
        custom = QHBoxLayout(); custom.setSpacing(8)
        label = QLabel(); label.setObjectName('settingsDescription'); bind_text(label, '或者自己填目标：'); custom.addWidget(label)
        self.target = QDoubleSpinBox(); self.target.setObjectName('loudnessTarget'); self.target.setRange(-60,-5); self.target.setDecimals(1)
        self.target.setSingleStep(.5); self.target.setSuffix(' LUFS'); self.target.setValue(loudness_target(self.project))
        self.target.setMinimumWidth(140); custom.addWidget(self.target); custom.addStretch(1)
        self.target.valueChanged.connect(self.target_changed)
        column.addLayout(custom)

        # ③ one button
        self.step3, column = step(3, '一键调好')
        go = QHBoxLayout(); go.setSpacing(10)
        self.match = QPushButton(); self.match.setObjectName('matchLoudness')
        button_role(self.match, 'primary'); install_themed_icon(self.match, 'fa5s.magic', 'on_accent')
        self.match.clicked.connect(self.apply_match); go.addWidget(self.match)
        self.outcome = QLabel(); self.outcome.setObjectName('settingsDescription'); self.outcome.setWordWrap(True)
        go.addWidget(self.outcome, 1)
        column.addLayout(go)
        self.reset = QPushButton(); bind_text(self.reset, '恢复原音量'); self.reset.setObjectName('resetProjectGain')
        button_role(self.reset, 'ghost', size='compact'); install_themed_icon(self.reset, 'fa5s.undo-alt', 'secondary')
        self.reset.clicked.connect(lambda: self.set_gain(0.))
        column.addWidget(self.reset, 0, Qt.AlignmentFlag.AlignLeft)

        # Manual gain, folded away.
        self.more = QToolButton(); self.more.setObjectName('loudnessManualToggle'); self.more.setCheckable(True)
        self.more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon); self.more.setArrowType(Qt.ArrowType.RightArrow)
        self.more.setAutoRaise(True); self.more.toggled.connect(self._toggle_more)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        button_role(self.more, 'ghost', size='compact')
        body.addWidget(self.more)
        self.manual = QWidget(); manual = QVBoxLayout(self.manual); manual.setContentsMargins(40, 0, 0, 0); manual.setSpacing(6)
        row = QHBoxLayout(); row.setSpacing(8)
        self.minus = QPushButton('−'); self.plus = QPushButton('+')
        from ..design.presentation import glyph_button
        for button in (self.minus, self.plus):
            button_role(button, 'secondary', size='compact'); glyph_button(button, size=32, glyph=18)
        self.fader = GainFader(self, vertical=False, ticks=True); self.fader.setObjectName('projectGainFader')
        from .gain_control import SignedDbSpin
        self.gain_spin = SignedDbSpin(self); self.gain_spin.setObjectName('projectGainDb')
        self.gain_spin.setRange(scale.MIN_DB, scale.MAX_DB); self.gain_spin.setDecimals(1); self.gain_spin.setSingleStep(1.)
        self.gain_spin.setSuffix(' dB'); self.gain_spin.setFixedWidth(108)
        self.gain_spin.setStyleSheet('QDoubleSpinBox { padding: 4px 8px; } QDoubleSpinBox QLineEdit { padding: 0px; border: none; background: transparent; }')
        row.addWidget(self.minus, 0, Qt.AlignmentFlag.AlignTop); row.addWidget(self.fader, 1); row.addWidget(self.plus, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.gain_spin, 0, Qt.AlignmentFlag.AlignTop)
        manual.addLayout(row)
        note = QLabel(); note.setObjectName('settingsDescription'); note.setWordWrap(True)
        bind_text(note, '只把整部片一起调大调小，不压缩、不改变原来的起伏。双击滑杆回到 0 dB；Shift 精调。')
        manual.addWidget(note)
        self.manual.setVisible(False); body.addWidget(self.manual)
        self.fader.valueChanged.connect(lambda value: self._gain_moved(value, 'fader'))
        self.fader.editFinished.connect(self.commit)
        self.gain_spin.valueChanged.connect(lambda value: self._gain_moved(value, 'spin'))
        self.gain_spin.editingFinished.connect(self.commit)
        self.gain_spin.scrubFinished.connect(self.commit)
        self.minus.clicked.connect(lambda: self.set_gain(self.gain_value() - 1.))
        self.plus.clicked.connect(lambda: self.set_gain(self.gain_value() + 1.))
        self._set_gain_widgets(project_gain_db(self.project))

        # Listening volume, apart.
        card = _MonitorCard(); monitor_row = QHBoxLayout(card); monitor_row.setContentsMargins(14, 10, 14, 10); monitor_row.setSpacing(12)
        phones = QLabel(); from ..design.themed_icons import themed_icon
        phones.setPixmap(themed_icon('fa5s.headphones', 'secondary').pixmap(22, 22)); monitor_row.addWidget(phones)
        words = QVBoxLayout(); words.setSpacing(0)
        title = QLabel(); bind_text(title, '试听音量'); font = title.font(); font.setBold(True); title.setFont(font); words.addWidget(title)
        sub = QLabel(); sub.setObjectName('settingsDescription'); bind_text(sub, '只影响你耳机里听到的，不会改变导出'); words.addWidget(sub)
        monitor_row.addLayout(words)
        self.monitor = QSlider(Qt.Horizontal); self.monitor.setObjectName('monitorVolume'); self.monitor.setRange(0,100)
        self.monitor.setValue(page.volume_slider.value()); monitor_row.addWidget(self.monitor, 1)
        self.monitor_label = QLabel(f'{self.monitor.value()}%'); self.monitor_label.setMinimumWidth(40)
        self.monitor_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); monitor_row.addWidget(self.monitor_label)
        self.monitor.valueChanged.connect(page.volume_slider.setValue)
        self.monitor.valueChanged.connect(lambda value: self.monitor_label.setText(f'{value}%'))
        body.addWidget(card)
        body.addStretch(1)

        foot = QLabel(); foot.setObjectName('settingsDescription'); foot.setWordWrap(True)
        bind_text(foot, '峰值会保持在 −1 dBTP 以内；预计值按当前混音估算，有损编码后可能略有变化，导出后可再测一次。')
        surface.footer_layout.addWidget(foot, 1)
        close = QPushButton(); bind_text(close, '关闭'); button_role(close, 'secondary'); surface.footer_layout.addWidget(close)
        close.clicked.connect(self.accept)

        self.cache = getattr(page, '_loudness_cache', {})
        page._loudness_cache = self.cache
        self.result = self.cache.get(self.identity)
        self.analyzing = False
        self.timer = QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.check_state); self.timer.start()
        self._sync_destinations()
        self.refresh_values()
        if not self.result: QTimer.singleShot(0, self.start)

    # ---- gain ----
    def gain_value(self) -> float:
        return self.fader.value()

    def _set_gain_widgets(self, value: float) -> None:
        self.fader.setValue(value, emit=False)
        self.gain_spin.blockSignals(True); self.gain_spin.setValue(value); self.gain_spin.blockSignals(False)

    def _gain_moved(self, value, source):
        value = scale.snap(value, fine=True)
        if source == 'spin': self.fader.setValue(value, emit=False)
        else:
            self.gain_spin.blockSignals(True); self.gain_spin.setValue(value); self.gain_spin.blockSignals(False)
        self.flash = None
        self.preview(value)

    def _toggle_more(self, open_):
        self.manual.setVisible(open_)
        self.more.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)

    def current(self): return not self.closed and self.page.project is self.project

    def preview(self, value):
        if self.current():
            self.page._project_gain_preview = value
            self.page._refresh_audio_mix_only(); self.refresh_values()

    def commit(self):
        if not self.current(): return
        value = self.gain_value(); self.page._project_gain_preview = None
        if abs(value-project_gain_db(self.project)) > .0001:
            self.page.undo_stack.push(project_gain_command(self.project, value))
        self.page._refresh_audio_mix_only(); self.refresh_values()

    def set_gain(self, value):
        self._set_gain_widgets(scale.snap(value, fine=True)); self.flash = None; self.commit()

    # ---- target ----
    def _sync_destinations(self):
        chosen = self.project.studio_state.get(DESTINATION_KEY, 'short')
        target = self.target.value()
        for card in self.destinations:
            card.setChecked(card.key == chosen and abs(card.target - target) < .05)

    def choose_destination(self, card):
        self.project.studio_state[DESTINATION_KEY] = card.key
        self.target.setValue(card.target)   # target_changed stores it and refreshes
        self._sync_destinations()

    def target_changed(self, value):
        self.project.studio_state[TARGET_KEY] = round(float(value), 1)
        self.flash = None
        self._sync_destinations(); self.refresh_values()

    # ---- state ----
    def check_state(self):
        if not self.current(): self.reject(); return
        identity = baseline_identity(self.project)
        if identity != self.identity:
            self.identity = identity; self.result = self.cache.get(identity)
            self.cancel_analysis()
            self.status.setText(str(tr('混音已变化，分析结果已过期，请重新测量')))
            self.refresh_values()
        elif (getattr(self.page, '_project_gain_preview', None) is None and not self.gain_spin.hasFocus()
              and self.fader._drag is None):
            self._set_gain_widgets(project_gain_db(self.project))
            self.refresh_values()

    def refresh_values(self, *_):
        from ..design.ui_theme import blend_hex  # noqa: F401 - keeps theme module warm for painting
        target = self.target.value(); gain = self.gain_value()
        bind_text(self.match, '调到 {value} LUFS', value=_lufs(target))
        bind_text(self.more, '自己微调总增益 · 现在 {value} dB', value=scale.signed(gain))
        self.reset.setVisible(abs(gain) > .04)
        analyzing = self.worker is not None
        self.progress_bar.setVisible(analyzing); self.cancel.setVisible(analyzing); self.analyze.setVisible(not analyzing)
        self.step1.set_done(bool(self.result) and not analyzing)
        if not self.result:
            self.loud_badge.set_role('accent')
            bind_text(self.loud_badge, '正在测量…' if analyzing else '还没测量')
            self.peak_label.setText(''); self.peak_badge.hide()
            self.ruler.set_values(target, None, None)
            self.match.setEnabled(False); self.step3.set_done(False)
            self.outcome.setText('')
            return
        loud, peak = self.result['integrated'], self.result['true_peak']
        now, now_peak = loud + gain, peak + gain
        role, words = loudness_status(now, target)
        self.loud_badge.set_role(role)
        self.loud_badge.setText(f'{_lufs(now)} LUFS · {tr(words)}')
        self.peak_label.setText(str(tr('峰值 {value} dBTP', value=_lufs(now_peak))))
        self.peak_badge.show()
        if now_peak > -1.001:
            self.peak_badge.set_role('danger'); bind_text(self.peak_badge, '快爆音了')
        else:
            self.peak_badge.set_role('success'); bind_text(self.peak_badge, '不会爆音')
        self.ruler.set_values(target, loud, now)
        near = abs(now - target) < .15
        self.step3.set_done(near)
        suggestion = match_gain(loud, peak, target)
        self.match.setEnabled(suggestion['available'] and not analyzing)
        if self.flash:
            self.outcome.setText(self.flash)
        elif not suggestion['available']:
            self.outcome.setText(str(tr(suggestion['reason'])))
        elif near:
            self.outcome.setText(str(tr('已经对准目标了')))
        else:
            value = math.floor((suggestion['gain_db'] + 1e-9) * 10) / 10
            self.outcome.setText(str(tr('会把整部片一起{direction} {value} dB，原来的起伏不变',
                                        direction=tr('调小') if value < 0 else tr('调大'), value=f'{abs(value):.1f}')))

    def apply_match(self):
        self.check_state()
        if not self.current() or not self.result or self.worker: return
        result = match_gain(self.result['integrated'], self.result['true_peak'], self.target.value())
        if not result['available']: self.status.setText(result['reason']); return
        # Round downward: tenths must never exceed the true-peak bound.
        self.set_gain(math.floor((result['gain_db']+1e-9)*10)/10)
        now = self.result['integrated'] + self.gain_value()
        if result['peak_limited']:
            self.flash = str(tr('峰值先到顶了，只能调到 {value} LUFS（再大会爆音）', value=_lufs(now)))
        elif result['range_limited']:
            self.flash = str(tr('增益范围受限，未完全达到目标；请查看预计值'))
        else:
            self.flash = str(tr('好了！总增益 {gain} dB，预计 {value} LUFS', gain=scale.signed(self.gain_value()), value=_lufs(now)))
        self.status.setText('')
        self.refresh_values()

    def start(self):
        if not self.current() or self.worker: return
        self.check_state()
        identity = self.identity
        worker = LoudnessWorker(self.project); self.worker = worker
        from .studio_analysis_request import retain_worker
        retain_worker(self.page,worker)
        self.progress_bar.setValue(0); self.status.setText(str(tr('正在听一遍完整混音，声音不会改变…')))
        self.refresh_values()
        worker.progress.connect(lambda value: self.progress_bar.setValue(round(value*1000)) if self.current() else None)
        def measured(result):
            if self.current() and not worker.isInterruptionRequested() and baseline_identity(self.project) == identity:
                self.result = result; self.cache[identity] = result
                while len(self.cache)>8: self.cache.pop(next(iter(self.cache)))
                self.status.setText(str(tr('测量完成 · {duration} 秒 · {rate} Hz / {channels} 声道 · 用时 {elapsed} 秒',
                    duration=f'{result["duration"]:.0f}', rate=result['sample_rate'], channels=result['channels'],
                    elapsed=f'{result["elapsed"]:.1f}')))
        def failed(message):
            if self.current(): self.status.setText(str(tr(message)))
        def finished():
            if self.current():
                self.worker = None; self.refresh_values()
        worker.measured.connect(measured); worker.failed.connect(failed); worker.finished.connect(finished); worker.start()

    def cancel_analysis(self):
        if self.worker: self.worker.requestInterruption()

    def done(self, result):
        if not self.closed:
            self.closed = True; self.timer.stop(); self.cancel_analysis()
            self.page._project_gain_preview = None
            if self.page.project is self.project: self.page._refresh_audio_mix_only()
            self.page._project_loudness_panel = None
            refresh = getattr(self.page, '_refresh_loudness_button', None)
            if callable(refresh): refresh()
        super().done(result)


def retire_gain_controls(page):
    """Project/page replacement cancels gestures before the new bus exists."""
    for name in ('_track_gain_dialog','_project_loudness_panel'):
        dialog=getattr(page,name,None)
        if dialog is not None: dialog.reject()
    timeline=getattr(page,'timeline',None)
    if timeline is not None:
        from .timeline_track_gain import finish
        finish(timeline,cancel=True)
    page._gain_preview_values={};page._project_gain_preview=None
