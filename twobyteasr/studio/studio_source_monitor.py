"""Independent source monitor; never attaches source media to the sequence player."""
from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QMimeData, QPointF, QRectF, QSize, QEvent
from PySide6.QtGui import QColor, QDrag, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QBoxLayout, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QScrollArea, QScrollBar, QSlider, QStackedWidget, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
    QSizePolicy)

from ..design.theme_manager import theme_key
from ..design.themed_icons import install_themed_icon
from ..design.ui_theme import theme_definition
from ..playback.studio_mpv import create_preview_controller
from ..timeline.source_selection import (SOURCE_MIME, SourceSelection, SourceInsertCommand,
    source_boundary, source_capabilities, source_state)
from ..timeline.studio_media_pool import asset_by_id
from .source_media_cache import SourceWaveCache, SourceMediaResolver
from .studio_helpers import format_timeline_timecode, parse_timeline_timecode


_FOCUS_API = None


def native_source_focus(surface):
    """None for Qt controls, otherwise whether the focused mpv owns this host."""
    if sys.platform != 'win32':return None
    import ctypes
    from ctypes import wintypes as W
    global _FOCUS_API
    if _FOCUS_API is None:
        class FocusInfo(ctypes.Structure):
            _fields_=[('cbSize',W.DWORD),('flags',W.DWORD),('hwndActive',W.HWND),
                ('hwndFocus',W.HWND),('hwndCapture',W.HWND),('hwndMenuOwner',W.HWND),
                ('hwndMoveSize',W.HWND),('hwndCaret',W.HWND),('rcCaret',W.RECT)]
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.GetGUIThreadInfo.argtypes=[W.DWORD,ctypes.POINTER(FocusInfo)]
        user.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,ctypes.c_int]
        user.IsChild.argtypes=[W.HWND,W.HWND]
        _FOCUS_API=(user,FocusInfo)
    user,FocusInfo=_FOCUS_API
    info=FocusInfo();info.cbSize=ctypes.sizeof(info)
    if not user.GetGUIThreadInfo(0,ctypes.byref(info)) or not info.hwndFocus:return None
    name=ctypes.create_unicode_buffer(40)
    user.GetClassNameW(info.hwndFocus,name,len(name))
    if name.value.lower()!='mpv':return None
    return bool(user.IsChild(int(surface.winId()),info.hwndFocus))


def source_mime(project, selection):
    mime = QMimeData()
    mime.setData(SOURCE_MIME, json.dumps(dict(project_id=project.project_id, **asdict(selection))).encode())
    return mime


def selection_from_mime(project, mime):
    payload = json.loads(bytes(mime.data(SOURCE_MIME)))
    if payload.pop('project_id', '') != project.project_id:
        raise ValueError('素材来自其他工程，请先添加到当前媒体池')
    selection = SourceSelection(**payload)
    selection.validate(project)
    return selection


