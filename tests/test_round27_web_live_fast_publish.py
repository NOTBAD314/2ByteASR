"""二十七轮：web-live 30fps 快速发布通道。

背景：旧路径每帧在 GUI 线程做 ~6 次全画布拷贝 + 3.7MB 同步写盘
（≈30-60ms/帧，用户实测视频层 ~10fps 一卡一卡）。新通道：
- worker 发**原始 PNG bytes**（发射路径不做同步解码——曾把发射周期拖到
  47ms≈22fps）；
- `_publish_web_live_frame` 首帧走 set_visual 绑定 snapshot，稳态帧把字节
  交给 `AdvancedLiveCanvas.publish_web_frame` → `MpvCanvas.publish_web_live_overlay`；
- 解码/ARGB32/bbox/裁剪/写盘/mpv 投递全部在专用发布线程（最新帧获胜；
  remove 递增 epoch 作废在途帧，防止旧帧在 overlay 移除后"复活"）。
"""

from __future__ import annotations

import base64
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from twobyteasr.studio import studio_advanced_flow
from twobyteasr.rendering.live_web_preview import _content_bounds, _decode_frame
from twobyteasr.studio.studio_video_canvas import MpvCanvas

# 1x1 红 PNG（round19/24 同款已验证常量；offscreen 下 QImage.save 会 abort，
# 手写 base64 会坏 header——libpng bad header 教训）。
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M"
    "9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication([])


class _FakeController:
    running = True

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.lock = threading.Lock()

    def post_raw_overlay(self, overlay_id, path, **geometry) -> bool:
        with self.lock:
            self.posts.append({
                "overlay_id": int(overlay_id),
                "path": str(path),
                "geometry": dict(geometry),
                "thread": threading.current_thread().name,
            })
        return True

    def post_remove_overlay(self, overlay_id) -> bool:
        return True

    def set_raw_overlay(self, overlay_id, path, **geometry) -> None:
        self.post_raw_overlay(overlay_id, path, **geometry)

    def remove_overlay(self, overlay_id) -> None:
        return None


def _filled_frame(width: int = 64, height: int = 32) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.fillRect(QRect(20, 10, 24, 12), QColor(255, 200, 60, 255))
    painter.end()
    return image


def test_content_bounds_finds_opaque_band():
    _app()
    image = _filled_frame()
    bounds = _content_bounds(image)
    assert bounds is not None
    # 允许 ±6px padding（辉光边缘），但必须包住不透明带且远小于全帧。
    assert bounds.left() <= 20 and bounds.right() >= 43
    assert bounds.top() <= 10 and bounds.bottom() >= 21
    assert bounds.width() < 64 and bounds.height() < 32


