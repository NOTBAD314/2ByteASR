# Legacy Qt decoder comparison tests; process backend contracts live in test_video_decode_pipe.py.
"""Round 52：clip 尾部残留根治、返回主页拆卸顺序、转换限速的回归。"""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat
from PySide6.QtWidgets import QApplication

from twobyteasr.playback.secondary_video_legacy import SecondaryVideoSource, _DecoderWorker
from twobyteasr.timeline.studio_media_pool import (
    add_media_asset,
    add_video_clip,
    create_video_track,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _tail_project(tmp_path: Path) -> SubtitleProject:
    """V1 主轨到 40s；V2 叠加片段 30~50s——graph 尾部由 V2 决定。"""

    v1 = tmp_path / "v1.mp4"
    v2 = tmp_path / "v2.mp4"
    v1.write_bytes(b"v1")
    v2.write_bytes(b"v2")
    project = SubtitleProject(
        media=StudioMedia(path=str(v1), duration_ms=40_000, width=1920, height=1080),
        cues=[StudioCue("c1", 0, 1_000, "cue")],
    )
    project.validate()
    project.video_tracks[0].locked = False
    asset = add_media_asset(project, v2, fingerprint="v2", duration_ms=90_000)
    track = create_video_track(project)
    add_video_clip(
        project, track.id, asset.asset_id,
        timeline_in_ms=30_000, source_in_ms=0, source_out_ms=20_000,
    )
    # 关联音频轨（A2）会让 target 落到 audio-only 分支；本测试聚焦视频轨尾部。
    for audio_track in project.audio_tracks:
        audio_track.enabled = False
    project.validate()
    return project


def test_tail_keep_resyncs_compositor_once_after_last_clip_ends(tmp_path):
    """播放头越过 graph 尾部（最尾 clip 的 end）后合成器必须被 resync——
    否则 mpv 里最后发布的 VIDEO_OVERLAY 位图（已结束叠加轨的最后一帧）
    永久残留（用户实录 V3 播完画面钉死，跳转几次才消失）。"""

    _app()
    project = _tail_project(tmp_path)
    page = SubtitleStudioPage()
    page.project = project

    class Controller:
        running = True

        def post_load_at(self, path, seconds, *, generation):
            return True

        def post_seek(self, seconds, **kwargs):
            return True

        def post_set_paused(self, paused):
            return True

    page.video.controller = Controller()
    page.video._media_path = project.media.path
    page.video._media_attached = True
    page.video._paused = True
    page._apply_active_video_track_volume = lambda _track_id: None
    calls: list[int] = []
    page._sync_video_compositor = lambda timeline_ms: calls.append(int(timeline_ms))  # type: ignore[method-assign]
    try:
        # 播放头处于 V1+V2 重叠段：正常路径 resync（叠加层在列、标志复位）。
        assert page._activate_multitrack_preview(35_000) is not None
        assert calls and calls[-1] == 35_000
        assert page._composition_keep_resynced is False

        # 播放头越过 graph 尾部（=V2 clip end 50s，V1 40s 已结束）：tail keep
        # 早退，但合成器必须仍被 resync 一次（层列表已空 → 叠加层退役）。
        calls.clear()
        assert page._activate_multitrack_preview(50_050) is None
        assert calls == [50_050], "keep-mpv 早退路径必须补一次合成器 resync"
        assert page._composition_keep_resynced is True

        # 尾部停留期间按 tick 去重：不重复 resync。
        page._activate_multitrack_preview(51_000)
        assert calls == [50_050]

        # 回到片段范围内：标志复位，正常路径恢复 resync。
        assert page._activate_multitrack_preview(35_000) is not None
        assert calls[-1] == 35_000
        assert page._composition_keep_resynced is False
    finally:
        page.close_page()
        page.deleteLater()


def test_release_drains_converter_before_unloading_session(tmp_path):
    """release() 顺序契约：先停路由→丢队列→join 转换线程，最后才能
    worker.shutdown()（卸载 WMF 会话）。转换在途时卸会话 = 会话析构与
    GIL 编组互等 = 返回主页偶发卡死（2026-09-07）。"""

    _app()
    source = tmp_path / "v2.mp4"
    source.write_bytes(b"v2")
    runtime = SecondaryVideoSource()
    runtime.prepare(str(source))
    assert runtime._started

    order: list[str] = []
    worker = runtime._worker
    converter_thread = runtime._convert_thread
    assert worker is not None
    if converter_thread is None:
        # 环境强制 inline 时无转换线程——顺序契约退化为只验 shutdown 可达。
        worker_shutdown = worker.shutdown

        def shutdown() -> None:
            order.append("shutdown")
            worker_shutdown()

        worker.shutdown = shutdown  # type: ignore[method-assign]
        runtime.release()
        assert order == ["shutdown"]
        return

    original_quit = converter_thread.quit
    original_wait = converter_thread.wait

    def quit() -> None:
        order.append("converter_quit")
        original_quit()

    def wait(ms: int = 0) -> bool:
        order.append(f"converter_wait:{int(ms)}")
        return original_wait(ms)

    worker_shutdown = worker.shutdown

    def shutdown() -> None:
        order.append("shutdown")
        worker_shutdown()

    converter_thread.quit = quit  # type: ignore[method-assign]
    converter_thread.wait = wait  # type: ignore[method-assign]
    worker.shutdown = shutdown  # type: ignore[method-assign]
    try:
        runtime.release()
    finally:
        runtime.thread_stopped = True
    assert order[:2] == ["converter_quit", "converter_wait:1000"], order
    assert order[2] == "shutdown", order


class _CountingWorker(_DecoderWorker):
    def __init__(self) -> None:
        super().__init__()
        self.converted = 0

    def _on_converted_frame(self, *args) -> None:
        self.converted += 1
        super()._on_converted_frame(*args)


def _fake_frame() -> QVideoFrame:
    return QVideoFrame(
        QVideoFrameFormat(QSize(64, 48), QVideoFrameFormat.Format_RGBX8888)
    )


def test_playback_conversion_is_rate_limited_to_display_rate():
    """播放态下帧供给高于显示速率时，超出部分在 toImage 转换前丢弃；
    暂停态（seek 收敛）不受限——需要精确帧。"""

    _app()
    worker = _CountingWorker()
    worker._wanted_ms = 1_000
    worker._last_paused = False  # playing
    worker._last_convert_ts = 0.0
    for _ in range(20):
        worker._on_frame(_fake_frame())
    assert worker.converted == 1, "同一间隔窗内的突发帧只应转换第一帧"

    # 窗口滑出后恢复转换。
    worker._last_convert_ts = perf_counter() - 1.0
    worker._on_frame(_fake_frame())
    assert worker.converted == 2

    # 暂停态：每帧都要转换（seek 收敛链）。
    worker._last_paused = True
    worker._held_pts_ms = None
    for _ in range(5):
        worker._on_frame(_fake_frame())
    assert worker.converted == 7
