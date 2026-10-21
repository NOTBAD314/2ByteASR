# Legacy Qt decoder comparison tests; process backend contracts live in test_video_decode_pipe.py.
"""第五十轮守护：V1/V2 同显残因 + 变换面板/画布 gizmo（2026-09-06）。

- 暂停态叠加层 seek 丢失重试（secondary_video 帧到达路径收敛）：
  `request` 同 signature 早退放开 + `_on_frame` 低频重发 seek。
- 变换面板：全部数值控件统一宽度；缩放默认等比链锁（可关闭）。
- 画布变换框：选中 mpv 承载的主轨片段也有 gizmo（此前只有最上层叠加层）。
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.studio.studio_ui import SubtitleStudioPage  # noqa: E402
from twobyteasr.playback.video_compositor import VideoCompositionScene  # noqa: E402


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    return app


def test_transform_panel_spin_widths_are_uniform():
    _app()
    page = SubtitleStudioPage()
    controls = [
        page.video_position_x, page.video_position_y,
        page.video_scale_x, page.video_scale_y,
        page.video_rotation, page.video_opacity,
        page.video_anchor_x, page.video_anchor_y,
    ]
    widths = {(c.minimumWidth(), c.maximumWidth()) for c in controls}
    assert len(widths) == 1, f"数值控件宽度不统一: {widths}"
    width = controls[0].minimumWidth()
    assert width > 0
    page.close_page()
    page.deleteLater()


def test_scale_link_defaults_on_and_syncs_both_axes():
    _app()
    page = SubtitleStudioPage()
    assert page.video_scale_link.isChecked() is True
    page._set_video_transform_controls({"scale_x": 1.0, "scale_y": 1.0})
    page.video_scale_x.setValue(150.0)
    assert page.video_scale_y.value() == 150.0
    page.video_scale_y.setValue(80.0)
    assert page.video_scale_x.value() == 80.0
    # 关闭链锁后两轴独立
    page.video_scale_link.setChecked(False)
    page.video_scale_x.setValue(220.0)
    assert page.video_scale_y.value() == 80.0
    # 程序化载入（blockSignals）不触发同步回写
    page.video_scale_link.setChecked(True)
    page._set_video_transform_controls({"scale_x": 1.3, "scale_y": 0.7})
    assert page.video_scale_x.value() == 130.0
    assert page.video_scale_y.value() == 70.0
    page.close_page()
    page.deleteLater()


def _base_layer(path: Path) -> dict:
    return {
        "track_id": "V1",
        "track_name": "V1",
        "track_locked": False,
        "clip_id": "clip-v1",
        "source_path": str(path),
        "source_ms": 1_000,
        "fps": 60.0,
        "source_w": 1920.0,
        "source_h": 1080.0,
        "primary_media": True,
        "transform": {"position_x": 0.5, "position_y": 0.5, "scale_x": 1.0, "scale_y": 1.0},
        "effects": {},
        "audio_enabled": True,
        "track_muted": False,
    }


def test_base_layer_selected_gets_canvas_gizmo(tmp_path):
    _app()
    scene = VideoCompositionScene()
    scene.resize(800, 450)
    media = tmp_path / "main.flv"
    media.write_bytes(b"x")
    layer = _base_layer(media)

    # 无叠加层且未选中主轨片段 → 照旧 suspend
    scene.set_composition(
        [layer], paused=True, rate=1.0,
        audio_master_track_id="V1", base_track_id="V1", volume=0.0,
        project_ms=1_000, mpv_path=str(media),
    )
    assert not scene.isVisible()

    # 选中主轨片段 → 保持可见且 grab 后有变换框 polygon（可拖拽命中）
    scene.set_selected_clip("clip-v1")
    scene.set_composition(
        [layer], paused=True, rate=1.0,
        audio_master_track_id="V1", base_track_id="V1", volume=0.0,
        project_ms=1_000, mpv_path=str(media),
    )
    assert scene.isVisible()
    scene.grab()  # 触发完整 paint
    polygon = scene._layer_polygons.get("clip-v1")
    assert polygon is not None, "主轨层无变换框 polygon"
    bounds: QRectF = polygon.boundingRect()
    center = bounds.center()
    assert scene.rect().contains(center.toPoint())

    # 锁定轨道不画 gizmo（面板与画布一致）
    locked = dict(layer)
    locked["track_locked"] = True
    scene.set_composition(
        [locked], paused=True, rate=1.0,
        audio_master_track_id="V1", base_track_id="V1", volume=0.0,
        project_ms=1_000, mpv_path=str(media),
    )
    scene.grab()
    assert "clip-v1" not in scene._layer_polygons
    scene.close()
    scene.deleteLater()


def test_base_layer_gizmo_drag_emits_transform(tmp_path):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent

    _app()
    scene = VideoCompositionScene()
    scene.resize(800, 450)
    media = tmp_path / "main.flv"
    media.write_bytes(b"x")
    scene.set_selected_clip("clip-v1")
    scene.set_composition(
        [_base_layer(media)], paused=True, rate=1.0,
        audio_master_track_id="V1", base_track_id="V1", volume=0.0,
        project_ms=1_000, mpv_path=str(media),
    )
    scene.grab()
    polygon = scene._layer_polygons.get("clip-v1")
    assert polygon is not None
    center = polygon.boundingRect().center()

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(center), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    scene.mousePressEvent(press)
    assert scene._drag is not None and scene._drag["track_id"] == "V1"

    emitted: list[tuple[str, str, dict]] = []
    scene.transform_preview.connect(lambda t, c, v: emitted.append((t, c, dict(v))))
    moved = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(center.x() + 40, center.y() + 10),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    scene.mouseMoveEvent(moved)
    assert emitted and emitted[0][0] == "V1"
    values = emitted[0][2]
    assert values["position_x"] > 0.5
    scene.close()
    scene.deleteLater()


def test_secondary_request_same_signature_allows_paused_reassert():
    """同 signature 暂停态不再盲目早退（seek 被吞后可低频重发）。"""
    _app()
    from PySide6.QtCore import QObject, Signal
    from twobyteasr.playback.secondary_video_legacy import _DecoderWorker, SourceState

    worker = _DecoderWorker()
    worker._ensure_player()

    class _FakePlayer(QObject):
        playbackStateChanged = Signal()

        def __init__(self):
            super().__init__()
            self.position_ms = 0
            self.rate = 1.0
            self.state = "PausedState"

        def playbackRate(self):
            return self.rate

        def setPlaybackRate(self, value):
            self.rate = value

        def position(self):
            return self.position_ms

        def setPosition(self, value):
            self.position_ms = int(value)

        def playbackState(self):
            from PySide6.QtMultimedia import QMediaPlayer
            return QMediaPlayer.PlaybackState.PausedState

        def pause(self):
            self.state = "PausedState"

        def play(self):
            self.state = "PlayingState"

        def stop(self):
            self.state = "StoppedState"

        def setVideoSink(self, sink):
            self._sink = sink

        def setSource(self, source):
            self._source = source

    worker.player = _FakePlayer()  # type: ignore[assignment]
    worker.path = "clip.mp4"
    worker._state = SourceState.READY
    worker._source_loaded = True
    worker.request(33_199, generation=1, paused=True, rate=1.0, volume=0.0,
                   audio_output_enabled=False, video_output_enabled=True)
    assert worker._wanted_ms == 33_199
    assert worker._pending_pause_after_frame is True
    assert worker.player.position_ms == 33_199
    # 播放器未收敛（position 远离目标）→ 同 signature 重入不早退，重发 seek
    worker.player.position_ms = 0
    worker._last_seek_attempt = 0.0  # 让 1.2s 节流窗过期
    worker.request(33_199, generation=1, paused=True, rate=1.0, volume=0.0,
                   audio_output_enabled=False, video_output_enabled=True)
    assert worker.player.position_ms == 33_199
    worker.shutdown()
    worker.deleteLater()
