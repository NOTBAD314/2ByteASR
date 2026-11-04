"""2026-09-18 P0 8x 回归防线：time_base rescale / 8x 时长塌缩 / 双映射 /
seek 回零 / 换绑速度迁移。"""
from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"


def run_ffmpeg(*args: str) -> None:
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True)


def duration_of(path: Path) -> float:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


# ------------------------------------------------- Test 1: time_base rescale

def test_proxy_rescale_survives_time_base_mismatch(tmp_path):
    """输入/输出 time_base 不同（制造 1/1000 与 1/90000 档）折叠后时长不变。"""
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap, build_continuous_proxy

    src = tmp_path / "holed.mkv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
        "-filter_complex",
        "[0:v]split=2[vA][vB];[1:a]asplit=2[aA][aB];"
        "[vA]trim=0:5,setpts=PTS-STARTPTS[v1];"
        "[aA]atrim=0:5,asetpts=PTS-STARTPTS[a1];"
        "[vB]trim=start=5,setpts=PTS-STARTPTS+2/TB[v2];"
        "[aB]atrim=start=5,asetpts=PTS-STARTPTS+2/TB[a2];"
        "[v1][v2]concat=n=2:v=1:a=0[v];[a1][a2]concat=n=2:v=0:a=1[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src),
    )
    gaps = [TimestampGap(5_000, 7_000, 2000, video=True, audio=True)]
    sync_map = AVSyncMap(gaps, source_duration_ms=int(duration_of(src) * 1000))
    source_duration = duration_of(src)
    proxy = build_continuous_proxy(src, sync_map, tmp_path / "p.mkv")
    assert abs(duration_of(proxy) - (source_duration - 2.0)) < 0.4, (
        duration_of(proxy), source_duration
    )
    # 抽样帧时间：30fps 下第 150 帧=洞前 5s 不动；洞后帧整体前移 2s。
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-select_streams", "v",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(proxy)],
        capture_output=True, text=True, check=True,
    )
    pts = [float(x) for x in out.stdout.split() if x.strip()]
    assert abs(pts[150] - 5.0) < 0.2, pts[150]
    post_hole = [p for p in pts if p > 5.5]
    assert post_hole and abs((post_hole[0] - 5.0) - 0.0) < 1.5, post_hole[:2]


# ------------------------------------------------- Test 2: 8x regression guard

def test_duration_ratio_gate_rejects_collapsed_proxy(tmp_path):
    """时长塌缩（8x=0.125 比例）的代理必须被采用门拒绝。"""
    from twobyteasr.playback.avsync import validate_continuous_proxy

    collapsed = tmp_path / "continuous.mkv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
        "-c:a", "aac", str(collapsed),
    )
    ok, reason = validate_continuous_proxy(
        tmp_path, FFPROBE, expected_duration_ms=80_000
    )
    assert not ok and "duration_mismatch" in reason, reason


# ------------------------------------------------------ Test 3: double mapping

def test_content_domain_media_bypasses_gap_map(tmp_path):
    """§6：PROJECT 域媒体（proxy）绝不再过 source↔content 转换。"""
    from PySide6.QtWidgets import QApplication
    from tests.test_round42_studio_recognition import _page
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap
    from twobyteasr.media import indexed_media as indexed_media_module

    app = QApplication.instance() or QApplication([])
    monkeypatch = _Monkey()
    page = _page(monkeypatch, tmp_path)
    try:
        page.project.media.path = str(tmp_path / "long.flv")
        gappy = AVSyncMap(
            [TimestampGap(2_000, 4_000, 2000, video=True, audio=True)],
            source_duration_ms=60_000,
        )
        proxy = tmp_path / "continuous.mkv"
        proxy.write_bytes(b"x")
        monkeypatch.setattr(indexed_media_module.GLOBAL_INDEXED_MEDIA,
                            "sync_map", lambda source: gappy)
        monkeypatch.setattr(indexed_media_module.GLOBAL_INDEXED_MEDIA,
                            "playback_source", lambda source: (proxy, "proxy"))
        page.project.media.duration_ms = 60_000
        page._maybe_apply_av_sync_map()
        assert page.video._playback_time_domain == "content"
        # 洞映射已折叠：seek/观测恒等
        assert page.video._content_to_source_seconds(10_000) == 10_000
        assert page.video._source_to_content_ms(10_000) == 10_000
        # 源域路径重新绑定时恢复映射
        monkeypatch.setattr(indexed_media_module.GLOBAL_INDEXED_MEDIA,
                            "playback_source", lambda source: (None, "original"))
        page._maybe_apply_av_sync_map()
        assert page.video._playback_time_domain == "source"
        assert page.video._content_to_source_seconds(5.0) == 7.0
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()


