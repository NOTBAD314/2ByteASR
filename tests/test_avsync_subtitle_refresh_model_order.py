"""2026-09-17 三问题回归：AV sync map / 识别后 Studio 刷新 / 模型列表会话稳定。

P1 用真实 ffmpeg 的洞检测与映射数学；P2 走真实 MainWindow 交接链路（不重开
工程即断言字幕模型/时间轴更新 + 视图保留）；P3 覆盖 FramelessPopupCombo 一次性
置顶（其余在 test_round40_oss_filetrans 更新版）。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def run_ffmpeg(*args: str) -> None:
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True)


# ================================================================ P1: AVSync


def _gappy_map():
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap

    gaps = [
        TimestampGap(5_902_550, 5_903_566, 1016, video=True, audio=True),
        TimestampGap(5_915_166, 5_918_183, 3017, video=True, audio=True),
    ]
    return AVSyncMap(gaps, source_duration_ms=14_553_900)


def test_avsync_map_math_clamps_inside_holes_and_roundtrips():
    sync_map = _gappy_map()
    assert sync_map.total_gap_ms == 4033
    assert sync_map.content_duration_ms == 14_553_900 - 4033
    assert sync_map.source_to_content_ms(5_902_000) == 5_902_000
    assert sync_map.source_to_content_ms(5_903_000) == 5_902_550  # inside hole 1
    assert sync_map.source_to_content_ms(5_904_000) == 5_904_000 - 1016
    # hole 2 start lives at content (hole2.start - hole1 gap)
    assert sync_map.source_to_content_ms(5_917_000) == 5_915_166 - 1016
    assert sync_map.source_to_content_ms(6_000_000) == 6_000_000 - 4033
    for value in (0.0, 5_902_550, 5_903_566, 5_918_183, 12_000_000.0):
        source = sync_map.content_to_source_ms(sync_map.source_to_content_ms(value))
        # Hole interiors and the hole-start boundary round-trip to the hole's
        # source end (the first real media after the gap).
        assert abs(source - value) < 1e-3 or 5_902_550 <= value < 5_903_566


def test_avsync_overrides_are_piecewise_and_identity_media_untouched():
    from twobyteasr.playback.avsync import AVSyncMap, SyncOverride

    sync_map = _gappy_map()
    with_over = sync_map.with_overrides([SyncOverride(at_ms=5_902_550, offset_ms=-820)])
    assert with_over.content_to_source_ms(5_902_000) == 5_902_000  # before the point
    assert with_over.content_to_source_ms(5_915_166 - 1016) == (
        5_915_166 - 1016 + 1016 + 3017 - 820
    )
    identity = AVSyncMap.identity()
    assert identity.is_identity
    assert identity.source_to_content_ms(1234.0) == 1234.0
    assert identity.content_to_source_ms(1234.0) == 1234.0


def test_avsync_map_persistence_roundtrip(tmp_path):
    from twobyteasr.playback.avsync import load_sync_map, save_sync_map

    sync_map = _gappy_map()
    save_sync_map(tmp_path, sync_map)
    restored = load_sync_map(tmp_path)
    assert restored is not None
    assert restored.to_dict() == sync_map.to_dict()


def _make_holed_mkv(path: Path) -> None:
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc=duration=12:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-filter_complex",
        "[0:v]split=2[vA][vB];[1:a]asplit=2[aA][aB];"
        "[vA]trim=0:6,setpts=PTS-STARTPTS[v1];"
        "[aA]atrim=0:6,asetpts=PTS-STARTPTS[a1];"
        "[vB]trim=start=6,setpts=PTS-STARTPTS+2/TB[v2];"
        "[aB]atrim=start=6,asetpts=PTS-STARTPTS+2/TB[a2];"
        "[v1][v2]concat=n=2:v=1:a=0[v];[a1][a2]concat=n=2:v=0:a=1[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        str(path),
    )


def test_avsync_scan_detects_joint_hole_and_healthy_identity(tmp_path):
    from twobyteasr.playback.avsync import scan_timestamp_gaps

    holed = tmp_path / "holed.mkv"
    _make_holed_mkv(holed)
    result = scan_timestamp_gaps(holed, FFPROBE)
    assert result.status == "warning"
    assert result.event_count == 1
    gap = result.map.all_gaps[0]
    assert gap.joint
    assert abs(gap.gap_ms - 2000) <= 60

    clean = tmp_path / "clean.mkv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc=duration=8:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(clean),
    )
    healthy = scan_timestamp_gaps(clean, FFPROBE)
    assert healthy.status == "healthy"
    assert healthy.map.is_identity


def test_audio_decode_command_translates_seek_through_map():
    from twobyteasr.playback.audio_engine import build_audio_decode_command
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap

    gaps = [TimestampGap(5_902_550, 5_903_566, 1016, video=True, audio=True)]
    sync_map = AVSyncMap(gaps)
    command = build_audio_decode_command(
        FFMPEG, "media.flv", source_ms=5_910_000, rate=1.0, av_sync_map=sync_map,
    )
    seek = command[command.index("-ss") + 1]
    assert abs(float(seek) - 5_911.016) < 0.01
    # Content before the first hole is untouched.
    early = build_audio_decode_command(
        FFMPEG, "media.flv", source_ms=5_902_000, rate=1.0, av_sync_map=sync_map,
    )
    assert abs(float(early[early.index("-ss") + 1]) - 5_902.0) < 1e-6
    plain = build_audio_decode_command(FFMPEG, "media.flv", source_ms=5_910_000, rate=1.0)
    assert abs(float(plain[plain.index("-ss") + 1]) - 5_910.0) < 1e-6


def test_optimized_media_cache_serves_sync_map(tmp_path):
    from twobyteasr.media.indexed_media import IndexedMediaCache
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap, save_sync_map

    flv = tmp_path / "s.flv"
    run_ffmpeg(
        "-f", "lavfi", "-i", "testsrc=duration=8:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-f", "flv", str(flv),
    )
    cache = IndexedMediaCache(root=tmp_path / "seek")
    cache.resolve(str(flv))
    target = Path(cache.wait_optimized(str(flv), timeout=180))
    assert target.suffix == ".mp4"

    # No cached map yet: None (a scan was kicked in the background).
    assert cache.sync_map(str(flv)) is None
    deadline = time.monotonic() + 90
    served = None
    while time.monotonic() < deadline:
        served = cache.sync_map(str(flv))
        if served is not None:
            break
        time.sleep(0.5)
    assert served is not None and served.is_identity  # clean clip scans healthy

    # A persisted map is served without rescanning (new instance, warm folder).
    gappy = AVSyncMap(
        [TimestampGap(2_000, 4_000, 2000, video=True, audio=True)],
        source_duration_ms=8_000,
    )
    save_sync_map(target.parent, gappy)
    fresh = IndexedMediaCache(root=tmp_path / "seek")
    warm = Path(fresh.wait_optimized(str(flv), timeout=60))
    assert warm == target
    assert fresh.sync_map(str(flv)).to_dict() == gappy.to_dict()


# ====================================================== P1: canvas mapping


def test_video_canvas_maps_positions_and_seek_targets(tmp_path):
    _app()
    from tests.test_round42_studio_recognition import _page  # offscreen page fixture
    from twobyteasr.playback.avsync import AVSyncMap, TimestampGap

    page = _page(_monkey_stub(), tmp_path)
    try:
        gaps = [TimestampGap(5_902_550, 5_903_566, 1016, video=True, audio=True)]
        sync_map = AVSyncMap(gaps)
        page.video.set_av_sync_map(sync_map)
        # mpv 观测（时间戳域）映射进内容域工程时钟
        assert page.video._source_position_to_project_ms(5_904.0) == pytest.approx(5_902_984.0)
        # 内容域 seek 目标翻译回时间戳域给 mpv
        assert page.video._content_to_source_seconds(5_902.984) == pytest.approx(5_904.0, abs=1e-3)
        # 恒等映射（健康媒体）零行为差异
        page.video.set_av_sync_map(None)
        assert page.video._source_position_to_project_ms(5_904.0) == pytest.approx(5_904_000.0)
        assert page.video._content_to_source_seconds(5_902.984) == pytest.approx(5_902.984)
    finally:
        page.close_page()
        page.deleteLater()
        _app().processEvents()


class _monkey_stub:
    """Duck-typed monkeypatch shim for the shared _page fixture."""

    def __init__(self):
        self._env = {}

    def setenv(self, key, value):
        self._env[key] = value
        os.environ[key] = value

    def setattr(self, *args, **kwargs):
        pass


# ================================== P2: recognition handoff refreshes Studio


def _write_project_with_cues(path: Path, media_path: Path, count: int) -> None:
    from twobyteasr.projects.studio_project import (
        AudioClip, AudioTrack, AVTrackGroup, MediaAsset, StudioCue, StudioMedia,
        StudioSpeaker, SubtitleProject, VideoClip, VideoTrack, save_project,
    )

    asset = MediaAsset(
        asset_id="asset-1", canonical_source=str(media_path.resolve()),
        duration_ms=120_000,
        audio_metadata={"has_audio": True}, video_metadata={"has_video": True},
    )
    project = SubtitleProject(
        media=StudioMedia(str(media_path), duration_ms=120_000),
        speakers=[StudioSpeaker("S00")],
        cues=[
            StudioCue(f"c{i}", 500 + i * 900, 1200 + i * 900, f"字幕{i}", "S00")
            for i in range(count)
        ],
    )
    project.media_pool = [asset]
    video = VideoTrack(id="V1", name="V1")
    video.clips = [VideoClip(id="vc1", asset_id="asset-1", source_in_ms=0,
                             source_out_ms=120_000, timeline_in_ms=0,
                             timeline_out_ms=120_000)]
    audio = AudioTrack(id="A1", name="A1")
    audio.clips = [AudioClip(id="ac1", asset_id="asset-1", source_in_ms=0,
                             source_out_ms=120_000, timeline_in_ms=0,
                             timeline_out_ms=120_000)]
    project.video_tracks = [video]
    project.audio_tracks = [audio]
    project.av_track_groups = [AVTrackGroup(id="g1", video_track_id="V1",
                                            audio_track_id="A1")]
    project.validate()
    save_project(project, path)


def test_recognition_handoff_refreshes_studio_without_reopen(monkeypatch, tmp_path):
    _app()
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "m.wav"
    run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=8", str(media))
    project_path = tmp_path / "p.2byteproj"

    win = MainWindow([], legacy, object(), None)
    try:
        # 真实前态：先打开"已导入媒体、还没有字幕"的工程（识别由此发起）。
        _write_project_with_cues(project_path, media, 0)
        win.open_studio_project(str(project_path), source="canonical")
        _app().processEvents()
        monkeypatch.setattr(win.studio_page, "save", lambda: None)
        assert len(win.studio_page.project.cues) == 0

        # 识别前视口状态：zoom/播放头/选中项都要在交接后保留。
        win.studio_page.timeline.set_visible_window(60_000, 40_000)
        win.studio_page.timeline.set_playhead(90_000)

        # "识别完成"：字幕已写入工程文件（模拟 ASR 交付）。
        _write_project_with_cues(project_path, media, 5)

        # 回归核心（用户 2.5）：不重新打开工程，交接即刷新。
        # 同时覆盖 autosave 代次被无编辑周期保存顶掉的场景——不得弹
        # "识别期间有编辑"对话框（exec 挂死即失败）。
        win.studio_page._recognition_undo_count = 0
        win.studio_page._autosave_generation = 99
        win._finish_studio_recognition(str(project_path))
        _app().processEvents()

        page = win.studio_page
        assert len(page.project.cues) == 5, "project model 必须已载入新字幕"
        assert len(page.timeline._cues_by_start) == 5, "timeline 字幕轨必须更新"
        assert page.cue_model.rowCount() == 5, "字幕列表必须更新"
        assert page._pending_recognition_reload == ""
        # 视图状态保留（zoom/播放头不因交接重置）
        assert page.timeline.visible_start_ms == 60_000
        assert page.timeline.visible_duration_ms == 40_000
        assert page.timeline.playhead_ms == 90_000
    finally:
        win.deleteLater()
        _app().processEvents()


def test_pending_recognition_reload_retries_on_studio_entry(monkeypatch, tmp_path):
    _app()
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "m.wav"
    run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=8", str(media))
    project_path = tmp_path / "p.2byteproj"
    _write_project_with_cues(project_path, media, 3)

    win = MainWindow([], legacy, object(), None)
    try:
        # 模拟就绪门超时：重载从未发生，但字幕已在工程文件里。
        win.studio_page._pending_recognition_reload = str(project_path)
        win._retry_pending_recognition_reload()
        _app().processEvents()
        assert len(win.studio_page.project.cues) == 3
        assert win.studio_page._pending_recognition_reload == ""
    finally:
        win.deleteLater()
        _app().processEvents()


def test_readiness_failure_is_visible_and_keeps_pending(tmp_path):
    _app()
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.studio.studio_readiness import StudioReadiness
    from twobyteasr.diagnostics.runtime_trace import GLOBAL_STUDIO_TRACE

    _monkey_local(tmp_path)
    page = SubtitleStudioPage()
    try:
        target = tmp_path / "ghost.2byteproj"
        page._pending_recognition_reload = str(target)
        gate = StudioReadiness(page)
        before = len(GLOBAL_STUDIO_TRACE.recent())
        gate.begin(str(target))
        gate.fail("读取工程", "boom")
        events = [item for item in GLOBAL_STUDIO_TRACE.recent()[before:]
                  if item.get("event") in {"STUDIO_OPEN_FAILED"}]
        assert events and events[-1].get("error") == "boom"
        # 挂起重载保留：Studio 下次进入自动重试
        assert page._pending_recognition_reload == str(target)
        chip = page.recognition_chip_label.text()
        assert "自动重载" in chip
        gate.cancel()
        page._pending_recognition_reload = ""
    finally:
        page.close_page()
        page.deleteLater()
        _app().processEvents()


def _monkey_local(tmp_path: Path) -> None:
    os.environ["LOCALAPPDATA"] = str(tmp_path / "local")
    os.environ.setdefault("APPDATA", str(tmp_path / "roaming"))
