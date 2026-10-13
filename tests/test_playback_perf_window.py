"""[PlaybackPerf] 窗口增量 + 心跳降采样（2026-09-18 D1/D2）。"""

import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_video_canvas import MpvCanvas


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _FakeController:
    def __init__(self, values):
        self.values = values

    def observed_property(self, name, default=None):
        return self.values.get(name, default)


class _FakePage:
    def __init__(self):
        self.events = []

    def _studio_trace(self, event, **fields):
        self.events.append((event, fields))

    def perf(self, name):
        return [fields for event, fields in self.events if event == name]


def _prime(canvas, controller, page):
    canvas.controller = controller
    canvas._studio_page = lambda: page
    canvas._track_playback_perf(paused=False)
    return canvas._perf_counters


def test_playback_perf_emits_window_deltas_and_na(qapp):
    canvas = MpvCanvas()
    page = _FakePage()
    controller = _FakeController({
        "decoder-frame-drop-count": 5,
        "frame-drop-count": 3,
        "vo-delayed-frame-count": 2,
        "mistimed-frame-count": None,  # 该上下文不可用 → N/A
        "estimated-vf-fps": 29.97,
    })
    try:
        counters = _prime(canvas, controller, page)
        counters["seek_requests"].append(time.monotonic())
        canvas._emit_playback_perf()
        rows = page.perf("PlaybackPerf")
        assert len(rows) == 1
        first = rows[0]
        assert first["decoder_dropped_10s"] == 5
        assert first["vo_dropped_10s"] == 3
        assert first["vo_delayed_10s"] == 2
        assert first["mistimed_10s"] == "N/A"
        assert first["estimated_vf_fps"] == 29.97
        assert first["seek_requests_10s"] == 1
        assert first["playing"] is True

        # 第二窗：累计计数推进 → 窗口增量
        controller.values.update({
            "decoder-frame-drop-count": 9, "frame-drop-count": 3, "vo-delayed-frame-count": 5,
        })
        for _ in range(3):
            counters["seek_requests"].append(time.monotonic())
        canvas._emit_playback_perf()
        second = page.perf("PlaybackPerf")[1]
        assert second["decoder_dropped_10s"] == 4
        assert second["vo_dropped_10s"] == 0
        assert second["vo_delayed_10s"] == 3
        assert second["seek_requests_10s"] == 3

        # 换源重载：mpv 计数归零（当前值 < 上窗值）→ 增量从当前值重算
        controller.values.update({"decoder-frame-drop-count": 1})
        counters["seek_requests"] = []
        canvas._emit_playback_perf()
        third = page.perf("PlaybackPerf")[2]
        assert third["decoder_dropped_10s"] == 1
        assert third["seek_requests_10s"] == 0
    finally:
        canvas._perf_timer.stop()
        canvas.deleteLater()


def test_playback_perf_missing_controller_properties_are_na(qapp):
    canvas = MpvCanvas()
    page = _FakePage()
    try:
        _prime(canvas, _FakeController({}), page)
        canvas._emit_playback_perf()
        row = page.perf("PlaybackPerf")[0]
        assert row["decoder_dropped_10s"] == "N/A"
        assert row["vo_dropped_10s"] == "N/A"
        assert row["estimated_vf_fps"] == "N/A"
    finally:
        canvas._perf_timer.stop()
        canvas.deleteLater()


def _adopt(canvas, position_ms, *, source, paused=True, rate=1.0):
    canvas._adopt_playback_snapshot(SimpleNamespace(
        presentation_media_ms=position_ms, paused=paused, seeking=False,
        playback_rate=rate, source=source,
    ))


def test_media_clock_heartbeat_downsampled_but_semantic_changes_logged(qapp):
    canvas = MpvCanvas()
    page = _FakePage()
    canvas._studio_page = lambda: page
    try:
        # 暂停态连拍心跳：位置不变、状态不变 → 只有首拍落盘
        for index in range(8):
            _adopt(canvas, 1000.0 + index * 0.0, source="heartbeat", paused=True)
        assert len(page.perf("MEDIA_CLOCK_POSITION")) == 1

        # 非心跳来源（seek/observe）不受门控
        _adopt(canvas, 2000.0, source="user_seek", paused=True)
        assert len(page.perf("MEDIA_CLOCK_POSITION")) == 2

        # 门控期内心跳仍被抑制
        _adopt(canvas, 2000.0, source="heartbeat", paused=True)
        assert len(page.perf("MEDIA_CLOCK_POSITION")) == 2

        # 暂停状态变化 → 立即落盘
        _adopt(canvas, 2000.0, source="heartbeat", paused=False)
        assert len(page.perf("MEDIA_CLOCK_POSITION")) == 3

        # 媒体源（代理换绑）→ 立即落盘
        canvas._media_path = r"X:\continuous.mkv"
        _adopt(canvas, 2000.0, source="heartbeat", paused=False)
        assert len(page.perf("MEDIA_CLOCK_POSITION")) == 4
    finally:
        canvas.deleteLater()


def test_steady_playback_ticks_write_one_record_per_second(qapp):
    """2026-10-11: playing logged ~70 MEDIA_CLOCK_POSITION + POSITION_MUTATION
    + MEDIA_CLOCK_OWNER records a second; studio-open.log reached 1.27 GB."""
    canvas = MpvCanvas()
    page = _FakePage()
    canvas._studio_page = lambda: page
    try:
        _adopt(canvas, 1000.0, source="user_seek", paused=False)
        for index in range(1, 31):  # ~0.5 s of 60 Hz ticks
            _adopt(canvas, 1000.0 + index * 16.7, source="visual_tick", paused=False)
        assert len(page.perf("MEDIA_CLOCK_POSITION")) <= 2
        assert len(page.perf("POSITION_MUTATION")) <= 2
        # The loop detector still sees every step.
        assert len(canvas._position_trace_samples) >= 30
        # A seek and a pause are logged at once.
        _adopt(canvas, 9000.0, source="user_seek", paused=False)
        assert page.perf("MEDIA_CLOCK_POSITION")[-1]["position_ms"] == 9000.0
        assert page.perf("POSITION_MUTATION")[-1]["source"] == "USER_SEEK"
        _adopt(canvas, 9016.7, source="visual_tick", paused=True)
        assert page.perf("MEDIA_CLOCK_POSITION")[-1]["position_ms"] == 9016.7
    finally:
        canvas.deleteLater()