def test_content_bounds_empty_frame_returns_none():
    _app()
    image = QImage(64, 32, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    assert _content_bounds(image) is None


def test_opposite_corner_pixels_keep_the_whole_stage():
    _app()
    image = QImage(64, 32, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(0, 0, QColor(10, 20, 30, 50))
    image.setPixelColor(63, 31, QColor(40, 50, 60, 50))
    assert _content_bounds(image) == image.rect()


def test_decode_frame_normalizes_argb_and_bounds():
    # 1x1 红点 PNG：解码 → ARGB32 + 有效 bbox。
    decoded = _decode_frame(_TINY_PNG)
    assert decoded is not None
    image, bounds = decoded
    assert image.format() == QImage.Format.Format_ARGB32
    assert bounds is not None and not bounds.isEmpty()


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_fast_channel_posts_off_gui_thread():
    _app()
    canvas = MpvCanvas()
    canvas.controller = _FakeController()
    canvas.begin_web_live_overlays()
    try:
        ok = canvas.publish_web_live_overlay(
            MpvCanvas.ADVANCED_OVERLAY_ID, _TINY_PNG, QRect(0, 0, 1280, 720),
        )
        assert ok
        controller = canvas.controller
        assert _wait_for(lambda: len(controller.posts) >= 1), "publisher thread must post"
        post = controller.posts[0]
        # 1x1 帧：bbox=整帧 → 1x1 ARGB32 = 4 字节。
        assert post["geometry"]["width"] == 1 and post["geometry"]["height"] == 1
        data = Path(post["path"]).read_bytes()
        # A reusable mapped slot reserves capacity. mpv consumes only h*stride.
        assert len(data) >= post['geometry']['height'] * post['geometry']['stride']
        # 关键：解码+投递发生在发布线程，不是 GUI 主线程。
        assert post["thread"] != threading.current_thread().name
        assert post["thread"] == "web-live-overlay-publisher"
    finally:
        canvas.detach_player_for_close()
        canvas.deleteLater()


def test_fast_channel_latest_wins_and_epoch_invalidates():
    _app()
    canvas = MpvCanvas()
    canvas.controller = _FakeController()
    canvas.begin_web_live_overlays()
    try:
        for _ in range(6):
            canvas.publish_web_live_overlay(
                MpvCanvas.ADVANCED_OVERLAY_ID, _TINY_PNG, QRect(0, 0, 1280, 720),
            )
        controller = canvas.controller
        assert _wait_for(lambda: len(controller.posts) >= 1)
        time.sleep(0.3)
        # 最新帧获胜：6 帧入队但至少 5 帧被丢弃（队列里只剩最新）。
        assert len(controller.posts) <= 2, controller.posts
        # overlay 移除 → epoch 递增；在途旧 epoch 帧全部作废（remove 之后
        # 新发布的帧拿新 epoch，属于下个 cue 的合法接管，不在本测范围——
        # 流层 _publish_web_live_frame 在 stop 后由 snapshot=None 拦截）。
        canvas._active_compositor_overlays.add(MpvCanvas.ADVANCED_OVERLAY_ID)
        stale_epoch = canvas._web_live_epoch
        assert canvas.remove_compositor_overlay(MpvCanvas.ADVANCED_OVERLAY_ID)
        assert canvas._web_live_epoch == stale_epoch + 1
        posted = len(controller.posts)
        canvas._ensure_web_overlay_publisher()
        canvas._web_fast_queue.put((
            stale_epoch, MpvCanvas.ADVANCED_OVERLAY_ID, _TINY_PNG,
            QRect(0, 0, 1280, 720), {},
        ))
        time.sleep(0.3)
        assert len(controller.posts) == posted, "stale in-flight frames must be dropped"
    finally:
        canvas.detach_player_for_close()
        canvas.deleteLater()


class _RecordingOverlay:
    """AdvancedLiveCanvas 替身：记录三类调用。"""

    def __init__(self) -> None:
        self.set_visual_calls: list = []
        self.fast_calls: list = []
        self.mirror_calls: list = []

    def set_visual(self, pixmap, snapshot, animate_graph=False) -> None:
        self.set_visual_calls.append((pixmap, snapshot, animate_graph))

    def publish_web_frame(self, payload, image_size=None) -> None:
        self.fast_calls.append(payload)

    def set_web_mirror_frame(self, pixmap) -> None:
        self.mirror_calls.append(pixmap)


class _FakeSnapshot:
    def __init__(self, cue_id: str) -> None:
        self.cue_id = cue_id


def _publish_harness(overlay, cue_id="cue-1"):
    class _Harness(studio_advanced_flow.StudioAdvancedFlowMixin):
        def __init__(self) -> None:
            self.advanced_cue_overlay = overlay
            self._web_live_snapshot = _FakeSnapshot(cue_id)
            self._web_live_cue_id = cue_id
            self._web_live_last_frame_at = 0.0
            self._advanced_canvas_source_kind = ""
            self._advanced_cue_pixmap = None
            self._studio_trace = lambda event, **fields: None

    return _Harness()


def test_publish_first_frame_binds_snapshot_then_fast_path():
    _app()
    overlay = _RecordingOverlay()
    harness = _publish_harness(overlay)
    # 首帧：set_visual（绑定 snapshot/可见性/慢速 overlay 建立）。
    harness._publish_web_live_frame(_TINY_PNG, 100.0, 1000.0,
                                     harness._web_live_snapshot, overlay)
    assert len(overlay.set_visual_calls) == 1
    assert harness._advanced_canvas_source_kind == "web_live"
    assert harness._advanced_cue_pixmap is not None
    # 稳态帧：快速通道（不再 set_visual），字节原样透传给发布线程。
    harness._publish_web_live_frame(_TINY_PNG, 133.0, 1033.0,
                                     harness._web_live_snapshot, overlay)
    assert len(overlay.set_visual_calls) == 1, "steady frames must bypass set_visual"
    assert overlay.fast_calls==[]  # identical pixels do not consume IPC
    from PIL import Image
    from io import BytesIO
    changed=BytesIO();Image.new('RGBA',(2,2),'white').save(changed,format='PNG')
    harness._publish_web_live_frame(changed.getvalue(),166,1066,harness._web_live_snapshot,overlay)
    assert overlay.fast_calls==[changed.getvalue()]
    # 换 cue：下一帧重新走 set_visual（新 snapshot 绑定）。
    harness._web_live_cue_id = "cue-2"
    harness._publish_web_live_frame(_TINY_PNG, 10.0, 2000.0,
                                     harness._web_live_snapshot, overlay)
    assert len(overlay.set_visual_calls) == 2


def test_publish_accepts_legacy_qimage_payload():
    _app()
    overlay = _RecordingOverlay()
    harness = _publish_harness(overlay)
    image = _filled_frame()
    harness._publish_web_live_frame(image, 0.0, 0.0,
                                    harness._web_live_snapshot, overlay)
    assert len(overlay.set_visual_calls) == 1
    pixmap = overlay.set_visual_calls[0][0]
    assert isinstance(pixmap, QPixmap) and not pixmap.isNull()
    # QImage 稳态帧也走快速通道（payload=QImage）。
    harness._publish_web_live_frame(image, 50.0, 50.0,
                                    harness._web_live_snapshot, overlay)
    assert overlay.fast_calls and overlay.fast_calls[0] is image


def test_same_cue_new_clock_or_content_binds_and_stale_frames_stay_rejected():
    from types import SimpleNamespace
    from twobyteasr.rendering.live_web_preview import WebFrame
    _app()
    overlay = _RecordingOverlay()
    harness = _publish_harness(overlay)
    clock = SimpleNamespace(playback_generation=1)
    sessions = []
    harness.video = SimpleNamespace(playback_position_snapshot=lambda: clock,
        begin_web_live_overlays=lambda: sessions.append(clock.playback_generation),_web_live_epoch=1)
    worker = harness._web_live_worker = SimpleNamespace(strip_key='one',_configuration_generation=1)
    frame = WebFrame(_TINY_PNG,id(worker),'one',1,1)
    publish = lambda data: harness._publish_web_live_frame(data,100,600,harness._web_live_snapshot,overlay)
    assert publish(frame)
    overlay.publish_web_frame = lambda data: False
    harness.video._web_live_epoch+=1  # actual removal invalidates the native session
    assert not publish(frame)  # a late same-identity frame cannot reopen removal
    assert len(sessions) == 1
    clock.playback_generation = 2
    assert not publish(frame)  # already queued old seek
    assert publish(WebFrame(_TINY_PNG,id(worker),'one',1,2))
    worker.strip_key = 'two';worker._configuration_generation = 2
    assert publish(WebFrame(_TINY_PNG,id(worker),'two',2,2))
    assert len(overlay.set_visual_calls) == len(sessions) == 3


def test_stop_resets_fast_path_state():
    _app()
    overlay = _RecordingOverlay()
    harness = _publish_harness(overlay)
    harness._publish_web_live_frame(_TINY_PNG, 0.0, 0.0,
                                    harness._web_live_snapshot, overlay)
    assert harness._web_live_published_cue == "cue-1"
    harness._stop_web_live_preview("test")
    assert harness._web_live_published_cue == ""
    assert harness._web_live_snapshot is None
    # 真实重接管路径：新 cue 重新 ensure（snapshot/cue_id 重建）后首帧
    # 必须走 set_visual 绑定新 snapshot。
    harness._web_live_snapshot = _FakeSnapshot("cue-2")
    harness._web_live_cue_id = "cue-2"
    harness._publish_web_live_frame(_TINY_PNG, 0.0, 0.0,
                                    harness._web_live_snapshot, overlay)
    assert len(overlay.set_visual_calls) == 2


def test_exit_removal_closes_session_stragglers_cannot_resurrect():
    """二十八轮回归：清场 REMOVE 后迟到帧不得复活 overlay。

    复活会让 set_native_subtitle_visible(True) 的 150ms 消抖循环无限押后，
    libass 永不恢复——用户实测"特效字幕放完，衔接的下一条普通字幕直接消失"。
    """
    _app()
    canvas = MpvCanvas()
    rect = QRect(0, 0, 1280, 720)

    # 会话关闭：迟到帧拒发。
    canvas.begin_web_live_overlays()
    canvas.stop_web_live_overlays()
    assert canvas.publish_web_live_overlay(
        canvas.ADVANCED_OVERLAY_ID, _TINY_PNG, rect,
    ) is False, "closed session must refuse straggler publishes"

    # REMOVE 成功路径必须关掉会话（清场=会话终点）。
    canvas.begin_web_live_overlays()
    assert canvas._web_live_overlay_active is True
    canvas._active_compositor_overlays.add(canvas.ADVANCED_OVERLAY_ID)
    canvas.remove_compositor_overlay(canvas.ADVANCED_OVERLAY_ID, force=True)
    assert canvas._web_live_overlay_active is False, (
        "successful removal of the advanced overlay must close the web-live session"
    )
    assert canvas.publish_web_live_overlay(
        canvas.ADVANCED_OVERLAY_ID, _TINY_PNG, rect,
    ) is False
