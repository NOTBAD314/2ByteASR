"""2026-09-18 P0/P1 回归防线（截图工程实测族）：

- P1：播放头拖拽/点击把 x 线性外推出视口右缘 → playhead_ms 无上界，
  1.5h 工程被拖到 3h+。所有指针定位入口必须钳到工程时长。
- P0 残余：坏 continuous 代理（336s 塌缩产物）被采用门拒删后，
  sync-map 命中即早退导致永远无人重建；且失败构建要有记忆防循环。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_END_MS = 5_386_572  # 截图工程（1:29:46 的 0 字幕工程）实测时长


# --------------------------------------------------------------- helpers

def _timeline_project(clip_out_ms: int = PROJECT_END_MS):
    from twobyteasr.projects.studio_project import (
        StudioMedia, SubtitleProject, VideoClip, VideoTrack,
    )

    return SubtitleProject(
        media=StudioMedia(path="F:/diag/2026-09-17 玩蓝色星原.flv",
                          duration_ms=PROJECT_END_MS),
        speakers=[],
        cues=[],
        video_tracks=[VideoTrack(
            id="v1", name="V1",
            clips=[VideoClip(
                id="c1", asset_id="a1",
                source_out_ms=clip_out_ms,
                timeline_out_ms=clip_out_ms,
            )],
        )],
    )


def _make_timeline(clip_out_ms: int = PROJECT_END_MS):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio.studio_ui import WaveformTimeline

    app = QApplication.instance() or QApplication([])
    timeline = WaveformTimeline()
    timeline.resize(1200, 320)
    timeline.set_project(_timeline_project(clip_out_ms))
    timeline.set_visible_window(0, 60_000)
    app.processEvents()
    return timeline, app, (QEvent, QPointF, Qt, QMouseEvent)


def _mouse(timeline, parts, kind, x: float, y: float, *, button, buttons):
    QEvent, QPointF, Qt, QMouseEvent = parts
    event = QMouseEvent(
        kind, QPointF(x, y), QPointF(x, y),
        button, buttons, Qt.KeyboardModifier.NoModifier,
    )
    if kind == QEvent.Type.MouseButtonPress:
        timeline.mousePressEvent(event)
    elif kind == QEvent.Type.MouseMove:
        timeline.mouseMoveEvent(event)
    else:
        timeline.mouseReleaseEvent(event)


# ------------------------------------------------- P1: playhead bounds

def test_scrub_beyond_right_edge_clamps_to_project_end():
    """拖到视口右缘之外（一次宽甩=+N 小时）必须钳到工程时长。"""
    timeline, app, parts = _make_timeline()
    seeks: list[float] = []
    timeline.seek_requested.connect(lambda s: seeks.append(s))
    try:
        QEvent, QPointF, Qt, QMouseEvent = parts
        ruler_y = max(2, timeline.RULER_HEIGHT // 2)
        x_inside = timeline.TRACK_HEADER_WIDTH + 100
        far_x = timeline.width() * 40  # 视口右缘之外几十屏
        _mouse(timeline, parts, QEvent.Type.MouseButtonPress, x_inside, ruler_y,
               button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton)
        _mouse(timeline, parts, QEvent.Type.MouseMove, far_x, ruler_y,
               button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton)
        app.processEvents()
        assert 0 <= timeline.playhead_ms <= PROJECT_END_MS, timeline.playhead_ms
        assert seeks and all(0.0 <= s * 1000.0 <= PROJECT_END_MS for s in seeks), seeks
        # 释放：scrub_finished 也必须在边界内
        finished: list[float] = []
        timeline.scrub_finished.connect(lambda s: finished.append(s))
        _mouse(timeline, parts, QEvent.Type.MouseButtonRelease, far_x, ruler_y,
               button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.NoButton)
        app.processEvents()
        assert finished and finished[-1] * 1000.0 <= PROJECT_END_MS, finished
        assert timeline.playhead_ms <= PROJECT_END_MS
    finally:
        timeline.deleteLater()
        app.processEvents()


def test_ruler_click_far_right_clamps():
    """标尺点击（pan 后单击/选框单击路径）同样必须有上界。"""
    timeline, app, parts = _make_timeline()
    try:
        raw = timeline._x_to_time(timeline.width() * 200)
        assert raw > PROJECT_END_MS * 2, raw
        bounded = timeline._bounded_time_ms(raw)
        assert bounded == PROJECT_END_MS, bounded
        assert timeline._bounded_time_ms(-5) == 0
        # paint 路径（解码观测）也走同一上界
        timeline._paint_playhead_at(raw)
        assert timeline.playhead_ms == PROJECT_END_MS, timeline.playhead_ms
    finally:
        timeline.deleteLater()
        app.processEvents()


def test_later_clip_extends_bounds():
    """合法的更晚内容（片段超出主轨媒体时长）必须能延长边界，不被媒体时长硬钳。"""
    later_end = PROJECT_END_MS * 2
    timeline, app, _parts = _make_timeline(clip_out_ms=later_end)
    try:
        target = int(PROJECT_END_MS * 1.5)
        assert timeline._duration_ms() >= later_end
        assert timeline._bounded_time_ms(target) == target
        timeline._paint_playhead_at(target)
        assert timeline.playhead_ms == target, timeline.playhead_ms
    finally:
        timeline.deleteLater()
        app.processEvents()


# ------------------------------- P0 residual: proxy rebuild after rejection

def _proxy_cache_env(monkeypatch, tmp_path: Path):
    from twobyteasr.playback import avsync
    from twobyteasr.media import indexed_media
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap, save_sync_map

    cache = indexed_media.IndexedMediaCache(root=tmp_path / "seek")
    src = tmp_path / "a.flv"
    src.write_bytes(b"")
    opt_dir = tmp_path / "seek" / "v2" / "key1"
    opt_dir.mkdir(parents=True)
    opt = opt_dir / "optimized.mp4"
    opt.write_bytes(b"opt")
    save_sync_map(opt_dir, AVSyncMap(
        [TimestampGap(766_101, 771_136, 5_035, video=True, audio=True)],
        source_duration_ms=5_386_570,
    ))
    bad = opt_dir / "continuous.mkv"
    bad.write_bytes(b"collapsed-336s-artifact")
    cache._ready[str(src)] = str(opt)
    # 绕过 remux：假 .flv 不进 prepare 队列
    monkeypatch.setattr(cache, "resolve", lambda source: str(src))
    return cache, src, opt_dir, avsync


def _wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_bad_proxy_rejected_deleted_and_rebuilt(tmp_path, monkeypatch):
    """采用门拒删坏产物后必须重排重建；新产物带 v2 标记方可投用。"""
    cache, src, opt_dir, avsync = _proxy_cache_env(monkeypatch, tmp_path)

    state = {"validate": 0, "builds": 0}

    def fake_validate(cache_dir, ffprobe, *, expected_duration_ms):
        state["validate"] += 1
        if state["validate"] == 1:
            # 首次=采用门：336s 塌缩产物（截图工程实测值）
            return False, f"duration_mismatch 336362 vs {expected_duration_ms}"
        return True, "ok"

    def fake_build(source, sync_map, target, **kwargs):
        state["builds"] += 1
        Path(target).write_bytes(b"rebuilt-good-proxy")
        return Path(target)

    monkeypatch.setattr(avsync, "validate_continuous_proxy", fake_validate)
    monkeypatch.setattr(avsync, "build_continuous_proxy", fake_build)

    path, kind = cache.playback_source(str(src))
    assert kind == "optimized" and Path(path) == Path(cache._ready[str(src)])

    assert _wait_until(lambda: (opt_dir / "continuous.json").is_file()), \
        "rejected proxy was never rebuilt"
    assert state["builds"] == 1, state
    # 现存的必须是重建产物（坏产物已被采用门删除，重建线程即刻补位）
    assert (opt_dir / "continuous.mkv").read_bytes() == b"rebuilt-good-proxy"
    path, kind = cache.playback_source(str(src))
    assert kind == "proxy" and Path(path) == opt_dir / "continuous.mkv"


def test_failing_proxy_build_memorized_no_retry_loop(tmp_path, monkeypatch):
    """构建反复不过时长门的源：一次会话只试一次，绝不无限重建。"""
    cache, src, opt_dir, avsync = _proxy_cache_env(monkeypatch, tmp_path)

    state = {"validate": 0, "builds": 0}

    def always_fail_validate(cache_dir, ffprobe, *, expected_duration_ms):
        state["validate"] += 1
        return False, "duration_mismatch always"

    def fake_build(source, sync_map, target, **kwargs):
        state["builds"] += 1
        Path(target).write_bytes(b"still-bad")
        return Path(target)

    monkeypatch.setattr(avsync, "validate_continuous_proxy", always_fail_validate)
    monkeypatch.setattr(avsync, "build_continuous_proxy", fake_build)

    for _ in range(3):
        cache.playback_source(str(src))
        cache.sync_map(str(src))
    assert _wait_until(lambda: state["builds"] >= 1), state
    assert _wait_until(
        lambda: str(src) in cache._proxy_failures or state["builds"] >= 1
    )
    time.sleep(0.3)
    builds_after_first = state["builds"]
    for _ in range(4):
        cache.playback_source(str(src))
        cache.sync_map(str(src))
        time.sleep(0.05)
    assert state["builds"] == builds_after_first == 1, state
    assert str(src) in cache._proxy_failures
    # 失败后的稳态：optimized 回退，不复活已删产物
    path, kind = cache.playback_source(str(src))
    assert kind == "optimized"
    assert not (opt_dir / "continuous.mkv").exists()