class _Monkey:
    def __init__(self):
        self._env = {}

    def setenv(self, key, value):
        os.environ[key] = value

    def setattr(self, target, name, value):
        setattr(target, name, value)


# --------------------------------------------------- Test 4: seek never zero

def test_seek_invalid_mapping_never_falls_back_to_zero(tmp_path):
    from PySide6.QtWidgets import QApplication
    from tests.test_round42_studio_recognition import _page
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap

    app = QApplication.instance() or QApplication([])
    page = _page(_Monkey(), tmp_path)
    try:
        page.video._av_sync_map = AVSyncMap(
            [TimestampGap(2_000, 4_000, 2000, video=True, audio=True)]
        )
        stub = _ControllerStub()
        page.video.controller = stub
        page.video._duration = 60.0
        # NaN 映射 → 阻断，绝不 seek(0)
        page.video.seek(float("nan"))
        assert stub.seeks == [], stub.seeks
        assert stub.paused is True
        stub.paused = False
        # 巨大 project 目标映射溢出（>duration）→ 钳到 duration 而非 0
        page.video.seek(59.999)
        assert stub.seeks and stub.seeks[-1] > 50_000, stub.seeks
        stub.paused = False
        page.video.seek(30.0)
        assert abs(stub.seeks[-1] - 32_000) < 5, stub.seeks  # 30s 内容 + 2s 洞
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()


class _ControllerStub:
    def __init__(self):
        self.seeks: list[float] = []
        self.paused = False
        self.running = True

    def seek(self, seconds, accurate=True):
        self.seeks.append(seconds * 1000.0)

    def set_paused(self, value):
        self.paused = bool(value)


# ------------------------------------------- Test 5: rebind migrates speed

def test_rebind_resyncs_stale_controller_speed(tmp_path):
    from PySide6.QtWidgets import QApplication
    from tests.test_round42_studio_recognition import _page

    app = QApplication.instance() or QApplication([])
    page = _page(_Monkey(), tmp_path)
    try:
        stub = _ControllerStub()
        stub.speed = 2.0  # 识别前观看用的 2x 残留在跨 reload 存活的控制器上
        page.video.controller = stub
        page.video._playback_rate = 1.0  # 重载后传输层 1x
        posted = page.video.switch_media_at_async(
            str(tmp_path / "proxy.mkv"), "",
            source_seconds=10.0, project_ms=10_000,
        )
        assert posted
        assert stub.speeds_applied == [1.0], stub.speeds_applied
    finally:
        page.close_page()
        page.deleteLater()
        app.processEvents()


def _extend_stub():
    _ControllerStub.speeds_applied = []
    _ControllerStub.speed = 1.0

    def post_set_speed(self, value):
        self.speed = float(value)
        self.speeds_applied.append(float(value))
        return True

    def post_load_at(self, path, seconds, *, generation):
        self.loaded_at = (str(path), float(seconds))
        return True

    _ControllerStub.post_set_speed = post_set_speed
    _ControllerStub.post_load_at = post_load_at


_extend_stub()
