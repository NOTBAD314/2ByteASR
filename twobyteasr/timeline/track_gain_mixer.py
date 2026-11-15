"""轨道音量 as a little mixer: one round fader per audio track (2026-11-14).

User (2026-11-14): redesign the track volume window, 「要够好用和顺手圆润」;
of three drafts they picked C, the mini mixer. Each strip shows the track's
colour and name, a fader with 0 dB near the middle, the live level of that
track while the video plays, the value (type it, or drag it sideways like
before) and a plain description. The strip the window was opened for is
「当前」 and owns the ``trackGainDb`` spin box the audits look for.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..design.main_ui_dialogs import DialogSurface, SpringDialog
from ..i18n import bind_text, tr
from ..studio import gain_scale as scale
from ..studio.gain_fader import GainFader, GainScaleLabels, LevelMeter, _theme
from .studio_track_gain import TRACK_HUES, audio_track_locked, gains_command, track_gain_db

STRIP_WIDTH = 112


class _Strip(QWidget):
    """A rounded card: name, fader + meter, value, words. Painted, so it follows the theme."""

    def __init__(self, mixer, track, hue: str, locked: bool):
        super().__init__()
        self.mixer, self.track_id, self.hue, self.locked = mixer, track.id, hue, locked
        self.current = False
        self.setFixedWidth(STRIP_WIDTH)
        self.setObjectName('trackGainStrip')
        self.setProperty('trackId', track.id)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 10)
        layout.setSpacing(6)
        name = track.name if track.name and track.name != track.id else str(tr('音轨'))
        self.title = QLabel(f'{track.id} {name}')
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setObjectName('trackGainStripTitle')
        self.title.setContentsMargins(14, 0, 0, 0)  # room for the colour dot painted at its left
        layout.addWidget(self.title)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addStretch(1)
        self.fader = GainFader(self, vertical=True)
        self.fader.setObjectName('trackGainFader')
        self.fader.setMinimumHeight(220)
        self.meter = LevelMeter(self)
        row.addWidget(self.fader)
        row.addWidget(self.meter)
        row.addStretch(1)
        layout.addLayout(row, 1)
        from ..studio.gain_control import SignedDbSpin
        self.spin = SignedDbSpin(self)
        self.spin.setRange(scale.MIN_DB, scale.MAX_DB)
        self.spin.setDecimals(1)
        self.spin.setSingleStep(1.)   # dragging the number: 4 px per dB, as before
        self.spin.setSuffix(' dB')
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setButtonSymbols(SignedDbSpin.ButtonSymbols.NoButtons)
        self.spin.setFixedWidth(STRIP_WIDTH - 16)
        self.spin.setObjectName('trackGainDb_' + track.id)
        bind_text(self.spin, '点一下输入，或左右拖动数值', property='toolTip')
        self.spin.setStyleSheet('QDoubleSpinBox { padding: 4px 6px; border-radius: 13px; }'
                                'QDoubleSpinBox QLineEdit { padding: 0px; border: none; background: transparent; }')
        layout.addWidget(self.spin, 0, Qt.AlignmentFlag.AlignHCenter)
        self.words = QLabel()
        self.words.setObjectName('settingsDescription')
        self.words.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.words.setWordWrap(True)
        self.words.setMinimumHeight(32)
        layout.addWidget(self.words)
        if locked:
            for widget in (self.fader, self.spin):
                widget.setEnabled(False)
            bind_text(self.words, '已锁定')

    def set_current(self, current: bool) -> None:
        self.current = bool(current)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        self.mixer.choose(self.track_id)
        super().mousePressEvent(event)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(2, 8, -2, -2)
        if self.current:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent_soft))
            painter.drawRoundedRect(card.adjusted(-2, -2, 2, 2), 20, 20)
        painter.setPen(QPen(QColor(theme.accent if self.current else theme.border), 1.6))
        painter.setBrush(QColor(theme.surface_elevated))
        painter.drawRoundedRect(card, 18, 18)
        title = self.title.geometry()
        dot = QRectF(title.left() + 2, title.center().y() - 5, 10, 10)
        width = self.title.fontMetrics().horizontalAdvance(self.title.text())
        dot.moveLeft(max(title.left() + 2, title.center().x() - (width + 14) / 2))
        painter.setPen(Qt.PenStyle.NoPen)
        hue = QColor(self.hue)
        if self.locked:
            hue.setAlpha(110)
        painter.setBrush(hue)
        painter.drawEllipse(dot)
        if self.current:
            font = QFont(self.font())
            font.setPixelSize(11)
            painter.setFont(font)
            text = str(tr('当前'))
            tag_w = painter.fontMetrics().horizontalAdvance(text) + 16
            tag = QRectF(card.center().x() - tag_w / 2, 0, tag_w, 17)
            painter.setBrush(QColor(theme.accent))
            painter.drawRoundedRect(tag, 8.5, 8.5)
            painter.setPen(QColor(theme.text_on_accent))
            painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class TrackGainMixer(SpringDialog):
    def __init__(self, page, project, selected: str):
        super().__init__(page, backdrop=False)
        from ..design.studio_theme import apply_secondary_surface_theme
        self.page, self.project, self.selected = page, project, selected
        bind_text(self, '轨道音量', property='windowTitle')
        self.setObjectName('trackGainDialog')
        apply_secondary_surface_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        surface = DialogSurface(self, title=str(tr('轨道音量')), close_callback=self.reject)
        layout.addWidget(surface)
        body = surface.body_layout
        top = QHBoxLayout()
        hint = QLabel()
        hint.setObjectName('settingsDescription')
        hint.setWordWrap(True)
        bind_text(hint, '上下拖动推子或滚轮调整 · Shift 精调 · 双击推子回到 0 dB · 下面的数字可以直接改')
        top.addWidget(hint, 1)
        self.listen = QPushButton()
        self.listen.setObjectName('trackGainListen')
        from ..design.presentation import button_role
        from ..design.themed_icons import install_themed_icon
        button_role(self.listen, 'secondary', size='compact')
        install_themed_icon(self.listen, 'fa5s.headphones', 'accent')
        self.listen.clicked.connect(self._toggle_listen)
        top.addWidget(self.listen, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(top)

        self.original = {track.id: track_gain_db(project, track.id) for track in project.audio_tracks}
        self.pending = dict(self.original)
        self.strips: dict[str, _Strip] = {}
        mixer = QWidget()
        row = QHBoxLayout(mixer)
        row.setContentsMargins(4, 6, 4, 4)
        row.setSpacing(10)
        strips = []
        for index, track in enumerate(project.audio_tracks):
            strip = _Strip(self, track, TRACK_HUES[index % len(TRACK_HUES)], audio_track_locked(project, track.id))
            strips.append(strip)
            self.strips[track.id] = strip
            strip.fader.setValue(self.pending[track.id], emit=False)
            strip.spin.blockSignals(True)
            strip.spin.setValue(self.pending[track.id])
            strip.spin.blockSignals(False)
            if not strip.locked:
                key = track.id
                strip.fader.valueChanged.connect(lambda value, key=key: self._set(key, value, source='fader'))
                strip.fader.editFinished.connect(lambda key=key: self.choose(key))
                strip.spin.valueChanged.connect(lambda value, key=key: self._set(key, value, source='spin'))
                strip.spin.editingFinished.connect(lambda key=key: self.choose(key))
        first = next((s for s in strips if not s.locked), strips[0])
        labels = GainScaleLabels(first.fader)
        row.addStretch(1)   # few tracks: the strips sit in the middle
        labels_box = QVBoxLayout()
        labels_box.setContentsMargins(0, 0, 0, 0)
        labels_box.addWidget(labels)
        row.addLayout(labels_box)
        for strip in strips:
            row.addWidget(strip)
        row.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName('trackGainScroll')
        scroll.setWidget(mixer)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.viewport().setAutoFillBackground(False)
        mixer.setAutoFillBackground(False)
        scroll.setMinimumHeight(360)
        body.addWidget(scroll, 1)
        self._labels = labels

        self.changed_label = QLabel()
        self.changed_label.setObjectName('settingsDescription')
        surface.footer_layout.addWidget(self.changed_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                        | QDialogButtonBox.StandardButton.Reset)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        button_role(self.apply_button, 'primary')
        bind_text(self.buttons.button(QDialogButtonBox.StandardButton.Cancel), '取消')
        reset = self.buttons.button(QDialogButtonBox.StandardButton.Reset)
        bind_text(reset, '全部回到 0 dB')
        reset.clicked.connect(self._reset_all)
        self.buttons.accepted.connect(self.commit)
        self.buttons.rejected.connect(self.reject)
        surface.footer_layout.addWidget(self.buttons)
        self.resize(min(980, 70 + len(strips) * (STRIP_WIDTH + 10) + 40), 560)
        self.setMinimumWidth(560)

        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.choose(selected)
        self._refresh()

    # ---- state ----
    def choose(self, key: str) -> None:
        strip = self.strips.get(key)
        if strip is None or strip.locked:
            return
        self.selected = key
        for other_key, other in self.strips.items():
            other.set_current(other_key == key)
            other.spin.setObjectName('trackGainDb' if other_key == key else 'trackGainDb_' + other_key)

    def focus_current(self) -> None:
        strip = self.strips.get(self.selected)
        if strip is not None:
            strip.spin.setFocus()
            strip.spin.selectAll()

    def _set(self, key: str, value: float, *, source: str) -> None:
        value = scale.snap(value, fine=True)
        strip = self.strips[key]
        self.pending[key] = value
        if source != 'fader':
            strip.fader.setValue(value, emit=False)
        if source != 'spin' and abs(strip.spin.value() - value) > 1e-6:
            strip.spin.blockSignals(True)
            strip.spin.setValue(value)
            strip.spin.blockSignals(False)
        if self.selected != key:
            self.choose(key)
        self._preview()
        self._refresh()

    def changed(self) -> dict[str, float]:
        return {key: value for key, value in self.pending.items() if abs(value - self.original[key]) > 1e-6}

    def _preview(self) -> None:
        if self.page.project is self.project:
            self.page._gain_preview_values = dict(self.changed())
            self.page._refresh_audio_mix_only()

    def _refresh(self) -> None:
        for key, strip in self.strips.items():
            if strip.locked:
                continue
            bind_text(strip.words, scale.words(self.pending[key]))
            edited = abs(self.pending[key] - self.original[key]) > 1e-6
            strip.spin.setProperty('edited', edited)
            font = strip.spin.font()
            font.setBold(edited)
            strip.spin.setFont(font)
        count = len(self.changed())
        if count:
            bind_text(self.changed_label, '改了 {count} 条轨道', count=count)
        else:
            self.changed_label.setText('')
        if count > 1:
            bind_text(self.apply_button, '应用 {count} 条', count=count)
        else:
            bind_text(self.apply_button, '应用')

    def _reset_all(self) -> None:
        for key, strip in self.strips.items():
            if not strip.locked:
                strip.fader.setValue(0.)

    # ---- live level ----
    def _toggle_listen(self) -> None:
        toggle = getattr(self.page, '_toggle_playback', None)
        if callable(toggle):
            toggle()
        self._tick()

    def _playing(self) -> bool:
        video = getattr(self.page, 'video', None)
        return video is not None and not bool(getattr(video, '_paused', True))

    def _tick(self) -> None:
        playing = self._playing()
        bind_text(self.listen, '试听中' if playing else '试听')
        self.listen.setProperty('listening', playing)
        levels = {}
        engine = getattr(self.page, 'audio_engine', None)
        if playing and engine is not None:
            try:
                snapshot = engine.telemetry_snapshot()
            except Exception:  # noqa: BLE001 - a meter must never break the dialog
                snapshot = {}
            fresh = time.monotonic() - float(snapshot.get('received_monotonic') or 0.) < .8
            if fresh:
                for item in snapshot.get('decoder_inputs') or ():
                    peak = float(item.get('peak') or 0.)
                    if peak > 0:
                        levels[str(item.get('track_id') or '')] = 20 * math.log10(peak)
        for key, strip in self.strips.items():
            level = levels.get(key)
            if level is not None:
                level += self.pending.get(key, 0.)
            strip.meter.set_level(level)

    # ---- outcome ----
    def commit(self) -> None:
        values = self.changed()
        self.page._gain_preview_values = {}
        if self.page.project is self.project and values:
            try:
                self.page.undo_stack.push(gains_command(self.project, values))
            except ValueError as exc:
                self.page.save_state.setText(str(exc))
                self.reject()
                return
        self.accept()

    def done(self, result):
        # Cancel restores the sound immediately, before the exit fade.
        self.timer.stop()
        for strip in self.strips.values():
            strip.spin._cancel_scrub()
        self.page._gain_preview_values = {}
        if self.page.project is self.project:
            self.page._refresh_audio_mix_only()
        super().done(result)

    def showEvent(self, event):  # noqa: N802 - Qt override
        super().showEvent(event)
        QTimer.singleShot(0, self._labels.update)

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._labels.update()