class ElidedLabel(QLabel):
    """One-line label that middle-elides long file names, keeping the extension."""
    def __init__(self, text=''):
        super().__init__()
        self.full_text = ''
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideMiddle, max(0, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (event.Type.FontChange, event.Type.StyleChange):
            self._elide()


class StatusLabel(QLabel):
    """Transient source messages; collapses when there is nothing to say."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('sourceStatus')
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setVisible(False)

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))


class SourceDragButton(QPushButton):
    def __init__(self, label, monitor, mode):
        super().__init__(label)
        self.monitor, self.mode = monitor, mode
        self.setCheckable(True)
        self.setObjectName('sourceModeButton')
        self.setToolTip(label.strip() + '：单击选择；按住拖到兼容轨道加入当前源选段')
        self.clicked.connect(lambda: monitor.set_mode(mode))
        self.origin = None

    def mousePressEvent(self, event):
        self.origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.origin is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint()-self.origin).manhattanLength() >= QApplication.startDragDistance()):
            self.setDown(False)
            self.monitor.set_mode(self.mode)
            self.monitor.start_drag(self, self.mode)
            self.origin = None
            return
        super().mouseMoveEvent(event)


class SourcePointButton(QPushButton):
    """Whole-row set-point button; double-click its timecode to edit it."""
    def __init__(self, field, callback, tip):
        super().__init__()
        self.editor = field
        self.setObjectName('sourcePoint')
        self.setAutoDefault(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip + '；双击时码可手动输入')
        self.setAccessibleName(tip)
        self.clicked.connect(callback)
        self._lock_editor()
        field.installEventFilter(self)
        field.editingFinished.connect(self._lock_editor)

    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize() if self.layout() else super().minimumSizeHint()

    def _lock_editor(self):
        self.editor.setReadOnly(True)
        self.editor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.editor.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.editor.geometry().contains(event.position().toPoint()):
            self.setDown(False)
            self._edit_before = self.editor.text()
            self.editor.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.editor.setReadOnly(False)
            self.editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.editor.setFocus()
            self.editor.selectAll()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.editor and event.type() == QEvent.Type.KeyPress and not self.editor.isReadOnly():
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                # Focus-out commits once, with focus already off the editor so
                # validation can refresh its text. Do not also emit Return's
                # editingFinished signal through the default QLineEdit path.
                self.setFocus()
                return True
            if event.key() == Qt.Key_Escape:
                blocked = self.editor.blockSignals(True)
                self.editor.setText(self._edit_before)
                self.setFocus()
                self.editor.blockSignals(blocked)
                self._lock_editor()
                return True
        return super().eventFilter(watched, event)


class SourceSelectionArea(QFrame):
    """Grab the selected range from the title/duration or card background."""
    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor
        self.origin = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('按住拖到时间线的兼容轨道和时间位置，加入当前入出点之间的选段')
        self.setAccessibleName('拖动当前源选段到时间线')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.origin is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint()-self.origin).manhattanLength() >= QApplication.startDragDistance()):
            self.origin = None
            self.monitor.start_drag(self, self.monitor.mode)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.origin = None
        super().mouseReleaseEvent(event)


class SourceRuler(QWidget):
    """Seekable waveform/ruler, including draggable half-open selection edges."""
    def __init__(self, monitor, *, large=False):
        super().__init__(monitor)
        self.monitor = monitor
        self.large = large
        self.setMinimumHeight(130 if large else 64)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.drag_edge = ''

    def x_for(self, ms):
        m = self.monitor
        return 12 + (ms-m.view_start) / max(1, m.view_span) * max(1, self.width()-24)

    def time_for(self, x):
        m = self.monitor
        return source_boundary(m.asset, m.view_start + (x-12) / max(1, self.width()-24) * m.view_span) if m.asset else 0

    def paintEvent(self, event):
        m = self.monitor
        t = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # The compact ruler sits on a card: labels float above a rounded track.
        body = QRectF(self.rect()) if self.large else QRectF(0, 20, self.width(), self.height()-20)
        clip = QPainterPath(); clip.addRoundedRect(body, 0 if self.large else 10, 0 if self.large else 10)
        painter.fillPath(clip, QColor(t.input_surface))
        if not m.asset:
            painter.setPen(QColor(t.text_muted))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '双击媒体池素材，在这里预览原文件')
            return
        start, end = m.range_ms()
        a, b = self.x_for(start), self.x_for(end)
        highlight = QColor(t.accent); highlight.setAlpha(45)
        painter.save(); painter.setClipPath(clip)
        painter.fillRect(QRectF(max(0, a), body.top(), max(0, min(self.width(), b)-max(0, a)), body.height()), highlight)
        painter.restore()
        painter.setPen(QPen(QColor(t.accent), 1))
        peaks = m.peaks
        if self.large and peaks is not None and len(peaks):
            center, amp = 24 + (self.height()-30)/2, (self.height()-34)/2
            for i, (lo, hi) in enumerate(peaks):
                x = 12 + i / max(1, len(peaks)-1) * (self.width()-24)
                painter.drawLine(QPointF(x, center-float(hi)*amp), QPointF(x, center-float(lo)*amp))
        elif self.large:
            painter.setPen(QColor(t.text))
            painter.drawText(self.rect().adjusted(15, 32, -15, -15), Qt.AlignmentFlag.AlignCenter,
                             m.wave_status + '\n可先试听、定位及设置入出点')
        ticks = 4 if self.width() >= 480 else 2
        font = painter.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(max(7.0, font.pointSizeF()*.9)); painter.setFont(font)
        for i in range(ticks+1):
            x = 12 + i*(self.width()-24)/ticks
            painter.setPen(QColor(t.border_strong))
            painter.drawLine(QPointF(x, body.top()+2 if not self.large else 20), QPointF(x, body.top()+7 if not self.large else 26))
            painter.setPen(QColor(t.text_muted))
            label = format_timeline_timecode(m.view_start+round(i*m.view_span/ticks))[3:]
            align = Qt.AlignmentFlag.AlignLeft if i == 0 else Qt.AlignmentFlag.AlignRight if i == ticks else Qt.AlignmentFlag.AlignHCenter
            painter.drawText(QRectF(max(0, min(self.width()-83, x-41)) if 0 < i < ticks else (0 if i == 0 else self.width()-83),
                                    0, 82, 18), align | Qt.AlignmentFlag.AlignVCenter, label)
        top = body.top() if not self.large else 22
        for x, label in ((a, 'I'), (b, 'O')):
            if -1 <= x <= self.width()+1:
                x = min(max(x, 1), self.width()-1)
                painter.setPen(QPen(QColor(t.accent), 2))
                painter.drawLine(QPointF(x, top), QPointF(x, self.height()))
                pill = QRectF(min(max(0, x-9), self.width()-18), self.height()-19, 18, 16)
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(t.accent))
                painter.drawRoundedRect(pill, 8, 8)
                painter.setPen(QColor(t.text_on_accent))
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)
        x = self.x_for(m.position_ms)
        if -6 <= x <= self.width()+6:
            painter.setPen(QPen(QColor(t.text), 2))
            painter.drawLine(QPointF(x, top), QPointF(x, self.height()))
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(t.text))
            painter.drawEllipse(QPointF(x, top+4), 5, 5)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.monitor.asset:
            return
        self.setFocus()
        m = self.monitor
        a, b = (self.x_for(v) for v in m.range_ms())
        self.drag_edge = 'in_ms' if abs(event.position().x()-a) < 9 else 'out_ms' if abs(event.position().x()-b) < 9 else 'seek'
        self._move(event.position().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.drag_edge:
            self._move(event.position().x())

    def mouseReleaseEvent(self, event):
        if self.drag_edge:
            self._move(event.position().x())
        self.drag_edge = ''

    def _move(self, x):
        value = self.time_for(x)
        if self.drag_edge == 'seek':
            self.monitor.seek(value)
        else:
            self.monitor.set_boundary(self.drag_edge, value)

    def wheelEvent(self, event):
        # Zoom has no visible control: Ctrl+wheel zooms, a plain wheel pans
        # only while zoomed so the panel itself still scrolls at full length.
        step = 1 if event.angleDelta().y() > 0 else -1
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            slider = self.monitor.zoom
            slider.setValue(slider.value() + 2*step)
            event.accept()
        elif self.monitor.zoom.value() > 1 and event.angleDelta().y():
            bar = self.monitor.scroll
            bar.setValue(bar.value() - step*max(1, bar.pageStep()//8))
            event.accept()
        else:
            super().wheelEvent(event)


class StudioSourceMonitor(QWidget):
    controller_ready = Signal(int, object, str)
    surface_retired = Signal(int)

    def __init__(self, page, parent=None, *, deferred_build=False):
        super().__init__(parent)
        self.page = page
        self.setObjectName('studioSourceMonitor')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.asset_id = ''
        self.source_path_at_open = ''
        self.project = None
        self.position_ms = 0
        self.mode = 'av'
        self.controller = None
        self.starting = False
        self._starting_epoch = None
        self._retired_surfaces = {}
        self.epoch = 0
        self.closed = False
        self.source_token = 0
        self.load_generation = 0
        self.resolved_source = self.resolved_path = self.resolve_requested = self.playback_source = ''
        self.paused = True
        self.loading = False
        self.loaded_at = 0.0
        self.play_range_end = None
        self.view_start, self.view_span = 0, 1
        self.peaks, self.wave_key = None, ''
        self.wave_status = '正在生成波形…'
        self.wave_cache = SourceWaveCache(self)
        self.wave_cache.ready.connect(self._wave_ready)
        self.resolver = SourceMediaResolver(self)
        self.resolver.ready.connect(self._resolved)
        self.controller_ready.connect(self._controller_ready)
        self.surface_retired.connect(self._surface_retired)
        self.narrow = False
        self._control_steps = self._build_control_steps()
        if not deferred_build:
            for _step in self.build_steps():
                pass

    def build_steps(self):
        if self._control_steps is not None:
            yield from self._control_steps
            self._control_steps = None

    def _build_control_steps(self):
        from ..design.gui_slices import GuiSlice
        budget = GuiSlice()
        # 2026-11-03 capsule layout: one-line title, fixed picture, then two
        # rounded cards (preview + in/out, selection + insertion).
        shell = QVBoxLayout(self); shell.setContentsMargins(10, 8, 10, 6); shell.setSpacing(8)
        yield from budget.checkpoint()
        header = QHBoxLayout(); header.setSpacing(8)
        self.title = ElidedLabel('双击媒体池素材，预览原文件'); self.title.setObjectName('sourceTitle')
        yield from budget.checkpoint()
        header.addWidget(self.title, 1)
        self.origin_chip = QLabel('原始内容'); self.origin_chip.setObjectName('sourceChip')
        yield from budget.checkpoint()
        self.origin_chip.setToolTip('显示原始文件内容，独立于序列；出点为下一帧边界')
        self.origin_chip.setVisible(False); header.addWidget(self.origin_chip)
        header.addWidget(self.icon_button('fa5s.times', '关闭源', self.close_source, 'sourceClose', 'muted', 13))
        yield from budget.checkpoint()
        shell.addLayout(header)
        self.visual = QStackedWidget()
        self.surface = self._new_surface()
        self.visual.addWidget(self.surface)
        yield from budget.checkpoint()
        self.waveform = SourceRuler(self, large=True)
        self.visual.addWidget(self.waveform)
        self.visual.setFixedHeight(150)
        self.waveform.setMinimumHeight(90)
        yield from budget.checkpoint()
        # Keep source picture/waveform visible while its narrow-column
        # controls scroll. The sequence canvas remains in the center.
        shell.addWidget(self.visual)
        self.content_scroll = QScrollArea(self)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        yield from budget.checkpoint()
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_scroll.setMinimumHeight(140)
        self.content = QWidget(); self.content.setObjectName('sourceContent')
        yield from budget.checkpoint()
        self.content_scroll.setWidget(self.content); shell.addWidget(self.content_scroll, 1)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 4); outer.setSpacing(8)
        yield from budget.checkpoint()
        # Zoom keeps its state objects (Ctrl+wheel, acceptance) without a visible row.
        self.zoom = QSlider(Qt.Orientation.Horizontal, self); self.zoom.hide()
        self.zoom.setRange(1, 100); self.zoom.setValue(1)
        yield from budget.checkpoint()
        self.zoom.valueChanged.connect(self._zoom_changed)
        self.scroll = QScrollBar(Qt.Orientation.Horizontal, self); self.scroll.hide()
        yield from budget.checkpoint()
        self.scroll.valueChanged.connect(self._scroll_changed)

        view_card, view = self.card()
        self.ruler = SourceRuler(self)
        self.ruler.setToolTip('点击定位，拖动 I/O 调整选段；Ctrl+滚轮缩放')
        yield from budget.checkpoint()
        view.addWidget(self.ruler)
        self.point_layouts = []
        points = self.points_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight); points.setSpacing(8)
        yield from budget.checkpoint()
        self.in_edit = self.time_field(lambda: self._time_edited('in_ms'))
        self.out_edit = self.time_field(lambda: self._time_edited('out_ms'))
        self.point_buttons = {}
        for label, key, field, which in (('入点', 'I', self.in_edit, 'in_ms'), ('出点', 'O', self.out_edit, 'out_ms')):
            point = self.point(f'{label}（{key}）', field, lambda _=False, w=which: self.set_boundary(w, self.position_ms),
                               f'把{label}设为当前位置 ({key})')
            self.point_buttons[which] = point
            points.addWidget(point, 1)
        yield from budget.checkpoint()
        view.addLayout(points)
        transport = self.transport_layout = QHBoxLayout(); transport.setSpacing(8)
        clock = QVBoxLayout(); clock.setSpacing(0)
        yield from budget.checkpoint()
        self.time_edit = self.time_field(lambda: self._time_edited('position'))
        self.time_edit.setProperty('role', 'position'); self.time_edit.setMinimumWidth(128)
        yield from budget.checkpoint()
        self.time_edit.setToolTip('源素材播放位置；不改变工程播放头')
        self.total_label = QLabel('/ 00:00:00.000'); self.total_label.setObjectName('sourceTotal')
        clock.addWidget(self.time_edit); clock.addWidget(self.total_label)
        yield from budget.checkpoint()
        transport.addLayout(clock, 1)
        self.play_button = self.icon_button('fa5s.play', '播放 (Space)', self.toggle_play, 'sourcePlay', 'on_accent', 17)
        self.transport_buttons = (self.icon_button('fa5s.step-backward', '上一帧 (←)', lambda: self.step(-1)),
                                  self.play_button, self.icon_button('fa5s.step-forward', '下一帧 (→)', lambda: self.step(1)))
        yield from budget.checkpoint()
        for button in self.transport_buttons:
            transport.addWidget(button)
        volume = QHBoxLayout(); volume.setSpacing(4); volume.addStretch(1)
        yield from budget.checkpoint()
        self.mute_button = self.icon_button('fa5s.volume-up', '试听音量；单击静音', self._toggle_mute, 'sourceGlyph', 'muted', 14)
        volume.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Orientation.Horizontal); self.volume.setObjectName('sourceVolume')
        yield from budget.checkpoint()
        self.volume.setRange(0, 100); self.volume.setValue(70); self.volume.setFixedWidth(64)
        self.volume.setToolTip('试听音量')
        yield from budget.checkpoint()
        self.volume.valueChanged.connect(self._volume_changed)
        volume.addWidget(self.volume); transport.addLayout(volume, 1)
        view.addLayout(transport)
        yield from budget.checkpoint()
        outer.addWidget(view_card)

        self.selection_card = SourceSelectionArea(self)
        put_card, put = self.card(self.selection_card)
        head = QHBoxLayout(); head.setSpacing(6)
        yield from budget.checkpoint()
        self.selection_handle = SourceSelectionArea(self)
        self.selection_handle.setObjectName('sourceSelectionHandle')
        grip_row = QHBoxLayout(self.selection_handle); grip_row.setContentsMargins(0, 0, 0, 0); grip_row.setSpacing(6)
        yield from budget.checkpoint()
        grip = QLabel('⠿'); grip.setObjectName('sourceDragGrip')
        yield from budget.checkpoint()
        heading = QLabel('选段'); heading.setObjectName('sourceSectionTitle')
        self.range_label = QLabel('00:00.000'); self.range_label.setObjectName('sourceDuration')
        yield from budget.checkpoint()
        for widget in (grip, heading, self.range_label):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            grip_row.addWidget(widget)
        grip_row.addStretch(1)
        head.addWidget(self.selection_handle, 1)
        play_range = self.link_button(' 试看选段', self.play_selection)
        yield from budget.checkpoint()
        install_themed_icon(play_range, 'fa5s.play', 'muted'); play_range.setIconSize(QSize(9, 9))
        head.addWidget(play_range); head.addWidget(self.link_button('清除', self.clear_range))
        yield from budget.checkpoint()
        put.addLayout(head)
        segment = QFrame(); segment.setObjectName('sourceSegment')
        segment.setToolTip('单击选择加入方式；按住拖到兼容轨道直接加入')
        yield from budget.checkpoint()
        modes = QHBoxLayout(segment); modes.setContentsMargins(3, 3, 3, 3); modes.setSpacing(2)
        self.mode_buttons = {}
        yield from budget.checkpoint()
        for mode, label, icon in (('av', '音视频', 'fa5s.photo-video'), ('video', '仅视频', 'fa5s.film'),
                                  ('audio', '仅音频', 'fa5s.music')):
            button = SourceDragButton(' '+label, self, mode)
            install_themed_icon(button, icon, 'secondary'); button.setIconSize(QSize(13, 13))
            modes.addWidget(button, 1); self.mode_buttons[mode] = button
        put.addWidget(segment)
        self.stream = QComboBox(); self.stream.setMinimumWidth(0); self.stream.setObjectName('sourceTarget')
        yield from budget.checkpoint()
        self.stream.setCursor(Qt.CursorShape.ArrowCursor)
        self.stream.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.stream.currentIndexChanged.connect(self._stream_changed)
        yield from budget.checkpoint()
        put.addWidget(self.stream)
        targets = self.targets_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight); targets.setSpacing(8)
        self.video_target = QComboBox(); self.audio_target = QComboBox()
        yield from budget.checkpoint()
        for combo in (self.video_target, self.audio_target):
            combo.setCursor(Qt.CursorShape.ArrowCursor)
            combo.setObjectName('sourceTarget')
            combo.setMinimumWidth(0); combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            targets.addWidget(combo, 1)
        self.video_target.setToolTip('画面目标轨；音视频一起时声音进入该轨的关联音轨')
        self.audio_target.setToolTip('仅音频的目标轨；可选择新建独立音轨')
        yield from budget.checkpoint()
        self.video_target.currentIndexChanged.connect(self._target_changed)
        put.addLayout(targets)
        self.insert_button = self.button(' 加入时间线 · 工程播放头', self.insert)
        self.insert_button.setObjectName('sourcePrimary')
        yield from budget.checkpoint()
        self.insert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        install_themed_icon(self.insert_button, 'fa5s.plus', 'on_accent'); self.insert_button.setIconSize(QSize(13, 13))
        put.addWidget(self.insert_button)
        yield from budget.checkpoint()
        self.status = StatusLabel(self); put.addWidget(self.status)
        outer.addWidget(put_card)
        outer.addStretch(1)
        yield from budget.checkpoint()
        self.timer = QTimer(self); self.timer.setInterval(40); self.timer.timeout.connect(self._tick)
        self.seek_timer = QTimer(self); self.seek_timer.setSingleShot(True); self.seek_timer.setInterval(25)
        yield from budget.checkpoint()
        self.seek_timer.timeout.connect(self._post_seek)
        self.wave_timer = QTimer(self); self.wave_timer.setSingleShot(True); self.wave_timer.setInterval(120)
        yield from budget.checkpoint()
        self.wave_timer.timeout.connect(self._request_wave)
        self.refresh_targets()
        yield from budget.checkpoint()
        self.set_mode('av')

    @staticmethod
    def _new_surface():
        surface=QFrame()
        surface.setObjectName('videoSurface');surface.setStyleSheet('background: #101014;')
        surface.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors,sys.platform=='win32')
        surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow,sys.platform!='darwin')
        surface.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return surface

    def _surface_retired(self,epoch):
        surface=self._retired_surfaces.pop(epoch,None)
        from shiboken6 import isValid
        if surface is not None and isValid(surface):surface.deleteLater()

    def _retire_controller(self,epoch,controller):
        def close():
            try:
                if controller is not None:controller.close()
            finally:
                try:self.surface_retired.emit(epoch)
                except RuntimeError:pass
        threading.Thread(target=close,name='source-player-close',daemon=True).start()

    @staticmethod
    def button(label, callback):
        button = QPushButton(label); button.setObjectName('studioButton')
        button.setFocusPolicy(Qt.FocusPolicy.ClickFocus); button.clicked.connect(callback)
        return button

    @staticmethod
    def link_button(label, callback):
        button = StudioSourceMonitor.button(label, callback); button.setObjectName('sourceLink')
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def icon_button(icon, tip, callback, name='sourceRound', role='secondary', size=13):
        button = QToolButton(); button.setObjectName(name); button.setToolTip(tip)
        button.setFocusPolicy(Qt.FocusPolicy.ClickFocus); button.setCursor(Qt.CursorShape.PointingHandCursor)
        install_themed_icon(button, icon, role); button.setIconSize(QSize(size, size))
        button.clicked.connect(callback)
        return button

    @staticmethod
    def card(frame=None):
        frame = frame if frame is not None else QFrame(); frame.setObjectName('sourceCard')
        layout = QVBoxLayout(frame); layout.setContentsMargins(12, 10, 12, 12); layout.setSpacing(10)
        return frame, layout

    def point(self, label, field, callback, tip):
        frame = SourcePointButton(field, callback, tip)
        row = QHBoxLayout(frame); row.setContentsMargins(10, 5, 5, 5); row.setSpacing(4)
        text = QBoxLayout(QBoxLayout.Direction.TopToBottom); text.setSpacing(0); self.point_layouts.append(text)
        caption = QLabel(label); caption.setObjectName('sourcePointLabel')
        caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text.addWidget(caption); text.addWidget(field); row.addLayout(text, 1)
        flag = self.icon_button('fa5s.flag', tip, callback, 'sourcePointSet', 'accent', 11)
        flag.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        flag.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(flag)
        return frame

    @staticmethod
    def time_field(callback):
        field = QLineEdit('00:00:00.000'); field.setObjectName('sourceTimecode')
        field.setMaximumWidth(150); field.setMinimumWidth(108)
        field.editingFinished.connect(callback)
        return field

    @property
    def asset(self):
        if self.project is not self.page.project or not self.asset_id or self.project is None:
            return None
        return next((a for a in self.project.media_pool if a.asset_id == self.asset_id), None)

    def owns_focus(self):
        if not self.isVisible() or not self.window().isActiveWindow():return False
        native=native_source_focus(self.surface)
        if native is not None:return native
        focus = QApplication.focusWidget()
        return focus is self or focus is not None and self.isAncestorOf(focus)

    def dispatch(self, sequence):
        if not self.owns_focus():
            return False
        focus = QApplication.focusWidget()
        from PySide6.QtWidgets import QAbstractSpinBox, QTextEdit, QPlainTextEdit
        if isinstance(focus, (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit)):
            return False
        callbacks = {'Space': self.toggle_play, 'I': lambda: self.set_boundary('in_ms', self.position_ms),
                     'O': lambda: self.set_boundary('out_ms', self.position_ms),
                     'Left': lambda: self.step(-1), 'Right': lambda: self.step(1)}
        callback = callbacks.get(sequence)
        if callback is None:
            return False
        callback()
        return True

    def open_asset(self, asset_id):
        self.pause()
        self.resolver.reset()
        self.source_token += 1
        self.resolved_source = self.resolved_path = self.resolve_requested = ''
        self.playback_source = ''
        self.loading = True
        self.project, self.asset_id = self.page.project, str(asset_id)
        if not self.asset:
            return
        self.source_path_at_open = self.asset.canonical_source
        self.closed = False
        state = source_state(self.project, self.asset_id)
        self.position_ms = min(self.asset.duration_ms, max(0, int(state.get('position_ms') or 0)))
        self.zoom.setValue(1)
        self.view_start, self.view_span = 0, max(1, self.asset.duration_ms)
        self.peaks = None
        video, audio = source_capabilities(self.asset)
        self.visual.setCurrentIndex(0 if video else 1)
        self.ruler.setVisible(video)
        self.stream.blockSignals(True); self.stream.clear()
        streams = self.asset.audio_metadata.get('streams') or ([{}] if audio else [])
        for i, stream in enumerate(streams):
            detail = ' · '.join(str(stream.get(key) or '') for key in ('language', 'title', 'codec') if stream.get(key))
            self.stream.addItem(f'音频 {i+1}' + (' · '+detail if detail else ''), i)
        self.stream.setCurrentIndex(min(len(streams)-1, max(0, int(state.get('stream_index') or 0))))
        self.stream.blockSignals(False)
        self.set_mode('av' if video and audio else 'video' if video else 'audio')
        self.refresh_targets(); self._refresh_range(); self._zoom_changed()
        self.title.set_full_text(self.asset.display_name); self.origin_chip.show()
        self.status.setText('')
        self.timer.start()
        self._load_current()
        self.content_scroll.verticalScrollBar().setValue(0)

    def refresh_metadata(self):
        if not self.asset:
            return
        video, audio = source_capabilities(self.asset)
        self.visual.setCurrentIndex(0 if video else 1)
        self.ruler.setVisible(video)
        streams = self.asset.audio_metadata.get('streams') or ([{}] if audio else [])
        if self.stream.count() != len(streams):
            selected = int(source_state(self.project, self.asset_id).get('stream_index') or 0)
            self.stream.blockSignals(True); self.stream.clear()
            for i, stream in enumerate(streams):
                label = ' · '.join(str(stream.get(k) or '') for k in ('language', 'title', 'codec') if stream.get(k))
                self.stream.addItem(f'音频 {i+1}' + (' · '+label if label else ''), i)
            self.stream.setCurrentIndex(min(len(streams)-1, selected)); self.stream.blockSignals(False)
        if self.mode == 'av' and not (video and audio) or self.mode == 'video' and not video or self.mode == 'audio' and not audio:
            self.set_mode('av' if video and audio else 'video' if video else 'audio')
        if self.view_span <= 1 and self.asset.duration_ms > 0:
            self._zoom_changed()
        self._refresh_range()

    def close_source(self):
        self.reset()
        self.page.source_tabs.setCurrentIndex(0)
        self.page.source_tabs.setTabText(1, '源素材')

    def _load_current(self):
        if not self.asset:
            return
        if self.controller is not None and not self.controller.running:
            self._detach_player()
        if self.asset.offline or not Path(self.asset.canonical_source).is_file():
            self._detach_player();self.loading=False
            self.status.setText('源文件缺失，请在右侧媒体池点击「重新定位」')
            return
        source = self.asset.canonical_source
        if source.lower().endswith('.flv') and self.resolved_source != source:
            if self.resolve_requested != source:
                self.resolve_requested = source
                self.resolver.request(self.source_token, source)
            self.status.setText('正在后台准备源素材时间映射…')
            return
        self.playback_source = self.resolved_path or source
        if self.controller is None:
            if self.starting:
                return
            self.starting = True
            epoch, hwnd = self.epoch, int(self.surface.winId())
            self._starting_epoch=epoch
            self.status.setText('正在准备源播放器…')
            def start():
                controller = None
                try:
                    controller = create_preview_controller()
                    controller.start(hwnd)
                    self.controller_ready.emit(epoch, controller, '')
                except Exception as exc:
                    if controller:
                        controller.close()
                    try:
                        self.controller_ready.emit(epoch, None, str(exc))
                    except RuntimeError:
                        pass
            threading.Thread(target=start, name='source-player-start', daemon=True).start()
            return
        self.loading = True
        self.load_generation += 1
        self.loaded_at = time.monotonic()
        self.controller.post_set_paused(True)
        self.controller.post_load_at(self.playback_source, self.position_ms/1000,
            generation=self.load_generation, source_audio_stream=int(self.stream.currentData() or 0))
        self.controller.post_set_subtitle_visible(False)
        self._volume_changed()

    def _resolved(self, token, source, path, error):
        if token != self.source_token or not self.asset or self.asset.canonical_source != source:
            return
        self.resolve_requested = ''
        if error:
            self.status.setText('源素材准备失败：'+error+'；重新双击可重试')
            return
        self.resolved_source, self.resolved_path = source, path
        self._load_current()

    def _controller_ready(self, epoch, controller, error):
        if self._starting_epoch == epoch:
            self.starting=False;self._starting_epoch=None
        if epoch != self.epoch or self.closed or not self.asset:
            self._retire_controller(epoch,controller)
            if not self.closed and self.asset:
                self._load_current()
            return
        self.controller = controller
        if error:
            self.status.setText('源播放器初始化失败：'+error+'；重新双击素材可重试')
        else:
            self._load_current()

    def pause(self):
        self.paused = True
        self.play_range_end = None
        if self.controller and self.controller.running:
            self.controller.post_set_paused(True)
        self._show_playing(False)

    def _show_playing(self, playing):
        install_themed_icon(self.play_button, 'fa5s.pause' if playing else 'fa5s.play', 'on_accent')
        self.play_button.setToolTip(('暂停' if playing else '播放') + ' (Space)')

    def _toggle_mute(self):
        if self.narrow:
            # Narrow columns hide the inline slider; the speaker opens it instead.
            menu = QMenu(self); slider = QSlider(Qt.Orientation.Horizontal); slider.setObjectName('sourceVolume')
            slider.setRange(0, 100); slider.setValue(self.volume.value()); slider.setFixedWidth(140)
            slider.valueChanged.connect(self.volume.setValue)
            action = QWidgetAction(menu); action.setDefaultWidget(slider); menu.addAction(action)
            menu.exec(self.mute_button.mapToGlobal(self.mute_button.rect().bottomLeft()))
            menu.deleteLater()
            return
        if self.volume.value():
            self._unmuted_volume = self.volume.value(); self.volume.setValue(0)
        else:
            self.volume.setValue(getattr(self, '_unmuted_volume', 70) or 70)

    def toggle_play(self):
        if not self.asset or not self.controller or self.loading:
            return
        if self.paused:
            if self.position_ms >= self.asset.duration_ms-1:
                self.seek(0)
            self.paused = False
            self.controller.post_set_paused(False)
            self._show_playing(True)
        else:
            self.pause()

    def play_selection(self):
        if not self.asset or not self.controller or self.loading:
            return
        start, end = self.range_ms()
        self.seek(start); self.seek_timer.stop(); self._post_seek()
        self.paused = False; self.play_range_end = end
        self.controller.post_set_paused(False)
        self._show_playing(True)

    def seek(self, value):
        if not self.asset:
            return
        self.position_ms = source_boundary(self.asset, value)
        source_state(self.project, self.asset_id)['position_ms'] = self.position_ms
        self._refresh_position()
        self.seek_timer.start()
        self.seek_until = time.monotonic()+0.35

    def _post_seek(self):
        if self.controller and self.asset:
            # At an exclusive tail, display its preceding real frame.
            fps = float(self.asset.video_metadata.get('fps') or 25)
            last = max(0, self.asset.duration_ms - (round(1000/fps) if source_capabilities(self.asset)[0] else 1))
            self.controller.post_seek(min(self.position_ms, last)/1000, generation=self.load_generation)

    def step(self, direction):
        if self.asset:
            self.pause()
            fps = float(self.asset.video_metadata.get('fps') or 25)
            self.seek(self.position_ms + direction * (1000/fps if source_capabilities(self.asset)[0] else 10))

    def range_ms(self):
        if not self.asset:
            return 0, 0
        state = source_state(self.project, self.asset_id)
        return (int(state.get('in_ms') or 0), self.asset.duration_ms if state.get('out_ms') is None else int(state['out_ms']))

    def set_boundary(self, which, value):
        if not self.asset:
            return
        value = source_boundary(self.asset, value)
        start, end = self.range_ms()
        if which == 'in_ms' and value >= end or which == 'out_ms' and value <= start:
            self.status.setText('入点必须早于出点，请先移动另一侧边界')
            self._refresh_range()
            return
        source_state(self.project, self.asset_id)[which] = value
        self._refresh_range()

    def clear_range(self):
        if self.asset:
            state = source_state(self.project, self.asset_id)
            state.pop('in_ms', None); state.pop('out_ms', None)
            self._refresh_range()

    def _time_edited(self, which):
        field = self.time_edit if which == 'position' else self.in_edit if which == 'in_ms' else self.out_edit
        value = parse_timeline_timecode(field.text())
        if value is None:
            self.status.setText('请输入 HH:MM:SS.mmm 或 MM:SS.mmm')
        elif which == 'position':
            self.seek(value)
        else:
            self.set_boundary(which, value)
        self._refresh_range(); self._refresh_position()

    def _refresh_range(self):
        start, end = self.range_ms()
        for field, value in ((self.in_edit, start), (self.out_edit, end)):
            if not field.hasFocus():
                field.setText(format_timeline_timecode(value))
        span = format_timeline_timecode(end-start)
        self.range_label.setText(span[3:] if span.startswith('00:') else span)
        self.total_label.setText('/ '+format_timeline_timecode(self.asset.duration_ms if self.asset else 0))
        self.ruler.update(); self.waveform.update()
        self._refresh_position()

    def _refresh_position(self):
        if not self.time_edit.hasFocus():
            self.time_edit.setText(format_timeline_timecode(self.position_ms))
        self.ruler.update(); self.waveform.update()

    def set_mode(self, mode):
        self.mode = mode
        video, audio = source_capabilities(self.asset) if self.asset else (False, False)
        for key, button in self.mode_buttons.items():
            button.setEnabled(video and audio if key == 'av' else video if key == 'video' else audio)
            button.setChecked(key == mode)
        self.video_target.setEnabled(mode != 'audio')
        self.audio_target.setEnabled(mode == 'audio')
        self.stream.setEnabled(audio and mode != 'video')
        self.stream.setVisible(audio and self.stream.count() > 1)
        self.insert_button.setEnabled(bool(self.asset))
        self._target_changed()

    def refresh_targets(self):
        project = self.page.project
        for combo, tracks, label in ((self.video_target, project.video_tracks if project else [], '新建视频轨'),
                                     (self.audio_target, project.audio_tracks if project else [], '新建独立音轨')):
            previous = combo.currentData()
            combo.blockSignals(True); combo.clear(); combo.addItem(('画面 → ' if combo is self.video_target else '声音 → ')+label, 'new')
            for track in tracks:
                combo.addItem(('画面 → ' if combo is self.video_target else '声音 → ')+f'{track.id} · {track.name}' + (' · 已锁定' if track.locked else ''), track.id)
            combo.setCurrentIndex(max(0, combo.findData(previous)))
            combo.blockSignals(False)
        self._target_changed()

    def _target_changed(self, *_):
        if self.mode == 'av':
            video_id = self.video_target.currentData()
            group = next((g for g in self.page.project.av_track_groups if g.video_track_id == video_id), None) if self.page.project else None
            self.audio_target.setCurrentIndex(max(0, self.audio_target.findData(group.audio_track_id if group else 'new')))
        self.insert_button.setToolTip('加入工程播放头位置；声音跟随视频关联轨' if self.mode == 'av'
                                      else '加入工程播放头位置；源入点决定内容，源播放头只用于预览')

    def insert(self, *_):
        if not self.asset:
            return
        try:
            selection = SourceSelection.capture(self.project, self.asset_id, self.mode)
            command = SourceInsertCommand(self.project, selection, self.page.timeline.playhead_ms,
                self.video_target.currentData() or 'new', self.audio_target.currentData() or 'new')
            self.page.undo_stack.push(command)
            message = (f'已加入 {format_timeline_timecode(command.placement["start_ms"])} → '
                       f'{format_timeline_timecode(command.placement["end_ms"])} · 可一步撤销')
            self.status.setText(message)
            QTimer.singleShot(5000, lambda: self.status.text() == message and self.status.setText(''))
            self.refresh_targets()
        except (ValueError, KeyError) as exc:
            self.status.setText(str(exc))

    def start_drag(self, widget, mode='auto'):
        if not self.asset:
            return
        try:
            selection = SourceSelection.capture(self.project, self.asset_id, mode)
            drag = QDrag(widget); drag.setMimeData(source_mime(self.project, selection))
            drag.exec(Qt.DropAction.CopyAction)
        except (ValueError, KeyError) as exc:
            self.status.setText(str(exc))

    def _stream_changed(self, *_):
        if self.asset:
            source_state(self.project, self.asset_id)['stream_index'] = int(self.stream.currentData() or 0)
            self.pause(); self._load_current(); self.peaks = None; self._request_wave()

    def _volume_changed(self, *_):
        if self.controller:
            self.controller.post_set_volume(self.volume.value())

    def _zoom_changed(self, *_):
        if not self.asset:
            return
        self.view_span = max(100, round(self.asset.duration_ms / self.zoom.value()))
        self.view_start = min(max(0, self.position_ms-self.view_span//2), max(0, self.asset.duration_ms-self.view_span))
        self.scroll.blockSignals(True); self.scroll.setRange(0, max(0, self.asset.duration_ms-self.view_span))
        self.scroll.setPageStep(self.view_span); self.scroll.setValue(self.view_start); self.scroll.blockSignals(False)
        self._window_changed()

    def _scroll_changed(self, value):
        self.view_start = value; self._window_changed()

    def _window_changed(self):
        self.peaks = None
        self.ruler.update(); self.waveform.update(); self.wave_timer.start()

    def _request_wave(self):
        if self.asset and source_capabilities(self.asset)[1] and not source_capabilities(self.asset)[0]:
            self.wave_status = '正在生成波形…'
            self.wave_key, peaks = self.wave_cache.request(self.asset.canonical_source,
                int(self.stream.currentData() or 0), self.view_start,
                min(self.asset.duration_ms, self.view_start+self.view_span), priority=True)
            if peaks is not None:
                self.peaks = peaks; self.waveform.update()

    def _wave_ready(self, key, peaks):
        if key == self.wave_key and self.asset:
            if isinstance(peaks, dict):
                self.wave_status = peaks.get('error', '波形解码失败')
            else:
                self.peaks = peaks
            self.waveform.update()

    def _tick(self):
        if not self.asset or not self.controller:
            return
        age=time.monotonic()-self.loaded_at
        if (not self.controller.running or
                (not self.loading or age>10) and not self.controller.source_alive()):
            self._detach_player();self.loading=False;self.pause()
            self.status.setText('源播放器连接中断；重新双击素材以重试')
            return
        props = self.controller.observed_properties()
        if (not self.playback_source or Path(str(props.get('path') or '')).resolve() != Path(self.playback_source).resolve()
                or self.loading and time.monotonic()-self.loaded_at < .12):
            if time.monotonic()-self.loaded_at > 10 and self.loading:
                self.status.setText('源素材加载失败或超时；重新双击可重试，文件缺失时请重新定位')
            return
        if self.loading:
            self.loading = False
            self.status.setText('')
        value = props.get('time-pos')
        if value is not None and not self.seek_timer.isActive() and time.monotonic() >= getattr(self, 'seek_until', 0):
            self.position_ms = max(0, min(self.asset.duration_ms, round(float(value)*1000)))
            source_state(self.project, self.asset_id)['position_ms'] = self.position_ms
            self._refresh_position()
        if self.play_range_end is not None and self.position_ms >= self.play_range_end-5:
            end = self.play_range_end; self.pause(); self.seek(end)
        elif props.get('eof-reached') and not self.paused:
            self.pause()

    def _detach_player(self):
        epoch=self.epoch
        if self.controller is not None or self._starting_epoch == epoch:
            old=self.surface
            was_current=self.visual.currentWidget() is old
            self.visual.removeWidget(old);old.hide()
            self._retired_surfaces[epoch]=old
            self.surface=self._new_surface();self.visual.insertWidget(0,self.surface)
            if was_current:self.visual.setCurrentWidget(self.surface)
        self.epoch += 1
        controller, self.controller = self.controller, None
        if controller:
            self._retire_controller(epoch,controller)

    def reset(self):
        self.pause()
        self.timer.stop(); self.seek_timer.stop(); self.wave_timer.stop()
        self.wave_cache.reset()
        self.resolver.reset(); self.source_token += 1
        self.asset_id = ''; self.project = None; self.peaks = None; self.wave_key = ''
        self.playback_source = ''; self.loading = False
        self._detach_player()
        self.title.set_full_text('双击媒体池素材，预览原文件'); self.origin_chip.hide(); self.status.setText('')
        self._refresh_range()

    def shutdown(self):
        self.closed = True; self.reset(); self.wave_cache.close(); self.resolver.close()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_density(self.width() < 430)
        self.visual.setFixedHeight(max(90, min(240, round((self.width()-20)*9/16), round(self.height()*.34))))

    def _apply_density(self, narrow):
        """Reflow for narrow left columns instead of clipping controls."""
        if narrow == self.narrow:
            return
        self.narrow = narrow
        row, column = QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.TopToBottom
        self.points_layout.setDirection(column if narrow else row)
        self.targets_layout.setDirection(column if narrow else row)
        for layout in self.point_layouts:
            layout.setDirection(row if narrow else column)
        self.volume.setVisible(not narrow)
        self.mute_button.setToolTip('试听音量' if narrow else '试听音量；单击静音')
        self.time_edit.setMinimumWidth(104 if narrow else 128)
        self.transport_layout.setSpacing(4 if narrow else 8)
        for widget in (*self.transport_buttons, self.time_edit):
            widget.setProperty('compact', narrow)
            widget.style().unpolish(widget); widget.style().polish(widget)

    def hideEvent(self, event):
        self.pause()
        self.timer.stop()
        super().hideEvent(event)

    def showEvent(self,event):
        super().showEvent(event)
        if self.asset:self.timer.start()

# Retain the installed daily's whole-source MIME for older drag callers.
from .legacy_source_monitor import (MEDIA_PART_MIME, media_part_mime, read_media_part,
    media_part_drag_move, media_part_drop, place_media_part)

def open_source_monitor(page, asset_id):
    page._set_major_panel_visible('cue_list', True)
    page.source_tabs.setCurrentIndex(1)
    page.source_monitor.open_asset(asset_id)

def close_source_monitor(page):
    monitor = getattr(page, 'source_monitor', None)
    if monitor is not None:
        monitor.reset()
        page.source_tabs.setCurrentIndex(0)
