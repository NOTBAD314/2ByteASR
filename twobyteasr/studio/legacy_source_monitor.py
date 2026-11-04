"""Source preview in the cue-list slot and picture / sound drags into the tracks.

2026-10-25 (user): "双击素材的媒体池可以在左侧字幕列表先预览影片，然后像
Premiere 一样能分别拖拽视频或音频进轨道内". Double-clicking a media-pool
source shows it where the cue list is, with its own player; three chips drag
both, the picture only or the sound only (a click adds at the playhead). The
media-pool rows drag both. Placement rules live in
``timeline.studio_media_pool.placement_plan``; every drop is one undo step.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from ..design.themed_icons import install_themed_icon
from ..i18n import bind_text, tr

MEDIA_PART_MIME = "application/x-2byteasr-media-part"
PART_LABELS = {"both": "视频+音频", "video": "仅视频", "audio": "仅音频"}
PART_ICONS = {"both": "fa5s.photo-video", "video": "fa5s.film", "audio": "fa5s.music"}


def media_part_mime(asset_id: str, part: str = "both") -> QMimeData:
    mime = QMimeData()
    mime.setData(MEDIA_PART_MIME, json.dumps({"asset_id": str(asset_id), "part": str(part)}).encode("utf-8"))
    return mime


def read_media_part(mime: QMimeData) -> dict | None:
    if mime is None or not mime.hasFormat(MEDIA_PART_MIME):
        return None
    try:
        payload = json.loads(bytes(mime.data(MEDIA_PART_MIME)).decode("utf-8"))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or not payload.get("asset_id"):
        return None
    return {"asset_id": str(payload["asset_id"]), "part": str(payload.get("part") or "both")}


def start_media_part_drag(source: QWidget, asset_id: str, part: str = "both") -> None:
    drag = QDrag(source)
    drag.setMimeData(media_part_mime(asset_id, part))
    drag.exec(Qt.DropAction.CopyAction)


# ---------------------------------------------------------------- placement

def _plan_at(page, payload: dict, point: QPoint | None) -> dict | None:
    """Placement for a pool drag at a page point (None: no timeline lane there)."""
    from ..timeline.studio_media_pool import placement_plan
    project = page.project
    timeline = page.timeline
    if project is None:
        return None
    if point is None:
        start, video_id, audio_id = int(timeline.playhead_ms), "", ""
        video_id = str(project.studio_state.get("selected_video_track_id") or "")
        audio_id = str(getattr(timeline, "selected_audio_track_id", "") or "")
    else:
        local = timeline.mapFrom(page, point)
        if not timeline.rect().contains(local) or local.x() < timeline.TRACK_HEADER_WIDTH:
            return None
        video_id, audio_id = timeline._video_track_at(local), timeline._audio_track_at(local)
        if not video_id and not audio_id:
            return None
        start = max(0, int(timeline._x_to_time(local.x())))
    try:
        plan = placement_plan(project, payload["asset_id"], payload["part"], timeline_in_ms=start,
                              video_track_id=video_id, audio_track_id=audio_id,
                              selected_video_track_id=str(project.studio_state.get("selected_video_track_id") or ""))
    except (KeyError, ValueError):
        return None
    plan["pointer_video_track_id"], plan["pointer_audio_track_id"] = video_id, audio_id
    return plan


def place_media_part(page, asset_id: str, part: str, plan: dict | None = None) -> str:
    """Add a source (or its picture / sound) as one undo step; '' or why not."""
    from ..timeline.studio_media_commands import media_graph_command
    from ..timeline.studio_media_pool import PLACEMENT_LABELS, apply_placement
    project = page.project
    if project is None:
        return tr("没有打开的工程")
    if plan is None:
        plan = _plan_at(page, {"asset_id": asset_id, "part": part}, None)
    if plan is None:
        from ..timeline.studio_media_pool import asset_by_id, asset_has_audio, asset_has_video
        try:
            asset = asset_by_id(project, asset_id)
        except KeyError:
            return tr("素材已不在媒体池")
        return tr("这个素材没有音频") if part == "audio" and not asset_has_audio(asset) else (
            tr("这个素材没有画面") if part == "video" and not asset_has_video(asset) else tr("无法添加片段"))
    try:
        command = media_graph_command(project, tr(PLACEMENT_LABELS[plan["part"]]),
                                      lambda working: apply_placement(working, plan))
    except (KeyError, ValueError) as exc:
        return str(exc)
    page.undo_stack.push(command)
    return ""


def media_part_drag_move(page, event) -> bool:
    """Accept a pool drag over a lane and show where it lands; False = not ours."""
    payload = read_media_part(event.mimeData())
    if payload is None:
        return False
    plan = _plan_at(page, payload, event.position().toPoint())
    page.timeline.set_media_drop_preview(plan)
    if plan is None:
        event.ignore()
    else:
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
    return True


def media_part_drop(page, event) -> bool:
    payload = read_media_part(event.mimeData())
    if payload is None:
        return False
    page.timeline.set_media_drop_preview(None)
    plan = _plan_at(page, payload, event.position().toPoint())
    if plan is None:
        event.ignore()
        return True
    problem = place_media_part(page, payload["asset_id"], payload["part"], plan)
    if problem and hasattr(page, "save_state"):
        page.save_state.setText(problem)
    event.setDropAction(Qt.DropAction.CopyAction)
    event.accept()
    return True


# ---------------------------------------------------------------- widgets

class MediaPartChip(QPushButton):
    """Drag it into the tracks; a click adds at the playhead."""

    add_requested = Signal(str)

    def __init__(self, part: str, parent=None):
        super().__init__(parent)
        self.part = part
        self.asset_id = ""
        self.setObjectName("studioButton")
        bind_text(self, PART_LABELS[part])
        install_themed_icon(self, PART_ICONS[part], "secondary")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._press = None
        self.clicked.connect(lambda: self.add_requested.emit(self.part))

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt API
        if (self._press is not None and self.asset_id and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            self.setDown(False)
            start_media_part_drag(self, self.asset_id, self.part)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        self._press = None
        super().mouseReleaseEvent(event)


class SourceMonitor(QFrame):
    """One source at a time, with its own player; never edits the project."""

    closed = Signal()

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.asset_id = ""
        self.duration_ms = 0
        self.canvas = None
        self.setObjectName("sourceMonitor")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 8, 8)
        layout.setSpacing(7)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("sectionTitle")
        self.title.setMinimumWidth(0)
        head.addWidget(self.title, 1)
        self.back_button = QPushButton()
        self.back_button.setObjectName("studioButton")
        bind_text(self.back_button, "返回字幕列表")
        install_themed_icon(self.back_button, "fa5s.list", "secondary")
        self.back_button.clicked.connect(self.close_monitor)
        head.addWidget(self.back_button)
        layout.addLayout(head)
        self.note = QLabel()
        self.note.setObjectName("mediaPoolMeta")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.canvas_host = QFrame()
        self.canvas_host.setObjectName("sourceMonitorPicture")
        self.canvas_layout = QVBoxLayout(self.canvas_host)
        self.canvas_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas_host, 1)
        transport = QHBoxLayout()
        self.play_button = QPushButton()
        self.play_button.setObjectName("studioButton")
        install_themed_icon(self.play_button, "fa5s.play", "secondary")
        bind_text(self.play_button, "播放 / 暂停", property="toolTip")
        self.play_button.clicked.connect(self.toggle_playback)
        transport.addWidget(self.play_button)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("sourceMonitorSlider")
        self.slider.sliderMoved.connect(self._seek)
        transport.addWidget(self.slider, 1)
        self.time_label = QLabel("00:00.0 / 00:00.0")
        self.time_label.setObjectName("mediaPoolMeta")
        transport.addWidget(self.time_label)
        layout.addLayout(transport)
        hint = QLabel()
        hint.setObjectName("mediaPoolMeta")
        hint.setWordWrap(True)
        bind_text(hint, "把下面的按钮拖到时间线轨道上；点一下就加到播放头处。")
        layout.addWidget(hint)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chips = {part: MediaPartChip(part) for part in ("both", "video", "audio")}
        for chip in self.chips.values():
            chip.add_requested.connect(self._add_part)
            chips.addWidget(chip)
        chips.addStretch(1)
        layout.addLayout(chips)

    # -- player
    def _ensure_canvas(self):
        if self.canvas is None:
            from .studio_video_canvas import MpvCanvas

            class SourceCanvas(MpvCanvas):
                # Its own read-only player: never coupled to the project page.
                def _studio_page(self):
                    return None

            self.canvas = SourceCanvas(self.canvas_host)
            self.canvas.setObjectName("sourceMonitorCanvas")
            self.canvas_layout.addWidget(self.canvas)
            self.canvas.position_changed.connect(self._position_changed)
            self.canvas.playback_state_changed.connect(self._playback_state_changed)
            self.canvas.error.connect(self.note.setText)
        return self.canvas

    def open_asset(self, asset) -> None:
        from ..timeline.studio_media_pool import asset_has_audio, asset_has_video
        self.asset_id = asset.asset_id
        self.duration_ms = max(0, int(asset.duration_ms or 0))
        self.title.setText(asset.display_name)
        self.title.setToolTip(asset.canonical_source)
        has_video, has_audio = asset_has_video(asset), asset_has_audio(asset)
        notes = [tr("预览不会改动工程")]
        if not has_video:
            notes.append(tr("音频素材，没有画面"))
        if asset.offline:
            notes.append(tr("素材离线，请先在媒体池重新定位"))
        self.note.setText("；".join(notes))
        for part, chip in self.chips.items():
            chip.asset_id = asset.asset_id
            usable = not asset.offline and {"both": has_video or has_audio, "video": has_video,
                                            "audio": has_audio}[part]
            chip.setEnabled(usable)
        self.slider.setRange(0, self.duration_ms)
        self.slider.setValue(0)
        self._position_changed(0.0)
        canvas = self._ensure_canvas()
        install_themed_icon(self.play_button, "fa5s.play", "secondary")
        if asset.offline:
            canvas.close_player()
            return

        def load():
            if self.asset_id != asset.asset_id or not self.isVisible():
                return
            canvas.load(asset.canonical_source, start_seconds=0.0)
            if canvas.controller:
                # No project audio engine here: this player owns its sound.
                canvas.controller.post_set_audio_enabled(True)
            canvas.set_paused(True)

        QTimer.singleShot(0, load)

    def toggle_playback(self) -> None:
        canvas = self.canvas
        if canvas is None or not canvas.controller:
            return
        if canvas._paused:
            _pause_project(self.page)
            if self.duration_ms and canvas.visual_position() * 1000 >= self.duration_ms - 50:
                canvas.seek(0.0)
        canvas.set_paused(not canvas._paused)

    def pause(self) -> None:
        if self.canvas is not None and self.canvas.controller and not self.canvas._paused:
            self.canvas.set_paused(True)

    def _seek(self, ms: int) -> None:
        if self.canvas is not None and self.canvas.controller:
            self.canvas.seek(ms / 1000)

    def _position_changed(self, seconds: float) -> None:
        def _format_duration(value: int) -> str:
            return f"{value // 60000:02d}:{value // 1000 % 60:02d}.{value // 100 % 10}"

        ms = max(0, round(float(seconds) * 1000))
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(ms)
            self.slider.blockSignals(False)
        self.time_label.setText(f"{_format_duration(ms)} / {_format_duration(self.duration_ms)}")

    def _playback_state_changed(self, paused: bool) -> None:
        install_themed_icon(self.play_button, "fa5s.play" if paused else "fa5s.pause", "secondary")

    def _add_part(self, part: str) -> None:
        problem = place_media_part(self.page, self.asset_id, part)
        if problem:
            self.note.setText(problem)

    def close_monitor(self) -> None:
        if self.canvas is not None:
            self.canvas.close_player()
        self.asset_id = ""
        self.closed.emit()


# ---------------------------------------------------------------- page glue

def _pause_project(page) -> None:
    """One sound at a time: the project pauses while a source plays."""
    video = getattr(page, "video", None)
    if video is not None and getattr(video, "controller", None) and not video._paused:
        video.set_paused(True)
        page._sync_play_button(True)


def open_source_monitor(page, asset_id: str) -> SourceMonitor | None:
    project = page.project
    asset = next((a for a in (project.media_pool if project else ()) if a.asset_id == asset_id), None)
    if asset is None:
        return None
    stack = page.cue_list_stack
    monitor = getattr(page, "source_monitor", None)
    if monitor is None:
        monitor = SourceMonitor(page)
        monitor.closed.connect(lambda: stack.setCurrentIndex(0))
        stack.addWidget(monitor)
        page.source_monitor = monitor
        page.video.playback_state_changed.connect(
            lambda paused: None if paused else monitor.pause())
    if not page.cue_list_panel.isVisible():
        page._set_major_panel_visible("cue_list", True)
    stack.setCurrentWidget(monitor)
    monitor.open_asset(asset)
    return monitor


def close_source_monitor(page) -> None:
    monitor = getattr(page, "source_monitor", None)
    if monitor is not None and monitor.asset_id:
        monitor.close_monitor()
