"""波形跨缩放一致性回归（2026-09-18 VIII）。

两类历史缺陷：
1. 逐视图 AGC（gain=0.72/可见峰值）把纵向标尺绑在缩放上——缩小视图必含
   全局峰值→普通语音≈1px“像静音”，放大安静段又放大 4 倍。修复=绝对
   dBFS 标尺（``waveform_db_heights``），同一振幅在任何缩放下同一视觉强度。
2. ``choose_level`` 的 covers() 用容器时长做窗口终点、slack 上限 50ms——
   音频流比容器早结束时，整段视图永远判不覆盖、永久跌回 56s/桶的稀疏
   outline 级（每 56s 仅 0.5s 真实采样→插值≈平线）。修复=请求终点钳到
   音频实际覆盖 + slack=整桶宽。
"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_db_heights_absolute_scale():
    from twobyteasr.studio.studio_timeline import waveform_db_heights

    heights = waveform_db_heights(np.array([0.0, 1.0, 0.5, 0.1, 0.004, 0.001], dtype="float32"))
    assert heights[0] == 0.0  # 数字静音=平线
    assert heights[1] == pytest.approx(1.0)  # 0 dBFS 满幅
    assert heights[2] == pytest.approx((48.0 - 20.0 * np.log10(2.0)) / 48.0)  # -6dB
    assert heights[3] == pytest.approx((48.0 - 20.0) / 48.0)  # -20dB 弱语音仍清晰
    assert heights[4] == pytest.approx(0.0, abs=1e-3)  # 低于显示下限
    assert heights[5] == 0.0
    # 单调：更大的振幅永不更矮
    ramps = waveform_db_heights(np.linspace(0.001, 1.0, 64))
    assert (np.diff(ramps) > -1e-9).all()


class _FakeCache:
    """窗口相关的桩：缩小视图返回含全局峰值的长窗，放大视图只返回安静段。"""

    def __init__(self, loud_pairs, quiet_pairs, level_ms):
        self._loud = loud_pairs
        self._quiet = quiet_pairs
        self._level_ms = level_ms
        self.calls = []

    def read_window(self, start_ms, end_ms, pixel_width):
        from twobyteasr.playback.waveform_cache import WaveformLevel

        self.calls.append((start_ms, end_ms, pixel_width))
        wide = (end_ms - start_ms) > 20000
        level = WaveformLevel(2, 128, float(self._level_ms), "fixture")
        return level, (self._loud if wide else self._quiet)


def _path_points(path):
    points = []
    for index in range(path.elementCount()):
        element = path.elementAt(index)
        points.append((element.x, element.y))
    return points


def test_same_amplitude_same_visual_strength_across_zoom():
    _app()
    from twobyteasr.studio.studio_timeline import WaveformTimeline, waveform_db_heights

    quiet = np.full((80, 2), 0.1, dtype="float32")
    loud = quiet.copy()
    loud[40] = (0.0, 1.0)  # 全局峰值只出现在缩小视图里
    cache = _FakeCache(loud, quiet[:20].copy(), level_ms=1000)
    timeline = WaveformTimeline()
    try:
        rect = QRectF(0, 100, 800, 28)
        amplitude = rect.height() * 0.36
        center_y = rect.center().y()  # envelope 返回前已 translate 到轨中心
        zoomed_out = timeline._waveform_envelope(cache, 0, 100000, 800, 0, 800, rect)
        zoomed_in = timeline._waveform_envelope(cache, 40000, 50000, 800, 0, 800, rect)
        quiet_height = float(waveform_db_heights(np.array([0.1], dtype="float32"))[0])
        out_points = [(x, y - center_y) for x, y in _path_points(zoomed_out)]
        in_points = [(x, y - center_y) for x, y in _path_points(zoomed_in)]
        # 全局峰值在缩小视图触满幅（不再被压扁）。
        assert min(y for _, y in out_points) == pytest.approx(-amplitude, abs=1e-6)
        # 同一 0.1 振幅的桶在两种缩放下高度一致（旧 AGC 会差 ~5.5 倍）。
        out_quiet = min(y for _, y in out_points if y > -amplitude + 1e-6)
        in_min = min(y for _, y in in_points)
        assert out_quiet == pytest.approx(-quiet_height * amplitude, abs=1e-6)
        assert in_min == pytest.approx(-quiet_height * amplitude, abs=1e-6)
    finally:
        timeline.close()


def test_partial_prefix_keeps_time_positions():
    _app()
    from twobyteasr.studio.studio_timeline import WaveformTimeline

    # 覆盖中：100s 窗只解码出前 10s（10 个 1s 桶）。
    pairs = np.full((10, 2), 0.2, dtype="float32")
    cache = _FakeCache(pairs, pairs, level_ms=1000)
    timeline = WaveformTimeline()
    try:
        rect = QRectF(0, 0, 800, 28)
        path = timeline._waveform_envelope(cache, 0, 100000, 800, 0, 800, rect)
        # 10 个桶按时间只占前 10%（末点 x=9*8=72；旧逻辑会把前缀拉伸铺满
        # 整个 clip 宽到 800）。
        assert path.boundingRect().right() == pytest.approx(72.0, abs=2.0)
        assert path.boundingRect().right() < 120
    finally:
        timeline.close()


def _synthetic_cache(tmp_path, lod0_frames, duration_ms=100000, incomplete=False):
    from twobyteasr.playback.waveform_cache import WaveformCache

    root = tmp_path / "wc"
    root.mkdir(parents=True)
    levels = []
    np.zeros((lod0_frames, 2), dtype="float32").tofile(root / "lod0.f32")
    levels.append(
        dict(level=0, frames=lod0_frames, milliseconds_per_frame=16.0, file="lod0.f32")
    )
    np.zeros((2, 2), dtype="float32").tofile(root / "outline.f32")
    levels.append(dict(level=8, frames=2, milliseconds_per_frame=50000.0, file="outline.f32"))
    payload = dict(
        schema_version=1,
        source_path="x.flv",
        source_size=1,
        source_mtime_ns=1,
        sample_rate=16000,
        window_samples=256,
        duration_ms=duration_ms,
        coverage_end_ms=int(lod0_frames * 16),
        levels=levels,
    )
    if incomplete:
        payload["incomplete"] = True
    (root / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    return WaveformCache(root)


def test_choose_level_not_demoted_to_outline_when_audio_shorter_than_container(tmp_path):
    # lod0 覆盖 99.2s，容器 100s：整段窗口（终点=容器时长）应选真实 lod0，
    # 而不是永久跌回 2 桶的 outline（旧 slack=50ms 的行为）。
    cache = _synthetic_cache(tmp_path, lod0_frames=6200, duration_ms=100000)
    level = cache.choose_level(0, 100000, 800)
    assert level.file == "lod0.f32"


def test_choose_level_outline_fallback_while_filling(tmp_path):
    # 增量解码进行中（incomplete，lod0 只覆盖 16s）：整段窗口仍回退
    # outline 预览，该设计行为保留（部分覆盖时先显示全时长剪影）。
    cache = _synthetic_cache(tmp_path, lod0_frames=1000, duration_ms=100000, incomplete=True)
    level = cache.choose_level(0, 100000, 800)
    assert level.file == "outline.f32"
    # 同样的覆盖但缓存已完成：终点钳到音频覆盖，回到真实 lod0。
    complete = _synthetic_cache(tmp_path / "complete", lod0_frames=1000, duration_ms=100000)
    assert complete.choose_level(0, 100000, 800).file == "lod0.f32"
